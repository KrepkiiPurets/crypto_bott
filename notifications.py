import json
import sqlite3
from typing import Dict, List, Set
from datetime import datetime
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

class NotificationManager:
 
    
    def __init__(self, db_name: str = 'crypto_bot.db'):
        self.db_name = db_name
        self._init_database()
    
    def _init_database(self):
   
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_notifications (
                user_id INTEGER PRIMARY KEY,
                enabled BOOLEAN DEFAULT 1,
                last_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def is_enabled(self, user_id: int) -> bool:
        """Перевірити, чи ввімкнені сповіщення для користувача"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT enabled FROM user_notifications WHERE user_id = ?",
            (user_id,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return bool(result[0])
        else:
           
            self.set_enabled(user_id, True)
            return True
    
    def set_enabled(self, user_id: int, enabled: bool):
        """Ввімкнути або вимкнути сповіщення для користувача"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_notifications (user_id, enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, 1 if enabled else 0))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Сповіщення для користувача {user_id} {'ввімкнено' if enabled else 'вимкнено'}")
    
    def save_summary(self, user_id: int, summary_data: Dict):
        """Зберегти інформацію про останнє сповіщення"""
        conn = None
        try:
            
            serializable_data = {}
            for exchange, tokens in summary_data.items():
                if isinstance(tokens, set):
                    serializable_data[exchange] = list(tokens)
                else:
                    serializable_data[exchange] = tokens
            
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE user_notifications 
                SET last_summary = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (json.dumps(serializable_data), user_id))
            
            conn.commit()
            logger.info(f"✅ Збережено сповіщення для користувача {user_id}: {serializable_data}")
            
        except Exception as e:
            logger.error(f"❌ Помилка збереження сповіщення для {user_id}: {e}")
        finally:
            if conn:
                conn.close()
    
    def format_delisting_summary(self, results: Dict[str, Set[str]]) -> str:
        """
        Сформувати коротке повідомлення про знайдені ST монети
        
        Args:
            results: Словник {exchange: [tokens]}
        
        Returns:
            Відформатоване повідомлення
        """
        if not results:
            return ""
        
        total_found = 0
        exchange_lines = []
        
      
        exchange_names = {
            'gate': 'Gate.io',
            'mexc': 'MEXC',
            'kucoin': 'KuCoin',
            'bingx': 'BingX'
        }
        
        for exchange, tokens in results.items():
            if tokens:
                count = len(tokens)
                total_found += count
                name = exchange_names.get(exchange, exchange)
                tokens_str = ', '.join(sorted(tokens))
                exchange_lines.append(f"• **{name}**: {count} монет ({tokens_str})")
        
        if total_found == 0:
            return "✅ **ST монети не знайдено**"
        
        
        if total_found >= 5:
            emoji = "🚨🚨🚨"
        elif total_found >= 3:
            emoji = "⚠️⚠️"
        elif total_found >= 1:
            emoji = "⚠️"
        else:
            emoji = "✅"
        
        message = (
            f"{emoji} **ЗВІТ ПРО ST МОНЕТИ** {emoji}\n\n"
            f"**Всього знайдено:** {total_found} монет у списках делістингу\n\n"
            + "\n".join(exchange_lines) +
            f"\n\n💡 Детальна інформація в меню кожної біржі"
        )
        
        return message
    


    def should_notify(self, user_id: int, new_results: Dict[str, Set[str]]) -> bool:
        """
        Перевірити, чи потрібно відправляти сповіщення
        
        Args:
            user_id: ID користувача
            new_results: Нові результати перевірки (з set)
        
        Returns:
            True якщо потрібно відправити сповіщення
        """
        if not self.is_enabled(user_id):
            logger.info(f"Користувач {user_id} вимкнув сповіщення")
            return False
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT last_summary FROM user_notifications WHERE user_id = ?",
            (user_id,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if not result or not result[0]:
          
            logger.info(f"Немає попередніх даних для користувача {user_id}, відправляємо")
            return True
        
        try:
            last_summary = json.loads(result[0])
            
       
            for exchange, tokens in new_results.items():
      
                new_tokens_set = set(tokens)
                last_tokens_set = set(last_summary.get(exchange, []))
                
                if new_tokens_set != last_tokens_set:
                    logger.info(f"Змінився набір монет для {exchange}: було {last_tokens_set}, стало {new_tokens_set}")
                    return True
            
            logger.info(f"Набір монет не змінився для користувача {user_id}")
            return False
        except Exception as e:
            logger.error(f"Помилка перевірки should_notify: {e}")
            return True


def add_notification_button_to_keyboard(keyboard):
    
    from telegram import InlineKeyboardButton
    
  
    if keyboard and keyboard.inline_keyboard:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton("🔔 Керування сповіщеннями", callback_data="notifications_menu")
        ])
    
    return keyboard


def get_notifications_menu_keyboard(user_id: int, notification_manager) -> InlineKeyboardMarkup:

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    is_enabled = notification_manager.is_enabled(user_id)
    
    status_text = "🟢 Увімкено" if is_enabled else "🔴 ВИМКНЕНО"
    toggle_text = "🔕 Вимкнути" if is_enabled else "🔔 Увімкнути"
    toggle_callback = "notifications_off" if is_enabled else "notifications_on"
    
    keyboard = [
        [InlineKeyboardButton(f"Статус: {status_text}", callback_data="notifications_status")],
        [InlineKeyboardButton(toggle_text, callback_data=toggle_callback)],
        [InlineKeyboardButton("🔙 Головне меню", callback_data="back_to_main")]
    ]
    
    return InlineKeyboardMarkup(keyboard)