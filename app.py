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

        data = ticker.history(period="1d", interval="1m")

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

        previous_data = ticker.history(period="5d")

        previous_close = None

        if len(previous_data) >= 2:
            previous_close = float(
                previous_data["Close"].iloc[-2]
            )

        change = None
        change_percent = None

        if previous_close:
            change = price - previous_close
            change_percent = (
                change / previous_close
            ) * 100

        return jsonify({

            "status": "success",
            "symbol": symbol,
            "exchange": "NSE",

            "price": round(price, 2),

            "previous_close":
                round(previous_close, 2)
                if previous_close else None,

            "open": round(day_open, 2),

            "high": round(day_high, 2),

            "low": round(day_low, 2),

            "volume": volume,

            "change":
                round(change, 2)
                if change is not None else None,

            "change_percent":
                round(change_percent, 2)
                if change_percent is not None else None
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "symbol": symbol,
            "message": str(e)
        }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )
