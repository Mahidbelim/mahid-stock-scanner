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

DAILY_BATCH_SIZE = 100
SHORTLIST_SIZE = 30
FINAL_SIZE = 5

MAX_SCAN_SECONDS = 240

# Fresh setup filters
MAX_5D_MOVE = 5.0
MAX_1D_MOVE = 3.0

# How close price should be to resistance/support
LEVEL_DISTANCE = 0.012
TIGHT_LEVEL_DISTANCE = 0.006

# Avoid stocks which already made a large breakout candle
MAX_CANDLE_BODY_ATR = 1.25

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
# GET SYMBOL DATA
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
        open_price = df["Open"].astype(float)
        volume = df["Volume"].astype(float)

        price = float(close.iloc[-1])

        if price <= 0:
            return None

        # =================================================
        # CURRENT DAY MOVE
        # =================================================

        today_open = float(
            open_price.iloc[-1]
        )

        day_change = (
            (price / today_open) - 1
        ) * 100

        # =================================================
        # 5 DAY MOVE
        # =================================================

        change_5d = (
            price /
            float(close.iloc[-6]) -
            1
        ) * 100

        # =================================================
        # TOO MUCH MOVE FILTER
        # =================================================

        if abs(change_5d) > MAX_5D_MOVE:
            return None

        if abs(day_change) > MAX_1D_MOVE:
            return None

        # =================================================
        # EMA
        # =================================================

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

        # =================================================
        # VOLUME
        # =================================================

        previous_volume = volume.iloc[-21:-1]

        if len(previous_volume) < 10:
            return None

        avg_volume = float(
            previous_volume.mean()
        )

        if avg_volume <= 0:
            return None

        volume_ratio = (
            float(volume.iloc[-1]) /
            avg_volume
        )

        # =================================================
        # SUPPORT / RESISTANCE
        # =================================================

        previous_high = float(
            high.iloc[-21:-1].max()
        )

        previous_low = float(
            low.iloc[-21:-1].min()
        )

        # =================================================
        # ATR
        # =================================================

        previous_close = close.shift(1)

        tr1 = high - low
        tr2 = (
            high -
            previous_close
        ).abs()

        tr3 = (
            low -
            previous_close
        ).abs()

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

        # =================================================
        # CURRENT CANDLE
        # =================================================

        o = float(
            open_price.iloc[-1]
        )

        h = float(
            high.iloc[-1]
        )

        l = float(
            low.iloc[-1]
        )

        c = float(
            close.iloc[-1]
        )

        bullish = c > o
        bearish = c < o

        candle_range = max(
            h - l,
            0.01
        )

        body = abs(c - o)

        body_ratio = (
            body /
            candle_range
        )

        # =================================================
        # ALREADY BREAKOUT?
        # =================================================

        already_breakout = (
            price >
            previous_high
        )

        already_breakdown = (
            price <
            previous_low
        )

        # =================================================
        # LEVEL DISTANCE
        # =================================================

        resistance_distance = (
            previous_high - price
        ) / price

        support_distance = (
            price - previous_low
        ) / price

        near_resistance = (
            0 <= resistance_distance
            <= LEVEL_DISTANCE
        )

        very_near_resistance = (
            0 <= resistance_distance
            <= TIGHT_LEVEL_DISTANCE
        )

        near_support = (
            0 <= support_distance
            <= LEVEL_DISTANCE
        )

        # =================================================
        # REJECT ALREADY MOVED STOCK
        # =================================================

        if already_breakout:
            return None

        if already_breakdown:
            return None

        # Huge candle = move may already be happening
        if body > atr * MAX_CANDLE_BODY_ATR:
            return None

        # =================================================
        # SCORE
        # =================================================

        score = 0

        reasons = []

        setup = "WATCH"

        # -------------------------------------------------
        # TREND
        # -------------------------------------------------

        if price > ema20:
            score += 8
            reasons.append("Above EMA20")

        if ema20 > ema50:
            score += 8
            reasons.append("EMA20 > EMA50")

        # -------------------------------------------------
        # FRESH MOMENTUM
        # -------------------------------------------------

        if 0.5 <= change_5d <= 3.0:

            score += 10
            reasons.append(
                "Fresh bullish momentum"
            )

        elif -3.0 <= change_5d <= -0.5:

            score += 10
            reasons.append(
                "Fresh bearish momentum"
            )

        # -------------------------------------------------
        # VOLUME BUILDUP
        # -------------------------------------------------

        if 1.15 <= volume_ratio < 2.0:

            score += 12
            reasons.append(
                "Volume buildup"
            )

        elif 1.0 <= volume_ratio < 1.15:

            score += 5

        elif volume_ratio >= 2.5:

            # Huge volume can mean move already started
            score -= 8
            reasons.append(
                "Late volume spike"
            )

        # -------------------------------------------------
        # VOLATILITY
        # -------------------------------------------------

        if 1.0 <= atr_percent <= 4.0:

            score += 8
            reasons.append(
                "Good volatility"
            )

        # -------------------------------------------------
        # PRE-BREAKOUT
        # -------------------------------------------------

        if near_resistance:

            score += 20
            setup = "PRE-BREAKOUT"

            reasons.append(
                "Near resistance"
            )

        if very_near_resistance:

            score += 8
            reasons.append(
                "Resistance pressure"
            )

        # -------------------------------------------------
        # SUPPORT REVERSAL
        # -------------------------------------------------

        if near_support and bullish:

            score += 20
            setup = "SUPPORT REVERSAL"

            reasons.append(
                "Support reversal"
            )

        # -------------------------------------------------
        # CANDLE
        # -------------------------------------------------

        if bullish:

            upper_wick = h - c
            lower_wick = o - l

            if (
                lower_wick > body
                and
                lower_wick > upper_wick
            ):

                score += 8

                if setup == "WATCH":
                    setup = "SUPPORT REVERSAL"

                reasons.append(
                    "Bullish rejection"
                )

        elif bearish:

            upper_wick = h - o
            lower_wick = c - l

            if (
                upper_wick > body
                and
                upper_wick > lower_wick
            ):

                score += 8

                if setup == "WATCH":
                    setup = "RESISTANCE REJECTION"

                reasons.append(
                    "Bearish rejection"
                )

        # =================================================
        # IMPORTANT:
        # DO NOT REWARD ALREADY-BROKEN LEVEL
        # =================================================

        # No breakout points here.
        # This is intentional.

        # =================================================
        # FINAL FILTER
        # =================================================

        if score < 38:
            return None

        # Need either a level setup or meaningful volume
        if (
            setup == "WATCH"
            and volume_ratio < 1.15
        ):
            return None

        return {

            "symbol": symbol,

            "price": round(
                price,
                2
            ),

            "score": int(
                max(score, 0)
            ),

            "setup": setup,

            "change_5d": round(
                change_5d,
                2
            ),

            "day_change": round(
                day_change,
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

            "distance_resistance": round(
                resistance_distance * 100,
                2
            ),

            "distance_support": round(
                support_distance * 100,
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

            if len(df) < 30:
                continue

            last = df.iloc[-1]

            price = float(
                last["Close"]
            )

            open_price = float(
                last["Open"]
            )

            high = float(
                last["High"]
            )

            low = float(
                last["Low"]
            )

            volume = float(
                last["Volume"]
            )

            # =================================================
            # 5M AVERAGE VOLUME
            # =================================================

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

                volume_ratio = 1.0

            # =================================================
            # 5M LEVELS
            # =================================================

            recent = df.tail(30)

            support = float(
                recent["Low"].min()
            )

            resistance = float(
                recent["High"].max()
            )

            # Previous 5M high excluding current candle
            previous_5m_high = float(
                df["High"]
                .tail(21)
                .iloc[:-1]
                .max()
            )

            previous_5m_low = float(
                df["Low"]
                .tail(21)
                .iloc[:-1]
                .min()
            )

            bullish = (
                price >
                open_price
            )

            bearish = (
                price <
                open_price
            )

            # =================================================
            # 5M DISTANCE
            # =================================================

            resistance_distance = (
                previous_5m_high -
                price
            ) / price

            support_distance = (
                price -
                previous_5m_low
            ) / price

            near_resistance = (
                0 <=
                resistance_distance
                <= 0.006
            )

            near_support = (
                0 <=
                support_distance
                <= 0.006
            )

            # =================================================
            # DO NOT CONFIRM IF ALREADY BROKEN
            # =================================================

            already_5m_breakout = (
                price >
                previous_5m_high
            )

            already_5m_breakdown = (
                price <
                previous_5m_low
            )

            if already_5m_breakout:
                continue

            if already_5m_breakdown:
                continue

            # =================================================
            # 5M CANDLE
            # =================================================

            candle_range = max(
                high - low,
                0.01
            )

            body = abs(
                price -
                open_price
            )

            # Reject huge candle
            if (
                body /
                candle_range
            ) > 0.75:
                continue

            # =================================================
            # CONFIRMATION
            # =================================================

            confirmation = 0
            confirmation_reasons = []

            # Volume buildup
            if 1.15 <= volume_ratio < 2.5:

                confirmation += 20

                confirmation_reasons.append(
                    "5M volume buildup"
                )

            # Pre-breakout pressure
            if (
                item["setup"] ==
                "PRE-BREAKOUT"
                and
                near_resistance
                and
                bullish
            ):

                confirmation += 25

                confirmation_reasons.append(
                    "5M breakout pressure"
                )

            # Support reversal
            if (
                item["setup"] ==
                "SUPPORT REVERSAL"
                and
                near_support
                and
                bullish
            ):

                confirmation += 25

                confirmation_reasons.append(
                    "5M support reaction"
                )

            # Resistance rejection
            if (
                near_resistance
                and
                bearish
            ):

                confirmation += 15

                confirmation_reasons.append(
                    "5M resistance rejection"
                )

            # Price close to resistance
            if near_resistance:

                confirmation += 10

            # Price close to support
            if near_support:

                confirmation += 10

            # =================================================
            # MINIMUM CONFIRMATION
            # =================================================

            if confirmation < 15:
                continue

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
                item["score"] +
                confirmation
            )

            if confirmation_reasons:

                item["reason"] = (
                    item["reason"] +
                    ", " +
                    ", ".join(
                        confirmation_reasons[:2]
                    )
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

        # =================================================
        # NSE SYMBOLS
        # =================================================

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

        # =================================================
        # DAILY SCAN
        # =================================================

        candidates = []

        for start in range(
            0,
            len(symbols),
            DAILY_BATCH_SIZE
        ):

            if (
                time.time() -
                start_time >
                MAX_SCAN_SECONDS
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
                f"Scanning fresh setups "
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

        # =================================================
        # SORT
        # =================================================

        candidates.sort(
            key=lambda x:
            x["score"],
            reverse=True
        )

        shortlist = candidates[
            :SHORTLIST_SIZE
        ]

        print(
            "FRESH DAILY CANDIDATES:",
            len(candidates)
        )

        # =================================================
        # NO CANDIDATE
        # =================================================

        if not shortlist:

            SCAN["status"] = "complete"

            SCAN["message"] = (
                "Scan complete. "
                "No fresh pre-move setup found."
            )

            SCAN["results"] = []

            SCAN["updated"] = (
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            return

        # =================================================
        # 5M CONFIRMATION
        # =================================================

        SCAN["message"] = (
            f"{len(shortlist)} fresh setups found. "
            f"Checking 5M pre-move confirmation..."
        )

        print(
            SCAN["message"]
        )

        final = confirm_5m(
            shortlist
        )

        # IMPORTANT:
        # Do NOT return unconfirmed daily stocks.
        # Otherwise old problem can come back.

        SCAN["results"] = final

        SCAN["status"] = "complete"

        SCAN["message"] = (
            f"Scan complete. "
            f"{len(final)} fresh setup(s) found."
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
            "Scanner error: " +
            str(e)
        )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return jsonify({

        "status":
            "success",

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

    if SCAN["status"] == "scanning":

        return jsonify({

            "status":
                "scanning",

            "message":
                SCAN["message"],

            "results":
                SCAN["results"],

            "progress":
                SCAN["progress"],

            "total":
                SCAN["total"]
        })

    thread = threading.Thread(
        target=run_scan,
        daemon=True
    )

    thread.start()

    return jsonify({

        "status":
            "scanning",

        "message":
            "Fresh setup scan started. "
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

        if (
            last["Close"] >
            last["Open"]
        ):

            candle = "BULLISH"

        elif (
            last["Close"] <
            last["Open"]
        ):

            candle = "BEARISH"

        else:

            candle = "NEUTRAL"

        return jsonify({

            "status":
                "success",

            "symbol":
                symbol,

            "price":
                round(
                    price,
                    2
                ),

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
