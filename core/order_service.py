import asyncio
from datetime import datetime
from typing import Dict, List, Optional
import logging

from config import get_exchange_keys
from exchanges import get_exchange_instance

logger = logging.getLogger(__name__)


class OrderService:
    """
    Сервіс для роботи з ордерами (перевірка виконаних, скасування)
    Спільний для Telegram та Discord
    """
    
    def __init__(self, shared_data):
        self.shared = shared_data
    
    async def get_open_orders(self, user_id: int, exchange_key: str, 
                              display_name: str) -> Optional[List[Dict]]:
        """Отримати всі відкриті ордери на біржі"""
        keys = get_exchange_keys(exchange_key)
        if not keys:
            return None
        
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
                timeout=15
            )
            
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
            orders = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, exchange.get_open_orders),
                timeout=30
            )
            
            return orders
            
        except asyncio.TimeoutError:
            logger.error(f"  ⏰ Таймаут отримання ордерів для {display_name}")
            return None
        except Exception as e:
            logger.error(f"  ❌ Помилка отримання ордерів для {display_name}: {e}")
            return None
    
    async def cancel_all_orders(self, user_id: int, exchange_key: str, 
                                display_name: str) -> Dict:
 
        result = {'cancelled': 0, 'failed': 0, 'total': 0}
        
        keys = get_exchange_keys(exchange_key)
        if not keys:
            result['error'] = "Немає API ключів"
            return result
        
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
                timeout=15
            )
            
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
            orders = await self.get_open_orders(user_id, exchange_key, display_name)
            
            if not orders:
                return result
            
            result['total'] = len(orders)
            
            for order in orders:
                try:
                    if exchange.cancel_order(order.get('id'), order.get('symbol')):
                        result['cancelled'] += 1
                    else:
                        result['failed'] += 1
                    await asyncio.sleep(0.3)
                except Exception:
                    result['failed'] += 1
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Помилка скасування ордерів: {e}")
            result['error'] = str(e)
            return result
    
    async def check_filled_orders(self, user_id: int, exchange_key: str,
                                  display_name: str) -> List[Dict]:

        cache_key = f"last_orders_check_{user_id}_{exchange_key}"
        last_check = self.shared.last_orders_check.get(cache_key, 0)
        
        keys = get_exchange_keys(exchange_key)
        if not keys:
            return []
        
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
                timeout=15
            )
            
            timeout_val = 45 if exchange_key == 'bingx' else 30
            
            filled_orders = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: exchange.check_filled_orders(last_check)
                ),
                timeout=timeout_val
            )
            
            if filled_orders:
                self.shared.last_orders_check[cache_key] = int(datetime.now().timestamp() * 1000)
            
            return filled_orders or []
            
        except asyncio.TimeoutError:
            if exchange_key == 'bingx':
                logger.info(f"  ⏰ BingX: таймаут перевірки ордерів")
            return []
        except Exception as e:
            logger.error(f"  ❌ Помилка перевірки ордерів {display_name}: {e}")
            return []
    
    def format_orders_message(self, exchange_name: str, orders: List[Dict]) -> str:
    
        if not orders:
            return f"📭 **На {exchange_name} немає відкритих лімітних ордерів**"
        
        total_value = 0
        message_lines = [
            f"📋 **Відкриті лімітні ордери на {exchange_name}**",
            f"**Всього ордерів:** {len(orders)}\n"
        ]
        
        for i, order in enumerate(orders[:20], 1):
            symbol = order.get('symbol', 'Невідомо')
            side = order.get('side', 'unknown').upper()
            amount = float(order.get('amount', 0))
            price = float(order.get('price', 0))
            value = amount * price
            emoji = "📤" if side == 'SELL' else "📥"
            
            message_lines.append(
                f"{emoji} **{i}. {symbol}**\n"
                f"   Тип: {side}\n"
                f"   Кількість: {amount:.4f}\n"
                f"   Ціна: ${price:.6f}\n"
                f"   Сума: ${value:.2f}"
            )
            total_value += value
        
        if len(orders) > 20:
            message_lines.append(f"📋 ... та ще {len(orders) - 20} ордерів")
        
        message_lines.append(f"\n💰 **Загальна сума в ордерах:** ${total_value:.2f}")
        
        return "\n".join(message_lines)
    
    def format_filled_order_message(self, order: Dict, exchange_name: str) -> str:
      
        symbol = order.get('symbol')
        amount = order.get('amount', 0)
        price = order.get('price', 0)
        total = order.get('cost', 0)
        
        if amount > 1000:
            amount_display = f"{amount:.0f}"
        elif amount > 100:
            amount_display = f"{amount:.1f}"
        else:
            amount_display = f"{amount:.4f}"
        
        return (
            f"💰 **Монета продана!**\n\n"
            f"**{symbol}**\n"
            f"Кількість: {amount_display}\n"
            f"Ціна: ${price:.6f}\n"
            f"Отримано: ${total:.2f} USDT\n"
            f"**Біржа:** {exchange_name}\n"
            f"🕒 {order.get('datetime', '')}"
        )