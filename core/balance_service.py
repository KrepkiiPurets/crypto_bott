import asyncio
from datetime import datetime
from typing import Dict, Set, Tuple, Optional
import logging

from config import get_exchange_keys
from exchanges import get_exchange_instance

logger = logging.getLogger(__name__)


class BalanceService:

    
    def __init__(self, shared_data):
        self.shared = shared_data
    
    async def get_user_coins(self, user_id: int, exchange_key: str, 
                             force_refresh: bool = False) -> Tuple[Set[str], Dict]:

        cache_key = f"{user_id}_{exchange_key}"
        

        if not force_refresh and cache_key in self.shared.user_coins_cache:
            cache_data = self.shared.user_coins_cache[cache_key]
            cache_time = cache_data.get('timestamp')
            

            lifetime = 1800 if exchange_key in ['kucoin', 'bingx'] else 3600
            
            if cache_time and (datetime.now() - cache_time).total_seconds() < lifetime:
                logger.info(f"  📦 Кеш {exchange_key}: {len(cache_data['coins'])} монет")
                return cache_data['coins'], cache_data['details']
        

        logger.info(f"  🔄 Оновлюю баланс для {exchange_key}...")
        
        keys = get_exchange_keys(exchange_key)
        if not keys:
            return set(), {}
        
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
            

            timeout_val = 45 if exchange_key == 'bingx' else 30
            
            balance_data = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, exchange.get_balance),
                timeout=timeout_val
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
            
            logger.info(f"  ✅ Оновлено баланс {exchange_key}: {len(user_coins)} монет")
            return user_coins, coins_details
            
        except asyncio.TimeoutError:
            logger.error(f"  ⏰ Таймаут отримання балансу для {exchange_key}")
            return set(), {}
        except Exception as e:
            logger.error(f"  ❌ Помилка отримання балансу для {exchange_key}: {e}")
            return set(), {}
    
    async def update_balance_cache(self, user_id: int, exchange_key: str):
    
        cache_key = f"{user_id}_{exchange_key}"
        
        if cache_key in self.shared.user_coins_cache:
            del self.shared.user_coins_cache[cache_key]
        
        await self.get_user_coins(user_id, exchange_key, force_refresh=True)
    
    def format_balance_message(self, exchange_name: str, total_usdt: float, 
                               coins: Dict, max_coins: int = 15) -> str:
   
        if not coins:
            return f"💰 **Баланс {exchange_name}:**\n📭 Порожній"
        
        message = f"💰 **Баланс {exchange_name}**\n"
        message += f"📈 **Загальна сума:** ${total_usdt:,.2f} USDT\n\n"
        
        sorted_coins = sorted(coins.items(), key=lambda x: x[1]['usdt_value'], reverse=True)[:max_coins]
        
        for coin, data in sorted_coins:
            percentage = (data['usdt_value'] / total_usdt * 100) if total_usdt > 0 else 0
            if percentage > 1:
                message += f"• **{coin}:** {data['amount']:.4f} (${data['usdt_value']:,.2f} | {percentage:.1f}%)\n"
            else:
                message += f"• {coin}: {data['amount']:.4f} (${data['usdt_value']:,.2f})\n"
        
        if len(coins) > max_coins:
            message += f"\n📋 ... та ще {len(coins) - max_coins} монет"
        
        return message
