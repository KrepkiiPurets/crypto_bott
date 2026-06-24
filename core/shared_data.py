import asyncio
from datetime import datetime
from typing import Dict, Set, List, Optional
import logging
import json
import os

logger = logging.getLogger(__name__)


class SharedData:

    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.user_coins_cache = {}
        self.scan_results = {}
        self.last_delisting_check = {}
        self.delisting_alerts_sent = {}
        self.last_orders_check = {}
        self.sent_order_notifications = {}
        self._users_cache = None
        self._users_cache_time = None
        self.delisting_check_running = False
        self.balance_cache_initialized = False  
        self.notification_callbacks = []
        self.cache_file = "balance_cache.json"
        self._load_cache_from_disk()
    
    def _get_cache_path(self) -> str:
   
        return os.path.join(os.path.dirname(__file__), '..', self.cache_file)
    
    def _load_cache_from_disk(self):
   
        try:
            cache_path = self._get_cache_path()
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
       
                for key, value in data.items():
                    if 'timestamp' in value:
                        value['timestamp'] = datetime.fromisoformat(value['timestamp'])
                    self.user_coins_cache[key] = value
                
                logger.info(f"📦 Завантажено кеш з диска: {len(self.user_coins_cache)} записів")
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося завантажити кеш: {e}")
    
    def _save_cache_to_disk(self):
     
        try:
            cache_path = self._get_cache_path()
       
            data = {}
            for key, value in self.user_coins_cache.items():
                data[key] = {
                    'coins': list(value['coins']),
                    'details': value['details'],
                    'timestamp': value['timestamp'].isoformat()
                }
            
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"💾 Кеш збережено на диск: {len(self.user_coins_cache)} записів")
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося зберегти кеш: {e}")
    
    def update_balance_cache(self, user_id: int, exchange_key: str, 
                             coins: Set[str], details: Dict):
 
        cache_key = f"{user_id}_{exchange_key}"
        self.user_coins_cache[cache_key] = {
            'coins': coins,
            'details': details,
            'timestamp': datetime.now()
        }
   
        self._save_cache_to_disk()
        logger.debug(f"🔄 Оновлено кеш для {exchange_key}: {len(coins)} монет")
    
    def get_balance_cache(self, user_id: int, exchange_key: str, 
                          max_age_seconds: int = 3600) -> Optional[tuple]:
 
        cache_key = f"{user_id}_{exchange_key}"
        
        if cache_key in self.user_coins_cache:
            cache_data = self.user_coins_cache[cache_key]
            cache_time = cache_data.get('timestamp')
            
            if cache_time and (datetime.now() - cache_time).total_seconds() < max_age_seconds:
                logger.debug(f"📦 Кеш {exchange_key}: {len(cache_data['coins'])} монет")
                return cache_data['coins'], cache_data['details']
        
        return None
    
    def invalidate_balance_cache(self, user_id: int, exchange_key: str = None):
      
        if exchange_key:
            cache_key = f"{user_id}_{exchange_key}"
            if cache_key in self.user_coins_cache:
                del self.user_coins_cache[cache_key]
                logger.info(f"🗑️ Очищено кеш для {exchange_key}")
        else:
        
            keys_to_delete = [k for k in self.user_coins_cache.keys() if k.startswith(f"{user_id}_")]
            for key in keys_to_delete:
                del self.user_coins_cache[key]
            logger.info(f"🗑️ Очищено всі кеші для користувача {user_id}")
        
        self._save_cache_to_disk()
    
    def is_balance_cache_fresh(self, user_id: int, exchange_key: str, 
                                max_age_seconds: int = 3600) -> bool:
      
        cache_key = f"{user_id}_{exchange_key}"
        
        if cache_key in self.user_coins_cache:
            cache_time = self.user_coins_cache[cache_key].get('timestamp')
            if cache_time:
                return (datetime.now() - cache_time).total_seconds() < max_age_seconds
        return False
    
    
    
    def register_notification_callback(self, callback):
    
        self.notification_callbacks.append(callback)
        logger.info(f"✅ Зареєстровано callback для сповіщень")
    
    async def send_notification(self, message: str, user_id: int = None):
       
        for callback in self.notification_callbacks:
            try:
                await callback(message, user_id)
            except Exception as e:
                logger.error(f"❌ Помилка відправки сповіщення: {e}")
    
    def get_all_users(self) -> List[int]:
   
        users = []
        users.append(646621423)  
       
        return list(set(users))
    
    def set_balance_cache_initialized(self):
     
        self.balance_cache_initialized = True
    
    def is_balance_cache_initialized(self) -> bool:
    
        return self.balance_cache_initialized
    
    def set_balance_cache_initialized(self):
    
        self.balance_cache_initialized = True
        logger.info("✅ Спільний кеш позначено як ініціалізований")