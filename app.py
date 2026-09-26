from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)
CORS(app)

NSE_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return jsonify({
        "status": "success",
        "message": "Mahid Scanner is running",
        "data_api": "/api/stock/RELIANCE",
        "scanner_api": "/api/scan"
    })


# =========================================================
# NSE STOCK LIST
# =========================================================

def get_nse_symbols():

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )
    }

    try:

        response = requests.get(
            NSE_LIST_URL,
            headers=headers,
            timeout=20
        )

        response.raise_for_status()

        df = pd.read_csv(
            io.StringIO(response.text)
        )

        if "SYMBOL" not in df.columns:
            return []

        symbols = []

        for _, row in df.iterrows():

            symbol = str(
                row["SYMBOL"]
            ).strip().upper()

            series = str(
                row.get(" SERIES", row.get("SERIES", "EQ"))
            ).strip().upper()

            if (
                symbol
                and symbol != "NAN"
                and series == "EQ"
            ):
                symbols.append(symbol)

        return sorted(
            list(set(symbols))
        )

    except Exception:

        return []


# =========================================================
# SAFE NUMBER
# =========================================================

def safe_float(value):

    try:

        if pd.isna(value):
            return None

        return float(value)

    except Exception:

        return None


# =========================================================
# DAILY ANALYSIS
# =========================================================

