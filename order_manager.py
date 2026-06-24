import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from keyboards import get_back_to_exchange_reply_keyboard, get_main_reply_keyboard

logger = logging.getLogger(__name__)

class OrderManager:

    
    def __init__(self):
        self.active_sessions = {} 
        self.user_states = {}  
        
    async def start_bulk_orders(self, update: Update, exchange, exchange_display_name: str):
       
        user_id = update.effective_user.id
        exchange_key = self._get_exchange_key(exchange_display_name)
        
        try:
        
            balance_data = exchange.get_balance()
            coins = balance_data['coins']
            
          
            tradable_coins = []
            coins_without_price = []
            
            for coin, data in coins.items():
                if coin != 'USDT' and data['amount'] > 0:
                 
                    current_price = None
                    price_error = None
                    
                    try:
                    
                        if exchange_key == 'gate':
                            current_price = await self._get_gate_price(exchange, coin)
                        else:
                            current_price = await self._get_price(exchange, coin)
                            
                    except Exception as e:
                        price_error = str(e)
                        logger.warning(f"⚠️ {coin}: {e}")
                    
                    coin_data = {
                        'coin': coin,
                        'amount': data['amount'],
                        'value': data['usdt_value'],
                        'current_price': current_price,
                        'price_error': price_error
                    }
                    
                    if current_price and current_price > 0:
                        tradable_coins.append(coin_data)
                        logger.info(f"✅ {coin}: ціна ${current_price:.6f}")
                    else:
                        coins_without_price.append(coin_data)
                        logger.warning(f"⚠️ {coin}: ціна не отримана")
            
         
            tradable_coins.sort(key=lambda x: x['value'], reverse=True)
            
          
            self.active_sessions[user_id] = {
                'exchange': exchange_display_name,
                'exchange_key': exchange_key,
                'exchange_instance': exchange,
                'coins': tradable_coins,
                'coins_without_price': coins_without_price,
                'step': 'waiting_percentage'
            }
            
       
            message_lines = [
                f"🎯 **Масове виставлення ордерів на {exchange_display_name}**\n",
                f"**Знайдено монет з ціною:** {len(tradable_coins)}"
            ]
            
            if coins_without_price:
                message_lines.append(f"**⚠️ Без ціни:** {len(coins_without_price)}")
            
            message_lines.append("\n**📊 Монети для продажу:**\n")
            
            for i, coin_data in enumerate(tradable_coins[:10], 1):
                price_info = f"@ ${coin_data['current_price']:.6f}"
                message_lines.append(
                    f"{i}. **{coin_data['coin']}**: {coin_data['amount']:.4f} "
                    f"({price_info}) ≈${coin_data['value']:.2f}"
                )
            
            if len(tradable_coins) > 10:
                message_lines.append(f"... та ще {len(tradable_coins) - 10} монет")
            
            if coins_without_price:
                message_lines.append(f"\n⚠️ **Монети без ціни (пропущені):**")
                for coin_data in coins_without_price[:5]:
                    message_lines.append(f"   • {coin_data['coin']}: {coin_data['amount']:.4f} ≈${coin_data['value']:.2f}")
                if len(coins_without_price) > 5:
                    message_lines.append(f"   ... та ще {len(coins_without_price) - 5} монет")
            
            message_lines.append(
                f"\n📊 **Введіть відсоток від поточної ціни** для виставлення ордерів "
                f"(наприклад: 105 для +5%, 95 для -5%):"
            )
            
            await update.message.reply_text(
                "\n".join(message_lines),
                parse_mode='Markdown'
            )
            
            self.user_states[user_id] = {
                'action': 'waiting_percentage',
                'exchange': exchange_display_name
            }
            
        except Exception as e:
            logger.error(f"Помилка при start_bulk_orders: {e}")
            await update.message.reply_text(
                f"❌ **Помилка:** {str(e)[:200]}",
                reply_markup=get_back_to_exchange_reply_keyboard(exchange_display_name)
            )
    
    async def _get_price(self, exchange, coin: str) -> Optional[float]:
    
        try:
        
            ticker = exchange.get_ticker(f"{coin}/USDT")
            if ticker and ticker.get('last') not in (None, 0):
                return float(ticker['last'])
        except Exception as e1:
            logger.debug(f"⚠️ {coin}: помилка ticker: {e1}")
            
           
            try:
                ticker2 = exchange.exchange.fetch_ticker(f"{coin}/USDT")
                if ticker2 and ticker2.get('last') not in (None, 0):
                    return float(ticker2['last'])
            except Exception as e2:
                logger.debug(f"⚠️ {coin}: помилка fetch_ticker: {e2}")
                
                
                try:
                    orders = exchange.get_open_orders(f"{coin}/USDT")
                    if orders:
                        prices = [o.get('price', 0) for o in orders if o.get('price', 0) > 0]
                        if prices:
                            return sum(prices) / len(prices)
                except:
                    pass
        
        return None
    
    async def _get_gate_price(self, exchange, coin: str) -> Optional[float]:
       
        try:
            symbol = f"{coin}/USDT"
            
           
            try:
                ticker = exchange.exchange.fetch_ticker(symbol)
                if ticker:
                   
                    price = None
                    for field in ['last', 'close', 'average']:
                        if field in ticker and ticker[field] not in (None, 0):
                            price = float(ticker[field])
                            break
                    
                    if price and price > 0:
                        logger.info(f"✅ Gate.io {coin}: ціна через ticker: ${price:.6f}")
                        return price
            except Exception as e:
                logger.debug(f"Gate.io {coin}: помилка fetch_ticker: {e}")
            
          
            try:
                markets = exchange.exchange.load_markets()
                if symbol in markets:
                    market_info = markets[symbol]
                    
                    if 'info' in market_info:
                        info = market_info['info']
                        if 'last' in info and info['last']:
                            return float(info['last'])
            except Exception as e:
                logger.debug(f"Gate.io {coin}: помилка markets: {e}")
            
         
            try:
                order_book = exchange.exchange.fetch_order_book(symbol, limit=1)
                if order_book and 'bids' in order_book and len(order_book['bids']) > 0:
                    bid_price = order_book['bids'][0][0]
                    if bid_price and bid_price > 0:
                        logger.info(f"✅ Gate.io {coin}: ціна з order book: ${bid_price:.6f}")
                        return float(bid_price)
            except Exception as e:
                logger.debug(f"Gate.io {coin}: помилка order book: {e}")
            
            return None
            
        except Exception as e:
            logger.error(f"Gate.io помилка для {coin}: {e}")
            return None
    
    def _get_exchange_key(self, exchange_display_name: str) -> str:
       
        from config import EXCHANGES
        return EXCHANGES.get(exchange_display_name, '')
    
    async def handle_percentage_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, percentage_str: str):
      
        user_id = update.effective_user.id
        
        if user_id not in self.active_sessions:
            await update.message.reply_text(
                "❌ Сесію не знайдено. Почніть спочатку.",
                reply_markup=get_main_reply_keyboard()
            )
            return
        
        try:
            percentage = float(percentage_str.replace('%', ''))
            if percentage <= 0:
                raise ValueError("Відсоток має бути більше 0")
        except ValueError:
            await update.message.reply_text(
                "❌ Некоректне значення. Введіть число (наприклад: 105 для +5%)"
            )
            return
        
        session = self.active_sessions[user_id]
        exchange_display_name = session['exchange']
        
        session['percentage'] = percentage
        session['step'] = 'confirm'
        
    
        total_value = sum(c['value'] for c in session['coins'])
        
        message_lines = [
            f"🎯 **Підтвердження масового виставлення ордерів**\n",
            f"**Біржа:** {exchange_display_name}\n"
            f"**Відсоток від ціни:** {percentage}% ({(percentage - 100):+.1f}% від поточної)\n",
            f"**Монет для продажу:** {len(session['coins'])}\n",
            f"**Орієнтовна сума:** ${total_value:.2f}\n\n",
            f"✅ Введіть **'так'** для підтвердження або **'ні'** для скасування:"
        ]
        
        await update.message.reply_text(
            "\n".join(message_lines),
            parse_mode='Markdown'
        )
        
        self.user_states[user_id] = {
            'action': 'waiting_confirmation',
            'exchange': exchange_display_name
        }
    
    async def execute_bulk_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Виконання масового виставлення ордерів"""
        user_id = update.effective_user.id
        
        if user_id not in self.active_sessions:
            await update.message.reply_text("❌ Сесію не знайдено")
            return
        
        session = self.active_sessions[user_id]
        exchange = session['exchange_instance']
        exchange_display_name = session['exchange']
        exchange_key = session.get('exchange_key', '')
        percentage = session['percentage']
        coins = session['coins']
        
        await update.message.reply_text(
            f"⏳ **Виставляю ордери на {exchange_display_name}...**\n"
            f"Це може зайняти деякий час."
        )
        
        results = {
            'success': [],
            'failed': [],
            'blocked': [],
            'skipped': []
        }
        
        for coin_data in coins:
            coin = coin_data['coin']
            amount = coin_data['amount']
            current_price = coin_data.get('current_price')
            
            if current_price is None or current_price <= 0:
                logger.warning(f"⚠️ {coin}: немає ціни, пропускаю")
                results['skipped'].append({
                    'coin': coin,
                    'amount': amount,
                    'reason': 'ціна не визначена'
                })
                continue
            
            order_price = current_price * (percentage / 100)
            
            if order_price <= 0:
                results['failed'].append({
                    'coin': coin,
                    'amount': amount,
                    'error': f'розрахована ціна {order_price} некоректна'
                })
                continue
            
            symbol = f"{coin}/USDT"
            
            try:
               
                try:
                    markets = exchange.exchange.load_markets()
                    if symbol in markets:
                        info = markets[symbol].get('info', {})
                        if info.get('apiStateSell') == False:
                            results['blocked'].append({
                                'coin': coin,
                                'amount': amount,
                                'reason': 'API продаж заборонено біржею'
                            })
                            continue
                except Exception as e:
                    logger.warning(f"Не вдалося перевірити API стан для {coin}: {e}")
                
             
                min_notional = 5
                if amount * order_price < min_notional:
                    results['skipped'].append({
                        'coin': coin,
                        'amount': amount,
                        'reason': f'сума ${amount * order_price:.2f} менша за мінімальну ${min_notional}'
                    })
                    continue
                
               
                if exchange_key == 'kucoin':
                    try:
                        market = exchange.exchange.market(symbol)
                        amount_str = self._format_amount(amount, market)
                        price_str = self._format_price(order_price, market)
                        
                        order = exchange.exchange.create_order(
                            symbol=symbol,
                            type='limit',
                            side='sell',
                            amount=amount_str,
                            price=price_str
                        )
                    except Exception as e:
                        logger.error(f"KuCoin special handling error for {coin}: {e}")
                        order = exchange.create_limit_sell_order(symbol, amount, order_price)
                else:
                    order = exchange.create_limit_sell_order(symbol, amount, order_price)
                
                if order:
                    results['success'].append({
                        'coin': coin,
                        'amount': amount,
                        'price': order_price,
                        'total': amount * order_price,
                        'order_id': order.get('id')
                    })
                    
                    logger.info(f"✅ Виставлено ордер на {coin}: {amount} @ ${order_price:.6f}")
                    
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"✅ **Ордер виставлено!**\n"
                            f"**Монета:** {coin}\n"
                            f"**Кількість:** {amount:.4f}\n"
                            f"**Ціна:** ${order_price:.6f}\n"
                            f"**Сума:** ${(amount * order_price):.2f}\n"
                            f"**Біржа:** {exchange_display_name}"
                        ),
                        parse_mode='Markdown'
                    )
                    
                    await asyncio.sleep(0.5)
                else:
                    results['failed'].append({
                        'coin': coin,
                        'amount': amount,
                        'error': 'ордер не створено'
                    })
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Помилка виставлення ордера для {coin}: {error_msg}")
                results['failed'].append({
                    'coin': coin,
                    'amount': amount,
                    'error': error_msg[:100]
                })
        
      
        report_lines = [
            f"📊 **Звіт про виставлення ордерів на {exchange_display_name}**\n",
            f"✅ **Успішно:** {len(results['success'])} ордерів"
        ]
        
        if results['success']:
            total_value = sum(o['total'] for o in results['success'])
            report_lines.append(f"   Загальна сума: ${total_value:.2f}")
            
            report_lines.append(f"\n📈 **Виставлені ордери:**")
            for s in results['success'][:5]:
                report_lines.append(f"   • {s['coin']}: {s['amount']:.4f} @ ${s['price']:.6f}")
        
        if results['skipped']:
            report_lines.append(f"\n⏭️ **Пропущено:** {len(results['skipped'])}")
            for s in results['skipped'][:5]:
                report_lines.append(f"   • {s['coin']}: {s['reason']}")
        
        if results['blocked']:
            report_lines.append(f"\n🔴 **Заблоковані:** {len(results['blocked'])}")
            for b in results['blocked'][:5]:
                report_lines.append(f"   • {b['coin']}: {b['amount']:.4f}")
        
        if results['failed']:
            report_lines.append(f"\n❌ **Помилки:** {len(results['failed'])}")
            for f in results['failed'][:5]:
                report_lines.append(f"   • {f['coin']}: {f['error'][:50]}")
        
        await update.message.reply_text(
            "\n".join(report_lines),
            parse_mode='Markdown'
        )
        
     
        del self.active_sessions[user_id]
        if user_id in self.user_states:
            del self.user_states[user_id]
    
    def _format_amount(self, amount: float, market: dict) -> str:
      
        try:
            step = market.get('precision', {}).get('amount', 8)
            if step is None:
                step = 8
            if isinstance(step, float):
                step = int(step)
            format_str = f"{{:.{step}f}}"
            return format_str.format(amount).rstrip('0').rstrip('.') or '0'
        except:
            return str(amount)
    
    def _format_price(self, price: float, market: dict) -> str:
      
        try:
            step = market.get('precision', {}).get('price', 8)
            if step is None:
                step = 8
            if isinstance(step, float):
                step = int(step)
            format_str = f"{{:.{step}f}}"
            return format_str.format(price).rstrip('0').rstrip('.') or '0'
        except:
            return str(price)
    
    def cancel_session(self, user_id: int):
      
        if user_id in self.active_sessions:
            del self.active_sessions[user_id]
        if user_id in self.user_states:
            del self.user_states[user_id]