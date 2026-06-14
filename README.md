# BingX SOL/USDT Auto-Trade Bot 🤖

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Exchange](https://img.shields.io/badge/Exchange-BingX-orange)
![Mode](https://img.shields.io/badge/Default-Paper%20Trading-brightgreen)

An automated algorithmic trading bot for **SOL/USDT Perpetual Futures** on the [BingX](https://bingx.com) exchange. It uses **MACD + RSI** technical indicators to detect high-confidence entry signals and executes trades automatically — with full Telegram notifications, circuit breaker risk management, and automatic crash recovery.

> ⚠️ **Start in Demo mode (default).** Trade with virtual money first to verify the strategy before enabling real money.

---

## 📸 What It Looks Like

**Terminal on startup:**
```
=======================================================
  BingX SOL/USDT Auto-Trade Bot  v4
=======================================================
  Symbol       : SOL-USDT
  Interval     : 1h
  Leverage     : 5x
  Trade Size   : $20.0 USDT
  Min Conf     : 60%
  Min Balance  : $15.0 USDT
  Max DailyLoss: $50.0
  Heartbeat    : every 30min
  API URL      : DEMO — open-api-vst.bingx.com
  Mode         : PAPER TRADING (safe)
=======================================================
```

**Telegram notifications you'll receive:**
- 🤖 Bot started
- 💓 Heartbeat every 30 min (Win rate, PnL, status)
- 🟢 LONG signal fired
- 🔴 SHORT signal fired
- ✅ Trade WIN
- ❌ Trade LOSS
- 🛑 Circuit breaker activated
- ⚠️ Bot error / crash alerts

---

## ✨ Features

| Feature | Description |
|---|---|
| 📈 **MACD + RSI Signals** | Detects bullish/bearish crossovers with confidence scoring |
| 🛡️ **Circuit Breaker** | Auto-pauses trading if daily loss limit is hit |
| 💓 **Heartbeat Ping** | Sends Telegram status every 30 minutes |
| 💾 **State Persistence** | Survives restarts — saves position and stats to disk |
| 🔄 **Auto-Restart** | Exponential backoff retry on API errors, auto-restart on crash |
| 📲 **Telegram Alerts** | Every event — trades, wins, losses, errors — sent to your phone |
| 💰 **Balance Guard** | Skips trade if available USDT is below minimum |
| 📝 **Demo + Live Mode** | Test safely on BingX demo exchange before going live |

---

## 🛠️ Setup Guide

### Prerequisites
- Python 3.10 or higher
- A [BingX account](https://bingx.com) with API access enabled
- A Telegram bot (created via [@BotFather](https://t.me/BotFather))

---

### Step 1 — Clone the Repository
```bash
git clone https://github.com/yourusername/bingx-autotrade-bot.git
cd bingx-autotrade-bot
```

### Step 2 — Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3 — Create Your `.env` File
Copy the example file and fill in your credentials:
```bash
cp env.example .env
```
Open `.env` and add:
```env
BINGX_API_KEY=your_bingx_api_key_here
BINGX_API_SECRET=your_bingx_api_secret_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

> 🔑 **How to get your BingX API keys:** Go to [BingX API Management](https://bingx.com/en/account/api/) → Create API → Enable `Read` + `Perpetual Futures` permissions. **Never enable Withdrawal.**

> 📲 **How to get your Telegram credentials:**
> 1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **Bot Token**
> 2. Message [@userinfobot](https://t.me/userinfobot) → copy your **Chat ID**
> 3. Open your bot on Telegram and click **Start** (required before it can message you)

### Step 4 — Run the Bot
```bash
python -X utf8 bingx_autotrade_bot.py
```

**Windows users** — just double-click `start_bot.bat` ✅

---

## ⚙️ Configuration

All settings are at the top of [`bingx_autotrade_bot.py`](bingx_autotrade_bot.py):

```python
# ── Trading Pair ────────────────────────────────────
SYMBOL         = "SOL-USDT"    # Coin pair to trade
INTERVAL       = "1h"          # Candle timeframe: 1m 5m 15m 1h 4h 1d
LIMIT          = 100           # Number of candles to fetch

# ── Position Sizing ─────────────────────────────────
TRADE_USDT     = 20.0          # USDT per trade (your position size)
LEVERAGE       = 5             # Leverage multiplier (5x)

# ── Risk Management ─────────────────────────────────
STOP_LOSS_PCT  = 0.015         # Stop loss at 1.5%
TARGET_PCT     = 0.030         # Take profit at 3.0% (1:2 risk/reward)
MIN_CONFIDENCE = 60            # Minimum signal score to trade (0-100)
MIN_BALANCE    = 15.0          # Skip trade if USDT balance below this
MAX_DAILY_LOSS_USDT = 50.0     # Circuit breaker: pause if day loss > $50

# ── Live vs Demo ─────────────────────────────────────
LIVE_TRADING   = False         # ⚠️ Set True ONLY when ready for real money
BINGX_BASE_URL = DEMO_URL      # Change to LIVE_URL for real trading
```

---

## 🔴 Enabling Live Trading

> ⚠️ **Only do this after paper/demo trading for at least 1 week!**

1. Open `bingx_autotrade_bot.py`
2. Change these two lines:
```python
LIVE_TRADING   = True
BINGX_BASE_URL = LIVE_URL   # "https://open-api.bingx.com"
```
3. Save and restart the bot.

> 💡 **ISP Blocking Note:** Some Internet Service Providers (especially in India, Singapore, etc.) block direct connections to `open-api.bingx.com`. If you get `ConnectionResetError`, use a **VPN** or deploy the bot on a **cloud VPS** (e.g., AWS, DigitalOcean, Hetzner). The Demo URL (`open-api-vst.bingx.com`) is NOT blocked and works fine locally.

---

## 🚀 Running Automatically on Windows Startup

1. Press `Win + R`, type `shell:startup`, press Enter
2. Right-click `start_bot.bat` → **Create Shortcut**
3. Move the shortcut into the Startup folder that opened

The bot will now auto-launch every time you log into Windows!

---

## 📊 How the Signal Works

The bot checks the market every **60 minutes** using these indicators:

| Indicator | Role |
|---|---|
| **MACD Histogram** | Detects momentum crossovers (main trigger) |
| **RSI-6** | Confirms signal strength and filters overbought/oversold |
| **Volume** | Confirms signal with volume spike (>1.2x 20-period average) |
| **Support/Resistance** | Adds confidence if price is near key levels |

**Signal Scoring (Confidence %):**
- MACD crossover detected → +40%
- RSI has room to move → +20%
- Volume spike present → +20%
- Near support/resistance → +20%
- **Minimum required: 60%** to place a trade

---

## 🔒 Security Best Practices

- ✅ **Never commit `.env`** — the `.gitignore` is pre-configured to block it
- ✅ **API permissions** — only enable `Read` + `Perpetual Futures` on BingX. **Never Withdrawal**
- ✅ **Start with Demo** — test for at least 1 week before going live
- ✅ **Set a stop loss** — always use `STOP_LOSS_PCT` to protect your capital
- ✅ **Use circuit breaker** — `MAX_DAILY_LOSS_USDT` automatically pauses trading on bad days

---

## 📁 File Structure

```
bingx-autotrade-bot/
├── bingx_autotrade_bot.py  # Main bot script
├── start_bot.bat           # Windows one-click launcher (with auto-restart)
├── env.example             # Template for your .env credentials
├── requirements.txt        # Python dependencies
├── .gitignore              # Keeps your .env and logs off GitHub
├── LICENSE                 # MIT License
└── README.md               # This file
```

---

## 📜 License

This project is open-source under the [MIT License](LICENSE).

---

## ⚠️ Disclaimer

This bot is for **educational purposes only**. Cryptocurrency trading carries significant financial risk. Past performance of any algorithm does not guarantee future results. **Trade at your own risk.** The author is not responsible for any financial losses incurred.