def analyze_daily(symbol):

    try:

        ticker = symbol + ".NS"

        data = yf.download(
            ticker,
            period="6mo",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False
        )

        if data is None or data.empty:
            return None

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        required = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
        ]

        for col in required:

            if col not in data.columns:
                return None

        data = data.dropna(
            subset=required
        )

        if len(data) < 60:
            return None

        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"]

        price = float(close.iloc[-1])

        previous_close = float(
            close.iloc[-2]
        )

        day_change_pct = (
            (price - previous_close)
            / previous_close
        ) * 100

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

        avg_volume = float(
            volume.iloc[-21:-1].mean()
        )

        current_volume = float(
            volume.iloc[-1]
        )

        if avg_volume > 0:
            volume_ratio = (
                current_volume
                / avg_volume
            )
        else:
            volume_ratio = 1.0

        # -------------------------------------------------
        # 20 DAY RANGE
        # -------------------------------------------------

        recent20 = data.tail(20)

        high20 = float(
            recent20["High"].max()
        )

        low20 = float(
            recent20["Low"].min()
        )

        range20 = high20 - low20

        if range20 <= 0:
            return None

        range_position = (
            (price - low20)
            / range20
        )

        # -------------------------------------------------
        # ATR
        # -------------------------------------------------

        previous = close.shift(1)

        tr1 = high - low

        tr2 = abs(
            high - previous
        )

        tr3 = abs(
            low - previous
        )

        true_range = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        atr14 = float(
            true_range.rolling(14).mean().iloc[-1]
        )

        atr_percent = (
            atr14 / price
        ) * 100

        # -------------------------------------------------
        # BREAKOUT / BREAKDOWN
        # -------------------------------------------------

        previous_high20 = float(
            data["High"].iloc[-21:-1].max()
        )

        previous_low20 = float(
            data["Low"].iloc[-21:-1].min()
        )

        near_breakout = (
            price >=
            previous_high20 * 0.995
        )

        near_breakdown = (
            price <=
            previous_low20 * 1.005
        )

        # -------------------------------------------------
        # CANDLE
        # -------------------------------------------------

        open_price = float(
            data["Open"].iloc[-1]
        )

        candle_pct = (
            (price - open_price)
            / open_price
        ) * 100

        bullish = price > open_price
        bearish = price < open_price

        # -------------------------------------------------
        # SUPPORT / RESISTANCE
        # -------------------------------------------------

        support = float(
            data["Low"].tail(20).min()
        )

        resistance = float(
            data["High"].tail(20).max()
        )

        support_distance = (
            abs(price - support)
            / price
        )

        resistance_distance = (
            abs(price - resistance)
            / price
        )

        # -------------------------------------------------
        # SCORE
        # -------------------------------------------------

        up_score = 0
        down_score = 0

        up_reasons = []
        down_reasons = []

        # Trend
        if price > ema20:
            up_score += 10
            up_reasons.append(
                "Price above EMA20"
            )

        if price > ema50:
            up_score += 10
            up_reasons.append(
                "Price above EMA50"
            )

        if price < ema20:
            down_score += 10
            down_reasons.append(
                "Price below EMA20"
            )

        if price < ema50:
            down_score += 10
            down_reasons.append(
                "Price below EMA50"
            )

        # Momentum
        if range_position >= 0.70:
            up_score += 15
            up_reasons.append(
                "Strong upper-range position"
            )

        if range_position <= 0.30:
            down_score += 15
            down_reasons.append(
                "Strong lower-range position"
            )

        # Volume
        if volume_ratio >= 1.5:

            if bullish:
                up_score += 20
                up_reasons.append(
                    "Volume expansion"
                )

            elif bearish:
                down_score += 20
                down_reasons.append(
                    "Volume expansion"
                )

        elif volume_ratio >= 1.2:

            if bullish:
                up_score += 10

            elif bearish:
                down_score += 10

        # Breakout
        if near_breakout:

            up_score += 25

            up_reasons.append(
                "Near 20-day breakout"
            )

        # Breakdown
        if near_breakdown:

            down_score += 25

            down_reasons.append(
                "Near 20-day breakdown"
            )

        # Candle
        if bullish and candle_pct >= 0.5:

            up_score += 10

            up_reasons.append(
                "Strong bullish candle"
            )

        if bearish and candle_pct <= -0.5:

            down_score += 10

            down_reasons.append(
                "Strong bearish candle"
            )

        # Volatility
        if atr_percent >= 1.5:

            if up_score >= down_score:
                up_score += 5
                up_reasons.append(
                    "Good movement range"
                )
            else:
                down_score += 5
                down_reasons.append(
                    "Good movement range"
                )

        # -------------------------------------------------
        # DIRECTION
        # -------------------------------------------------

        if up_score > down_score:

            direction = "UP"

            score = up_score

            reasons = up_reasons

        elif down_score > up_score:

            direction = "DOWN"

            score = down_score

            reasons = down_reasons

        else:

            direction = "NEUTRAL"

            score = 0

            reasons = []

        # -------------------------------------------------
        # MINIMUM QUALITY FILTER
        # -------------------------------------------------

        if score < 55:

            return None

        return {
            "symbol": symbol,
            "price": round(price, 2),
            "previous_close": round(
                previous_close,
                2
            ),
            "change_percent": round(
                day_change_pct,
                2
            ),
            "direction": direction,
            "score": int(score),
            "volume_ratio": round(
                volume_ratio,
                2
            ),
            "atr_percent": round(
                atr_percent,
                2
            ),
            "support": round(
                support,
                2
            ),
            "resistance": round(
                resistance,
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
            "reasons": reasons
        }

    except Exception:

        return None


# =========================================================
# 5 MINUTE CONFIRMATION
# =========================================================

def confirm_5m(item):

    try:

        symbol = item["symbol"]

        ticker = yf.Ticker(
            symbol + ".NS"
        )

        data = ticker.history(
            period="5d",
            interval="5m"
        )

        if data is None or data.empty:
            return item

        data = data.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close",
                "Volume"
            ]
        )

        if len(data) < 25:
            return item

        last = data.iloc[-1]

        price = float(
            last["Close"]
        )

        open_price = float(
            last["Open"]
        )

        volume = float(
            last["Volume"]
        )

        avg_volume = float(
            data["Volume"]
            .tail(21)
            .iloc[:-1]
            .mean()
        )

        if avg_volume > 0:

            volume_ratio = (
                volume
                / avg_volume
            )

        else:

            volume_ratio = 1.0

        recent = data.tail(30)

        support_5m = float(
            recent["Low"].min()
        )

        resistance_5m = float(
            recent["High"].max()
        )

        bullish = (
            price > open_price
        )

        bearish = (
            price < open_price
        )

        item["price"] = round(
            price,
            2
        )

        item["volume_ratio_5m"] = round(
            volume_ratio,
            2
        )

        item["support_5m"] = round(
            support_5m,
            2
        )

        item["resistance_5m"] = round(
            resistance_5m,
            2
        )

        # 5M confirmation

        if item["direction"] == "UP":

            if bullish:
                item["score"] += 10
                item["confirmation"] = (
                    "5M bullish confirmation"
                )
            else:
                item["confirmation"] = (
                    "5M confirmation pending"
                )

        elif item["direction"] == "DOWN":

            if bearish:
                item["score"] += 10
                item["confirmation"] = (
                    "5M bearish confirmation"
                )
            else:
                item["confirmation"] = (
                    "5M confirmation pending"
                )

        return item

    except Exception:

        item["confirmation"] = (
            "5M data unavailable"
        )

        return item


