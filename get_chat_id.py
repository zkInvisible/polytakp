import requests
import os
import time
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def get_chat_id():
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    print(f"Checking for updates from bot... (Send a message to your bot now!)")
    
    while True:
        try:
            response = requests.get(url)
            data = response.json()
            
            if data.get("ok"):
                results = data.get("result", [])
                if results:
                    last_update = results[-1]
                    chat_id = last_update.get("message", {}).get("chat", {}).get("id")
                    username = last_update.get("message", {}).get("chat", {}).get("username")
                    
                    if chat_id:
                        print(f"\nSUCCESS! Found Chat ID:")
                        print(f"Chat ID: {chat_id}")
                        print(f"Username: {username}")
                        print(f"\nPlease add this Chat ID to your .env file or bot.py settings.")
                        return
            
            time.sleep(2)
            print(".", end="", flush=True)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    get_chat_id()
