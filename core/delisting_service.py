import asyncio
from datetime import datetime
from typing import Dict, Set, Optional
import logging

from config import get_exchange_keys, get_all_configured_exchanges
from exchanges import get_exchange_instance
from analysis.delisting_checker import DelistingChecker

logger = logging.getLogger(__name__)


class DelistingService:

    
    def __init__(self, shared_data):
        self.shared = shared_data
        self._lock = asyncio.Lock()
    
    async def check_single_exchange(self, user_id: int, exchange_key: str, 
                                    display_name: str) -> Optional[Dict]:
  
        keys = get_exchange_keys(exchange_key)
        if not keys:
            return None
        
        supported = ['gate', 'mexc', 'kucoin', 'bingx']
        if exchange_key not in supported:
            return None
        
        checker = None
        
        try:
        
            exchange = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: get_exchange_instance(
                        exchange_key,
                        api_key=keys['api_key'],
                        api_secret=keys['secret'],
                        password=keys.get('password')
                    )
                ),
                timeout=20
            )
            
        
            user_coins, coins_details = await self._get_cached_coins(user_id, exchange_key, exchange)
            
            if not user_coins:
                return None
            
  
            checker = DelistingChecker()
            
            timeouts = {'gate': 75, 'kucoin': 75, 'mexc': 90, 'bingx': 90}
            timeout_value = timeouts.get(exchange_key, 75)
            
            result = await asyncio.wait_for(
                checker.check_exchange_delistings(exchange_key, user_coins),
                timeout=timeout_value
            )
            
            found_tokens = result.get(exchange_key, set())
            
            if found_tokens:
                return {exchange_key: found_tokens, 'details': coins_details, 'exchange': exchange}
            
            return None
            
        except Exception as e:
            logger.error(f"❌ {exchange_key}: {e}")
            return None
        finally:
            if checker:
                await checker.close()
    
    async def _get_cached_coins(self, user_id: int, exchange_key: str, exchange):
   
        cache_key = f"{user_id}_{exchange_key}"
        
        cache_lifetime = 1800 if exchange_key in ['kucoin', 'bingx'] else 3600
        
        if cache_key in self.shared.user_coins_cache:
            cache_data = self.shared.user_coins_cache[cache_key]
            cache_time = cache_data.get('timestamp')
            
            if cache_time and (datetime.now() - cache_time).total_seconds() < cache_lifetime:
                return cache_data['coins'], cache_data['details']
        
  
        balance_data = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, exchange.get_balance),
            timeout=45
        )
        
        user_coins = set()
        coins_details = {}
        
        for coin, data in balance_data['coins'].items():
            if coin != 'USDT' and data['amount'] > 0:
                user_coins.add(coin)
                coins_details[coin] = data
        
        self.shared.user_coins_cache[cache_key] = {
            'coins': user_coins,
            'details': coins_details,
            'timestamp': datetime.now()
        }
        
        return user_coins, coins_details
    
    def format_delisting_message(self, results: Dict, exchange_name: str) -> str:
      
        found_tokens = results.get(exchange_name, set())
        if not found_tokens:
            return None
        
        details = results.get('details', {})
        message_lines = [f"🚨 **⚠️ ТЕРМІНОВО! Виявлено монети в списках делістингу!**"]
        message_lines.append(f"**Біржа:** {exchange_name.capitalize()}")
        message_lines.append(f"**Знайдені монети:** {', '.join(found_tokens)}\n")
        
        for token in found_tokens:
            if token in details:
                amount = details[token]['amount']
                value = details[token]['usdt_value']
                message_lines.append(f"• **{token}**: {amount:.4f} (${value:,.2f})")
        
        return "\n".join(message_lines)