# =========================================================
# NEXT DAY SCANNER
# =========================================================

@app.route("/api/scan")
def scan_market():

    try:

        symbols = get_nse_symbols()

        if not symbols:

            return jsonify({
                "status": "error",
                "message": (
                    "NSE stock list could not be loaded"
                )
            }), 500

        # -------------------------------------------------
        # DAILY SCAN
        # -------------------------------------------------

        candidates = []

        # Parallel scan
        with ThreadPoolExecutor(
            max_workers=8
        ) as executor:

            futures = {
                executor.submit(
                    analyze_daily,
                    symbol
                ): symbol
                for symbol in symbols
            }

            for future in as_completed(
                futures
            ):

                result = future.result()

                if result is not None:

                    candidates.append(
                        result
                    )

        # -------------------------------------------------
        # FIRST FILTER
        # -------------------------------------------------

        candidates.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        # Top 20 get 5M confirmation
        shortlist = candidates[:20]

        confirmed = []

        with ThreadPoolExecutor(
            max_workers=5
        ) as executor:

            futures = [
                executor.submit(
                    confirm_5m,
                    item
                )
                for item in shortlist
            ]

            for future in as_completed(
                futures
            ):

                try:

                    confirmed.append(
                        future.result()
                    )

                except Exception:
                    pass

        # -------------------------------------------------
        # FINAL SORT
        # -------------------------------------------------

        confirmed.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        # Only strong final setups
        final = [
            item
            for item in confirmed
            if item["score"] >= 60
        ]

        # Maximum 5 stocks
        final = final[:5]

        return jsonify({

            "status": "success",

            "market": "NSE",

            "universe_scanned": len(
                symbols
            ),

            "technical_candidates": len(
                candidates
            ),

            "final_count": len(
                final
            ),

            "message": (
                "Next-session movement "
                "candidates generated"
            ),

            "stocks": final

        })

    except Exception as e:

        return jsonify({

            "status": "error",

            "message": str(e)

        }), 500


# =========================================================
# EXISTING SINGLE STOCK API
# =========================================================

