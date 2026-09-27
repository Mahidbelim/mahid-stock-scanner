from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import requests
import io
import threading
import time

app = Flask(__name__)
CORS(app)

# =========================================================
# SETTINGS
# =========================================================

# Free Render ko overload na karne ke liye controlled scan
DAILY_BATCH_SIZE = 100
SHORTLIST_SIZE = 20
FINAL_SIZE = 5

# Scan timeout protection
MAX_SCAN_SECONDS = 240

# Global scan state
SCAN = {
    "status": "idle",
    "message": "Scanner ready",
    "results": [],
    "updated": None,
    "progress": 0,
    "total": 0
}

SCAN_LOCK = threading.Lock()


# =========================================================
# NSE SYMBOL LIST
# =========================================================

def get_nse_symbols():

    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "Referer": "https://www.nseindia.com/"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        df = pd.read_csv(
            io.BytesIO(response.content)
        )

        df.columns = [
            str(c).strip().upper()
            for c in df.columns
        ]

        if "SYMBOL" not in df.columns:
            return []

        symbols = (
            df["SYMBOL"]
            .dropna()
            .astype(str)
            .str.strip()
            .tolist()
        )

        clean = []

        for symbol in symbols:

            if not symbol:
                continue

            if "-" in symbol:
                continue

            if "&" in symbol:
                continue

            clean.append(symbol)

        return list(dict.fromkeys(clean))

    except Exception as e:

        print("NSE LIST ERROR:", e)

        return []


# =========================================================
# DAILY DATA
# =========================================================

def download_daily(symbols):

    if not symbols:
        return pd.DataFrame()

    tickers = [
        symbol + ".NS"
        for symbol in symbols
    ]

    try:

        data = yf.download(
            tickers=tickers,
            period="3mo",
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
            timeout=15
        )

        return data

    except Exception as e:

        print("DAILY DOWNLOAD ERROR:", e)

        return pd.DataFrame()


# =========================================================
# GET SYMBOL DATA FROM DOWNLOAD
# =========================================================

def get_symbol_df(data, symbol):

    try:

        ticker = symbol + ".NS"

        if data is None or data.empty:
            return None

        if isinstance(data.columns, pd.MultiIndex):

            level0 = data.columns.get_level_values(0)

            if ticker not in level0:
                return None

            df = data[ticker].copy()

        else:

            df = data.copy()

        if df.empty:
            return None

        required = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
        ]

        missing = [
            c for c in required
            if c not in df.columns
        ]

        if missing:
            return None

        df = df.dropna(
            subset=required
        )

        if len(df) < 30:
            return None

        return df

    except Exception as e:

        print("DATA ERROR", symbol, e)

        return None


# =========================================================
# ANALYZE DAILY STOCK
# =========================================================

def analyze_stock(symbol, data):

    try:

        df = get_symbol_df(
            data,
            symbol
        )

        if df is None:
            return None

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float)

        price = float(close.iloc[-1])

        if price <= 0:
            return None

        # -------------------------------------------------
        # EMA
        # -------------------------------------------------

        ema20 = float(
            close.ewm(
                span=20,
                adjust=False
            ).mean().iloc[-1]
        )

        ema50 = float(
            close.ewm(
                span=50,
                adjust=False
            ).mean().iloc[-1]
        )

        # -------------------------------------------------
        # VOLUME
        # -------------------------------------------------

        previous_volume = volume.iloc[-21:-1]

        if len(previous_volume) < 10:
            return None

        avg_volume = float(
            previous_volume.mean()
        )

        if avg_volume <= 0:
            return None

        volume_ratio = (
            float(volume.iloc[-1])
            / avg_volume
        )

        # -------------------------------------------------
        # SUPPORT / RESISTANCE
        # -------------------------------------------------

        previous_high = float(
            high.iloc[-21:-1].max()
        )

        previous_low = float(
            low.iloc[-21:-1].min()
        )

        # -------------------------------------------------
        # ATR
        # -------------------------------------------------

        previous_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - previous_close).abs()
        tr3 = (low - previous_close).abs()

        tr = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        atr = float(
            tr.rolling(14).mean().iloc[-1]
        )

        if atr <= 0:
            return None

        atr_percent = (
            atr / price
        ) * 100

        # -------------------------------------------------
        # 5 DAY MOMENTUM
        # -------------------------------------------------

        if len(close) < 6:
            return None

        change_5d = (
            price / float(close.iloc[-6]) - 1
        ) * 100

        # -------------------------------------------------
        # CANDLE
        # -------------------------------------------------

        o = float(df["Open"].iloc[-1])
        h = float(df["High"].iloc[-1])
        l = float(df["Low"].iloc[-1])
        c = float(df["Close"].iloc[-1])

        bullish = c > o
        bearish = c < o

        body = abs(c - o)
        candle_range = max(
            h - l,
            0.01
        )

        strong_candle = (
            body / candle_range
        ) >= 0.50

        # -------------------------------------------------
        # BREAKOUT / BREAKDOWN
        # -------------------------------------------------

        breakout = price > previous_high
        breakdown = price < previous_low

        # -------------------------------------------------
        # SCORE
        # -------------------------------------------------

        score = 0

        reasons = []

        setup = "WATCH"

        # Trend
        if price > ema20:

            score += 10
            reasons.append(
                "Above EMA20"
            )

        if ema20 > ema50:

            score += 10
            reasons.append(
                "EMA20 > EMA50"
            )

        # Volume
        if volume_ratio >= 1.5:

            score += 15
            reasons.append(
                "Strong volume"
            )

        elif volume_ratio >= 1.2:

            score += 8

        # Volatility
        if atr_percent >= 1.5:

            score += 10
            reasons.append(
                "Good volatility"
            )

        elif atr_percent >= 1.0:

            score += 5

        # Momentum
        if abs(change_5d) >= 2:

            score += 10
            reasons.append(
                "Momentum"
            )

        # Breakout
        if breakout:

            score += 25
            setup = "BREAKOUT"

            reasons.append(
                "20D breakout"
            )

        elif breakdown:

            score += 25
            setup = "BREAKDOWN"

            reasons.append(
                "20D breakdown"
            )

        # Candle
        if strong_candle:

            score += 10

            if bullish:

                reasons.append(
                    "Strong bullish candle"
                )

            elif bearish:

                reasons.append(
                    "Strong bearish candle"
                )

        # -------------------------------------------------
        # Minimum score
        # -------------------------------------------------

        if score < 50:
            return None

        return {

            "symbol": symbol,

            "price": round(
                price,
                2
            ),

            "score": int(score),

            "setup": setup,

            "change_5d": round(
                change_5d,
                2
            ),

            "volume_ratio": round(
                volume_ratio,
                2
            ),

            "atr_percent": round(
                atr_percent,
                2
            ),

            "ema20": round(
                ema20,
                2
            ),

            "ema50": round(
                ema50,
                2
            ),

            "support": round(
                previous_low,
                2
            ),

            "resistance": round(
                previous_high,
                2
            ),

            "candle": (
                "BULLISH"
                if bullish
                else "BEARISH"
                if bearish
                else "NEUTRAL"
            ),

            "reason": ", ".join(
                reasons[:5]
            )
        }

    except Exception as e:

        print(
            "ANALYZE ERROR:",
            symbol,
            e
        )

        return None


# =========================================================
# 5 MIN CONFIRMATION
# =========================================================

