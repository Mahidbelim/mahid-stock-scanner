from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({
        "status": "success",
        "message": "Mahid Stock Scanner backend is running"
    })

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok"
    })

@app.route("/api/stock/<symbol>")
def stock(symbol):
    return jsonify({
        "symbol": symbol.upper(),
        "message": "Stock data connection ready"
    })

if __name__ == "__main__":
    app.run()