@app.route("/api/stock/<symbol>")
def stock(symbol):

    try:

        symbol = symbol.upper().strip()

        ticker = yf.Ticker(
            symbol + ".NS"
        )

        # 5 MINUTE DATA

        data_5m = ticker.history(
            period="5d",
            interval="5m"
        )

        if data_5m.empty:

            return jsonify({
                "status": "error",
                "symbol": symbol,
                "message": (
                    "5 minute data not available"
                )
            })

        data_5m = data_5m.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close"
            ]
        )

        last = data_5m.iloc[-1]

        price = float(
            last["Close"]
        )

        candle_open = float(
            last["Open"]
        )

        volume = int(
            last["Volume"]
        )

        recent_5m = data_5m.tail(30)

        intraday_high = float(
            recent_5m["High"].max()
        )

        intraday_low = float(
            recent_5m["Low"].min()
        )

        range_5m = (
            intraday_high
            - intraday_low
        )

        if range_5m <= 0:

            range_5m = max(
                price * 0.01,
                0.01
            )

        support_5m = (
            intraday_low
            + range_5m * 0.25
        )

        resistance_5m = (
            intraday_low
            + range_5m * 0.75
        )

        midpoint_5m = (
            intraday_low
            + range_5m * 0.50
        )

        # DAILY DATA

        data_day = ticker.history(
            period="3mo",
            interval="1d"
        )

        if not data_day.empty:

            data_day = data_day.dropna(
                subset=[
                    "High",
                    "Low",
                    "Close"
                ]
            )

            recent_day = data_day.tail(20)

            day_high = float(
                recent_day["High"].max()
            )

            day_low = float(
                recent_day["Low"].min()
            )

            day_range = (
                day_high
                - day_low
            )

            if day_range <= 0:

                day_range = max(
                    price * 0.05,
                    0.01
                )

            major_support = (
                day_low
                + day_range * 0.25
            )

            major_resistance = (
                day_low
                + day_range * 0.75
            )

        else:

            major_support = support_5m
            major_resistance = resistance_5m

        # VOLUME

        volume_data = (
            data_5m["Volume"]
            .tail(21)
            .iloc[:-1]
        )

        average_volume = float(
            volume_data.mean()
        )

        if average_volume > 0:

            volume_ratio = (
                volume
                / average_volume
            )

        else:

            volume_ratio = 1.0

        strong_volume = (
            volume_ratio >= 1.5
        )

        # CANDLE

        candle_close = float(
            last["Close"]
        )

        bullish_candle = (
            candle_close
            > candle_open
        )

        bearish_candle = (
            candle_close
            < candle_open
        )

        # ZONE

        if price < midpoint_5m:

            zone = "Discount Zone"

        elif price > midpoint_5m:

            zone = "Premium Zone"

        else:

            zone = "Equilibrium"

        support_distance = (
            abs(
                price - support_5m
            ) / price
        )

        resistance_distance = (
            abs(
                price - resistance_5m
            ) / price
        )

        near_support = (
            support_distance <= 0.003
        )

        near_resistance = (
            resistance_distance <= 0.003
        )

        signal = "WAIT"

        signal_reason = (
            "No confirmed setup"
        )

        if (

            zone == "Discount Zone"

            and near_support

            and bullish_candle

            and strong_volume

        ):

            signal = "BUY AREA"

            signal_reason = (
                "Discount zone + "
                "5M support + "
                "bullish candle + "
                "strong volume"
            )

        elif (

            zone == "Premium Zone"

            and near_resistance

            and bearish_candle

            and strong_volume

        ):

            signal = "SELL AREA"

            signal_reason = (
                "Premium zone + "
                "5M resistance + "
                "bearish candle + "
                "strong volume"
            )

        previous_data = ticker.history(
            period="5d",
            interval="1d"
        )

        previous_close = None

        if len(previous_data) >= 2:

            previous_close = float(
                previous_data[
                    "Close"
                ].iloc[-2]
            )

        change = None
        change_percent = None

        if previous_close is not None:

            change = (
                price
                - previous_close
            )

            change_percent = (
                change
                / previous_close
            ) * 100

        return jsonify({

            "status": "success",

            "symbol": symbol,

            "exchange": "NSE",

            "price": round(
                price,
                2
            ),

            "previous_close":
                round(
                    previous_close,
                    2
                )
                if previous_close is not None
                else None,

            "support_5m":
                round(
                    support_5m,
                    2
                ),

            "resistance_5m":
                round(
                    resistance_5m,
                    2
                ),

            "major_support":
                round(
                    major_support,
                    2
                ),

            "major_resistance":
                round(
                    major_resistance,
                    2
                ),

            "volume":
                volume,

            "average_volume":
                round(
                    average_volume,
                    0
                ),

            "volume_ratio":
                round(
                    volume_ratio,
                    2
                ),

            "zone":
                zone,

            "candle":
                "BULLISH"
                if bullish_candle
                else
                "BEARISH"
                if bearish_candle
                else
                "NEUTRAL",

            "signal":
                signal,

            "signal_reason":
                signal_reason,

            "change":
                round(
                    change,
                    2
                )
                if change is not None
                else None,

            "change_percent":
                round(
                    change_percent,
                    2
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


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )
