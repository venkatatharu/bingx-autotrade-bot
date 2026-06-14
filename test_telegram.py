import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

print("Testing Telegram Connection...")
print(f"Bot Token: {TOKEN[:15]}...{TOKEN[-10:]}")
print(f"Chat ID: {CHAT_ID}")

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
data = {
    "chat_id": CHAT_ID,
    "text": "🔔 *Telegram test message from BingX Bot!* If you see this, your credentials are correct.",
    "parse_mode": "Markdown"
}

try:
    r = requests.post(url, json=data, timeout=10)
    print("Response Status Code:", r.status_code)
    print("Response JSON:", r.json())
    if r.status_code == 200:
        print("✅ SUCCESS! Message sent successfully. Check your Telegram!")
    else:
        print("❌ FAILED! Check the error description above.")
        print("\n💡 Tip: Make sure you have opened a chat with your bot on Telegram and clicked 'Start' or sent a message to it first!")
except Exception as e:
    print("Error:", e)
