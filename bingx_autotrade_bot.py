"""
SOL/USDT BingX Auto-Trade Bot — v4 (Production Ready)
======================================================
Fixes in v4:
  ✅ NaN/null timestamp crash fixed (fetch_candles cleans bad candles)
  ✅ ConnectionResetError retry capped at 60s max (no infinite hang)
  ✅ Balance check before every live trade (min $15 guard)
  ✅ Demo vs Live URL clearly separated and auto-selected
  ✅ AUTO_CONFIRM env var for start_bot.bat launcher
  ✅ Log file written in UTF-8 (no emoji crash on Windows)
  ✅ All v3 features kept: heartbeat, circuit breaker, auto-restart

Run:
    python -X utf8 bingx_autotrade_bot.py
"""

import os, sys, hmac, time, json, hashlib, logging, schedule, traceback
import requests
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv
from datetime import datetime, date
from pathlib import Path

load_dotenv()

# ─────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("BingXBot")

# ─────────────────────────────────────────────────────
# CONFIG  ← Edit these settings
# ─────────────────────────────────────────────────────
BINGX_API_KEY      = os.getenv("BINGX_API_KEY", "")
BINGX_API_SECRET   = os.getenv("BINGX_API_SECRET", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ⚠️ URL controls Demo vs Live trading
DEMO_URL = "https://open-api-vst.bingx.com"   # Virtual/Demo — no real money
LIVE_URL = "https://open-api.bingx.com"        # Live — real money

LIVE_TRADING   = False       # ⚠️ Set True ONLY when ready for real money trades
# ⚠️ NOTE: Using DEMO_URL (open-api-vst.bingx.com) by default — safe for everyone.
# To trade with real money: set LIVE_TRADING = True AND BINGX_BASE_URL = LIVE_URL
# (also requires a VPN or VPS in a non-restricted region for some ISPs)
BINGX_BASE_URL = DEMO_URL

SYMBOL         = "SOL-USDT"
INTERVAL       = "1h"        # Options: 1m 5m 15m 1h 4h 1d
LIMIT          = 100

TRADE_USDT     = 20.0        # USDT per trade
LEVERAGE       = 5           # Leverage multiplier
STOP_LOSS_PCT  = 0.015       # 1.5% stop loss
TARGET_PCT     = 0.030       # 3.0% take profit (1:2 risk/reward)
MIN_CONFIDENCE = 60          # Minimum signal confidence to trade
MIN_BALANCE    = 15.0        # Skip trade if balance below this (USDT)

MAX_DAILY_LOSS_USDT = 50.0   # Circuit breaker daily loss limit
MAX_RETRIES         = 5
RETRY_BASE_DELAY    = 5      # seconds (doubles each attempt, max 60s)
HEARTBEAT_INTERVAL  = 30     # minutes between heartbeat messages
STATE_FILE          = "bot_state.json"

# ─────────────────────────────────────────────────────
# STATE — Persisted to disk (survives restarts)
# ─────────────────────────────────────────────────────
DEFAULT_STATE = {
    "position": {
        "active": False, "side": None, "entry": None,
        "stop": None, "target": None, "order_id": None,
        "qty": None, "time": None
    },
    "stats": {
        "total_trades": 0, "wins": 0, "losses": 0,
        "total_pnl": 0.0, "daily_loss": 0.0,
        "last_reset_date": str(date.today())
    },
    "last_heartbeat": None
}

def load_state() -> dict:
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in DEFAULT_STATE.items():
                if k not in saved:
                    saved[k] = v
            return saved
        except Exception as e:
            log.warning(f"State load failed: {e} — using default")
    return json.loads(json.dumps(DEFAULT_STATE))

def save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error(f"State save failed: {e}")

def reset_daily_if_needed(state: dict) -> dict:
    if state["stats"]["last_reset_date"] != str(date.today()):
        log.info("New day — resetting daily loss counter")
        state["stats"]["daily_loss"] = 0.0
        state["stats"]["last_reset_date"] = str(date.today())
        save_state(state)
    return state

state = load_state()

# ─────────────────────────────────────────────────────
# RETRY HELPER
# ─────────────────────────────────────────────────────
def with_retry(func, *args, retries=MAX_RETRIES, **kwargs):
    """Call func with exponential backoff retry, capped at 60s per attempt."""
    delay = RETRY_BASE_DELAY
    for attempt in range(1, retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == retries:
                log.error(f"All {retries} retries failed [{func.__name__}]: {e}")
                raise
            log.warning(f"Attempt {attempt}/{retries} failed: {e} — retry in {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 60)  # ✅ FIX: cap at 60s, no infinite hanging

# ─────────────────────────────────────────────────────
# BINGX API
# ─────────────────────────────────────────────────────
def sign(params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(BINGX_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

def _raw_request(method: str, endpoint: str, params: dict, signed: bool) -> dict:
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    if signed:
        params["signature"] = sign(params)
    headers = {"X-BX-APIKEY": BINGX_API_KEY}
    url = BINGX_BASE_URL + endpoint
    if method == "GET":
        r = requests.get(url, params=params, headers=headers, timeout=15)
    else:
        r = requests.post(url, json=params, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise Exception(f"BingX [{data.get('code')}]: {data.get('msg')}")
    return data

def bingx_get(endpoint, params={}, signed=False):
    return with_retry(_raw_request, "GET", endpoint, params, signed)

def bingx_post(endpoint, params={}, signed=False):
    return with_retry(_raw_request, "POST", endpoint, params, signed)

# ─────────────────────────────────────────────────────
# ACCOUNT
# ─────────────────────────────────────────────────────
def get_balance() -> float:
    data = bingx_get("/openApi/swap/v2/user/balance", signed=True)
    balance_data = data["data"]["balance"]
    # Handle both list and dict response formats
    if isinstance(balance_data, list):
        for a in balance_data:
            if a["asset"] == "USDT":
                return float(a["availableMargin"])
    elif isinstance(balance_data, dict):
        return float(balance_data.get("availableMargin", 0))
    return 0.0

def get_open_position():
    # ✅ FIX: Fetch all positions (no symbol param) to avoid ISP connection reset
    data = bingx_get("/openApi/swap/v2/user/positions", signed=True)
    for p in data.get("data", []):
        if p.get("symbol") == SYMBOL and float(p.get("positionAmt", 0)) != 0:
            return p
    return None

def get_price() -> float:
    data = bingx_get("/openApi/swap/v2/quote/price", params={"symbol": SYMBOL})
    return float(data["data"]["price"])

def calc_qty(price: float) -> float:
    return round((TRADE_USDT * LEVERAGE) / price, 2)

def set_leverage():
    for side in ["LONG", "SHORT"]:
        try:
            bingx_post("/openApi/swap/v2/trade/leverage",
                       params={"symbol": SYMBOL, "side": side, "leverage": LEVERAGE},
                       signed=True)
        except Exception as e:
            log.warning(f"Set leverage {side} skipped (may already be set): {e}")

# ─────────────────────────────────────────────────────
# CANDLES  ← v4 FIX: Drop NaN/null rows before casting
# ─────────────────────────────────────────────────────
def fetch_candles() -> pd.DataFrame:
    data = bingx_get("/openApi/swap/v3/quote/klines",
                     params={"symbol": SYMBOL, "interval": INTERVAL, "limit": LIMIT})

    raw = data.get("data", [])
    if not raw:
        raise Exception("BingX returned empty candle data")

    df = pd.DataFrame(raw)

    # Rename 'time' → 'timestamp' (BingX v3 returns key 'time')
    if "time" in df.columns and "timestamp" not in df.columns:
        df = df.rename(columns={"time": "timestamp"})

    needed = ["timestamp", "open", "high", "low", "close", "volume"]
    for col in needed:
        if col not in df.columns:
            raise Exception(f"Missing column '{col}' in BingX response. Got: {list(df.columns)}")
    df = df[needed].copy()

    # ✅ FIX: Drop null/empty rows BEFORE type casting (prevents NaN crash)
    df = df.dropna(subset=needed)
    df = df[df["timestamp"].astype(str).str.strip() != ""]
    df = df[df["timestamp"] != 0]

    # Safe numeric conversion
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].astype("int64")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna()

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.sort_values("timestamp").reset_index(drop=True)

    if len(df) < 30:
        raise Exception(f"Not enough clean candles: only {len(df)} rows after cleanup")

    return df

# ─────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd_hist"] = macd["MACDh_12_26_9"]
    df["rsi6"]      = ta.rsi(df["close"], length=6)
    df["rsi12"]     = ta.rsi(df["close"], length=12)
    df["rsi24"]     = ta.rsi(df["close"], length=24)
    df["vol_ma"]    = df["volume"].rolling(20).mean()
    df["support"]   = df["low"].rolling(20).min()
    df["resistance"]= df["high"].rolling(20).max()
    return df

# ─────────────────────────────────────────────────────
# SIGNAL
# ─────────────────────────────────────────────────────
def generate_signal(df: pd.DataFrame) -> dict:
    cur, prev = df.iloc[-1], df.iloc[-2]
    price     = float(cur["close"])
    rsi6      = float(cur["rsi6"])
    mh        = float(cur["macd_hist"])
    pmh       = float(prev["macd_hist"])
    vol_spike = float(cur["volume"]) > float(cur["vol_ma"]) * 1.2

    signal = "NEUTRAL"; side = None; confidence = 0
    reasons = []; stop = target = None

    if (mh > 0 and pmh <= 0) and rsi6 < 70:         # LONG
        signal, side = "LONG", "BUY"
        stop   = round(price * (1 - STOP_LOSS_PCT), 3)
        target = round(price * (1 + TARGET_PCT), 3)
        confidence += 40; reasons.append("MACD bullish crossover")
        if rsi6 < 60:  confidence += 20; reasons.append(f"RSI6={rsi6:.1f} has room to grow")
        if vol_spike:  confidence += 20; reasons.append("Volume spike confirmed")
        if price <= float(cur["support"]) * 1.01:
            confidence += 20; reasons.append("Price near support level")

    elif (mh < 0 and pmh >= 0) and rsi6 > 30:        # SHORT
        signal, side = "SHORT", "SELL"
        stop   = round(price * (1 + STOP_LOSS_PCT), 3)
        target = round(price * (1 - TARGET_PCT), 3)
        confidence += 40; reasons.append("MACD bearish crossover")
        if rsi6 > 40:  confidence += 20; reasons.append(f"RSI6={rsi6:.1f} has room to fall")
        if vol_spike:  confidence += 20; reasons.append("Volume spike confirmed")
        if price >= float(cur["resistance"]) * 0.99:
            confidence += 20; reasons.append("Price near resistance level")

    return {
        "signal": signal, "side": side, "confidence": confidence,
        "price": price, "stop": stop, "target": target,
        "rsi6": round(rsi6, 2),
        "rsi12": round(float(cur["rsi12"]), 2),
        "rsi24": round(float(cur["rsi24"]), 2),
        "macd_hist": round(mh, 4), "reasons": reasons,
        "time": cur["timestamp"].strftime("%Y-%m-%d %H:%M"),
    }

# ─────────────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────────────
def place_order(side: str, qty: float, price: float) -> dict:
    params = {
        "symbol": SYMBOL, "side": side,
        "positionSide": "LONG" if side == "BUY" else "SHORT",
        "type": "MARKET", "quantity": qty
    }
    if LIVE_TRADING:
        data = bingx_post("/openApi/swap/v2/trade/order", params, signed=True)
        return data["data"]["order"]
    log.info(f"[PAPER] {side} {qty} SOL @ ${price:.3f}")
    return {"orderId": f"PAPER_{int(time.time())}"}

def place_sl_tp(side: str, qty: float, stop: float, target: float):
    close_side = "SELL" if side == "BUY" else "BUY"
    pos_side   = "LONG" if side == "BUY" else "SHORT"
    for order_type, px in [("STOP_MARKET", stop), ("TAKE_PROFIT_MARKET", target)]:
        params = {
            "symbol": SYMBOL, "side": close_side, "positionSide": pos_side,
            "type": order_type, "quantity": qty,
            "stopPrice": px, "closePosition": "true"
        }
        if LIVE_TRADING:
            bingx_post("/openApi/swap/v2/trade/order", params, signed=True)
    label = "set on exchange" if LIVE_TRADING else "[PAPER simulated]"
    log.info(f"SL @ ${stop} | TP @ ${target} — {label}")

# ─────────────────────────────────────────────────────
# POSITION MONITOR
# ─────────────────────────────────────────────────────
def monitor_position():
    global state
    pos = state["position"]
    if not pos["active"]:
        return

    price    = get_price()
    entry    = float(pos["entry"])
    side     = pos["side"]
    pnl_pct  = ((price - entry) / entry * 100) if side == "BUY" else ((entry - price) / entry * 100)
    pnl_usdt = round(TRADE_USDT * LEVERAGE * (pnl_pct / 100), 2)
    log.info(f"Monitor | ${price:.3f} | PnL: {pnl_pct:.2f}% (${pnl_usdt})")

    hit = None
    if side == "BUY":
        if price <= float(pos["stop"]):    hit = ("LOSS", price, pnl_pct, pnl_usdt)
        elif price >= float(pos["target"]): hit = ("WIN",  price, pnl_pct, pnl_usdt)
    else:
        if price >= float(pos["stop"]):    hit = ("LOSS", price, pnl_pct, pnl_usdt)
        elif price <= float(pos["target"]): hit = ("WIN",  price, pnl_pct, pnl_usdt)

    if hit:
        result, exit_price, pct, usdt = hit
        emoji = "✅" if result == "WIN" else "❌"
        send_telegram(
            f"*{emoji} SOL-USDT Trade {result}*\n"
            f"Entry:  `${entry}`\n"
            f"Exit:   `${exit_price:.3f}`\n"
            f"PnL:    `{pct:.2f}%` (`${usdt}`)\n"
            f"Mode:   {'LIVE' if LIVE_TRADING else 'PAPER'}"
        )
        stats = state["stats"]
        stats["total_trades"] += 1
        stats["total_pnl"]     = round(stats["total_pnl"] + usdt, 2)
        if result == "WIN":
            stats["wins"] += 1
        else:
            stats["losses"]     += 1
            stats["daily_loss"]  = round(stats["daily_loss"] + abs(usdt), 2)
        state["position"] = json.loads(json.dumps(DEFAULT_STATE["position"]))
        save_state(state)

# ─────────────────────────────────────────────────────
# CIRCUIT BREAKER
# ─────────────────────────────────────────────────────
def is_circuit_breaker_active() -> bool:
    dl = state["stats"]["daily_loss"]
    if dl >= MAX_DAILY_LOSS_USDT:
        log.warning(f"Circuit breaker! Daily loss ${dl} >= limit ${MAX_DAILY_LOSS_USDT}")
        send_telegram(
            f"*🛑 Circuit Breaker Activated*\n"
            f"Daily loss `${dl}` hit limit `${MAX_DAILY_LOSS_USDT}`\n"
            f"Trading paused until tomorrow."
        )
        return True
    return False

# ─────────────────────────────────────────────────────
# HEARTBEAT
# ─────────────────────────────────────────────────────
def send_heartbeat():
    global state
    stats   = state["stats"]
    pos     = state["position"]
    winrate = (stats["wins"] / stats["total_trades"] * 100) if stats["total_trades"] > 0 else 0
    send_telegram(
        f"*💓 Bot Heartbeat* | {datetime.now().strftime('%H:%M:%S')}\n\n"
        f"Status:  {'🟢 Position open' if pos['active'] else '⏳ Waiting for signal'}\n"
        f"Mode:    {'🔴 LIVE' if LIVE_TRADING else '📝 PAPER'}\n"
        f"API:     `{'LIVE' if BINGX_BASE_URL == LIVE_URL else 'DEMO (VST)'}`\n\n"
        f"*Stats:*\n"
        f"Trades: {stats['total_trades']} | W:{stats['wins']} L:{stats['losses']} | WR:{winrate:.0f}%\n"
        f"Total PnL:  `${stats['total_pnl']}`\n"
        f"Daily Loss: `${stats['daily_loss']}` / `${MAX_DAILY_LOSS_USDT}`"
    )
    state["last_heartbeat"] = str(datetime.now())
    save_state(state)

# ─────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────
def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.info(f"[Telegram off] {message[:80]}")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
        log.info("Telegram sent" if r.status_code == 200 else f"Telegram error: {r.text[:120]}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")

# ─────────────────────────────────────────────────────
# MAIN BOT CYCLE
# ─────────────────────────────────────────────────────
def run_bot():
    global state
    log.info("=" * 55)
    env_label = "LIVE" if BINGX_BASE_URL == LIVE_URL else "DEMO"
    log.info(f"Bot cycle | {SYMBOL} {INTERVAL} | {'LIVE' if LIVE_TRADING else 'PAPER'} | {env_label} API")

    try:
        state = reset_daily_if_needed(state)

        # 1 — Monitor existing position
        if state["position"]["active"]:
            monitor_position()
            if state["position"]["active"]:
                log.info("Position still open — skipping new signal")
                return

        # 2 — Circuit breaker check
        if is_circuit_breaker_active():
            return

        # 3 — Check for untracked live position
        if LIVE_TRADING:
            open_pos = get_open_position()
            if open_pos:
                log.warning("Untracked open position on BingX — skipping new trade")
                return

        # 4 — Balance check (live only) ✅ v4 FIX
        if LIVE_TRADING:
            balance = get_balance()
            log.info(f"Balance: ${balance:.2f} USDT")
            if balance < MIN_BALANCE:
                log.warning(f"Balance ${balance:.2f} < minimum ${MIN_BALANCE} — trade skipped")
                send_telegram(
                    f"⚠️ *Low Balance Warning*\n"
                    f"Available: `${balance:.2f}` USDT\n"
                    f"Minimum required: `${MIN_BALANCE}` USDT\n"
                    f"Trade skipped."
                )
                return

        # 5 — Generate signal
        df     = fetch_candles()
        df     = calculate_indicators(df)
        signal = generate_signal(df)
        log.info(f"Signal: {signal['signal']} | Conf:{signal['confidence']}% | ${signal['price']:.3f} | RSI6:{signal['rsi6']}")

        if signal["signal"] == "NEUTRAL":
            log.info("No signal — waiting for next cycle")
            return

        if signal["confidence"] < MIN_CONFIDENCE:
            log.info(f"Confidence {signal['confidence']}% < threshold {MIN_CONFIDENCE}% — skipping")
            return

        # 6 — Execute trade
        price = signal["price"]
        qty   = calc_qty(price)
        log.info(f"Executing {signal['signal']} | Qty:{qty} | SL:${signal['stop']} | TP:${signal['target']}")

        if LIVE_TRADING:
            set_leverage()

        order = place_order(signal["side"], qty, price)
        place_sl_tp(signal["side"], qty, signal["stop"], signal["target"])

        # 7 — Save position state
        state["position"] = {
            "active": True, "side": signal["side"],
            "entry": price, "stop": signal["stop"],
            "target": signal["target"], "order_id": order.get("orderId"),
            "qty": qty, "time": signal["time"]
        }
        save_state(state)

        emoji = "🟢" if signal["signal"] == "LONG" else "🔴"
        reasons_text = "\n".join(f"• {r}" for r in signal["reasons"])
        send_telegram(
            f"*{emoji} SOL-USDT {signal['signal']} {'LIVE' if LIVE_TRADING else '[PAPER]'}*\n"
            f"🕐 {signal['time']}\n\n"
            f"Entry:  `${price:.3f}`\n"
            f"Stop:   `${signal['stop']}`\n"
            f"Target: `${signal['target']}`\n"
            f"Qty:    `{qty} SOL` × `{LEVERAGE}x`\n"
            f"Conf:   `{signal['confidence']}%`\n\n"
            f"{reasons_text}\n\n"
            f"⚠️ _Trade at your own risk._"
        )
        log.info("Trade placed and state saved!")

    except Exception as e:
        log.error(f"Bot cycle error: {e}\n{traceback.format_exc()}")
        send_telegram(f"⚠️ *Bot Error*\n`{str(e)[:300]}`\nWill retry next cycle.")

# ─────────────────────────────────────────────────────
# AUTO-RESTART WRAPPER
# ─────────────────────────────────────────────────────
def run_forever():
    crash_count = 0
    max_crashes = 10

    while crash_count < max_crashes:
        try:
            log.info("Starting bot scheduler...")
            env_label = "LIVE — open-api.bingx.com" if BINGX_BASE_URL == LIVE_URL else "DEMO — open-api-vst.bingx.com"
            send_telegram(
                f"*🤖 BingX Bot v4 Started!*\n\n"
                f"Symbol:  `{SYMBOL}` | `{INTERVAL}`\n"
                f"Mode:    {'🔴 LIVE' if LIVE_TRADING else '📝 PAPER'}\n"
                f"API:     `{env_label}`\n"
                f"Trade:   `${TRADE_USDT}` × `{LEVERAGE}x lev`\n"
                f"Min Conf: `{MIN_CONFIDENCE}%`\n"
                f"Max Loss: `${MAX_DAILY_LOSS_USDT}/day`"
            )

            schedule.clear()
            schedule.every(60).minutes.do(run_bot)
            schedule.every(HEARTBEAT_INTERVAL).minutes.do(send_heartbeat)

            run_bot()        # Run immediately on start
            send_heartbeat() # Send first heartbeat

            while True:
                schedule.run_pending()
                time.sleep(1)

        except KeyboardInterrupt:
            log.info("Bot stopped by user (Ctrl+C)")
            send_telegram("🛑 *Bot manually stopped*")
            break

        except Exception as e:
            crash_count += 1
            wait = min(60 * crash_count, 300)
            log.error(f"Scheduler crashed #{crash_count}: {e}")
            send_telegram(
                f"*💥 Bot Crashed (#{crash_count}/{max_crashes})*\n"
                f"`{str(e)[:200]}`\n"
                f"Restarting in {wait}s..."
            )
            time.sleep(wait)

    log.critical(f"Too many crashes ({max_crashes}). Stopping.")
    send_telegram(f"*❌ Bot stopped after {max_crashes} crashes.*\nManual restart needed.")

# ─────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  BingX SOL/USDT Auto-Trade Bot  v4")
    print("=" * 55)
    print(f"  Symbol       : {SYMBOL}")
    print(f"  Interval     : {INTERVAL}")
    print(f"  Leverage     : {LEVERAGE}x")
    print(f"  Trade Size   : ${TRADE_USDT} USDT")
    print(f"  Min Conf     : {MIN_CONFIDENCE}%")
    print(f"  Min Balance  : ${MIN_BALANCE} USDT")
    print(f"  Max DailyLoss: ${MAX_DAILY_LOSS_USDT}")
    print(f"  Heartbeat    : every {HEARTBEAT_INTERVAL}min")
    print(f"  API URL      : {'LIVE — open-api.bingx.com' if BINGX_BASE_URL == LIVE_URL else 'DEMO — open-api-vst.bingx.com'}")
    print(f"  Mode         : {'LIVE TRADING (real money!)' if LIVE_TRADING else 'PAPER TRADING (safe)'}")
    print("=" * 55)

    if LIVE_TRADING and os.getenv("AUTO_CONFIRM") != "1":
        print("\n  WARNING: LIVE TRADING IS ON — real money will be used!")
        confirm = input("  Type YES to confirm: ")
        if confirm.strip() != "YES":
            print("  Cancelled.")
            sys.exit(0)

    run_forever()


# ═══════════════════════════════════════════════════
# .env FILE (create in same folder as this script)
# ═══════════════════════════════════════════════════
# BINGX_API_KEY=your_key
# BINGX_API_SECRET=your_secret
# TELEGRAM_BOT_TOKEN=your_bot_token
# TELEGRAM_CHAT_ID=your_chat_id
#
# BingX API permissions needed:
#   Read  +  Perpetual Futures  (NEVER enable Withdrawal!)