def confirm_5m(candidates):

    if not candidates:
        return []

    symbols = [
        item["symbol"]
        for item in candidates
    ]

    tickers = [
        symbol + ".NS"
        for symbol in symbols
    ]

    try:

        data = yf.download(
            tickers=tickers,
            period="5d",
            interval="5m",
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
            timeout=20
        )

    except Exception as e:

        print(
            "5M DOWNLOAD ERROR:",
            e
        )

        # Daily candidates still returned
        return candidates[:FINAL_SIZE]

    final = []

    for item in candidates:

        try:

            symbol = item["symbol"]

            df = get_symbol_df(
                data,
                symbol
            )

            if df is None:
                continue

            if len(df) < 20:
                continue

            last = df.iloc[-1]

            price = float(
                last["Close"]
            )

            open_price = float(
                last["Open"]
            )

            volume = float(
                last["Volume"]
            )

            previous_volume = (
                df["Volume"]
                .tail(21)
                .iloc[:-1]
            )

            avg_volume = float(
                previous_volume.mean()
            )

            if avg_volume > 0:

                volume_ratio = (
                    volume /
                    avg_volume
                )

            else:

                volume_ratio = 1

            recent = df.tail(30)

            support = float(
                recent["Low"].min()
            )

            resistance = float(
                recent["High"].max()
            )

            bullish = (
                price > open_price
            )

            bearish = (
                price < open_price
            )

            near_support = (
                abs(price - support)
                / price
                <= 0.004
            )

            near_resistance = (
                abs(price - resistance)
                / price
                <= 0.004
            )

            confirmation = 0

            if volume_ratio >= 1.5:

                confirmation += 20

            if (
                item["setup"]
                == "BREAKOUT"
                and bullish
            ):

                confirmation += 20

            if (
                item["setup"]
                == "BREAKDOWN"
                and bearish
            ):

                confirmation += 20

            if (
                near_support
                and bullish
            ):

                confirmation += 15

            if (
                near_resistance
                and bearish
            ):

                confirmation += 15

            item["price_5m"] = round(
                price,
                2
            )

            item["support_5m"] = round(
                support,
                2
            )

            item["resistance_5m"] = round(
                resistance,
                2
            )

            item["volume_ratio_5m"] = round(
                volume_ratio,
                2
            )

            item["confirmation"] = int(
                confirmation
            )

            item["total_score"] = int(
                item["score"]
                + confirmation
            )

            final.append(item)

        except Exception as e:

            print(
                "5M ANALYZE ERROR:",
                item.get("symbol"),
                e
            )

            continue

    final.sort(
        key=lambda x:
        x.get(
            "total_score",
            0
        ),
        reverse=True
    )

    return final[:FINAL_SIZE]


# =========================================================
# BACKGROUND SCANNER
# =========================================================

def run_scan():

    global SCAN

    start_time = time.time()

    try:

        with SCAN_LOCK:

            SCAN["status"] = "scanning"
            SCAN["message"] = (
                "Loading NSE stock list..."
            )
            SCAN["results"] = []
            SCAN["updated"] = None
            SCAN["progress"] = 0
            SCAN["total"] = 0

        # -------------------------------------------------
        # NSE SYMBOLS
        # -------------------------------------------------

        symbols = get_nse_symbols()

        if not symbols:

            SCAN["status"] = "error"

            SCAN["message"] = (
                "NSE stock list could not be loaded"
            )

            return

        SCAN["total"] = len(symbols)

        print(
            "TOTAL NSE SYMBOLS:",
            len(symbols)
        )

        # -------------------------------------------------
        # DAILY SCAN
        # -------------------------------------------------

        candidates = []

        for start in range(
            0,
            len(symbols),
            DAILY_BATCH_SIZE
        ):

            # Timeout protection
            if (
                time.time()
                - start_time
                > MAX_SCAN_SECONDS
            ):

                print(
                    "SCAN TIMEOUT PROTECTION"
                )

                break

            batch = symbols[
                start:
                start + DAILY_BATCH_SIZE
            ]

            SCAN["message"] = (
                f"Scanning daily data "
                f"{min(start + len(batch), len(symbols))}"
                f"/{len(symbols)}..."
            )

            SCAN["progress"] = min(
                start + len(batch),
                len(symbols)
            )

            print(
                SCAN["message"]
            )

            data = download_daily(
                batch
            )

            if data.empty:

                print(
                    "EMPTY DAILY BATCH"
                )

                continue

            for symbol in batch:

                result = analyze_stock(
                    symbol,
                    data
                )

                if result:

                    candidates.append(
                        result
                    )

        # -------------------------------------------------
        # SORT
        # -------------------------------------------------

        candidates.sort(
            key=lambda x:
            x["score"],
            reverse=True
        )

        shortlist = candidates[
            :SHORTLIST_SIZE
        ]

        print(
            "DAILY CANDIDATES:",
            len(candidates)
        )

        # -------------------------------------------------
        # NO CANDIDATE
        # -------------------------------------------------

        if not shortlist:

            SCAN["status"] = "complete"

            SCAN["message"] = (
                "Scan complete. "
                "No strong setup found."
            )

            SCAN["results"] = []

            SCAN["updated"] = (
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            return

        # -------------------------------------------------
        # 5M
        # -------------------------------------------------

        SCAN["message"] = (
            f"{len(shortlist)} daily candidates found. "
            f"Checking 5M confirmation..."
        )

        print(
            SCAN["message"]
        )

        final = confirm_5m(
            shortlist
        )

        # If 5M fails, don't leave scanner stuck
        if not final:

            final = shortlist[
                :FINAL_SIZE
            ]

        SCAN["results"] = final

        SCAN["status"] = "complete"

        SCAN["message"] = (
            f"Scan complete. "
            f"{len(final)} stocks found."
        )

        SCAN["updated"] = (
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        print(
            SCAN["message"]
        )

    except Exception as e:

        print(
            "SCAN ERROR:",
            repr(e)
        )

        SCAN["status"] = "error"

        SCAN["message"] = (
            "Scanner error: "
            + str(e)
        )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return jsonify({

        "status": "success",

        "message":
            "Mahid Scanner is running",

        "scan_api":
            "/api/scan",

        "status_api":
            "/api/scan/status"
    })


# =========================================================
# START / CHECK SCAN
# =========================================================

@app.route("/api/scan")
def scan():

    global SCAN

    # Already running
    if SCAN["status"] == "scanning":

        return jsonify({

            "status": "scanning",

            "message":
                SCAN["message"],

            "results":
                SCAN["results"],

            "progress":
                SCAN["progress"],

            "total":
                SCAN["total"]
        })

    # Start scanner
    thread = threading.Thread(
        target=run_scan,
        daemon=True
    )

    thread.start()

    return jsonify({

        "status": "scanning",

        "message":
            "NSE scan started. "
            "Check status shortly.",

        "results": [],

        "progress": 0,

        "total": 0
    })


# =========================================================
# STATUS
# =========================================================

@app.route("/api/scan/status")
def scan_status():

    return jsonify({

        "status":
            SCAN["status"],

        "message":
            SCAN["message"],

        "results":
            SCAN["results"],

        "updated":
            SCAN["updated"],

        "progress":
            SCAN["progress"],

        "total":
            SCAN["total"]
    })


# =========================================================
# SINGLE STOCK
# =========================================================

@app.route("/api/stock/<symbol>")
def stock(symbol):

    try:

        symbol = (
            symbol
            .upper()
            .strip()
        )

        ticker = yf.Ticker(
            symbol + ".NS"
        )

        data = ticker.history(
            period="5d",
            interval="5m"
        )

        if data.empty:

            return jsonify({

                "status":
                    "error",

                "message":
                    "Data not available"
            })

        data = data.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close"
            ]
        )

        if data.empty:

            return jsonify({

                "status":
                    "error",

                "message":
                    "Data not available"
            })

        last = data.iloc[-1]

        price = float(
            last["Close"]
        )

        if last["Close"] > last["Open"]:

            candle = "BULLISH"

        elif last["Close"] < last["Open"]:

            candle = "BEARISH"

        else:

            candle = "NEUTRAL"

        return jsonify({

            "status":
                "success",

            "symbol":
                symbol,

            "price":
                round(price, 2),

            "candle":
                candle
        })

    except Exception as e:

        return jsonify({

            "status":
                "error",

            "symbol":
                symbol,

            "message":
                str(e)

        }), 500


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=10000
    )
