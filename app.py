from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf

app = Flask(__name__)
CORS(app)


# -------------------------------------------------
# HOME
# -------------------------------------------------

@app.route("/")
def home():
    return jsonify({
        "status": "success",
        "message": "Mahid Scanner is running",
        "data_api": "/api/stock/RELIANCE"
    })


# -------------------------------------------------
# STOCK API
# -------------------------------------------------

@app.route("/api/stock/<symbol>")
def stock(symbol):

    try:

        symbol = symbol.upper().strip()

        ticker = yf.Ticker(symbol + ".NS")


        # =================================================
        # 5 MINUTE DATA
        # =================================================

        data_5m = ticker.history(
            period="5d",
            interval="5m"
        )

        if data_5m.empty:

            return jsonify({
                "status": "error",
                "symbol": symbol,
                "message": "5 minute data not available"
            })


        # Remove incomplete rows

        data_5m = data_5m.dropna(
            subset=["Open", "High", "Low", "Close"]
        )


        last = data_5m.iloc[-1]


        price = float(last["Close"])

        candle_open = float(last["Open"])

        candle_high = float(last["High"])

        candle_low = float(last["Low"])

        volume = int(last["Volume"])


        # =================================================
        # RECENT 5M RANGE
        # =================================================

        recent_5m = data_5m.tail(30)


        intraday_high = float(
            recent_5m["High"].max()
        )

        intraday_low = float(
            recent_5m["Low"].min()
        )


        range_5m = intraday_high - intraday_low


        # Prevent zero range

        if range_5m <= 0:

            range_5m = max(price * 0.01, 0.01)


        # =================================================
        # 5M SUPPORT / RESISTANCE
        # =================================================

        support_5m = (
            intraday_low +
            (range_5m * 0.25)
        )


        resistance_5m = (
            intraday_low +
            (range_5m * 0.75)
        )


        midpoint_5m = (
            intraday_low +
            (range_5m * 0.50)
        )


        # =================================================
        # DAY DATA
        # =================================================

        data_day = ticker.history(
            period="3mo",
            interval="1d"
        )


        if not data_day.empty:

            data_day = data_day.dropna(
                subset=["High", "Low", "Close"]
            )


            recent_day = data_day.tail(20)


            day_high = float(
                recent_day["High"].max()
            )


            day_low = float(
                recent_day["Low"].min()
            )


            day_range = day_high - day_low


            if day_range <= 0:

                day_range = max(price * 0.05, 0.01)


            major_support = (
                day_low +
                (day_range * 0.25)
            )


            major_resistance = (
                day_low +
                (day_range * 0.75)
            )

        else:

            major_support = support_5m

            major_resistance = resistance_5m


        # =================================================
        # VOLUME CONFIRMATION
        # =================================================

        volume_data = data_5m["Volume"].tail(20)

        average_volume = float(
            volume_data.mean()
        )


        if average_volume > 0:

            volume_ratio = (
                volume / average_volume
            )

        else:

            volume_ratio = 1.0


        # Strong volume = 1.5x average

        strong_volume = (
            volume_ratio >= 1.5
        )


        # =================================================
        # 5M CANDLE DIRECTION
        # =================================================

        bullish_candle = (
            candle_close := float(last["Close"])
        ) > candle_open


        bearish_candle = (
            candle_close < candle_open
        )


        # =================================================
        # DISTANCE FROM 5M LEVELS
        # =================================================

        support_distance = abs(
            price - support_5m
        ) / price


        resistance_distance = abs(
            price - resistance_5m
        ) / price


        # 0.30% ke andar level ke paas maana jayega

        near_support = (
            support_distance <= 0.003
        )


        near_resistance = (
            resistance_distance <= 0.003
        )


        # =================================================
        # ZONE
        # =================================================

        if price < midpoint_5m:

            zone = "Discount Zone"

        elif price > midpoint_5m:

            zone = "Premium Zone"

        else:

            zone = "Equilibrium"


        # =================================================
        # SIGNAL
        # =================================================

        signal = "WAIT"


        signal_reason = (
            "No confirmed setup"
        )


        # -------------------------------------------------
        # BUY SETUP
        # -------------------------------------------------

        if (

            near_support
            and bullish_candle
            and strong_volume

        ):

            signal = "BUY AREA"

            signal_reason = (
                "5M support + bullish candle + strong volume"
            )


        # -------------------------------------------------
        # SELL SETUP
        # -------------------------------------------------

        elif (

            near_resistance
            and bearish_candle
            and strong_volume

        ):

            signal = "SELL AREA"

            signal_reason = (
                "5M resistance + bearish candle + strong volume"
            )


        # -------------------------------------------------
        # SECONDARY BUY SETUP
        # Price below midpoint and bullish
        # but only with volume
        # -------------------------------------------------

        elif (

            price < midpoint_5m
            and bullish_candle
            and strong_volume
            and price > major_support

        ):

            signal = "BUY AREA"

            signal_reason = (
                "Discount zone + bullish candle + strong volume"
            )


        # -------------------------------------------------
        # SECONDARY SELL SETUP
        # -------------------------------------------------

        elif (

            price > midpoint_5m
            and bearish_candle
            and strong_volume
            and price < major_resistance

        ):

            signal = "SELL AREA"

            signal_reason = (
                "Premium zone + bearish candle + strong volume"
            )


        # =================================================
        # PREVIOUS CLOSE
        # =================================================

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

            change = (
                price -
                previous_close
            )


            change_percent = (
                change /
                previous_close
            ) * 100


        # =================================================
        # RESPONSE
        # =================================================

        return jsonify({

            "status": "success",

            "symbol": symbol,

            "exchange": "NSE",

            "price": round(
                price, 2
            ),

            "previous_close":
                round(
                    previous_close, 2
                )
                if previous_close is not None
                else None,


            # 5M LEVELS

            "support_5m":
                round(
                    support_5m, 2
                ),

            "resistance_5m":
                round(
                    resistance_5m, 2
                ),


            # DAY LEVELS

            "major_support":
                round(
                    major_support, 2
                ),

            "major_resistance":
                round(
                    major_resistance, 2
                ),


            # MARKET DATA

            "volume":
                volume,

            "average_volume":
                round(
                    average_volume, 0
                ),

            "volume_ratio":
                round(
                    volume_ratio, 2
                ),


            # ZONE

            "zone":
                zone,


            # SIGNAL

            "signal":
                signal,


            "signal_reason":
                signal_reason,


            # PRICE ACTION

            "candle":
                "BULLISH"
                if bullish_candle
                else "BEARISH"
                if bearish_candle
                else "NEUTRAL",


            # CHANGE

            "change":
                round(
                    change, 2
                )
                if change is not None
                else None,


            "change_percent":
                round(
                    change_percent, 2
                )
                if change_percent is not None
                else None

        })


    except Exception as e:

        return jsonify({

            "status": "error",

            "symbol": symbol,

            "message": str(e)

        }), 500
