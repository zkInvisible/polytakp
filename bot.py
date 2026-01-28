import os
import json
import time
import requests
import logging
import html
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()
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
GAMMA_API_URL = "https://gamma-api.polymarket.com"

# Cache for market names to avoid spamming API
# Asset ID -> Market Title
MARKET_CACHE = {}

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
        if e.response is not None:
             logging.error(f"Telegram Error Details: {e.response.text}")

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

def resolve_market_name(asset_id):
    """
    Fetches market title from Polymarket API using Asset ID (Token ID).
    """
    if not asset_id or asset_id == "Unknown Asset":
        return asset_id
        
    # Check cache first
    if asset_id in MARKET_CACHE:
        return MARKET_CACHE[asset_id]
        
    # Try Gamma API (markets logic)
    # We query /markets?clobTokenIds=... 
    
    url = f"{GAMMA_API_URL}/markets"
    params = {"clobTokenIds": asset_id}
    
    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                market = data[0]
                # Combine question + outcome if needed
                question = market.get("question", "Unknown Market")
                MARKET_CACHE[asset_id] = question
                return question
    except Exception as e:
        logging.warning(f"Failed to resolve market name for {asset_id}: {e}")
        
    return asset_id

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
    
    if market_slug:
        market_display = market_slug
    elif asset != "Unknown Asset":
        # Try to resolve valid Asset ID
        market_display = resolve_market_name(asset)
    else:
        market_display = asset
    
    # Determine Action (ALDI/SATTI)
    # logic: if side == "BUY", it's usually ALDI.
    if side.upper() == "BUY":
        action = "ALDI 🟢"
    elif side.upper() == "SELL":
        action = "SATTI 🔴"
    else:
        action = f"{side} ⚪"

    message = (
        f"👤 <b>Cüzdan:</b> {html.escape(str(name))}\n"
        f"📝 <b>Eylem:</b> {action}\n"
        f"💰 <b>Miktar:</b> {html.escape(str(size))} @ {html.escape(str(price))}\n"
        f"📊 <b>Market:</b> {html.escape(str(market_display))} ({html.escape(str(outcome))})\n"
        f"🔗 <a href='https://polymarket.com/profile/{address}'>Profil Linki</a>"
    )
    
    send_telegram_message(message)
    logging.info(f"Notification sent for {name}: {action} {size} @ {price}")


    
# duplicate suppression cache: address -> {asset_id, side, timestamp}
LAST_NOTIFICATION_CACHE = {}

def process_wallet(address, name, last_tx_hash):
    activities = get_user_activity(address)
    if not activities:
        return last_tx_hash

    # Found newest hash in the list
    newest_hash_in_batch = last_tx_hash
    
    # Filter for new trades only
    new_trades = []
    
    # Current time for filtering old trades
    current_time = time.time()
    
    for activity in activities:
        tx_hash = activity.get("transactionHash") or activity.get("id") # Fallback to ID if hash missing
        
        if not tx_hash:
            continue
            
        if tx_hash == last_tx_hash:
            break
            
        # TIMESTAMP CHECK: Ignore trades older than 30 minutes (1800 seconds)
        # Polymarket API usually returns timestamp in seconds or milliseconds. 
        # API documentation says 'timestamp' is unix timestamp (seconds).
        # Sometimes it might be missing, so we safely get it.
        trade_timestamp = activity.get("timestamp")
        
        if trade_timestamp:
            try:
                trade_ts = float(trade_timestamp)
                # If timestamp is in milliseconds (huge number), convert to seconds
                if trade_ts > 1000000000000: 
                    trade_ts = trade_ts / 1000
                
                # If trade is older than 30 mins, skip it
                if current_time - trade_ts > 1800:
                    logging.info(f"Skipping old trade for {name}: {current_time - trade_ts:.0f}s old.")
                    continue
            except ValueError:
                pass # If parsing fails, proceed safely (or skip? safely proceed to be sure)
        
        new_trades.append(activity)
    
    # If last_tx_hash was None (first run), we might not want to spam all history.
    if last_tx_hash is None:
        if activities:
             # First run: Mark the most recent one as seen, don't alert
             # We take the very first item (index 0) which is the newest activity
             logging.info(f"First run for {name}. Setting baseline to latest transaction.")
             return activities[0].get("transactionHash") or activities[0].get("id")
        return None

    # Process new trades (reverse to send notifications in chronological order)
    if new_trades:
        for trade in reversed(new_trades):
            # DUPLICATE SUPPRESSION
            # Check if we just notified about this asset/side for this wallet
            wallet_last_notif = LAST_NOTIFICATION_CACHE.get(address)
            current_asset = trade.get("asset")
            current_side = trade.get("side")
            
            should_notify = True
            if wallet_last_notif:
                last_asset = wallet_last_notif.get("asset")
                last_side = wallet_last_notif.get("side")
                last_time = wallet_last_notif.get("time", 0)
                
                # If same asset AND same side AND sent less than 5 minutes ago
                if last_asset == current_asset and last_side == current_side:
                    if time.time() - last_time < 3600: # 60 minutes debounce
                        logging.info(f"Suppressing duplicate notification for {name} ({current_asset})")
                        should_notify = False
            
            if should_notify:
                notify_trade(trade, name, address)
                # Update cache
                LAST_NOTIFICATION_CACHE[address] = {
                    "asset": current_asset, 
                    "side": current_side,
                    "time": time.time()
                }

            # Always update the hash pointer so we don't process it again
            newest_hash_in_batch = trade.get("transactionHash") or trade.get("id")

    return newest_hash_in_batch

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
