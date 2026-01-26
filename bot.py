import os
import json
import time
import requests
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
POLY_API_KEY = os.getenv("POLY_API_KEY")

# Wallets File
WALLETS_FILE = "wallets.json"

def load_wallets():
    if os.path.exists(WALLETS_FILE):
        try:
            with open(WALLETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading wallets.json: {e}")
            return {}
    else:
        # Create default file if not exists
        default_wallets = {"0xYourWalletAddressHere": "Ornek Cuzdan 1"}
        try:
            with open(WALLETS_FILE, "w", encoding="utf-8") as f:
                json.dump(default_wallets, f, indent=4)
        except Exception as e:
             logging.error(f"Error creating default wallets.json: {e}")
        return default_wallets

# Load wallets initially
WALLET_LIST = load_wallets()

# File to store the last processed transaction hash for each wallet
STATE_FILE = "state.json"
API_BASE_URL = "https://data-api.polymarket.com"

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        logging.warning("Telegram configuration missing. Skipping notification.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send Telegram message: {e}")

def get_user_activity(address):
    url = f"{API_BASE_URL}/activity"
    params = {
        "user": address,
        "limit": 10,
        "type": "TRADE"
    }
    headers = {}
    if POLY_API_KEY:
        headers["Authorization"] = f"Bearer {POLY_API_KEY}"

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 429:
            logging.warning("Rate limit hit. Sleeping for 5 seconds.")
            time.sleep(5)
            # Retry once after sleep? Or just skip to next cycle.
            # Let's simple return empty list to not crash loop
            return []
            
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching activity for {address}: {e}")
        return []

def process_wallet(address, name, last_tx_hash):
    activities = get_user_activity(address)
    if not activities:
        return last_tx_hash

    # Activities are usually returned newest first.
    # We process them in reverse order (oldest to newest) if we want to catch up, 
    # but for simplicity in a loop, we just check if it's new.
    
    # Found newest hash in the list
    newest_hash_in_batch = last_tx_hash
    
    # Filter for new trades only
    new_trades = []
    
    for activity in activities:
        tx_hash = activity.get("transactionHash") or activity.get("id") # Fallback to ID if hash missing
        
        if not tx_hash:
            continue
            
        if tx_hash == last_tx_hash:
            break
            
        new_trades.append(activity)
    
    # If last_tx_hash was None (first run), we might not want to spam all history.
    if last_tx_hash is None:
        if activities:
             # First run: Mark the most recent one as seen, don't alert (or alert only latest?)
             logging.info(f"First run for {name}. Setting baseline to latest transaction.")
             return activities[0].get("transactionHash") or activities[0].get("id")
        return None

    # Process new trades (reverse to send notifications in chronological order)
    if new_trades:
        for trade in reversed(new_trades):
            notify_trade(trade, name, address)
            newest_hash_in_batch = trade.get("transactionHash") or trade.get("id")

    return newest_hash_in_batch

def notify_trade(trade, name, address):
    # Parse Trade Details
    side = trade.get("side", "UNKNOWN") # BUY / SELL
    size = trade.get("size", "0")
    price = trade.get("price", "0")
    asset = trade.get("asset", "Unknown Asset")
    
    # Try to find a readable name for the market/asset
    # The API might return 'marketSlug' or 'outcome'
    market_slug = trade.get("marketSlug", "")
    outcome = trade.get("outcome", "")
    
    market_display = market_slug if market_slug else asset
    
    # Determine Action (ALDI/SATTI)
    # logic: if side == "BUY", it's usually ALDI.
    if side.upper() == "BUY":
        action = "ALDI 🟢"
    elif side.upper() == "SELL":
        action = "SATTI 🔴"
    else:
        action = f"{side} ⚪"

    message = (
        f"👤 <b>Cüzdan:</b> {name}\n"
        f"📝 <b>Eylem:</b> {action}\n"
        f"💰 <b>Miktar:</b> {size} @ {price}\n"
        f"📊 <b>Market:</b> {market_display} ({outcome})\n"
        f"🔗 <a href='https://polymarket.com/profile/{address}'>Profil Linki</a>"
    )
    
    send_telegram_message(message)
    logging.info(f"Notification sent for {name}: {action} {size} @ {price}")

def main():
    logging.info("Polymarket Bot Started...")
    
    # Check if config is filled
    if not TELEGRAM_BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN is missing in .env file!")
        return

    if not CHAT_ID:
        logging.warning("⚠️ CHAT_ID is missing in .env file! Notifications will NOT be sent.")
        logging.warning("Please run 'python get_chat_id.py' to find your Chat ID.")

    state = load_state()
    
    while True:
        try:
            for address, name in WALLET_LIST.items():
                if address == "0xYourWalletAddressHere":
                    logging.warning("⚠️ Monitor list contains '0xYourWalletAddressHere'. Please edit WALLET_LIST in bot.py!")
                    continue
                    
                logging.info(f"Checking {name} ({address})...")
                
                last_tx = state.get(address)
                new_last_tx = process_wallet(address, name, last_tx)
                
                if new_last_tx and new_last_tx != last_tx:
                    state[address] = new_last_tx
                    save_state(state)
                    
                # Short sleep between wallets to be nice to API
                time.sleep(2)
                
            logging.info("Cycle complete. Waiting 60s...")
            time.sleep(60)
            
        except KeyboardInterrupt:
            logging.info("Bot stopped by user.")
            break
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            time.sleep(60) # Wait before retrying

if __name__ == "__main__":
    main()
