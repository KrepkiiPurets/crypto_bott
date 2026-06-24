import json
import sqlite3
import os
from bs4 import BeautifulSoup
from order_manager import OrderManager
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, JobQueue, MessageHandler, filters 

)

from core.shared_data import SharedData
import sys
import io
import asyncio
from typing import Dict, List, Set, Optional
import traceback
from telegram.ext import MessageHandler, filters
import time

if sys.platform == 'win32':

    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    

    os.system('chcp 65001 > nul')

from config import BOT_TOKEN, EXCHANGES, MAX_VOLUME_USDT, MIN_AMPLITUDE_PERCENT, MIN_CANDLES_COUNT
from config import get_exchange_keys, get_all_configured_exchanges, has_exchange_keys
from exchanges import get_exchange_instance
from analysis.token_scanner import TokenScanner
from analysis.delisting_checker import DelistingChecker
from database.db_handler import DatabaseHandler
from notifications import NotificationManager, get_notifications_menu_keyboard
from keyboards import (
    get_main_reply_keyboard,
    get_exchange_reply_keyboard,
    get_notifications_reply_keyboard,
    get_back_to_exchange_reply_keyboard,
    get_confirmation_reply_keyboard,
    clear_keyboard,
    get_scan_results_inline_keyboard,
    get_delisting_results_inline_keyboard,
    get_orders_management_inline_keyboard
)


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class CryptoBot:
    def __init__(self):
        self.db = DatabaseHandler()
        self.scan_in_progress = {}  # Словник для відстеження сканувань по користувачах
        self.scan_results = {}  # Зберігаємо результати сканувань
        self.current_page = {}  # Зберігаємо поточну сторінку для кожного користувача
        self.user_balances_cache = {}  # Кеш балансів користувачів
        self.user_coins_cache = {}  # Кеш монет користувачів для автоматичної перевірки
        self.delisting_check_task = None  # Завдання автоматичної перевірки делістингу
        self.last_delisting_check = {}  
        self.delisting_alerts_sent = {}  
        self.notification_manager = NotificationManager()
        self.order_manager = OrderManager()
        self.last_orders_check = {}
        self.sent_order_notifications = {}
        self._users_cache = None
        self._users_cache_time = None
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
       
        user_id = update.effective_user.id
        
   
        try:
            conn = sqlite3.connect(self.db.db_name)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO user_api_keys (user_id, exchange_keys) VALUES (?, ?)",
                (user_id, '{}')
            )
            conn.commit()
            conn.close()
            logger.info(f"Користувача {user_id} додано в БД")
        except Exception as e:
            logger.error(f"Помилка збереження користувача {user_id}: {e}")
        
      
        keyboard = get_main_reply_keyboard()
        
        if not keyboard:
            await update.message.reply_text(
                "⚠️ **Увага!** Не знайдено жодної налаштованої біржі.\n\n"
                "Будь ласка, налаштуйте API ключі в файлі `.env`.\n"
                "Після налаштування натисніть /start знову.",
                parse_mode='Markdown'
            )
            return
        

        
        welcome_message = (
            "👋 **Вітаю у Crypto Portfolio Bot!**\n\n"
            "🔹 **Функціонал:**\n"
            "• 📊 Перегляд балансу на біржах\n"
            "• 🔍 Аналіз ВСІХ токенів за технічними критеріями\n"
            "• ⚠️ **АВТОМАТИЧНА ПЕРЕВІРКА ДЕЛІСТИНГУ (ST)** кожні 10 хвилин\n"
            "• 💹 **АВТОМАТИЧНИЙ ПРОДАЖ** при виявленні делістингу\n"
            "• 📋 Перегляд лімітних ордерів\n\n"
            "🔘 **Кнопки внизу екрану** - завжди доступні\n"
            "🏠 **Головне меню** - повернення до списку бірж\n\n"
            "⚡ **Оберіть біржу в меню нижче:**"
        )
        
        await update.message.reply_text(
            welcome_message,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка текстових повідомлень (натискання кнопок)"""
        text = update.message.text
        user_id = update.effective_user.id
        
        logger.info(f"Отримано повідомлення: {text}")
        
      
        if text == "🏠 Головне меню":
            keyboard = get_main_reply_keyboard()
            await update.message.reply_text(
                "🏠 **Головне меню**\n\nОберіть біржу:",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return
        
      
        configured_exchanges = get_all_configured_exchanges()
        
        for display_name, exchange_key in configured_exchanges.items():
            if text == f"🏦 {display_name}":
                await self.show_exchange_menu(update, display_name)
                return
        
     
        if text == "🔔 Сповіщення":
            is_enabled = self.notification_manager.is_enabled(user_id)
            keyboard = get_notifications_reply_keyboard(is_enabled)
            await update.message.reply_text(
                f"🔔 **Керування сповіщеннями**\n\n"
                f"Поточний статус: {'🟢 Увімкнено' if is_enabled else '🔴 Вимкнено'}\n\n"
                f"Використовуйте кнопки нижче для керування:",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return
        
     
        if text == "🔔 Увімкнути":
            self.notification_manager.set_enabled(user_id, True)
            keyboard = get_notifications_reply_keyboard(True)
            await update.message.reply_text(
                "✅ **Сповіщення ввімкнено!**\n\n"
                "Тепер ви будете отримувати звіти після кожної автоматичної перевірки.",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return
        
        if text == "🔕 Вимкнути":
            self.notification_manager.set_enabled(user_id, False)
            keyboard = get_notifications_reply_keyboard(False)
            await update.message.reply_text(
                "🔕 **Сповіщення вимкнено**\n\n"
                "Ви більше не будете отримувати автоматичні звіти.",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return
        
        if text.startswith("📊 Статус:"):
            is_enabled = self.notification_manager.is_enabled(user_id)
            keyboard = get_notifications_reply_keyboard(is_enabled)
            await update.message.reply_text(
                f"📊 **Поточний статус:** {'🟢 Увімкнено' if is_enabled else '🔴 Вимкнено'}",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return
        
      
        if text == "⚙️ Статус":
            await self.status_command(update, context)
            return
        
       
        for display_name, exchange_key in configured_exchanges.items():
            if text == f"💰 Баланс {display_name}":
                await self.handle_balance(update, display_name)
                return
            if text == f"🔍 Аналіз {display_name}":
                await self.handle_tokens_analysis(update, display_name, context) 
                return
            if text == f"⚠️ ST {display_name}":
                await self.handle_delisting_check(update, display_name, context) 
                return
            if text == f"📋 Ордери {display_name}":
                await self.handle_orders_check(update, display_name, context)  
                return
            if text == f"🎯 Виставити ордери {display_name}":  
                await self.handle_bulk_orders(update, display_name, context)
                return
            if text == f"🔙 Назад до {display_name}":
                await self.show_exchange_menu(update, display_name)
                return
            if text == f"💰 Баланс {display_name}":
                await self.handle_balance(update, display_name)
                return
            if text == f"📅 Статистика {display_name}":  
                await self.handle_monthly_stats(update, display_name)
                return
            if text == f"🔍 Аналіз {display_name}":
                await self.handle_tokens_analysis(update, display_name, context)
                return
        
      
        if text.startswith("✅ Так,"):
            await self.handle_confirmation(update, text, context) 
            return
        
        if text == "❌ Ні, назад":
            keyboard = get_main_reply_keyboard()
            await update.message.reply_text(
                "🏠 **Головне меню**",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return
        
      
        await update.message.reply_text(
            "❓ Невідома команда. Використовуйте кнопки в меню.",
            reply_markup=get_main_reply_keyboard()
        )
        if text == f"🎯 Виставити ордери {display_name}":
            await self.handle_bulk_orders(update, display_name, context)
            return
        
        if user_id in self.order_manager.user_states:
            state = self.order_manager.user_states[user_id]
            
            if state['action'] == 'waiting_percentage':
                await self.order_manager.handle_percentage_input(update, context, text)
                return
            
            elif state['action'] == 'waiting_confirmation':
                if text.lower() == 'так':
                    await self.order_manager.execute_bulk_orders(update, context)
                elif text.lower() == 'ні':
                    self.order_manager.cancel_session(user_id)
                    await update.message.reply_text(
                        "❌ Операцію скасовано.",
                        reply_markup=get_back_to_exchange_reply_keyboard(state['exchange'])
                    )
                else:
                    await update.message.reply_text(
                        "❌ Введіть 'так' для підтвердження або 'ні' для скасування."
                    )
                return
    async def show_exchange_menu(self, update: Update, exchange_display_name: str):
     
        exchange_key = EXCHANGES.get(exchange_display_name)
        
        if not has_exchange_keys(exchange_key):
            await update.message.reply_text(
                f"❌ **{exchange_display_name} не налаштована**\n\n"
                f"Додайте API ключі в файл `.env`",
                reply_markup=get_main_reply_keyboard(),
                parse_mode='Markdown'
            )
            return
        
        keyboard = get_exchange_reply_keyboard(exchange_display_name)
        
        await update.message.reply_text(
            f"📊 **{exchange_display_name}**\n\n"
            f"Оберіть дію:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    
    async def start_auto_delisting_check(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Оптимізований запуск автоматичних перевірок через JobQueue
        """
        self.last_delisting_check.clear()
        logger.info("🚀 Налаштування автоматичних перевірок...")
        
        if not context.job_queue:
            logger.error("❌ JobQueue не доступний!")
            return
        
        await self._init_balance_cache()
        
        context.job_queue.run_repeating(
            self.check_all_exchanges_auto_job,
            interval=600,
            first=10,
            name='delisting_check'
        )
        
        context.job_queue.run_repeating(
            self.check_filled_orders_auto_job,
            interval=300,
            first=420,
            name='orders_check'
        )
        
       
        context.job_queue.run_repeating(
            self._cleanup_old_cache,
            interval=7200,
            first=7200,
            name='cleanup_cache'
        )
        
        logger.info("✅ Автоматичні перевірки налаштовано")

    async def _cleanup_old_cache(self, context: ContextTypes.DEFAULT_TYPE):
        """Очищення старого кешу (старше 6 годин)"""
        now = datetime.now()
        old_keys = []
        
        for key, data in self.user_coins_cache.items():
            cache_time = data.get('timestamp')
            if cache_time and (now - cache_time).total_seconds() > 21600:
                old_keys.append(key)
        
        for key in old_keys:
            del self.user_coins_cache[key]
        
        if old_keys:
            logger.info(f"🧹 Очищено {len(old_keys)} старих записів кешу")
    async def check_all_exchanges_auto_job(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Job для автоматичної перевірки делістингу - запускається через JobQueue
        """
        job_name = context.job.name if context.job else 'unknown'
        logger.info(f"🔍 Запуск перевірки делістингу (job: {job_name})")
        
        try:

            if hasattr(self, '_delisting_check_running') and self._delisting_check_running:
                logger.warning("⚠️ Перевірка делістингу вже виконується, пропускаємо")
                return
            
        
            self._delisting_check_running = True
         
            
          
            task = asyncio.create_task(self._check_all_exchanges_auto_internal(context))
            
           
            try:
                await asyncio.wait_for(task, timeout=280)  
                logger.info("✅ Перевірка делістингу успішно завершена")
            except asyncio.TimeoutError:
                logger.error("❌ Перевірка делістингу перевищила ліміт часу")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            except Exception as e:
                logger.error(f"❌ Помилка під час виконання перевірки: {e}")
                
        except Exception as e:
            logger.error(f"❌ Помилка в job перевірки делістингу: {e}")
        
        finally:
        
            self._delisting_check_running = False
     
        
            
    async def check_filled_orders_auto_job(self, context: ContextTypes.DEFAULT_TYPE):
     
        if hasattr(self, '_delisting_check_running') and self._delisting_check_running:
            return
        
        try:
            task = asyncio.create_task(self._check_filled_orders_auto_internal(context))
            await asyncio.wait_for(task, timeout=170)
        except:
            pass
        
    async def _check_all_exchanges_auto_internal(self, context: ContextTypes.DEFAULT_TYPE):
   
        
      
        if not hasattr(self, 'last_delisting_check'):
            self.last_delisting_check = {}
        
   
        keys_to_delete = [k for k, v in self.last_delisting_check.items() if v is None or not isinstance(v, datetime)]
        for key in keys_to_delete:
            del self.last_delisting_check[key]
        
      
        try:
            users = self.get_all_users()
        except Exception as e:
            logger.error(f"❌ Помилка отримання користувачів: {e}")
            return
        
        if not users:
            return
        
      
        semaphore = asyncio.Semaphore(2)
        
        async def check_user_with_limit(user_id):
            async with semaphore:
                try:
                  
                    await asyncio.wait_for(
                        self._check_user_exchanges_auto_internal(user_id, context),
                        timeout=300 
                    )
                except asyncio.TimeoutError:
                    logger.error(f"⏰ Таймаут перевірки для користувача {user_id}")
                except Exception as e:
                    logger.error(f"❌ Помилка для користувача {user_id}: {e}")
        
      
        tasks = [check_user_with_limit(user_id) for user_id in users[:5]]
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("✅ Внутрішня перевірка делістингу завершена")
        except Exception as e:
            logger.error(f"❌ Помилка при виконанні перевірок: {e}")
      
    async def _check_user_exchanges_auto_internal(self, user_id: int, context: ContextTypes.DEFAULT_TYPE):
  
   
        check_key = f"_checking_user_{user_id}"
        if hasattr(self, check_key) and getattr(self, check_key):
            logger.info(f"  ⏭️ Пропускаю {user_id} - вже виконується")
            return
        setattr(self, check_key, True)
        
        try:
            logger.info(f"👤 Перевірка для користувача {user_id}...")
            
            all_exchanges = get_all_configured_exchanges()
            if not all_exchanges:
                return
            
            first_group = {}
            second_group = {}
            
            for display_name, exchange_key in all_exchanges.items():
                if exchange_key in ['gate', 'kucoin']:
                    first_group[display_name] = exchange_key
                elif exchange_key in ['mexc', 'bingx']:
                    second_group[display_name] = exchange_key
            
            all_found_tokens = {}
            
            async def check_exchange_group(group_name, group_exchanges):
                if not group_exchanges:
                    return {}
                
                logger.info(f"  🚀 Група {group_name}: {list(group_exchanges.values())}")
                
                async def check_single(display_name, exchange_key):
                    try:
                        timeouts = {'gate': 75, 'kucoin': 75, 'mexc': 90, 'bingx': 90}
                        timeout_value = timeouts.get(exchange_key, 75)
                        
                        result = await asyncio.wait_for(
                            self._check_single_exchange_auto(user_id, display_name, exchange_key, context),
                            timeout=timeout_value
                        )
                        return result
                    except Exception as e:
                        logger.error(f"  ❌ [{exchange_key}] Помилка: {e}")
                        return None
                
                tasks = [check_single(name, key) for name, key in group_exchanges.items()]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                found = {}
                for result in results:
                    if result and isinstance(result, dict):
                        found.update(result)
                return found
            
            logger.info(f"  📌 ГРУПА 1: Gate + KuCoin")
            group1_result = await check_exchange_group("1", first_group)
            all_found_tokens.update(group1_result)
            
            logger.info(f"  ⏳ Чекаю 10 секунд...")
            await asyncio.sleep(10)
            
            logger.info(f"  📌 ГРУПА 2: MEXC + BingX")
            group2_result = await check_exchange_group("2", second_group)
            all_found_tokens.update(group2_result)
            
            if all_found_tokens:
                await self.send_delisting_summary(context, user_id, all_found_tokens)
            
            logger.info(f"  ✅ Перевірка завершена")
            
        finally:
            setattr(self, check_key, False)
    async def handle_monthly_stats(self, update: Update, exchange_display_name: str):
       
        user_id = update.effective_user.id
        exchange_key = EXCHANGES.get(exchange_display_name)
        
        try:
          
            keys = get_exchange_keys(exchange_key)
            if not keys:
                await update.message.reply_text(f"❌ Немає API ключів для {exchange_display_name}")
                return
            
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
          
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
         
            current_balance = exchange.get_balance()
            current_total = current_balance['total_usdt']
            
          
            current_month = datetime.now().strftime('%Y-%m')
            previous_balance = self.db.get_monthly_balance(user_id, exchange_key, current_month)
            
          
            message_lines = [
                f"📅 **Статистика {exchange_display_name}**\n",
                f"📊 **Поточний баланс:** ${current_total:,.2f}\n"
            ]
            
            if previous_balance:
                old_total = previous_balance['total_balance']
                change = current_total - old_total
                change_percent = (change / old_total * 100) if old_total > 0 else 0
                
                emoji = "📈" if change >= 0 else "📉"
                sign = "+" if change >= 0 else ""
                
                message_lines.extend([
                    f"📅 **На початок місяця:** ${old_total:,.2f}",
                    f"{emoji} **Зміна:** {sign}${change:,.2f} ({sign}{change_percent:.1f}%)",
                    f"📆 **Період:** {current_month}"
                ])
                
               
                if previous_balance.get('balance_details'):
                    import json
                    details = previous_balance['balance_details']
                    if details:
                        message_lines.append(f"\n**🏆 Топ монет на початок місяця:**")
                        sorted_coins = sorted(details.items(), key=lambda x: x[1]['usdt_value'], reverse=True)[:5]
                        for coin, data in sorted_coins:
                            message_lines.append(f"  • {coin}: ${data['usdt_value']:,.2f}")
            else:
                message_lines.append(f"\n❌ Немає даних на початок місяця")
                message_lines.append(f"💡 Дані з'являться 1-го числа наступного місяця")
                
              
                message_lines.append(f"\n📝 Бажаєте зберегти поточний баланс як точку відліку?")
                
            
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = [[InlineKeyboardButton("✅ Зберегти як початок періоду", 
                                                callback_data=f"save_monthly_{exchange_display_name}")]]
                await update.message.reply_text(
                    "\n".join(message_lines),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            await update.message.reply_text(
                "\n".join(message_lines),
                parse_mode='Markdown'
            )
            
        
            await update.message.reply_text(
                f"🔙 Повернутись до меню {exchange_display_name}:",
                reply_markup=get_back_to_exchange_reply_keyboard(exchange_display_name)
            )
            
        except Exception as e:
            logger.error(f"Помилка отримання статистики: {e}")
            await update.message.reply_text(
                f"❌ **Помилка:** {str(e)[:200]}",
                reply_markup=get_back_to_exchange_reply_keyboard(exchange_display_name)
            )
            

    async def _check_single_exchange_auto(self, user_id: int, display_name: str, 
                                        exchange_key: str, context: ContextTypes.DEFAULT_TYPE) -> Optional[Dict]:
    
        
        keys = get_exchange_keys(exchange_key)
        if not keys:
            return None
        
        supported = ['gate', 'mexc', 'kucoin', 'bingx']
        if exchange_key not in supported:
            return None
        
   
        max_attempts = 3 if exchange_key == 'bingx' else 1
        
        for attempt in range(max_attempts):
            checker = None
            try:
                if attempt > 0:
                    logger.info(f"  🔄 [{exchange_key}] Спроба {attempt + 1}/{max_attempts}")
                    await asyncio.sleep(5)
                
                exchange = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: get_exchange_instance(
                        exchange_key, api_key=keys['api_key'], api_secret=keys['secret'], password=keys.get('password'))),
                    timeout=20
                )
                
                if exchange_key == 'bingx':
                    await asyncio.sleep(0.5)
                
                user_coins, coins_details = await self._get_cached_user_coins(user_id, exchange_key, exchange)
                
                if not user_coins:
                    return None
                
                from analysis.delisting_checker import DelistingChecker
                checker = DelistingChecker()
                
                timeouts = {'gate': 60, 'mexc': 90, 'kucoin': 60, 'bingx': 90}
                timeout_value = timeouts.get(exchange_key, 60)
                
                result = await asyncio.wait_for(checker.check_exchange_delistings(exchange_key, user_coins), timeout=timeout_value)
                found_tokens = result.get(exchange_key, set())
                
                if found_tokens:
                    sellable = set()
                    blocked = set()
                    
                    for token in found_tokens:
                        try:
                            markets = await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(None, exchange.exchange.load_markets), timeout=5)
                            symbol = f"{token}/USDT"
                            if symbol in markets:
                                info = markets[symbol].get('info', {})
                                if info.get('apiStateSell') == False:
                                    blocked.add(token)
                                    continue
                            sellable.add(token)
                        except:
                            sellable.add(token)
                    
                    if sellable:
                        await self.handle_delisted_tokens_auto(user_id, exchange_key, exchange, sellable, coins_details, context)
                        await self._update_cached_balance(user_id, exchange_key, exchange)
                    
                    if blocked:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"⚠️ **УВАГА! Монети не можна продати через API**\n\n**Монети:** {', '.join(blocked)}\n**Біржа:** {display_name}\n\n🔴 **Продайте вручну!**",
                            parse_mode='Markdown'
                        )
                    
                    return {exchange_key: found_tokens}
                
                return None
                
            except asyncio.TimeoutError:
                if exchange_key == 'bingx' and attempt < max_attempts - 1:
                    logger.warning(f"  ⏰ BingX таймаут, повторна спроба...")
                    continue
                return None
            except Exception as e:
                logger.error(f"❌ {exchange_key}: {e}")
                return None
            finally:
                if checker:
                    await checker.close()
        
        return None
    async def _init_balance_cache(self):
      
        logger.info("🔄 Ініціалізація кешу балансів...")
        
        configured_exchanges = get_all_configured_exchanges()
        users = self.get_all_users()
        
        for user_id in users:
            for display_name, exchange_key in configured_exchanges.items():
                try:
                
                    keys = get_exchange_keys(exchange_key)
                    if not keys:
                        logger.warning(f"  ⚠️ {exchange_key}: немає API ключів")
                        continue
                    
                    logger.info(f"  🔄 {exchange_key}: створюю екземпляр біржі...")
                    
                
                    exchange = get_exchange_instance(
                        exchange_key,
                        api_key=keys['api_key'],
                        api_secret=keys['secret'],
                        password=keys.get('password')
                    )
                    
                  
                    timeouts = {
                        'gate': 40,
                        'mexc': 60,
                        'kucoin': 30,
                        'bingx': 60  
                    }
                    timeout_value = timeouts.get(exchange_key, 30)
                    
                    logger.info(f"  ⏱️ {exchange_key}: отримую баланс (таймаут {timeout_value}с)...")
                    
                
                    try:
                        balance_data = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                None, exchange.get_balance
                            ),
                            timeout=timeout_value
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"  ⏰ {exchange_key}: таймаут отримання балансу ({timeout_value}с)")
                        continue
                    except Exception as e:
                        logger.error(f"  ❌ {exchange_key}: помилка отримання балансу: {e}")
                        continue
             
                    
               
                    cache_key = f"{user_id}_{exchange_key}"
                    self.user_coins_cache[cache_key] = {
                        'coins': set(),
                        'details': {},
                        'timestamp': datetime.now()
                    }
                    
                    coin_count = 0
                    for coin, data in balance_data['coins'].items():
                        if coin != 'USDT' and data['amount'] > 0:
                            self.user_coins_cache[cache_key]['coins'].add(coin)
                            self.user_coins_cache[cache_key]['details'][coin] = data
                            coin_count += 1
                    
                    logger.info(f"  ✅ {exchange_key}: закешовано {coin_count} монет")
                    
               
                    if exchange_key == 'bingx' and coin_count > 0:
                        logger.info(f"     📝 BingX монети: {sorted(self.user_coins_cache[cache_key]['coins'])[:10]}")
                    
                except Exception as e:
                    logger.error(f"  ❌ Помилка ініціалізації кешу для {exchange_key}: {e}")
                    import traceback
                    traceback.print_exc()
        
        logger.info("✅ Ініціалізація кешу балансів завершена")
    async def _get_cached_user_coins(self, user_id: int, exchange_key: str, exchange) -> tuple:

        
        shared = SharedData()
        cache_key = f"{user_id}_{exchange_key}"
        
   
        cache_lifetime = {
            'kucoin': 1800,   
            'gate': 3600,    
            'mexc': 3600,    
            'bingx': 1800     
        }
        lifetime = cache_lifetime.get(exchange_key, 3600)
        
    
        if cache_key in shared.user_coins_cache:
            cache_data = shared.user_coins_cache[cache_key]
            cache_time = cache_data.get('timestamp')
            
            if cache_time and (datetime.now() - cache_time).total_seconds() < lifetime:
                logger.info(f"  📦 Спільний кеш {exchange_key}: {len(cache_data['coins'])} монет")
                return cache_data['coins'], cache_data['details']
            else:
                logger.info(f"  🔄 Спільний кеш {exchange_key} застарів, оновлюю...")
        
    
        for attempt in range(2):
            try:
                balance_data = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, exchange.get_balance),
                    timeout=45 if exchange_key == 'bingx' else 30
                )
                break
            except asyncio.TimeoutError:
                if attempt == 0:
                    logger.warning(f"  ⚠️ {exchange_key} таймаут, повторна спроба...")
                    await asyncio.sleep(3)
                else:
                    raise
        
        user_coins = set()
        coins_details = {}
        
        for coin, data in balance_data['coins'].items():
            if coin != 'USDT' and data['amount'] > 0:
                user_coins.add(coin)
                coins_details[coin] = data
        
  
        shared.user_coins_cache[cache_key] = {
            'coins': user_coins,
            'details': coins_details,
            'timestamp': datetime.now()
        }
        
        logger.info(f"  ✅ Оновлено баланс {exchange_key}: {len(user_coins)} монет")
        return user_coins, coins_details
    async def _update_cached_balance(self, user_id: int, exchange_key: str, exchange):
    
        from core.shared_data import SharedData
        
    
        shared = SharedData()
        cache_key = f"{user_id}_{exchange_key}"
        
        try:
            balance_data = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, exchange.get_balance),
                timeout=30
            )
            
            user_coins = set()
            coins_details = {}
            
            for coin, data in balance_data['coins'].items():
                if coin != 'USDT' and data['amount'] > 0:
                    user_coins.add(coin)
                    coins_details[coin] = data
            
          
            shared.user_coins_cache[cache_key] = {
                'coins': user_coins,
                'details': coins_details,
                'timestamp': datetime.now()
            }
            
            logger.info(f"  🔄 Оновлено СПІЛЬНИЙ кеш для {exchange_key} після продажу: {len(user_coins)} монет")
            
        except Exception as e:
            logger.error(f"  ❌ Помилка оновлення кешу для {exchange_key}: {e}")
    async def _check_filled_orders_auto_internal(self, context: ContextTypes.DEFAULT_TYPE):
   
        users = self.get_all_users()
        if not users:
            return
        
        async def check_user(user_id):
            try:
                await asyncio.wait_for(self._check_single_user_orders(user_id, context), timeout=60)
            except:
                pass
        
        await asyncio.gather(*[check_user(u) for u in users], return_exceptions=True)
    async def _check_single_user_orders(self, user_id: int, context: ContextTypes.DEFAULT_TYPE):
   
        exchanges = get_all_configured_exchanges()
        if not exchanges:
            return
        
        async def check_exchange(display_name, exchange_key):
            try:
                cache_key = f"last_orders_check_{user_id}_{exchange_key}"
                last_check = self.last_orders_check.get(cache_key, 0)
                
                keys = get_exchange_keys(exchange_key)
                if not keys:
                    return
                
                exchange = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: get_exchange_instance(
                        exchange_key, api_key=keys['api_key'], api_secret=keys['secret'], password=keys.get('password'))),
                    timeout=15
                )
                
                timeout_val = 45 if exchange_key == 'bingx' else 30
                filled = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: exchange.check_filled_orders(last_check)),
                    timeout=timeout_val
                )
                
                if filled:
                    for order in filled:
                        order_key = f"{user_id}_{exchange_key}_{order['id']}"
                        if order_key in self.sent_order_notifications:
                            continue
                        
                        amount = order['amount']
                        amount_disp = f"{amount:.0f}" if amount > 1000 else (f"{amount:.1f}" if amount > 100 else f"{amount:.4f}")
                        
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"💰 **Монета продана!**\n\n**{order['symbol']}**\nКількість: {amount_disp}\nЦіна: ${order['price']:.6f}\nОтримано: ${order['cost']:.2f} USDT\nБіржа: {display_name}\n🕒 {order['datetime']}",
                            parse_mode='Markdown'
                        )
                        
                        self.sent_order_notifications[order_key] = datetime.now()
                        
                     
                        try:
                            new_balance = await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(None, exchange.get_balance),
                                timeout=30
                            )
                            
                            cache_key_bal = f"{user_id}_{exchange_key}"
                            new_coins = {}
                            for coin, data in new_balance['coins'].items():
                                if coin != 'USDT' and data['amount'] > 0:
                                    new_coins[coin] = data
                            
                            self.user_coins_cache[cache_key_bal] = {
                                'coins': set(new_coins.keys()),
                                'details': new_coins,
                                'timestamp': datetime.now()
                            }
                            logger.info(f"  🔄 Оновлено кеш {exchange_key} після продажу {order['symbol']}")
                        except:
                            pass
                 
                    
                    self.last_orders_check[cache_key] = int(datetime.now().timestamp() * 1000)
                
                self._cleanup_old_order_notifications()
                
            except asyncio.TimeoutError:
                if exchange_key == 'bingx':
                    logger.info(f"  ⏰ BingX: таймаут")
            except:
                pass
        
        await asyncio.gather(*[check_exchange(name, key) for name, key in exchanges.items()], return_exceptions=True)
    def get_all_users(self) -> List[int]:
        
        now = datetime.now()
        if hasattr(self, '_users_cache') and self._users_cache_time:
            if (now - self._users_cache_time).total_seconds() < 300:
                return self._users_cache
        
        users = [646621423]  
        
        try:
            conn = sqlite3.connect(self.db.db_name)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT user_id FROM user_api_keys")
            users.extend([row[0] for row in cursor.fetchall()])
            conn.close()
        except Exception as e:
            logger.error(f"Помилка отримання користувачів: {e}")
        
        self._users_cache = list(set(users))
        self._users_cache_time = now
        logger.info(f"✅ Оновлено кеш користувачів: {len(self._users_cache)} записів")
        return self._users_cache
    
    def _cleanup_old_order_notifications(self):
     
        now = datetime.now()
        to_delete = []
        
        for key, timestamp in self.sent_order_notifications.items():
            if (now - timestamp).total_seconds() > 86400: 
                to_delete.append(key)
        
        for key in to_delete:
            del self.sent_order_notifications[key]
        
        if to_delete:
            logger.info(f"🧹 Очищено {len(to_delete)} старих сповіщень про ордери")
    
    async def handle_bulk_orders(self, update: Update, exchange_display_name: str, context: ContextTypes.DEFAULT_TYPE):
      
        user_id = update.effective_user.id
        exchange_key = EXCHANGES.get(exchange_display_name)
        
       
        keys = get_exchange_keys(exchange_key)
        if not keys:
            await update.message.reply_text(
                f"❌ API ключі для {exchange_display_name} не знайдено.",
                reply_markup=get_main_reply_keyboard()
            )
            return
        
        try:
        
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
         
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
        
            await self.order_manager.start_bulk_orders(update, exchange, exchange_display_name)
            
        except Exception as e:
            logger.error(f"Помилка при виставленні ордерів: {e}")
            await update.message.reply_text(
                f"❌ **Помилка:** {str(e)[:200]}",
                reply_markup=get_back_to_exchange_reply_keyboard(exchange_display_name)
            )
    
    def cleanup_old_alerts(self):
     
        now = datetime.now()
        to_delete = []
        
        for key, timestamp in self.delisting_alerts_sent.items():
            if (now - timestamp).seconds > 86400:  # 24 години
                to_delete.append(key)
        
        for key in to_delete:
            del self.delisting_alerts_sent[key]
    
   

    async def handle_delisted_tokens_auto(self, user_id: int, exchange_key: str, exchange,
                                        found_tokens: Set[str], coins_details: Dict,
                                        context: ContextTypes.DEFAULT_TYPE):
     
        
        logger.info(f"⚠️ АВТОМАТИЧНА ОБРОБКА ДЕЛІСТИНГУ для {found_tokens}")
        
        if exchange_key == 'bingx':
            await asyncio.sleep(0.5)
        
        sold_tokens = []
        failed_tokens = []
        offline_tokens = []
        
        for token in found_tokens:
            try:
                symbol = f"{token}/USDT"
                amount = coins_details.get(token, {}).get('amount', 0)
                
                if amount <= 0:
                    logger.warning(f"  ⚠️ {token}: нульовий баланс, пропускаю")
                    continue
                
              
                try:
                    for order in exchange.get_open_orders(symbol) or []:
                        try:
                            exchange.cancel_order(order['id'], symbol)
                            await asyncio.sleep(0.2)
                        except:
                            pass
                except Exception as e:
                    logger.warning(f"  ⚠️ {token}: помилка зняття ордерів: {e}")
                
          
                can_sell = True
                price_info = None
                
                try:
                    ticker = exchange.get_ticker(symbol)
                    if not ticker or ticker.get('last', 0) == 0:
                        can_sell = False
                        offline_tokens.append(f"{token} (ціна = 0)")
                        continue
                    price_info = ticker['last']
                except Exception as e:
                    error_msg = str(e).lower()
                    if "offline" in error_msg or "not found" in error_msg or "inactive" in error_msg:
                        can_sell = False
                        offline_tokens.append(f"{token} (пара неактивна)")
                        continue
                    else:
                        logger.warning(f"  ⚠️ {token}: помилка отримання ціни: {e}")
                
                if not can_sell:
                    continue
                
       
                try:
                    order = exchange.create_market_sell_order(symbol, amount)
                    
                    if order:
                        sold_amount = order.get('amount', order.get('filled', amount))
                        avg_price = order.get('average', order.get('price', price_info))
                        total = sold_amount * avg_price
                        
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"✅ **Успішний продаж!**\n**Монета:** {token}\n**Кількість:** {sold_amount:.4f}\n**Ціна:** ${avg_price:.6f}\n**Отримано:** ${total:.2f} USDT\n**Біржа:** {exchange_key}",
                            parse_mode='Markdown'
                        )
                        sold_tokens.append(token)
                        await asyncio.sleep(0.5)
                    else:
                        failed_tokens.append(f"{token} (ордер не створено)")
                        
                except Exception as e:
                    error_msg = str(e).lower()
                    if "offline" in error_msg or "symbol is offline" in error_msg:
                        offline_tokens.append(f"{token} (пара неактивна)")
                    elif "insufficient" in error_msg:
                        failed_tokens.append(f"{token} (недостатньо коштів)")
                    elif "rate limit" in error_msg:
                        failed_tokens.append(f"{token} (ліміт запитів, спробуйте пізніше)")
                    else:
                        failed_tokens.append(f"{token} ({str(e)[:50]})")
                        logger.error(f"❌ Помилка продажу {token}: {e}")
                    
            except Exception as e:
                logger.error(f"❌ Критична помилка при обробці {token}: {e}")
                failed_tokens.append(f"{token} (критична помилка)")
        
  
        
    
        if sold_tokens:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ **Успішно продано на {exchange_key}:**\n{', '.join(sold_tokens)}",
                parse_mode='Markdown'
            )
        
    
        if failed_tokens:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ **НЕ ВДАЛОСЯ АВТОМАТИЧНО ПРОДАТИ на {exchange_key}:**\n{', '.join(failed_tokens)}\n\n🔴 **Потрібен ручний продаж!**\nВикористайте кнопку ⚠️ ST {exchange_key} для ручної перевірки та продажу.",
                parse_mode='Markdown'
            )
        
   
        if offline_tokens:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ **НЕАКТИВНІ ПАРИ на {exchange_key}:**\n{', '.join(offline_tokens)}\n\n🔴 **Ці монети вже не торгуються на біржі!**\nПеревірте баланс на сайті біржі - можливо, вони були автоматично конвертовані або виведені.",
                parse_mode='Markdown'
            )
        
    
        if sold_tokens or failed_tokens or offline_tokens:
            try:
                new_balance = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, exchange.get_balance),
                    timeout=30
                )
                
                cache_key = f"{user_id}_{exchange_key}"
                new_coins = {}
                for coin, data in new_balance['coins'].items():
                    if coin != 'USDT' and data['amount'] > 0:
                        new_coins[coin] = data
                
                self.user_coins_cache[cache_key] = {
                    'coins': set(new_coins.keys()),
                    'details': new_coins,
                    'timestamp': datetime.now()
                }
                
                logger.info(f"  🔄 Оновлено кеш {exchange_key}: {len(new_coins)} монет")
                
            except Exception as e:
                logger.error(f"  ❌ Помилка оновлення кешу: {e}")
    async def get_open_orders(self, exchange, symbol: str) -> List[Dict]:
     
        try:
       
            if hasattr(exchange.exchange, 'fetch_open_orders'):
                orders = await exchange.exchange.fetch_open_orders(symbol)
                return orders
            
          
            return []
        except Exception as e:
            logger.error(f"Помилка отримання ордерів для {symbol}: {e}")
            return []
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка команди /help"""
        help_text = (
            "🆘 **Довідка Crypto Portfolio Bot**\n\n"
            "📋 **Доступні команди:**\n"
            "• /start - Початок роботи, головне меню\n"
            "• /help - Ця довідка\n"
            "• /status - Статус налаштувань\n"
            "• /debug <біржа> <токен> - Детальний аналіз токена\n\n"
            "🔧 **Налаштування:**\n"
            "API ключі налаштовуються в файлі `.env`.\n"
            "Перезапустіть бота після зміни ключів.\n\n"
            "🏦 **Підтримувані біржі:**\n"
            "• KuCoin (потрібен passphrase)\n"
            "• Bitget (потрібен passphrase)\n"
            "• BingX\n"
            "• HTX\n"
            "• Gate.io\n"
            "• MEXC\n\n"
            "📊 **Функціонал:**\n"
            "1. **Баланс** - показує ваш портфель в USDT\n"
            "2. **Аналіз ВСІХ токенів** - шукає токени за критеріями\n"
            "3. **⚠️ АВТОМАТИЧНА ПЕРЕВІРКА ДЕЛІСТИНГУ** - кожні 10 хвилин\n"
            "4. **💹 АВТОМАТИЧНИЙ ПРОДАЖ** - при виявленні делістингу\n"
            "5. **📋 Перегляд лімітних ордерів** - ручна перевірка\n\n"
            "💰 **Важливо:** Бот використовує **ОБОРОТ (TURNOVER)** в USDT, не Volume!\n"
            "⏰ Час аналізу: 2-3 хвилини для тестового сканування.\n\n"
            "💡 **Порада:** Bitget має багато низькокапітальних токенів!\n\n"
            "📞 **Підтримка:**\n"
            "При проблемах використовуйте /debug для перевірки конкретного токена."
        )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробка команди /status"""
        configured_exchanges = get_all_configured_exchanges()
        
        status_message = (
            "📊 **Статус системи**\n\n"
            f"🤖 **Бот:** {'🟢 Активний' if BOT_TOKEN else '🔴 Не активний'}\n"
            f"📈 **Налаштовано бірж:** {len(configured_exchanges)}\n"
            f"🎯 **Критерії аналізу:**\n"
            f"• Амплітуда >{MIN_AMPLITUDE_PERCENT}% (high-low відносно open)\n"
            f"• **24h ОБОРОТ** ≤${MAX_VOLUME_USDT:,}/день (в USDT!)\n"
            f"• Мінімум {MIN_CANDLES_COUNT} днів за останні 30 днів\n"
            f"• **🏆 Відмічає монети з вашого портфеля**\n"
            f"• **⚠️ АВТОМАТИЧНА ПЕРЕВІРКА ДЕЛІСТИНГУ (ST)** - кожні 10 хвилин\n"
            f"• **💹 АВТОМАТИЧНИЙ ПРОДАЖ** - при виявленні делістингу\n"
            f"• **📋 Перегляд лімітних ордерів** - доступно в меню\n"
            f"• **Аналізуються перші 200 токенів (тестовий режим)**\n\n"
        )
        
        if configured_exchanges:
            status_message += "✅ **Доступні біржі:**\n"
            for exchange in configured_exchanges.keys():
                status_message += f"• {exchange}\n"
            
       
            status_message += "\n💡 **Поради:**\n"
            if 'Bitget' in configured_exchanges:
                status_message += "• Bitget - багато low-cap токенів, рекомендовано\n"
            if 'KuCoin' in configured_exchanges:
                status_message += "• KuCoin - гарна ліквідність\n"
            if 'MEXC' in configured_exchanges:
                status_message += "• MEXC - багато нових токенів\n"
            if 'BingX' in configured_exchanges:
                status_message += "• BingX - хороші API ліміти\n"
            if 'Gate.io' in configured_exchanges:
                status_message += "• Gate.io - багато низькокапітальних токенів\n"
            
            status_message += "\n⏰ **Автоматична перевірка делістингу:** кожні 10 хвилин"
        else:
            status_message += (
                "⚠️ **Немає налаштованих бірж**\n"
                "Додайте API ключі в файл `.env`\n\n"
                "**Приклад для Bitget:**\n"
                "```\n"
                "BITGET_API_KEY=ваш_ключ\n"
                "BITGET_SECRET_KEY=ваш_секрет\n"
                "BITGET_PASSPHRASE=ваш_пасфраза\n"
                "```\n\n"
                "**Приклад для KuCoin:**\n"
                "```\n"
                "KUCOIN_API_KEY=ваш_ключ\n"
                "KUCOIN_SECRET_KEY=ваш_секрет\n"
                "KUCOIN_PASSPHRASE=ваш_пасфраза\n"
                "```"
            )
        
        await update.message.reply_text(status_message, parse_mode='Markdown')
    
    async def debug_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Дебаг конкретного токена"""
        args = context.args
        if not args or len(args) < 2:
            await update.message.reply_text(
                "Використовуйте: /debug <exchange> <token>\n"
                "Наприклад: /debug gate MAJO/USDT\n"
                "Або: /debug gate MAJO"
            )
            return
        
        exchange_name = args[0].lower()
        token_symbol = args[1].upper()
        if not token_symbol.endswith('/USDT'):
            token_symbol = f"{token_symbol}/USDT"
        
     
        keys = get_exchange_keys(exchange_name)
        if not keys:
            await update.message.reply_text(f"❌ Біржа {exchange_name} не налаштована")
            return
        
        try:
          
            exchange = get_exchange_instance(
                exchange_name,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
          
            await update.message.reply_text(f"🔍 Детальний аналіз {token_symbol} на {exchange_name}...")
            
       
            try:
                ticker = exchange.get_ticker(token_symbol)
                result_lines = [
                    f"📊 **Тікер {token_symbol}**",
                    f"• Поточна ціна: ${ticker['last']:.6f}",
                    f"• 24h High: ${ticker['high']:.6f}",
                    f"• 24h Low: ${ticker['low']:.6f}",
                    f"• 24h Volume (токени): {ticker['volume']:,.0f}",
                    f"• **24h ОБОРОТ (USDT): ${ticker['turnover_24h']:,.0f}**",
                    f"• Зміна 24h: {ticker['percentage']:.2f}%",
                ]
                
             
                today_volume = exchange.get_today_volume_usdt(token_symbol)
                if today_volume:
                    result_lines.append(f"• Об'єм сьогодні (USDT): ${today_volume:,.0f}")
                
                await update.message.reply_text("\n".join(result_lines))
            except Exception as e:
                await update.message.reply_text(f"⚠️ Помилка отримання тікера: {str(e)}")
            
            #Отримуємо OHLCV дані
            ohlcv_data = exchange.get_ohlcv(token_symbol, '1d', 35)
            
            if not ohlcv_data or len(ohlcv_data) < 30:
                await update.message.reply_text(f"❌ Недостатньо даних для {token_symbol}")
                return
            
            # Аналізуємо вручну
            from analysis.candlestick_analyzer import CandlestickAnalyzer
            analyzer = CandlestickAnalyzer()
            
            analysis_result = analyzer.analyze_token_detailed(ohlcv_data, token_symbol)
            
            if 'error' in analysis_result:
                await update.message.reply_text(f"❌ Помилка аналізу: {analysis_result['error']}")
                return
            
            summary = analysis_result['summary']
            
            # Формуємо детальний звіт
            report_lines = [
                f"📈 **Детальний аналіз {token_symbol}**",
                f"**Період:** останні {summary['total_days']} днів",
                f"**Критерій амплітуди:** >{MIN_AMPLITUDE_PERCENT}%",
                f"**Днів з високою амплітудою:** {summary['high_amplitude_days']}",
                f"**Середня амплітуда:** {summary['avg_amplitude']:.1f}%",
                f"**Середній щоденний оборот:** ${summary['avg_daily_turnover']:,.0f}",
                f"**Загальний оборот за 30 днів:** ${summary['total_turnover']:,.0f}",
                f"**Максимальний оборот:** ${MAX_VOLUME_USDT:,}",
                f"**Статус:** {'✅ ПРОЙШОВ' if summary['high_amplitude_days'] >= MIN_CANDLES_COUNT and summary['avg_daily_turnover'] <= MAX_VOLUME_USDT else '❌ НЕ ПРОЙШОВ'}",
            ]
            
           
            high_amp_days = []
            for day in analysis_result['analysis']:
                if day['is_high_amplitude']:
                    high_amp_days.append(f"{day['date']}: {day['amplitude']:.1f}% (оборот ${day['turnover_usdt']:,.0f})")
            
            if high_amp_days:
                report_lines.append(f"\n**📅 Дні з амплітудою >{MIN_AMPLITUDE_PERCENT}%:**")
                for day_info in high_amp_days[:10]:  
                    report_lines.append(f"• {day_info}")
            
            await update.message.reply_text("\n".join(report_lines))
            
           
            sample_lines = ["\n**📊 Перші 5 днів (для перевірки):**"]
            for i, day in enumerate(analysis_result['analysis'][:5], 1):
                amplitude = analyzer.calculate_candle_amplitude(day['open'], day['high'], day['low'])
                is_high = amplitude >= MIN_AMPLITUDE_PERCENT
                sample_lines.append(
                    f"{i}. {day['date']}: "
                    f"Open=${day['open']:.6f}, "
                    f"High=${day['high']:.6f}, "
                    f"Low=${day['low']:.6f}, "
                    f"Close=${day['close']:.6f}, "
                    f"Амплітуда={amplitude:.1f}% {'✅' if is_high else ''}"
                )
            
            await update.message.reply_text("\n".join(sample_lines))
            
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {str(e)}")
            traceback.print_exc()
    
    async def check_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перевірка налаштувань"""
        query = update.callback_query
        await query.answer()
        
        configured_exchanges = get_all_configured_exchanges()
        
        if not configured_exchanges:
            message = (
                "⚠️ **Статус налаштувань**\n\n"
                "🔴 Не знайдено жодної налаштованої біржі.\n\n"
                "📝 **Що робити:**\n"
                "1. Додайте API ключі в файл `.env`\n"
                "2. Перезапустіть бота\n\n"
                "📋 **Приклад для Bitget:**\n"
                "```\n"
                "BITGET_API_KEY=ваш_ключ\n"
                "BITGET_SECRET_KEY=ваш_секрет\n"
                "BITGET_PASSPHRASE=ваш_пасфраза\n"
                "```\n\n"
                "📋 **Приклад для KuCoin:**\n"
                "```\n"
                "KUCOIN_API_KEY=ваш_ключ\n"
                "KUCOIN_SECRET_KEY=ваш_секрет\n"
                "KUCOIN_PASSPHRASE=ваш_пасфраза\n"
                "```"
            )
        else:
            message = "✅ **Налаштовані біржі:**\n\n"
            for display_name, exchange_key in configured_exchanges.items():
                keys = get_exchange_keys(exchange_key)
                has_password = 'password' in keys and keys['password']
                password_status = " (з пасфразою)" if has_password else ""
                
             
                special_notes = ""
                if exchange_key == 'bitget':
                    special_notes = " 🪙 багато low-cap"
                elif exchange_key == 'kucoin':
                    special_notes = " 💎 гарна ліквідність"
                elif exchange_key == 'mexc':
                    special_notes = " 🚀 нові токени"
                elif exchange_key == 'bingx':
                    special_notes = " ⚡ хороші ліміти"
                elif exchange_key == 'gate':
                    special_notes = " 📊 багато low-turnover"
                
                message += f"• **{display_name}** - ✓ Налаштовано{password_status}{special_notes}\n"
            
            message += f"\n📊 **Всього:** {len(configured_exchanges)} бірж(і)\n"
            message += f"🎯 **Критерії аналізу:** Амплітуда >{MIN_AMPLITUDE_PERCENT}%, Оборот ≤${MAX_VOLUME_USDT:,}/24h\n"
            message += f"⚠️ **АВТОМАТИЧНА ПЕРЕВІРКА ДЕЛІСТИНГУ (ST):** Активовано (кожні 10 хв)\n"
            message += f"💹 **АВТОМАТИЧНИЙ ПРОДАЖ:** Активовано\n"
            message += f"🏆 **НОВА ФІЧА:** Відмічає монети з вашого портфеля\n"
            
            message += "\n⚡ **Готово до роботи!**"
        
        await query.edit_message_text(
            message,
            reply_markup=get_main_reply_keyboard(),
            parse_mode='Markdown'
        )
    
    async def refresh_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Оновити конфігурацію"""
        query = update.callback_query
        await query.answer("🔄 Оновлюю налаштування...")
        
     
        keyboard = get_main_reply_keyboard()
        if keyboard:
            await query.edit_message_text(
                "✅ Налаштування оновлено!\n\n"
                "🏠 **Оберіть біржу для роботи:**",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "⚠️ **Не знайдено налаштованих бірж**\n\n"
                "Додайте API ключі в `.env` файл та перезапустіть бота.",
                parse_mode='Markdown'
            )
    
    async def handle_exchange_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
          
            query = update.callback_query
            await query.answer()
            
            exchange_display_name = query.data.replace('exchange_', '')
            exchange_key = EXCHANGES.get(exchange_display_name)
            
            if not exchange_key:
                await query.edit_message_text(
                    "❌ Помилка: біржа не знайдена",
                    reply_markup=get_main_reply_keyboard()
                )
                return
            
         
            if not has_exchange_keys(exchange_key):
            
                if exchange_key in ['kucoin', 'bitget']:
                    await query.edit_message_text(
                        f"❌ **{exchange_display_name} не налаштована**\n\n"
                        f"📝 Додайте в `.env` файл:\n"
                        f"```\n"
                        f"{exchange_key.upper()}_API_KEY=ваш_ключ\n"
                        f"{exchange_key.upper()}_SECRET_KEY=ваш_секрет\n"
                        f"{exchange_key.upper()}_PASSPHRASE=ваш_пасфраза\n"
                        f"```\n"
                        f"ℹ️ **{exchange_display_name} вимагає passphrase!**",
                        reply_markup=get_back_to_exchange_reply_keyboard()(exchange_display_name),
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text(
                        f"❌ **{exchange_display_name} не налаштована**\n\n"
                        f"📝 Додайте в `.env` файл:\n"
                        f"```\n"
                        f"{exchange_key.upper()}_API_KEY=ваш_ключ\n"
                        f"{exchange_key.upper()}_SECRET_KEY=ваш_секрет\n"
                        f"```",
                        reply_markup=get_back_to_exchange_reply_keyboard()(exchange_display_name),
                        parse_mode='Markdown'
                    )
                return
            
      
            welcome_extras = ""
            if exchange_key == 'bitget':
                welcome_extras = "\n💡 **Bitget:** Багато low-cap токенів для аналізу!"
            elif exchange_key == 'kucoin':
                welcome_extras = "\n💡 **KuCoin:** Гарна ліквідність та багато пар."
            elif exchange_key == 'mexc':
                welcome_extras = "\n💡 **MEXC:** Багато нових та ексклюзивних токенів."
            elif exchange_key == 'bingx':
                welcome_extras = "\n💡 **BingX:** Хороші API ліміти для повного сканування."
            elif exchange_key == 'gate':
                welcome_extras = "\n💡 **Gate.io:** Багато низькокапітальних токенів з низьким оборотом."
            
            welcome_extras += "\n\n🏆 **Нова функція:** Бот показує, які монети вже є у вашому портфелі!"
            welcome_extras += "\n⚠️ **АВТОМАТИЧНА ПЕРЕВІРКА ДЕЛІСТИНГУ (ST):** Активовано (кожні 10 хв)"
            welcome_extras += "\n💹 **АВТОМАТИЧНИЙ ПРОДАЖ:** Активовано"
            
            await query.edit_message_text(
                f"📊 **Ви обрали: {exchange_display_name}**{welcome_extras}\n\n"
                "🔧 **Оберіть дію:**",
                reply_markup=get_exchange_reply_keyboard()(exchange_display_name),
                parse_mode='Markdown'
            )
    
    async def get_user_balance_coins(self, user_id: int, exchange_key: str, exchange_instance) -> List[str]:
      
        try:
       
            cache_key = f"{user_id}_{exchange_key}"
            if cache_key in self.user_balances_cache:
                return self.user_balances_cache[cache_key]
            
     
            balance_data = exchange_instance.get_balance()
            coins = balance_data['coins']
            
    
            user_coins = []
            for coin, data in coins.items():
                if coin != 'USDT' and data['amount'] > 0:
                    user_coins.append(coin)
            
 
            self.user_balances_cache[cache_key] = user_coins
            
            logger.info(f"User {user_id} has {len(user_coins)} coins on {exchange_key}: {user_coins[:5]}...")
            return user_coins
            
        except Exception as e:
            logger.error(f"Error getting user balance for {user_id} on {exchange_key}: {e}")
            return []
    
    async def handle_save_monthly(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
     
        query = update.callback_query
        await query.answer()
        
        exchange_display_name = query.data.replace('save_monthly_', '')
        exchange_key = EXCHANGES.get(exchange_display_name)
        user_id = query.from_user.id
        
        try:
            keys = get_exchange_keys(exchange_key)
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
            balance_data = exchange.get_balance()
            
        
            self.db.save_monthly_balance(user_id, exchange_key, balance_data['total_usdt'], balance_data['coins'])
            
            await query.edit_message_text(
                f"✅ **Баланс збережено!**\n\n"
                f"Тепер ви можете відстежувати зміни за місяць.\n"
                f"Сума: ${balance_data['total_usdt']:,.2f}"
            )
            
        except Exception as e:
            await query.edit_message_text(f"❌ Помилка: {str(e)[:200]}")
    
    async def handle_balance(self, update: Update, exchange_display_name: str):
      
        user_id = update.effective_user.id
        exchange_key = EXCHANGES.get(exchange_display_name)
        
     
        cache_key = f"{user_id}_{exchange_key}"
        if cache_key in self.user_balances_cache:
            del self.user_balances_cache[cache_key]
        
       
        keys = get_exchange_keys(exchange_key)
        if not keys:
            await update.message.reply_text(
                f"❌ API ключі для {exchange_display_name} не знайдено.",
                reply_markup=get_main_reply_keyboard()
            )
            return
        
        try:
          
            loading_msg = await update.message.reply_text(f"🔄 Отримую баланс з {exchange_display_name}...")
            
      
            exchange = await asyncio.wait_for(
                asyncio.to_thread(
                    get_exchange_instance,
                    exchange_key,
                    keys['api_key'],
                    keys['secret'],
                    keys.get('password')
                ),
                timeout=20
            )
            
      
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
        
            balance_data = await asyncio.wait_for(
                asyncio.to_thread(exchange.get_balance),
                timeout=45 if exchange_key == 'bingx' else 30
            )
            
            total_usdt = balance_data['total_usdt']
            coins = balance_data['coins']
            
     
            message_lines = [
                f"💰 **Баланс на {exchange_display_name}**\n",
                f"📈 **Загальна сума:** ${total_usdt:,.2f} USDT\n"
            ]
            
            if coins:
                total_coins = len(coins)
                message_lines.append(f"📊 **Топ монети ({total_coins} всього):**")
                
                sorted_coins = list(coins.items())[:10]
                
                for coin, data in sorted_coins:
                    percentage = (data['usdt_value'] / total_usdt * 100) if total_usdt > 0 else 0
                    if percentage > 1:
                        message_lines.append(
                            f"• **{coin}:** {data['amount']:.4f} "
                            f"(${data['usdt_value']:,.2f} | {percentage:.1f}%)"
                        )
                    else:
                        message_lines.append(
                            f"• {coin}: {data['amount']:.4f} "
                            f"(${data['usdt_value']:,.2f})"
                        )
                
                if len(coins) > 10:
                    message_lines.append(f"\n📋 ... та ще {len(coins) - 10} монет")
            else:
                message_lines.append("📭 **Баланс порожній**")
            
       
            keyboard = get_back_to_exchange_reply_keyboard(exchange_display_name)
            
            await loading_msg.edit_text(
                "\n".join(message_lines),
                parse_mode='Markdown'
            )
            
        except asyncio.TimeoutError:
            logger.error(f"Таймаут отримання балансу для {exchange_display_name}")
            await update.message.reply_text(
                f"⏰ **Таймаут!** Біржа {exchange_display_name} не відповідає. Спробуйте пізніше.",
                reply_markup=get_back_to_exchange_reply_keyboard(exchange_display_name)
            )
        except Exception as e:
            logger.error(f"Помилка отримання балансу: {e}")
            await update.message.reply_text(
                f"❌ **Помилка:** {str(e)[:200]}",
                reply_markup=get_main_reply_keyboard()
            )
    

    async def send_delisting_summary(self, context: ContextTypes.DEFAULT_TYPE, 
                                    user_id: int, results: Dict[str, Set[str]]):
       
        if not self.notification_manager.is_enabled(user_id):
            return
        
        if not self.notification_manager.should_notify(user_id, results):
            return
        
        summary = self.notification_manager.format_delisting_summary(results)
        if not summary:
            return
        
        try:
            await context.bot.send_message(chat_id=user_id, text=summary, parse_mode='Markdown')
            self.notification_manager.save_summary(user_id, results)
        except Exception as e:
            logger.error(f"❌ Помилка відправки сповіщення: {e}")
        
    async def handle_orders_check(self, update: Update, exchange_display_name: str, context: ContextTypes.DEFAULT_TYPE):
   
        user_id = update.effective_user.id
        exchange_key = EXCHANGES.get(exchange_display_name)
        
        keys = get_exchange_keys(exchange_key)
        if not keys:
            await update.message.reply_text(f"❌ API ключі для {exchange_display_name} не знайдено.", reply_markup=get_main_reply_keyboard())
            return
        
        try:
            loading_msg = await update.message.reply_text(f"📋 **Перевірка лімітних ордерів на {exchange_display_name}...**\n\n⏳ Завантажую список ордерів...")
            
            exchange = get_exchange_instance(exchange_key, api_key=keys['api_key'], api_secret=keys['secret'], password=keys.get('password'))
            
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
            all_orders = exchange.get_open_orders()
            
            if not all_orders:
                await loading_msg.edit_text(f"📭 **На {exchange_display_name} немає відкритих лімітних ордерів**", parse_mode='Markdown')
                return
            
            message_lines = [f"📋 **Відкриті лімітні ордери на {exchange_display_name}**", f"**Всього ордерів:** {len(all_orders)}\n"]
            total_value = 0
            
            for i, order in enumerate(all_orders[:20], 1):
                symbol = order.get('symbol', 'Невідомо')
                side = order.get('side', 'unknown').upper()
                amount = float(order.get('amount', 0))
                price = float(order.get('price', 0))
                value = amount * price
                emoji = "📤" if side == 'SELL' else "📥"
                
                message_lines.append(f"{emoji} **{i}. {symbol}**\n   Тип: {side}\n   Кількість: {amount:.4f}\n   Ціна: ${price:.6f}\n   Сума: ${value:.2f}\n")
                total_value += value
            
            if len(all_orders) > 20:
                message_lines.append(f"📋 ... та ще {len(all_orders) - 20} ордерів")
            
            message_lines.append(f"\n💰 **Загальна сума в ордерах:** ${total_value:.2f}")
            
            await loading_msg.edit_text("\n".join(message_lines), parse_mode='Markdown')
            
            await update.message.reply_text("Керування ордерами:", reply_markup=get_orders_management_inline_keyboard(exchange_display_name))
            
        except Exception as e:
            logger.error(f"Помилка перевірки ордерів: {e}")
            await update.message.reply_text(f"❌ **Помилка перевірки ордерів:**\n\n{str(e)[:200]}", reply_markup=get_back_to_exchange_reply_keyboard(exchange_display_name))
    async def handle_cancel_all_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
      
        query = update.callback_query
        await query.answer("🗑️ Знімаю всі ордери...")
        
        exchange_display_name = query.data.replace('cancel_all_orders_', '')
        exchange_key = EXCHANGES.get(exchange_display_name)
        
      
        keys = get_exchange_keys(exchange_key)
        if not keys:
            await query.edit_message_text(
                f"❌ API ключі для {exchange_display_name} не знайдено.",
                reply_markup=get_main_reply_keyboard()  
            )
            return
        
        try:
        
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
          
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
       
            all_orders = exchange.get_open_orders()
            
            if not all_orders:
                await query.edit_message_text(
                    f"📭 Немає ордерів для зняття на {exchange_display_name}",
                    parse_mode='Markdown'
                )


                return
            
       
            cancelled = 0
            failed = 0
            
            message_lines = [
                f"🗑️ **Зняття всіх ордерів на {exchange_display_name}**\n"
            ]
            
            for order in all_orders:
                try:
                    symbol = order.get('symbol')
                    order_id = order.get('id')
                    
                    if exchange.cancel_order(order_id, symbol):
                        cancelled += 1
                        message_lines.append(f"✅ Знято: {symbol}")
                    else:
                        failed += 1
                    
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    failed += 1
                    logger.error(f"Помилка зняття ордера: {e}")
            
            message_lines.append(f"\n📊 **Результат:**")
            message_lines.append(f"✅ Знято: {cancelled}")
            if failed > 0:
                message_lines.append(f"❌ Помилок: {failed}")
            
            await query.edit_message_text(
                "\n".join(message_lines),
                parse_mode='Markdown'
            )
            

            
        except Exception as e:
            logger.error(f"Помилка зняття ордерів: {e}")
            await query.edit_message_text(
                f"❌ **Помилка зняття ордерів:**\n\n{str(e)[:200]}",
                parse_mode='Markdown'
            )
        
    async def handle_tokens_analysis(self, update: Update, exchange_display_name: str, context: ContextTypes.DEFAULT_TYPE):
    
        user_id = update.effective_user.id
        
      
        if user_id in self.scan_in_progress and self.scan_in_progress[user_id]:
            await update.message.reply_text(
                "⏳ Сканування вже виконується. Зачекайте завершення..."
            )
            return
        
        exchange_key = EXCHANGES.get(exchange_display_name)
        
     
        keys = get_exchange_keys(exchange_key)
        if not keys:
            await update.message.reply_text(
                f"❌ API ключі для {exchange_display_name} не знайдено в конфігурації.",
                reply_markup=get_main_reply_keyboard()
            )
            return
        
       
        info_message = (
            f"🔍 **ПОВНЕ сканування токенів на {exchange_display_name}**\n\n"
            f"**🎯 Критерії пошуку:**\n"
            f"1. Амплітуда свічки >{MIN_AMPLITUDE_PERCENT}%\n"
            f"2. Середній щоденний оборот ≤${MAX_VOLUME_USDT:,} за 30 днів\n"
            f"3. Мінімум {MIN_CANDLES_COUNT} днів з амплітудою >{MIN_AMPLITUDE_PERCENT}%\n\n"
            f"**🏆 НОВА ФУНКЦІЯ:**\n"
            f"• Монети, які вже є у вашому портфелі, будуть позначені 🏆\n\n"
            f"**⚡ ТЕСТОВИЙ РЕЖИМ:** аналіз перших 200 монет\n\n"
            f"⏰ **Сканування розпочато... Це може зайняти 2-3 хвилини.**\n"
            f"Я надішлю результати, коли сканування завершиться. ⏱️"
        )
        
        await update.message.reply_text(info_message, parse_mode='Markdown')
        
    
        asyncio.create_task(
            self.perform_scan_async(
                update.message.chat_id, 
                user_id, 
                exchange_display_name, 
                exchange_key, 
                keys, 
                update.message.chat_id,
                context  
            )
        )
    
    
    async def perform_scan_async(self, chat_id: int, user_id: int, exchange_display_name: str,
                            exchange_key: str, keys: Dict, original_chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Асинхронне виконання сканування"""
        try:
          
            self.scan_in_progress[user_id] = True
            
       
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
      
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
         
            user_coins = await self.get_user_balance_coins(user_id, exchange_key, exchange)
            
      
            scanner = TokenScanner(exchange)
            
        
            filtered_tokens = await scanner.scan_all_low_turnover_tokens()
            
        
            for token in filtered_tokens:
                symbol_without_usdt = token['symbol'].replace('/USDT', '')
                token['in_portfolio'] = symbol_without_usdt in user_coins
            
           
            self.scan_results[user_id] = {
                'exchange': exchange_display_name,
                'tokens': filtered_tokens,
                'user_coins': user_coins,
                'timestamp': datetime.now()
            }
            
           
            self.current_page[user_id] = 0
            
           
            await self.send_scan_results(context, user_id, chat_id, 0)
            
        except Exception as e:
            logger.error(f"Error in async scan on {exchange_display_name}: {e}")
            import traceback
            traceback.print_exc()
            
            error_details = str(e)
            if "rate limit" in error_details.lower():
                error_msg = f"⏳ **Перевищено ліміт запитів до {exchange_display_name}**\n\nЗачекайте 10-15 хвилин."
            elif "network" in error_details.lower():
                error_msg = f"🌐 **Проблема з мережевим з'єднанням**\n\nПеревірте інтернет."
            else:
                error_msg = f"❌ **Помилка сканування:**\n\n{error_details[:150]}..."
            
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=error_msg,
                    parse_mode='Markdown'
                )
            except:
                pass
        
        finally:
          
            self.scan_in_progress[user_id] = False
        
        
    async def send_scan_results(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, page: int = 0):
       
        TOKENS_PER_PAGE = 30
        
        if user_id not in self.scan_results:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Результати сканування не знайдені."
            )
            return
        
        scan_data = self.scan_results[user_id]
        filtered_tokens = scan_data['tokens']
        exchange_display_name = scan_data['exchange']
        user_coins = scan_data.get('user_coins', [])
        
        if not filtered_tokens:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔍 **Результати ПОВНОГО сканування {exchange_display_name}**\n\n❌ Не знайдено токенів, що відповідають критеріям.",
                parse_mode='Markdown'
            )

            return
        
      
        total_tokens = len(filtered_tokens)
        total_pages = (total_tokens + TOKENS_PER_PAGE - 1) // TOKENS_PER_PAGE
        
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        
        self.current_page[user_id] = page
        
        start_idx = page * TOKENS_PER_PAGE
        end_idx = min(start_idx + TOKENS_PER_PAGE, total_tokens)
        page_tokens = filtered_tokens[start_idx:end_idx]
        
       
        message_lines = [
            f"📊 **Результати сканування {exchange_display_name}**",
            f"**Сторінка {page + 1}/{total_pages}** (токени {start_idx + 1}-{end_idx} з {total_tokens})\n",
            f"**🎯 Критерії:** Амплітуда >{MIN_AMPLITUDE_PERCENT}%, Оборот ≤${MAX_VOLUME_USDT:,}\n",
            f"**🏆 Монет у портфелі:** {len(user_coins)}",
            f"**📈 Знайдені токени:**\n"
        ]
        
        for i, token in enumerate(page_tokens, start=start_idx + 1):
            amplitude_days = token['high_amplitude_candles_count']
            if amplitude_days >= 15:
                emoji = "🔥🔥"
            elif amplitude_days >= 10:
                emoji = "🔥"
            elif amplitude_days >= 7:
                emoji = "⚡"
            else:
                emoji = "📈"
            
            portfolio_marker = " 🏆 В ПОРТФЕЛІ" if token.get('in_portfolio', False) else ""
            symbol_short = token['symbol'].replace('/USDT', '')
            message_lines.append(f"{emoji} **{i}. {symbol_short}** - {amplitude_days} днів{portfolio_marker}")
        
     
        inline_keyboard = get_scan_results_inline_keyboard(exchange_display_name, page, total_pages)
        
     
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(message_lines),
            parse_mode='Markdown',
            reply_markup=inline_keyboard
        )
        
        
        
    async def handle_page_navigation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
     
        query = update.callback_query
        
 
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"Could not answer callback query for page nav: {e}")
       
        
        user_id = query.from_user.id
        data = query.data.replace('page_', '')
        
    
        parts = data.split('_')
        if len(parts) < 2:
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ Помилка навігації"
                )
            except:
                pass
            return
        
        try:
            exchange_display_name = parts[0]
            page = int(parts[1])
            
         
            self.current_page[user_id] = page
            
          
            await self.edit_scan_results_page(query, context, user_id, page)
            
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing page navigation data: {e}")
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ Помилка навігації"
                )
            except:
                pass
    
    async def edit_scan_results_page(self, query, context, user_id: int, page: int = 0):
      
        TOKENS_PER_PAGE = 30
        
     
        if user_id not in self.scan_results:
            try:
                await query.edit_message_text(
                    "❌ Результати сканування не знайдені. Будь ласка, запустіть сканування знову."
                )
            except:
                pass
            return
        
        scan_data = self.scan_results[user_id]
        filtered_tokens = scan_data['tokens']
        exchange_display_name = scan_data['exchange']
        user_coins = scan_data.get('user_coins', [])
        
        if not filtered_tokens:
            try:
                await query.edit_message_text(
                    f"❌ Не знайдено токенів, що відповідають критеріям на {exchange_display_name}",
                    reply_markup=get_back_to_exchange_reply_keyboard()(exchange_display_name)
                )
            except:
                pass
            return
        
     
        total_tokens = len(filtered_tokens)
        total_pages = (total_tokens + TOKENS_PER_PAGE - 1) // TOKENS_PER_PAGE
        
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        
     
        self.current_page[user_id] = page
        
      
        start_idx = page * TOKENS_PER_PAGE
        end_idx = min(start_idx + TOKENS_PER_PAGE, total_tokens)
        page_tokens = filtered_tokens[start_idx:end_idx]
        
      
        message_lines = [
            f"📊 **Результати сканування {exchange_display_name}**",
            f"**Сторінка {page + 1}/{total_pages}** (токени {start_idx + 1}-{end_idx} з {total_tokens})\n",
            f"**🎯 Застосовані критерії:**",
            f"• Амплітуда >{MIN_AMPLITUDE_PERCENT}% (high-low відносно open)",
            f"• Середній щоденний оборот ≤${MAX_VOLUME_USDT:,} (за 30 днів)",
            f"• Мінімум {MIN_CANDLES_COUNT} днів з амплітудою >{MIN_AMPLITUDE_PERCENT}%\n",
            f"**🏆 Монет у вашому портфелі:** {len(user_coins)}",
            f"**📈 Знайдені токени:**\n"
        ]
        
        for i, token in enumerate(page_tokens, start=start_idx + 1):
        
            amplitude_days = token['high_amplitude_candles_count']
            if amplitude_days >= 15:
                emoji = "🔥🔥"
            elif amplitude_days >= 10:
                emoji = "🔥"
            elif amplitude_days >= 7:
                emoji = "⚡"
            elif amplitude_days >= MIN_CANDLES_COUNT:
                emoji = "📈"
            else:
                emoji = "📊"
            
        
            portfolio_marker = " 🏆 В ПОРТФЕЛІ" if token.get('in_portfolio', False) else ""
            
          
            symbol_short = token['symbol'].replace('/USDT', '')
            message_lines.append(f"{emoji} **{i}. {symbol_short}** - {amplitude_days} днів{portfolio_marker}")
        
      
        keyboard_buttons = []
        
     
        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ Попередня", callback_data=f"page_{exchange_display_name}_{page-1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="current_page"))
            
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Наступна ➡️", callback_data=f"page_{exchange_display_name}_{page+1}"))
            
            if nav_buttons:
                keyboard_buttons.append(nav_buttons)
        
      
        keyboard_buttons.append([InlineKeyboardButton("🔄 Оновити баланс", callback_data=f"refresh_balance_{exchange_display_name}")])
        
   
        keyboard_buttons.append([InlineKeyboardButton("🔙 Повернутись до меню", callback_data=f"exchange_{exchange_display_name}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        
     
        try:
            await query.edit_message_text(
                "\n".join(message_lines),
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Could not edit message for page navigation: {e}")
           
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="\n".join(message_lines),
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            except:
                pass
    
    
    async def handle_notifications_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
      
        query = update.callback_query
        
       
        await query.answer()
        
        user_id = query.from_user.id
        is_enabled = self.notification_manager.is_enabled(user_id)
        
       
        from keyboards import get_notifications_menu_keyboard
        keyboard = get_notifications_menu_keyboard(is_enabled)
        
        await query.edit_message_text(
            "🔔 **Керування сповіщеннями про ST монети**\n\n"
            "Тут ви можете ввімкнути або вимкнути автоматичні сповіщення "
            "про знайдені монети в списках делістингу.\n\n"
            "📊 Сповіщення приходять після кожної автоматичної перевірки (кожні 10 хвилин).\n\n"
            f"**Поточний статус:** {'🟢 УВІМКНЕНО' if is_enabled else '🔴 ВИМКНЕНО'}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    async def handle_notifications_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ввімкнути/вимкнути сповіщення"""
        query = update.callback_query
        await query.answer()
    
        user_id = query.from_user.id
        action = query.data  
    
        enabled = action == 'notifications_on'
        self.notification_manager.set_enabled(user_id, enabled)
    
      
        keyboard = get_notifications_menu_keyboard(user_id, self.notification_manager)
    
        status_text = "🟢 УВІМКНЕНО" if enabled else "🔴 ВИМКНЕНО"

        await query.edit_message_text(
            f"🔔 **Керування сповіщеннями про ST монети**\n\n"
            f"✅ Налаштування збережено!\n"
            f"**Поточний статус:** {status_text}\n\n"
            f"📊 Сповіщення приходять після кожної автоматичної перевірки (кожні 10 хвилин).",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

    async def handle_refresh_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    
        query = update.callback_query
        
      
        try:
            await query.answer("🔄 Оновлюю інформацію про баланс...")
        except Exception as e:
            logger.warning(f"Could not answer callback query for balance refresh: {e}")
        
        user_id = query.from_user.id
        exchange_display_name = query.data.replace('refresh_balance_', '')
        exchange_key = EXCHANGES.get(exchange_display_name)
        
      
        cache_key = f"{user_id}_{exchange_key}"
        if cache_key in self.user_balances_cache:
            del self.user_balances_cache[cache_key]
        
      
        if user_id in self.scan_results:
            try:
           
                keys = get_exchange_keys(exchange_key)
                if keys:
                
                    exchange = get_exchange_instance(
                        exchange_key,
                        api_key=keys['api_key'],
                        api_secret=keys['secret'],
                        password=keys.get('password')
                    )
                    
               
                    user_coins = await self.get_user_balance_coins(user_id, exchange_key, exchange)
                    
                  
                    for token in self.scan_results[user_id]['tokens']:
                        symbol_without_usdt = token['symbol'].replace('/USDT', '')
                        token['in_portfolio'] = symbol_without_usdt in user_coins
                    
                    self.scan_results[user_id]['user_coins'] = user_coins
                    
                
                    current_page = self.current_page.get(user_id, 0)
                    await self.edit_scan_results_page(query, context, user_id, current_page)
                else:
                    try:
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text="❌ Не вдалося оновити баланс: API ключі не знайдені"
                        )
                    except:
                        pass
            
            except Exception as e:
                logger.error(f"Error refreshing balance: {e}")
                try:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="❌ Помилка оновлення балансу"
                    )
                except:
                    pass
    
    async def handle_delisting_check(self, update: Update, exchange_display_name: str, context: ContextTypes.DEFAULT_TYPE):
        """Ручна перевірка монет на делістинг (ST)"""
        user_id = update.effective_user.id
        exchange_key = EXCHANGES.get(exchange_display_name)
        
     
        keys = get_exchange_keys(exchange_key)
        if not keys:
            await update.message.reply_text(
                f"❌ API ключі для {exchange_display_name} не знайдено.",
                reply_markup=get_main_reply_keyboard()
            )
            return
        
        try:
            
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
          
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
          
            loading_msg = await update.message.reply_text(
                f"🔍 **Ручна перевірка монет на делістинг ({exchange_display_name})...**\n\n"
                f"⏳ Завантажую інформацію про ваш баланс..."
            )
            
        
            balance_data = exchange.get_balance()
            user_coins = set()
            coins_details = {}
            
            for coin, data in balance_data['coins'].items():
                if coin != 'USDT' and data['amount'] > 0:
                    user_coins.add(coin)
                    coins_details[coin] = data
            
            if not user_coins:
                await loading_msg.edit_text(
                    f"📭 У вас немає монет на {exchange_display_name}",
                    parse_mode='Markdown'
                )

                return
            
    
            await loading_msg.edit_text(
                f"🔍 **Ручна перевірка монет на делістинг ({exchange_display_name})...**\n\n"
                f"💰 Знайдено {len(user_coins)} монет у вашому портфелі\n"
                f"🌐 Завантажую останні оголошення про делістинг...\n\n"
                f"⏳ Це може зайняти кілька секунд..."
            )
            
        
            checker = DelistingChecker()
            
            try:
             
                result = await checker.check_exchange_delistings(
                    exchange_key,
                    user_coins
                )
                
                found_tokens = result.get(exchange_key, set())
                
                if found_tokens:
                 
                    message_lines = [
                        f"⚠️ **УВАГА! Знайдено монети в списках делістингу на {exchange_display_name}**\n",
                        f"**Знайдені монети ({len(found_tokens)}):**\n"
                    ]
                    
                    for token in sorted(found_tokens):
                        if token in coins_details:
                            amount = coins_details[token]['amount']
                            value = coins_details[token]['usdt_value']
                            message_lines.append(f"• **{token}**: {amount:.4f} (${value:,.2f})")
                        else:
                            message_lines.append(f"• **{token}**")
                    
                    await loading_msg.edit_text(
                        "\n".join(message_lines),
                        parse_mode='Markdown'
                    )
                    
                  
                    inline_keyboard = get_delisting_results_inline_keyboard(exchange_display_name, True)
                    await update.message.reply_text(
                        "Оберіть дію:",
                        reply_markup=inline_keyboard
                    )
                    

                else:
                    await loading_msg.edit_text(
                        f"✅ **Ваші монети на {exchange_display_name} в безпеці!**\n\n"
                        f"Жодна з ваших {len(user_coins)} монет не знайдена в списках делістингу.",
                        parse_mode='Markdown'
                    )

                    
            finally:
                await checker.close()
                
        except Exception as e:
            logger.error(f"Помилка ручної перевірки делістингу: {e}")
            await update.message.reply_text(
                f"❌ **Помилка перевірки делістингу:**\n\n{str(e)[:200]}",
                reply_markup=get_back_to_exchange_reply_keyboard(exchange_display_name)
            )
    async def handle_sell_delisted(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
       
        query = update.callback_query
        await query.answer("💰 Продаю знайдені монети...")
        
        user_id = query.from_user.id
        exchange_display_name = query.data.replace('sell_delisted_', '')
        exchange_key = EXCHANGES.get(exchange_display_name)
        
      
        keys = get_exchange_keys(exchange_key)
        if not keys:
            await query.edit_message_text(
                f"❌ API ключі для {exchange_display_name} не знайдено.",
                reply_markup=get_back_to_exchange_reply_keyboard()(exchange_display_name)
            )
            return
        
        try:
         
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
           
            if exchange_key == 'bingx':
                await asyncio.sleep(0.5)
            
            
            balance_data = exchange.get_balance()
            coins_details = balance_data['coins']
            
         
            message_text = query.message.text
            found_tokens = set()
            
        
            import re
            
         
            lines = message_text.split('\n')
            for line in lines:
                
                match = re.match(r'•\s+([A-Z0-9]+):', line.strip())
                if match:
                    token = match.group(1)
                    found_tokens.add(token)
                    logger.info(f"Знайдено монету з повідомлення: {token}")
            
           
            if not found_tokens:
              
                potential_tokens = re.findall(r'\b([A-Z]{2,10})\b', message_text)
                
              
                for token in potential_tokens:
                    if token in coins_details:
                        found_tokens.add(token)
                        logger.info(f"Знайдено через потенційний пошук: {token}")
            
          
            if not found_tokens:
                logger.error(f"Не вдалося знайти монети в тексті: {message_text[:500]}")
                
            
                await query.edit_message_text(
                    f"❌ **Помилка парсингу монет**\n\n"
                    f"Текст повідомлення:\n```\n{message_text[:500]}...\n```\n\n"
                    f"Будь ласка, використайте кнопку \"⚠️ Перевірити делістинг\" знову.",
                    reply_markup=get_back_to_exchange_reply_keyboard()(exchange_display_name),
                    parse_mode='Markdown'
                )
                return
            
            logger.info(f"🚨 Ручний продаж для монет: {found_tokens}")
            
          
            await self.handle_delisted_tokens_auto(
                user_id, exchange_key, exchange,
                found_tokens, coins_details, context
            )
            
           
            try:
                await query.message.delete()
            except:
                pass
            
        except Exception as e:
            logger.error(f"Помилка ручного продажу: {e}")
            await query.edit_message_text(
                f"❌ **Помилка:**\n\n{str(e)[:200]}",
                reply_markup=get_back_to_exchange_reply_keyboard()(exchange_display_name),
                parse_mode='Markdown'
            )

   
    async def handle_quick_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
     
        query = update.callback_query
        await query.answer()
        
        exchange_display_name = query.data.replace('quick_', '')
        
        await query.edit_message_text(
            f"⚡ **Швидке сканування {exchange_display_name}**\n\n"
            "Функція в розробці. Використовуйте повне сканування для аналізу токенів.",
            reply_markup=get_back_to_exchange_reply_keyboard()(exchange_display_name),
            parse_mode='Markdown'
        )
    
    async def handle_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
      
        query = update.callback_query
        await query.answer()
        
        keyboard = get_main_reply_keyboard()
        if keyboard:
            await query.edit_message_text(
                "🏠 **Оберіть біржу для роботи:**",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "⚠️ **Не знайдено налаштованих бірж**\n\n"
                "Додайте API ключі в `.env` файл та перезапустіть бота.",
                parse_mode='Markdown'
            )

            
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
       
        logger.error(f"Exception while handling an update: {context.error}")
        
       
        try:
            error_msg = str(context.error)[:200]
            if isinstance(update, Update) and update.callback_query:
                try:
                    await update.callback_query.message.reply_text(
                        f"❌ **Сталася помилка:**\n{error_msg}...\n\nСпробуйте ще раз."
                    )
                except:
                    pass
            elif isinstance(update, Update) and update.message:
                await update.message.reply_text(
                    f"❌ **Сталася помилка:**\n{error_msg}...\n\nСпробуйте ще раз."
                )
        except Exception as e:
            logger.error(f"Error in error handler: {e}")

def main():
    """Запуск бота"""
  
    if not BOT_TOKEN or BOT_TOKEN == 'ваш_токен_бота_з_@BotFather':
        print("❌ Помилка: TELEGRAM_BOT_TOKEN не встановлено в файлі .env")
        print("\n📄 Створіть файл .env з таким вмістом:")
        print("=" * 65)
        print("TELEGRAM_BOT_TOKEN=ваш_токен_з_botfather")
        print("\n# Bitget (рекомендовано для low-cap токенів)")
        print("BITGET_API_KEY=ваш_ключ")
        print("BITGET_SECRET_KEY=ваш_секрет")
        print("BITGET_PASSPHRASE=ваш_пасфраза")
        print("\n# KuCoin")
        print("KUCOIN_API_KEY=ваш_ключ")
        print("KUCOIN_SECRET_KEY=ваш_секрет")
        print("KUCOIN_PASSPHRASE=ваш_пасфраза")
        print("\n# MEXC")
        print("MEXC_API_KEY=ваш_ключ")
        print("MEXC_SECRET_KEY=ваш_секрет")
        print("\n# BingX")
        print("BINGX_API_KEY=ваш_ключ")
        print("BINGX_SECRET_KEY=ваш_секрет")
        print("\n# Gate.io")
        print("GATE_API_KEY=ваш_ключ")
        print("GATE_SECRET_KEY=ваш_секрет")
        print("=" * 65)
        print("\n💡 Додайте ключі для бірж, які ви хочете використовувати")
        print("🎯 Bitget чудово підходить для пошуку low-cap токенів!")
        return
    
   
    configured_exchanges = get_all_configured_exchanges()
    
    print("=" * 60)
    print("🤖 Crypto Portfolio Bot - Запуск системи")
    print("=" * 60)
    
    if configured_exchanges:
        print(f"✅ Налаштовано бірж: {len(configured_exchanges)}")
        for exchange in configured_exchanges:
            print(f"  ✓ {exchange}")
        
      
        print("\n💡 **Рекомендації:**")
        if 'Bitget' in configured_exchanges:
            print("  • Bitget: багато low-cap токенів (найкраще для сканування)")
        if 'KuCoin' in configured_exchanges:
            print("  • KuCoin: гарна ліквідність")
        if 'MEXC' in configured_exchanges:
            print("  • MEXC: нові токени")
        if 'BingX' in configured_exchanges:
            print("  • BingX: хороші API ліміти")
        if 'Gate.io' in configured_exchanges:
            print("  • Gate.io: багато низькокапітальних токенів")
    else:
        print("⚠️ Увага: Не знайдено жодної налаштованої біржі")
        print("   Додайте API ключі в файл .env")
    
    print(f"\n🎯 **Критерії аналізу токенів:**")
    print(f"• Амплітуда >{MIN_AMPLITUDE_PERCENT}% (high-low відносно open)")
    print(f"• **Середній щоденний оборот ≤${MAX_VOLUME_USDT:,}/день (за 30 днів)**")
    print(f"• Мінімум {MIN_CANDLES_COUNT} днів з амплітудою >{MIN_AMPLITUDE_PERCENT}% за останні 30 днів")
    print(f"• 🏆 **НОВА ФІЧА:** Показує монети, які вже є у вашому портфелі")
    print(f"• ⚠️ **АВТОМАТИЧНА ПЕРЕВІРКА ДЕЛІСТИНГУ (ST):** Кожні 10 хвилин")
    print(f"• 💹 **АВТОМАТИЧНИЙ ПРОДАЖ:** При виявленні делістингу")
    print(f"• 📋 **ПЕРЕГЛЯД ОРДЕРІВ:** Доступно в меню")
    print(f"• ⚠️ ТЕСТОВИЙ РЕЖИМ: перші 200 монет")
    print("=" * 60)
    
    
    bot = None
    
    try:
     
        application = Application.builder().token(BOT_TOKEN).build()
        
        bot = CryptoBot()
        from core.shared_data import SharedData
        shared = SharedData()

      
        try:
         
            pass
        except:
            pass
       
        application.add_handler(CommandHandler("start", bot.start))
        application.add_handler(CommandHandler("help", bot.help_command))
        application.add_handler(CommandHandler("status", bot.status_command))
        application.add_handler(CommandHandler("debug", bot.debug_token))

        application.add_handler(CallbackQueryHandler(bot.handle_cancel_all_orders, pattern="^cancel_all_orders_"))
        application.add_handler(CallbackQueryHandler(bot.handle_sell_delisted, pattern="^sell_delisted_"))
        application.add_handler(CallbackQueryHandler(bot.handle_quick_scan, pattern="^quick_"))
        application.add_handler(CallbackQueryHandler(bot.handle_back, pattern="^back_to_main"))
        application.add_handler(CallbackQueryHandler(bot.check_config, pattern="^check_config$"))
        application.add_handler(CallbackQueryHandler(bot.refresh_config, pattern="^refresh_config$"))
       
    
        application.add_handler(CallbackQueryHandler(bot.handle_page_navigation, pattern="^page_"))
      
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
        application.add_error_handler(bot.error_handler)
        
        application.add_handler(CallbackQueryHandler(bot.handle_save_monthly, pattern="^save_monthly_"))
        application.add_handler(CallbackQueryHandler(bot.handle_notifications_toggle, pattern="^notifications_status$"))
        
        
        application.add_handler(CallbackQueryHandler(bot.handle_refresh_balance, pattern="^refresh_balance_"))
        
        
        if application.job_queue:
         
            async def setup_jobs_callback(context):
                await bot.start_auto_delisting_check(context)
            
            application.job_queue.run_once(setup_jobs_callback, when=1, name='setup_auto_checks')
            print("⏰ Заплановано налаштування автоматичних перевірок через 1 секунду")
        else:
            print("⚠️ УВАГА: JobQueue не доступний!")
        
     
        print("\n🚀 Бот запущено...")
        print("📱 Відкрийте Telegram та знайдіть свого бота")
        print("⚡ Використовуйте команду /start для початку")
        print("💬 Команда /help - довідка, /status - статус системи")
        print("🔍 Команда /debug <біржа> <токен> - детальний аналіз токена")
        print("💰 **ВАЖЛИВО:** Бот використовує середній щоденний оборот за 30 днів!")
        print("🏆 **НОВА ФІЧА:** Показує монети, які вже є у вашому портфелі")
        print("⚠️ **АВТОМАТИЧНА ПЕРЕВІРКА ДЕЛІСТИНГУ (ST):** Кожні 10 хвилин")
        print("💹 **АВТОМАТИЧНИЙ ПРОДАЖ:** При виявленні делістингу")
        print("📋 **ПЕРЕГЛЯД ОРДЕРІВ:** Нова кнопка в меню біржі")
        print("📄 **ПАГІНАЦІЯ:** результати відображаються по 30 токенів на сторінці")
        print("🔄 **ОНОВЛЕННЯ:** кнопка 'Оновити баланс' для актуальної інформації")
        print("⏰ **ВАЖЛИВО:** Сканування триває 2-3 хвилини - зачекайте результатів")
        print("⚠️ ТЕСТОВИЙ РЕЖИМ: аналіз перших 200 монет")
        print("🛑 Натисніть Ctrl+C для зупинки\n")
        
      
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=['message', 'callback_query'],
            timeout=30
        )
        
    except KeyboardInterrupt:
        print("\n\n🛑 Бот зупинено користувачем")
    except Exception as e:
        print(f"❌ Критична помилка: {e}")
        traceback.print_exc()
    finally:
      
        if bot and hasattr(bot, '_global_checker') and bot._global_checker:
            try:
                import asyncio
              
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                loop.run_until_complete(bot._global_checker.close())
                print("✅ Глобальний чекер Playwright закрито")
            except Exception as e:
                print(f"⚠️ Помилка при закритті Playwright: {e}")
     

if __name__ == '__main__':
    main()