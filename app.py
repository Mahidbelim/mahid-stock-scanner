from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import threading
import time

app = Flask(__name__)
CORS(app)

# =========================
# SETTINGS
# =========================
BATCH_SIZE = 50
SHORTLIST_SIZE = 20
FINAL_SIZE = 5

scan_lock = threading.Lock()

SCAN = {
    "status": "idle",
    "message": "Scanner ready",
    "results": [],
    "updated": None
}


# =========================
# NSE SYMBOL LIST
# =========================
def get_nse_symbols():
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "Referer": "https://www.nseindia.com/"
    }

    try:
        r = requests.get(url, headers=headers, timeout=20)

        if r.status_code != 200:
            return []

        df = pd.read_csv(io.BytesIO(r.content))

        df.columns = [str(c).strip().upper() for c in df.columns]

        if "SYMBOL" not in df.columns:
            return []

        symbols = df["SYMBOL"].dropna().astype(str).str.strip().tolist()

        # Remove unwanted symbols
        symbols = [
            s for s in symbols
            if s and not any(x in s for x in ["-", "&"])
        ]

        return list(dict.fromkeys(symbols))

    except Exception:
        return []


# =========================
# DAILY BATCH DOWNLOAD
# =========================
def download_daily(symbols):

    tickers = [s + ".NS" for s in symbols]

    try:
        data = yf.download(
            tickers=tickers,
            period="3mo",
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            threads=False,
            progress=False,
            timeout=20
        )

        return data

    except Exception:
        return pd.DataFrame()


# =========================
# ANALYZE ONE STOCK
# =========================
def analyze_stock(symbol, data):

    try:

        ticker = symbol + ".NS"

        if data.empty:
            return None

        if isinstance(data.columns, pd.MultiIndex):

            if ticker not in data.columns.get_level_values(0):
                return None

            df = data[ticker].copy()

        else:
            df = data.copy()

        if df.empty:
            return None

        df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

        if len(df) < 30:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        price = float(close.iloc[-1])

        # EMA
        ema20 = float(close.ewm(span=20).mean().iloc[-1])
        ema50 = float(close.ewm(span=50).mean().iloc[-1])

        # Average volume
        avg_volume = float(volume.iloc[-21:-1].mean())

        if avg_volume <= 0:
            return None

        volume_ratio = float(volume.iloc[-1] / avg_volume)

        # Previous 20 day high/low
        previous_high = float(high.iloc[-21:-1].max())
        previous_low = float(low.iloc[-21:-1].min())

        # ATR
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = float(tr.rolling(14).mean().iloc[-1])

        if atr <= 0:
            return None

        atr_percent = (atr / price) * 100

        # Candle
        o = float(df["Open"].iloc[-1])
        h = float(df["High"].iloc[-1])
        l = float(df["Low"].iloc[-1])
        c = float(df["Close"].iloc[-1])

        bullish = c > o
        bearish = c < o

        body = abs(c - o)
        candle_range = max(h - l, 0.01)

        strong_candle = (body / candle_range) >= 0.50

        # Momentum
        change_5d = ((price / float(close.iloc[-6])) - 1) * 100

        # Breakout / breakdown
        breakout = price > previous_high
        breakdown = price < previous_low

        score = 0
        setup = "WATCH"

        reasons = []

        # Trend
        if price > ema20:
            score += 10
            reasons.append("Above EMA20")

        if ema20 > ema50:
            score += 10
            reasons.append("EMA20 > EMA50")

        # Volume
        if volume_ratio >= 1.5:
            score += 15
            reasons.append("Strong volume")

        elif volume_ratio >= 1.2:
            score += 8

        # Volatility
        if atr_percent >= 1.5:
            score += 10
            reasons.append("Good volatility")

        elif atr_percent >= 1.0:
            score += 5

        # Momentum
        if abs(change_5d) >= 2:
            score += 10
            reasons.append("Momentum")

        # Breakout
        if breakout:
            score += 25
            setup = "BREAKOUT"
            reasons.append("20D breakout")

        elif breakdown:
            score += 25
            setup = "BREAKDOWN"
            reasons.append("20D breakdown")

        # Candle
        if strong_candle and bullish:
            score += 10
            reasons.append("Strong bullish candle")

        elif strong_candle and bearish:
            score += 10
            reasons.append("Strong bearish candle")

        # Only useful setups
        if score < 50:
            return None

        return {
            "symbol": symbol,
            "price": round(price, 2),
            "score": int(score),
            "setup": setup,
            "volume_ratio": round(volume_ratio, 2),
            "atr_percent": round(atr_percent, 2),
            "change_5d": round(change_5d, 2),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "support": round(previous_low, 2),
            "resistance": round(previous_high, 2),
            "candle": (
                "BULLISH"
                if bullish
                else "BEARISH"
                if bearish
                else "NEUTRAL"
            ),
            "reason": ", ".join(reasons[:5])
        }

    except Exception:
        return None


