import os
from dotenv import load_dotenv
from typing import Dict, Optional


load_dotenv()


BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')


EXCHANGES = {
    'Kucoin': 'kucoin',
    'BingX': 'bingx',
    'Gate.io': 'gate',
    'MEXC': 'mexc',
}


EXCHANGE_KEYS = {
    'kucoin': {
        'api_key': os.getenv('KUCOIN_API_KEY'),
        'secret': os.getenv('KUCOIN_SECRET_KEY'),
        'password': os.getenv('KUCOIN_PASSPHRASE', '')
    },
    'bingx': {
        'api_key': os.getenv('BINGX_API_KEY'),
        'secret': os.getenv('BINGX_SECRET_KEY')
    },
    'gate': {
        'api_key': os.getenv('GATE_API_KEY'),
        'secret': os.getenv('GATE_SECRET_KEY')
    },
    'mexc': {
        'api_key': os.getenv('MEXC_API_KEY'),
        'secret': os.getenv('MEXC_SECRET_KEY')
    }

}


DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')  
DISCORD_GUILD_ID = os.getenv('DISCORD_GUILD_ID')    
DISCORD_CHANNEL_ID = os.getenv('DISCORD_CHANNEL_ID') 

MAX_VOLUME_USDT = 40000  
MIN_AMPLITUDE_PERCENT = 35  
MIN_CANDLES_COUNT = 4  
TIMEFRAME = '1d'


DB_NAME = 'crypto_bot.db'


GATE_LOGIN_URL = 'https://www.gate.io/uk/signup'
GATE_BALANCE_URL = 'https://www.gate.io/uk/myaccount/funds/spot'
GATE_EMAIL = os.getenv('GATE_EMAIL', '')
GATE_PASSWORD = os.getenv('GATE_PASSWORD', '')


SELENIUM_TIMEOUT = 30
SELENIUM_IMPLICIT_WAIT = 10


def get_exchange_keys(exchange_name: str) -> Optional[Dict]:
 
    return EXCHANGE_KEYS.get(exchange_name)

def has_exchange_keys(exchange_name: str) -> bool:
 
    keys = get_exchange_keys(exchange_name)
    if not keys:
        return False
    
  
    required_keys = ['api_key', 'secret']
    for key in required_keys:
        if not keys.get(key):
            return False
    return True

def get_all_configured_exchanges() -> Dict:
   
    configured = {}
    for display_name, exchange_key in EXCHANGES.items():
        if has_exchange_keys(exchange_key):
            configured[display_name] = exchange_key
    return configured

def has_gate_credentials() -> bool:
   
    return bool(GATE_EMAIL and GATE_PASSWORD)