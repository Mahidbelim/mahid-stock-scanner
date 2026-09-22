from flask import Flask, jsonify
import yfinance as yf

app = Flask(__name__)

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
        info = ticker.fast_info

        price = info.get("last_price")
        previous_close = info.get("previous_close")
        day_open = info.get("open")
        day_high = info.get("day_high")
        day_low = info.get("day_low")
        volume = info.get("last_volume")

        change = None
        change_percent = None

        if price is not None and previous_close:
            change = price - previous_close
            change_percent = (change / previous_close) * 100

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "exchange": "NSE",
            "price": price,
            "previous_close": previous_close,
            "open": day_open,
            "high": day_high,
            "low": day_low,
            "volume": volume,
            "change": round(change, 2) if change is not None else None,
            "change_percent": round(change_percent, 2)
                if change_percent is not None else None
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "symbol": symbol,
            "message": str(e)
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
