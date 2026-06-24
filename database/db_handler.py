import sqlite3
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

class DatabaseHandler:
    def __init__(self, db_name: str = 'crypto_bot.db'):
        self.db_name = db_name
        self.init_database()
    
    def init_database(self):
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
       
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monthly_balance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                exchange TEXT,
                month_year TEXT,
                total_balance REAL,
                balance_details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                exchange_keys TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
 
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                exchange TEXT,
                scan_date TEXT,
                tokens_found INTEGER,
                scan_duration REAL,
                results TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Базу даних ініціалізовано")
    
    def save_monthly_balance(self, user_id: int, exchange: str, total_balance: float, 
                            balance_details: dict):
        """Зберегти баланс на початок місяця"""
        month_year = datetime.now().strftime('%Y-%m')
   
        logger.info(f"💾 Зберігаю баланс для {exchange}")
        logger.info(f"   user_id: {user_id}")
        logger.info(f"   month_year: {month_year}")
        logger.info(f"   total_balance: {total_balance}")
        logger.info(f"   balance_details type: {type(balance_details)}")
        
     
        if isinstance(balance_details, dict):
            logger.info(f"   balance_details keys: {list(balance_details.keys())}")
            balance_details_json = json.dumps(balance_details, ensure_ascii=False)
        elif isinstance(balance_details, str):
            logger.info(f"   balance_details is string, length: {len(balance_details)}")
    
            try:
       
                json.loads(balance_details)
                balance_details_json = balance_details
                logger.info(f"   balance_details is valid JSON string")
            except:
         
                balance_details_json = json.dumps({"raw": balance_details})
                logger.warning(f"   balance_details is not valid JSON, wrapping")
        else:
 
            logger.warning(f"   balance_details is {type(balance_details)}, converting to string")
            balance_details_json = json.dumps({"data": str(balance_details)})
        
        logger.info(f"   balance_details_json type: {type(balance_details_json)}")
        logger.info(f"   balance_details_json preview: {balance_details_json[:200]}...")
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO monthly_balance (user_id, exchange, month_year, total_balance, balance_details)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, exchange, month_year, total_balance, balance_details_json))
            
            conn.commit()
            logger.info(f"✅ Баланс успішно збережено в БД")
        except Exception as e:
            logger.error(f"❌ Помилка SQLite: {e}")
        finally:
            conn.close()
    def get_monthly_balance(self, user_id: int, exchange: str, month_year: str = None):
 
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        if month_year:
            cursor.execute('''
                SELECT * FROM monthly_balance 
                WHERE user_id = ? AND exchange = ? AND month_year = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id, exchange, month_year))
        else:
       
            cursor.execute('''
                SELECT * FROM monthly_balance 
                WHERE user_id = ? AND exchange = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id, exchange))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            try:
         
                balance_details_raw = result[5]  
                
                logger.info(f"📖 Читаю баланс для {exchange}")
                logger.info(f"   raw data type: {type(balance_details_raw)}")
                
             
                if isinstance(balance_details_raw, dict):
                    logger.error(f"   ⚠️ ПОМИЛКА: balance_details_raw вже словник!")
                    balance_details = balance_details_raw  
                else:
               
                    balance_details = json.loads(balance_details_raw) if balance_details_raw else {}
                    logger.info(f"   ✅ JSON розпарсено успішно")
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ Помилка парсингу JSON: {e}")
                logger.error(f"   problematic data: {balance_details_raw[:200] if balance_details_raw else 'None'}")
                balance_details = {}
            except Exception as e:
                logger.error(f"❌ Інша помилка: {e}")
                balance_details = {}
            
            return {
                'id': result[0],
                'user_id': result[1],
                'exchange': result[2],
                'month_year': result[3],
                'total_balance': result[4],
                'balance_details': balance_details,
                'created_at': result[6]
            }
        
        logger.info(f"Баланс для {exchange} не знайдено")
        return None

    def save_scan_results(self, user_id: int, exchange: str, tokens_found: int, 
                         scan_duration: float, results: list):
  
        scan_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO scan_results (user_id, exchange, scan_date, tokens_found, scan_duration, results)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, exchange, scan_date, tokens_found, scan_duration, json.dumps(results, ensure_ascii=False)))
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Результати сканування збережено для {user_id}")
    
    def get_recent_scans(self, user_id: int, limit: int = 5):
 
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM scan_results 
            WHERE user_id = ?
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (user_id, limit))
        
        results = cursor.fetchall()
        conn.close()
        
        scans = []
        for result in results:
            try:
                scans.append({
                    'id': result[0],
                    'user_id': result[1],
                    'exchange': result[2],
                    'scan_date': result[3],
                    'tokens_found': result[4],
                    'scan_duration': result[5],
                    'results': json.loads(result[6]) if result[6] else [],
                    'created_at': result[7]
                })
            except json.JSONDecodeError as e:
                logger.error(f"Помилка парсингу результатів сканування: {e}")
                continue
        
        return scans
