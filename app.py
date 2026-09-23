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

        data = ticker.history(
            period="1d",
            interval="1m"
        )

        if data.empty:
            return jsonify({
                "status": "error",
                "symbol": symbol,
                "message": "Market data not available"
            })

        last = data.iloc[-1]

        price = float(last["Close"])
        day_open = float(data["Open"].iloc[0])
        day_high = float(data["High"].max())
        day_low = float(data["Low"].min())
        volume = int(last["Volume"])

        # SUPPORT & RESISTANCE
        price_range = day_high - day_low

        support = day_low + (price_range * 0.25)
        resistance = day_low + (price_range * 0.75)

        # DISCOUNT / PREMIUM
        midpoint = day_low + (price_range * 0.50)

        if price < midpoint:
            zone = "Discount Zone"
            signal = "BUY AREA"

        elif price > midpoint:
            zone = "Premium Zone"
            signal = "SELL AREA"

        else:
            zone = "Equilibrium"
            signal = "WAIT"

        # PREVIOUS CLOSE
        previous_data = ticker.history(period="5d")

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
                change / previous_close
            ) * 100

        # RESPONSE
        return jsonify({
            "status": "success",
            "symbol": symbol,
            "exchange": "NSE",
            "price": round(price, 2),
            "previous_close": (
                round(previous_close, 2)
                if previous_close is not None
                else None
            ),
            "open": round(day_open, 2),
            "high": round(day_high, 2),
            "low": round(day_low, 2),
            "volume": volume,
            "change": (
                round(change, 2)
                if change is not None
                else None
            ),
            "change_percent": (
                round(change_percent, 2)
                if change_percent is not None
                else None
            ),
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "zone": zone,
            "signal": signal
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "symbol": symbol,
            "message": str(e)
        }), 500