# =========================
# 5 MIN CONFIRMATION
# =========================
def confirm_5m(candidates):

    if not candidates:
        return []

    symbols = [x["symbol"] for x in candidates]
    tickers = [s + ".NS" for s in symbols]

    try:

        data = yf.download(
            tickers=tickers,
            period="5d",
            interval="5m",
            auto_adjust=False,
            group_by="ticker",
            threads=False,
            progress=False,
            timeout=30
        )

    except Exception:
        return candidates

    final = []

    for item in candidates:

        try:

            ticker = item["symbol"] + ".NS"

            if isinstance(data.columns, pd.MultiIndex):

                if ticker not in data.columns.get_level_values(0):
                    continue

                df = data[ticker].copy()

            else:
                df = data.copy()

            if df.empty:
                continue

            df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

            if len(df) < 20:
                continue

            last = df.iloc[-1]

            price = float(last["Close"])
            open_price = float(last["Open"])
            volume = float(last["Volume"])

            avg_volume = float(df["Volume"].tail(21).iloc[:-1].mean())

            volume_ratio = (
                volume / avg_volume
                if avg_volume > 0
                else 1
            )

            recent = df.tail(30)

            support = float(recent["Low"].min())
            resistance = float(recent["High"].max())

            bullish = price > open_price
            bearish = price < open_price

            near_support = abs(price - support) / price <= 0.004
            near_resistance = abs(price - resistance) / price <= 0.004

            confirmation = 0

            if volume_ratio >= 1.5:
                confirmation += 20

            if item["setup"] == "BREAKOUT" and bullish:
                confirmation += 20

            if item["setup"] == "BREAKDOWN" and bearish:
                confirmation += 20

            if near_support and bullish:
                confirmation += 15

            if near_resistance and bearish:
                confirmation += 15

            item["price_5m"] = round(price, 2)
            item["support_5m"] = round(support, 2)
            item["resistance_5m"] = round(resistance, 2)
            item["volume_ratio_5m"] = round(volume_ratio, 2)
            item["confirmation"] = confirmation

            item["total_score"] = item["score"] + confirmation

            final.append(item)

        except Exception:
            continue

    final.sort(
        key=lambda x: x.get("total_score", 0),
        reverse=True
    )

    return final[:FINAL_SIZE]


# =========================
# BACKGROUND SCANNER
# =========================
def run_scan():

    global SCAN

    try:

        SCAN["status"] = "scanning"
        SCAN["message"] = "Scanning NSE stocks..."
        SCAN["results"] = []

        symbols = get_nse_symbols()

        if not symbols:
            SCAN["status"] = "error"
            SCAN["message"] = "NSE stock list could not be loaded"
            return

        all_candidates = []

        # Batch scan
        for start in range(0, len(symbols), BATCH_SIZE):

            batch = symbols[start:start + BATCH_SIZE]

            data = download_daily(batch)

            if data.empty:
                continue

            for symbol in batch:

                result = analyze_stock(symbol, data)

                if result:
                    all_candidates.append(result)

            # Small pause to reduce rate limiting
            time.sleep(1)

        # Strongest daily candidates
        all_candidates.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        shortlist = all_candidates[:SHORTLIST_SIZE]

        SCAN["message"] = (
            f"Daily scan complete. "
            f"{len(shortlist)} candidates found. "
            f"Checking 5M..."
        )

        final = confirm_5m(shortlist)

        SCAN["results"] = final
        SCAN["status"] = "complete"
        SCAN["message"] = (
            f"Scan complete. "
            f"{len(final)} strong stocks found."
        )
        SCAN["updated"] = time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    except Exception as e:

        SCAN["status"] = "error"
        SCAN["message"] = str(e)


# =========================
# HOME
# =========================
@app.route("/")
def home():

    return jsonify({
        "status": "success",
        "message": "Mahid Scanner is running",
        "scan_api": "/api/scan"
    })


# =========================
# START / CHECK SCAN
# =========================
@app.route("/api/scan")
def scan():

    global SCAN

    if SCAN["status"] == "scanning":

        return jsonify({
            "status": "scanning",
            "message": SCAN["message"],
            "results": SCAN["results"]
        })

    # Start new scan
    thread = threading.Thread(
        target=run_scan,
        daemon=True
    )

    thread.start()

    return jsonify({
        "status": "scanning",
        "message": "NSE scan started. Please check again shortly.",
        "results": []
    })


# =========================
# STATUS
# =========================
@app.route("/api/scan/status")
def scan_status():

    return jsonify({
        "status": SCAN["status"],
        "message": SCAN["message"],
        "results": SCAN["results"],
        "updated": SCAN["updated"]
    })


# =========================
# SINGLE STOCK
# =========================
@app.route("/api/stock/<symbol>")
def stock(symbol):

    try:

        symbol = symbol.upper().strip()

        ticker = yf.Ticker(symbol + ".NS")

        data = ticker.history(
            period="5d",
            interval="5m"
        )

        if data.empty:
            return jsonify({
                "status": "error",
                "message": "Data not available"
            })

        data = data.dropna(
            subset=["Open", "High", "Low", "Close"]
        )

        last = data.iloc[-1]

        price = float(last["Close"])

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "price": round(price, 2),
            "candle": (
                "BULLISH"
                if last["Close"] > last["Open"]
                else "BEARISH"
            )
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "symbol": symbol,
            "message": str(e)
        }), 500
