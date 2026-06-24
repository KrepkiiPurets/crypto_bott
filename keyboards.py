from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from config import get_all_configured_exchanges



def get_main_reply_keyboard():
   
    configured_exchanges = get_all_configured_exchanges()
    
    if not configured_exchanges:
        return None
    
 
    exchange_buttons = []
    for exchange_name in configured_exchanges.keys():
        exchange_buttons.append([KeyboardButton(f"🏦 {exchange_name}")])
    
  
    exchange_buttons.append([
        KeyboardButton("🔔 Сповіщення"),
        KeyboardButton("⚙️ Статус")
    ])
    
    return ReplyKeyboardMarkup(
        exchange_buttons,
        resize_keyboard=True, 
        one_time_keyboard=False  
    )

def get_exchange_reply_keyboard(exchange_name: str):
   
    keyboard = [
        [KeyboardButton(f"💰 Баланс {exchange_name}")],
        [KeyboardButton(f"🔍 Аналіз {exchange_name}")],
        [KeyboardButton(f"⚠️ ST {exchange_name}")],
        [KeyboardButton(f"📋 Ордери {exchange_name}")],
        [KeyboardButton("🏠 Головне меню")]
    ]
    
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_notifications_reply_keyboard(is_enabled: bool):
   
    status_text = "🔴 Вимкнено" if not is_enabled else "🟢 Увімкнено"
    
    keyboard = [
        [KeyboardButton(f"📊 Статус: {status_text}")],
        [KeyboardButton("🔕 Вимкнути" if is_enabled else "🔔 Увімкнути")],
        [KeyboardButton("🏠 Головне меню")]
    ]
    
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_back_to_exchange_reply_keyboard(exchange_name: str):
    
    keyboard = [
        [KeyboardButton(f"🔙 Назад до {exchange_name}")],
        [KeyboardButton("🏠 Головне меню")]
    ]
    
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_confirmation_reply_keyboard(action: str, exchange_name: str):
   
    keyboard = [
        [
            KeyboardButton(f"✅ Так, {action}"),
            KeyboardButton(f"❌ Ні, назад")
        ],
        [KeyboardButton("🏠 Головне меню")]
    ]
    
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )

def clear_keyboard():
  
    return ReplyKeyboardMarkup([[]], resize_keyboard=True)



def get_scan_results_inline_keyboard(exchange_name: str, current_page: int, total_pages: int):
   
    keyboard = []
    
  
    if total_pages > 1:
        nav_buttons = []
        if current_page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"page_{exchange_name}_{current_page-1}"))
        
        nav_buttons.append(InlineKeyboardButton(f"{current_page+1}/{total_pages}", callback_data="current_page"))
        
        if current_page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"page_{exchange_name}_{current_page+1}"))
        
        keyboard.append(nav_buttons)
    
   
    keyboard.append([InlineKeyboardButton("🔄 Оновити баланс", callback_data=f"refresh_balance_{exchange_name}")])
    
    return InlineKeyboardMarkup(keyboard)

def get_delisting_results_inline_keyboard(exchange_name: str, has_tokens: bool = False):
   
    keyboard = []
    
    if has_tokens:
        keyboard.append([InlineKeyboardButton("💰 Продати всі знайдені", callback_data=f"sell_delisted_{exchange_name}")])
    
    return InlineKeyboardMarkup(keyboard)

def get_orders_management_inline_keyboard(exchange_name: str):
    
    keyboard = [
        [InlineKeyboardButton("🗑️ Зняти всі ордери", callback_data=f"cancel_all_orders_{exchange_name}")],
        [InlineKeyboardButton("🔄 Оновити", callback_data=f"refresh_orders_{exchange_name}")]
    ]
    
    return InlineKeyboardMarkup(keyboard)



def get_exchange_reply_keyboard(exchange_name: str):
   
    keyboard = [
        [KeyboardButton(f"💰 Баланс {exchange_name}")],
        [KeyboardButton(f"📅 Статистика {exchange_name}")],  
        [KeyboardButton(f"🔍 Аналіз {exchange_name}")],
        [KeyboardButton(f"⚠️ ST {exchange_name}")],
        [KeyboardButton(f"📋 Ордери {exchange_name}")],
        [KeyboardButton(f"🎯 Виставити ордери {exchange_name}")],
        [KeyboardButton("🏠 Головне меню")]
    ]
    
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )