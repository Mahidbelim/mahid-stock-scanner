from flask import Flask, jsonify
import yfinance as yf

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({
        "status": "success",
        "message": "Mahid Scanner is running"
    })

@app.route("/api/stock/<symbol>")
def stock(symbol):
    try:
        data = yf.Ticker(symbol + ".NS")
        price = data.fast_info["last_price"]

        return jsonify({
            "status": "success",
            "symbol": symbol.upper(),
            "price": price
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        })

if __name__ == "__main__":
    app.run()
