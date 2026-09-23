from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return jsonify({
        "status": "success",
        "message": "Mahid Scanner is running",
        "data_api": "/api/stock/RELIANCE"
    })


@app.route("/api/stock/<symbol>")
def stock(symbol):

    try:
        symbol = symbol.upper().strip()

        ticker = yf.Ticker(symbol + ".NS")

        # -----------------------------
        # 5 MINUTE DATA
        # -----------------------------
        data_5m = ticker.history(
            period="5d",
            interval="5m"
        )

        if data_5m.empty:
            return jsonify({
                "status": "error",
                "symbol": symbol,
                "message": "5 minute market data not available"
            })

        last = data_5m.iloc[-1]

        price = float(last["Close"])
        volume = int(last["Volume"])

        # Recent 5M candles
        recent_5m = data_5m.tail(30)

        intraday_high = float(recent_5m["High"].max())
        intraday_low = float(recent_5m["Low"].min())

        # -----------------------------
        # 5M SUPPORT / RESISTANCE
        # -----------------------------
        range_5m = intraday_high - intraday_low

        support_5m = intraday_low + (range_5m * 0.25)
        resistance_5m = intraday_low + (range_5m * 0.75)

        midpoint_5m = intraday_low + (range_5m * 0.50)

        # -----------------------------
        # DAY DATA
        # -----------------------------
        data_day = ticker.history(
            period="1mo",
            interval="1d"
        )

        if not data_day.empty:

            recent_day = data_day.tail(20)

            day_high = float(recent_day["High"].max())
            day_low = float(recent_day["Low"].min())

            day_range = day_high - day_low

            major_support = day_low + (day_range * 0.25)
            major_resistance = day_low + (day_range * 0.75)

        else:

            major_support = support_5m
            major_resistance = resistance_5m

        # -----------------------------
        # DISCOUNT / PREMIUM
        # -----------------------------
        if price < midpoint_5m:

            zone = "Discount Zone"
            signal = "BUY AREA"

        elif price > midpoint_5m:

            zone = "Premium Zone"
            signal = "SELL AREA"

        else:

            zone = "Equilibrium"
            signal = "WAIT"

        # -----------------------------
        # PREVIOUS CLOSE
        # -----------------------------
        previous_data = ticker.history(
            period="5d",
            interval="1d"
        )

        previous_close = None

        if len(previous_data) >= 2:
            previous_close = float(
                previous_data["Close"].iloc[-2]
            )

        change = None
        change_percent = None

        if previous_close is not None:

            change = price - previous_close

            change_percent = (
                (change / previous_close) * 100
            )

        # -----------------------------
        # RESULT
        # -----------------------------
        return jsonify({

            "status": "success",

            "symbol": symbol,

            "exchange": "NSE",

            "price": round(price, 2),

            "previous_close":
                round(previous_close, 2)
                if previous_close is not None
                else None,

            "volume": volume,

            # 5M LEVELS
            "support_5m":
                round(support_5m, 2),

            "resistance_5m":
                round(resistance_5m, 2),

            # DAY LEVELS
            "major_support":
                round(major_support, 2),

            "major_resistance":
                round(major_resistance, 2),

            # ZONE
            "zone": zone,

            "signal": signal,

            "change":
                round(change, 2)
                if change is not None
                else None,

            "change_percent":
                round(change_percent, 2)
                if change_percent is not None
                else None

        })

    except Exception as e:

        return jsonify({

            "status": "error",

            "symbol": symbol,

            "message": str(e)

        }), 500
