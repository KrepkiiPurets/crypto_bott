from abc import ABC, abstractmethod
import ccxt
from typing import Dict, List, Optional, Tuple
import time
import logging
from datetime import datetime
logger = logging.getLogger(__name__)

class BaseExchange(ABC):
    def __init__(self, api_key: str = None, api_secret: str = None, password: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.password = password
        self.exchange = None
        self.setup_exchange()
    
    @abstractmethod
    def setup_exchange(self):
        pass
    
    def get_balance(self) -> Dict:
      
        try:
            balance = self.exchange.fetch_balance()
            total_usdt = 0
            coins_data = {}
            
            for coin, amount in balance['total'].items():
                if amount > 0:  
                    try:
                        if coin == 'USDT':
                            coins_data[coin] = {
                                'amount': float(amount),
                                'usdt_value': float(amount)
                            }
                            total_usdt += float(amount)
                        else:
                            symbol = f"{coin}/USDT"
                            ticker = self.exchange.fetch_ticker(symbol)
                            usdt_value = amount * ticker['last']
                            
                            if usdt_value > 0.01:  
                                coins_data[coin] = {
                                    'amount': float(amount),
                                    'usdt_value': float(usdt_value)
                                }
                                total_usdt += usdt_value
                    except Exception as e:
                        continue
            
            sorted_coins = dict(sorted(coins_data.items(), 
                                      key=lambda x: x[1]['usdt_value'], 
                                      reverse=True))
            
            return {
                'total_usdt': float(total_usdt),
                'coins': sorted_coins
            }
        except Exception as e:
            raise Exception(f"Error fetching balance: {str(e)}")
    
    def get_ohlcv(self, symbol: str, timeframe: str = '1d', limit: int = 30) -> List[Dict]:
   
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            candles = []
            for candle in ohlcv:
                candles.append({
                    'timestamp': int(candle[0]),
                    'open': float(candle[1]),
                    'high': float(candle[2]),
                    'low': float(candle[3]),
                    'close': float(candle[4]),
                    'volume': float(candle[5])  
                })
            return candles
        except Exception as e:
            raise Exception(f"Error fetching OHLCV for {symbol}: {str(e)}")
    
    def get_ticker(self, symbol: str) -> Dict:
    
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            
            if self.exchange.id == 'gateio':
                return self._gateio_parse_ticker(ticker, symbol)
            
            return self._standard_parse_ticker(ticker, symbol)
            
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            return {
                'symbol': symbol,
                'last': 0,
                'high': 0,
                'low': 0,
                'volume': 0,
                'turnover_24h': 0,
                'percentage': 0,
                'change': 0,
                'timestamp': 0
            }

    def _standard_parse_ticker(self, ticker: dict, symbol: str) -> dict:
   
        last = ticker.get('last')
        if last is None:
            last = ticker.get('close', 0)
        if last is None:
            last = 0
        last = float(last)
        
        high = ticker.get('high')
        if high is None:
            high = last
        high = float(high)
        
        low = ticker.get('low')
        if low is None:
            low = last
        low = float(low)
        
        volume = ticker.get('volume')
        if volume is None:
            volume = 0
        volume = float(volume)
        
        if 'quoteVolume' in ticker and ticker['quoteVolume'] is not None:
            turnover_24h = float(ticker['quoteVolume'])
        elif volume > 0 and last > 0:
            avg_price = (high + low) / 2 if high > 0 and low > 0 else last
            turnover_24h = volume * avg_price
        else:
            turnover_24h = 0
        
        return {
            'symbol': symbol,
            'last': last,
            'high': high,
            'low': low,
            'volume': volume,
            'turnover_24h': turnover_24h,
            'percentage': float(ticker.get('percentage', 0)),
            'change': float(ticker.get('change', 0)),
            'timestamp': ticker.get('timestamp', 0)
        }

    def _gateio_parse_ticker(self, ticker: dict, symbol: str) -> dict:
     
        try:
            logger.debug(f"Gate.io raw ticker for {symbol}: {ticker}")
            
            last = ticker.get('last')
            if last is None:
                last = ticker.get('close')
            if last is None:
                info = ticker.get('info', {})
                last = info.get('last') or info.get('close')
            if last is None:
                last = 0
            
            try:
                last = float(last) if last is not None else 0
            except (TypeError, ValueError):
                last = 0
            
            high = ticker.get('high')
            if high is None:
                high = last
            try:
                high = float(high) if high is not None else last
            except (TypeError, ValueError):
                high = last
            
            low = ticker.get('low')
            if low is None:
                low = last
            try:
                low = float(low) if low is not None else last
            except (TypeError, ValueError):
                low = last
            
            volume = ticker.get('volume')
            if volume is None:
                info = ticker.get('info', {})
                volume = info.get('volume')
            try:
                volume = float(volume) if volume is not None else 0
            except (TypeError, ValueError):
                volume = 0
            
            turnover_24h = 0
            if 'quoteVolume' in ticker and ticker['quoteVolume'] is not None:
                try:
                    turnover_24h = float(ticker['quoteVolume'])
                except (TypeError, ValueError):
                    pass
            elif 'info' in ticker:
                info = ticker['info']
                if 'quote_volume' in info:
                    try:
                        turnover_24h = float(info['quote_volume'])
                    except (TypeError, ValueError):
                        pass
            
            if turnover_24h == 0 and volume > 0 and last > 0:
                avg_price = (high + low) / 2 if high > 0 and low > 0 else last
                turnover_24h = volume * avg_price
            
            percentage = ticker.get('percentage', 0)
            if percentage is None:
                info = ticker.get('info', {})
                percentage = info.get('change_percentage', 0)
            try:
                percentage = float(percentage) if percentage is not None else 0
            except (TypeError, ValueError):
                percentage = 0
            
            result = {
                'symbol': symbol,
                'last': last,
                'high': high,
                'low': low,
                'volume': volume,
                'turnover_24h': turnover_24h,
                'percentage': percentage,
                'change': float(ticker.get('change', 0)),
                'timestamp': ticker.get('timestamp', 0)
            }
            
            logger.info(f"Gate.io parsed {symbol}: last=${last:.6f}, volume={volume:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"Gate.io parse error for {symbol}: {e}")
            return {
                'symbol': symbol,
                'last': 0,
                'high': 0,
                'low': 0,
                'volume': 0,
                'turnover_24h': 0,
                'percentage': 0,
                'change': 0,
                'timestamp': 0
            }
        
        
    def get_current_price(self, symbol: str) -> float:

        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return float(ticker['last'])
        except Exception as e:
            raise Exception(f"Error fetching price for {symbol}: {str(e)}")
    
    def get_today_volume_usdt(self, symbol: str) -> Optional[float]:
  
        try:
            ohlcv_today = self.exchange.fetch_ohlcv(symbol, '1d', limit=1)
            if not ohlcv_today:
                return None
            
            candle = ohlcv_today[0]
            volume_tokens = float(candle[5])
            high = float(candle[2])
            low = float(candle[3])
            avg_price = (high + low) / 2
            volume_usdt = volume_tokens * avg_price
            
            return volume_usdt
        except Exception as e:
            print(f"Error getting today's volume for {symbol}: {str(e)}")
            return None
    
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:

        try:
            if hasattr(self.exchange, 'fetch_open_orders'):
                orders = self.exchange.fetch_open_orders(symbol)
                
                normalized_orders = []
                for order in orders:
                    normalized_orders.append({
                        'id': order.get('id'),
                        'symbol': order.get('symbol'),
                        'type': order.get('type', 'limit'),
                        'side': order.get('side'),
                        'amount': float(order.get('amount', 0)),
                        'price': float(order.get('price', 0)),
                        'filled': float(order.get('filled', 0)),
                        'remaining': float(order.get('remaining', 0)),
                        'status': order.get('status', 'open'),
                        'timestamp': order.get('timestamp'),
                        'datetime': order.get('datetime')
                    })
                
                return normalized_orders
            else:
                if hasattr(self.exchange, 'fetch_orders'):
                    all_orders = self.exchange.fetch_orders(symbol)
                    open_orders = [o for o in all_orders if o.get('status') == 'open']
                    return open_orders
                else:
                    return []
        except Exception as e:
            print(f"Error fetching open orders: {str(e)}")
            return []
    
    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:

        try:
            if hasattr(self.exchange, 'cancel_order'):
                result = self.exchange.cancel_order(order_id, symbol)
                return True
            return False
        except Exception as e:
            print(f"Error cancelling order {order_id}: {str(e)}")
            return False
    
    def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict:

        result = {
            'total': 0,
            'cancelled': 0,
            'failed': 0,
            'details': []
        }
        
        try:
            orders = self.get_open_orders(symbol)
            result['total'] = len(orders)
            
            for order in orders:
                try:
                    order_symbol = order.get('symbol')
                    order_id = order.get('id')
                    
                    if self.cancel_order(order_id, order_symbol):
                        result['cancelled'] += 1
                        result['details'].append({
                            'id': order_id,
                            'symbol': order_symbol,
                            'status': 'cancelled'
                        })
                    else:
                        result['failed'] += 1
                        result['details'].append({
                            'id': order_id,
                            'symbol': order_symbol,
                            'status': 'failed'
                        })
                    
                    time.sleep(0.2)
                    
                except Exception as e:
                    result['failed'] += 1
                    result['details'].append({
                        'id': order.get('id'),
                        'symbol': order.get('symbol'),
                        'status': 'error',
                        'error': str(e)
                    })
            
            return result
            
        except Exception as e:
            print(f"Error in cancel_all_orders: {str(e)}")
            result['error'] = str(e)
            return result
    
    def create_market_sell_order(self, symbol: str, amount: float) -> Optional[Dict]:

        try:
            exchange_id = self.exchange.id
            
            if exchange_id == 'kucoin':
                market = self.exchange.market(symbol)
                
                amount_precision = market.get('precision', {}).get('amount')
                
                if amount_precision is None:
                    amount_precision = 8
                
                if isinstance(amount_precision, float):
                    precision_str = f"{amount_precision:.10f}".rstrip('0')
                    if '.' in precision_str:
                        amount_precision = len(precision_str.split('.')[1])
                    else:
                        amount_precision = 8
                elif isinstance(amount_precision, int):
                    pass
                else:
                    amount_precision = 8
                
                amount_precision = int(amount_precision)
                
                if amount_precision > 8:
                    amount_precision = 8
                if amount_precision < 0:
                    amount_precision = 0
                
                try:
                    amount_str = f"{amount:.{amount_precision}f}"
                    amount_str = amount_str.rstrip('0').rstrip('.')
                    if amount_str == '' or amount_str == '-':
                        amount_str = '0'
                except (ValueError, TypeError) as e:
                    logger.error(f"Помилка форматування amount {amount}: {e}")
                    amount_str = str(amount)
                
                logger.info(f"KuCoin: продаж {symbol}, amount={amount_str}, precision={amount_precision}")
                
                order = self.exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side='sell',
                    amount=amount_str
                )
                
                filled = float(order.get('filled', order.get('amount', amount)))
                price = float(order.get('price', 0))
                if price == 0 and 'fills' in order and order['fills']:
                    total_value = sum(float(fill.get('price', 0)) * float(fill.get('amount', 0)) 
                                    for fill in order['fills'])
                    total_amount = sum(float(fill.get('amount', 0)) for fill in order['fills'])
                    price = total_value / total_amount if total_amount > 0 else 0
                
                return {
                    'id': order.get('id'),
                    'symbol': order.get('symbol'),
                    'type': 'market',
                    'side': 'sell',
                    'amount': filled,
                    'price': price,
                    'average': price,
                    'cost': filled * price,
                    'filled': filled,
                    'status': order.get('status', 'closed'),
                    'timestamp': order.get('timestamp'),
                    'datetime': order.get('datetime'),
                    'raw': order
                }
            
            elif hasattr(self.exchange, 'create_market_sell_order'):
                order = self.exchange.create_market_sell_order(symbol, amount)
                
                return {
                    'id': order.get('id'),
                    'symbol': order.get('symbol'),
                    'type': 'market',
                    'side': 'sell',
                    'amount': float(order.get('amount', amount)),
                    'price': float(order.get('price', 0)),
                    'average': float(order.get('average', 0)),
                    'cost': float(order.get('cost', 0)),
                    'filled': float(order.get('filled', 0)),
                    'status': order.get('status', 'closed'),
                    'timestamp': order.get('timestamp'),
                    'datetime': order.get('datetime'),
                    'raw': order
                }
            return None
        except Exception as e:
            logger.error(f"Error creating market sell order for {symbol}: {e}")
            raise Exception(f"Помилка створення маркет-ордера: {str(e)}")
    
    def create_limit_sell_order(self, symbol: str, amount: float, price: float) -> Optional[Dict]:
        """
        Створити лімітний ордер на продаж
        
        Args:
            symbol: Символ пари
            amount: Кількість для продажу
            price: Ціна лімітного ордера
        """
        try:
            if hasattr(self.exchange, 'create_limit_sell_order'):
                order = self.exchange.create_limit_sell_order(symbol, amount, price)
                
                return {
                    'id': order.get('id'),
                    'symbol': order.get('symbol'),
                    'type': 'limit',
                    'side': 'sell',
                    'amount': float(order.get('amount', amount)),
                    'price': float(order.get('price', price)),
                    'filled': float(order.get('filled', 0)),
                    'remaining': float(order.get('remaining', amount)),
                    'status': order.get('status', 'open'),
                    'timestamp': order.get('timestamp'),
                    'datetime': order.get('datetime'),
                    'raw': order
                }
            return None
        except Exception as e:
            print(f"Error creating limit sell order for {symbol}: {str(e)}")
            raise Exception(f"Помилка створення лімітного ордера: {str(e)}")
    
    def _normalize_order_result(self, order: dict, original_amount: float) -> dict:
        """Нормалізує результат ордера для однакового формату"""
        try:
            filled = float(order.get('filled', order.get('amount', original_amount)))
            
            price = float(order.get('average', order.get('price', 0)))
            if price == 0 and 'fills' in order and order['fills']:
                total_value = sum(float(fill.get('price', 0)) * float(fill.get('amount', 0)) 
                                for fill in order['fills'])
                total_amount = sum(float(fill.get('amount', 0)) for fill in order['fills'])
                price = total_value / total_amount if total_amount > 0 else 0
            
            cost = float(order.get('cost', filled * price))
            
            return {
                'id': order.get('id'),
                'symbol': order.get('symbol'),
                'type': order.get('type', 'market'),
                'side': order.get('side', 'sell'),
                'amount': filled,
                'price': price,
                'cost': cost,
                'filled': filled,
                'status': order.get('status', 'closed'),
                'timestamp': order.get('timestamp'),
                'datetime': order.get('datetime')
            }
        except Exception as e:
            logger.error(f"Помилка нормалізації ордера: {e}")
            return {
                'id': order.get('id'),
                'symbol': order.get('symbol'),
                'type': 'market',
                'side': 'sell',
                'amount': original_amount,
                'price': 0,
                'cost': 0,
                'filled': 0,
                'status': 'unknown'
            }
    
    def get_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Dict]:

        try:
            if hasattr(self.exchange, 'fetch_order'):
                order = self.exchange.fetch_order(order_id, symbol)
                
                return {
                    'id': order.get('id'),
                    'symbol': order.get('symbol'),
                    'type': order.get('type'),
                    'side': order.get('side'),
                    'amount': float(order.get('amount', 0)),
                    'price': float(order.get('price', 0)),
                    'filled': float(order.get('filled', 0)),
                    'remaining': float(order.get('remaining', 0)),
                    'status': order.get('status'),
                    'timestamp': order.get('timestamp'),
                    'datetime': order.get('datetime')
                }
            return None
        except Exception as e:
            print(f"Error fetching order {order_id}: {str(e)}")
            return None
        

    def check_filled_orders(self, since_timestamp: Optional[int] = None) -> List[Dict]:

        try:
            filled_orders = []
            exchange_id = self.exchange.id
            
            now = datetime.now()
            start_of_day = datetime(now.year, now.month, now.day, 0, 0, 0)
            start_of_day_ms = int(start_of_day.timestamp() * 1000)
            
            min_time = max(since_timestamp or 0, start_of_day_ms)
            
            logger.info(f"🔍 {exchange_id}: перевірка ордерів з {datetime.fromtimestamp(min_time/1000)}")
            
            if exchange_id == 'kucoin':
                if hasattr(self.exchange, 'fetch_closed_orders'):
                    orders = self.exchange.fetch_closed_orders()
                    for order in orders:
                        if order.get('timestamp', 0) < min_time:
                            continue
                        if order.get('side') == 'sell' and (order.get('status') == 'closed' or order.get('filled', 0) > 0):
                            filled_orders.append(self._normalize_order(order))
            
            elif exchange_id == 'bingx':
                if hasattr(self.exchange, 'fetch_closed_orders'):
                    try:
                        balance = self.get_balance()
                        for coin in balance['coins'].keys():
                            if coin != 'USDT':
                                try:
                                    symbol = f"{coin}/USDT"
                                    orders = self.exchange.fetch_closed_orders(symbol)
                                    for order in orders:
                                        if order.get('timestamp', 0) < min_time:
                                            continue
                                        if order.get('side') == 'sell' and (order.get('status') == 'closed' or order.get('filled', 0) > 0):
                                            filled_orders.append(self._normalize_order(order))
                                except Exception as e:
                                    logger.debug(f"BingX: помилка для {symbol}: {e}")
                                    continue
                    except Exception as e:
                        logger.error(f"BingX: помилка отримання балансу: {e}")
            
            
            elif exchange_id == 'gateio':
                if hasattr(self.exchange, 'fetch_closed_orders'):
                    orders = self.exchange.fetch_closed_orders()
                    for order in orders:
                        if order.get('timestamp', 0) < min_time:
                            continue
                        if order.get('side') == 'sell' and (order.get('status') == 'closed' or order.get('filled', 0) > 0):
                            filled_orders.append(self._normalize_order(order))
            
            elif exchange_id == 'mexc':
                try:
                    balance = self.get_balance()
                    for coin in balance['coins'].keys():
                        if coin != 'USDT':
                            try:
                                symbol = f"{coin}/USDT"
                                orders = self.exchange.fetch_closed_orders(symbol)
                                for order in orders:
                                    if order.get('timestamp', 0) < min_time:
                                        continue
                                    if order.get('side') == 'sell' and (order.get('status') == 'closed' or order.get('filled', 0) > 0):
                                        filled_orders.append(self._normalize_order(order))
                            except Exception as e:
                                logger.debug(f"MEXC: помилка для {symbol}: {e}")
                                continue
                except Exception as e:
                    logger.error(f"MEXC: помилка отримання балансу: {e}")
            
            
            significant_orders = [o for o in filled_orders if o.get('cost', 0) > 1]
            
            if filled_orders:
                logger.info(f" {exchange_id}: знайдено {len(filled_orders)} виконаних SELL ордерів за сьогодні")
                if len(filled_orders) != len(significant_orders):
                    logger.info(f"   (відфільтровано {len(filled_orders) - len(significant_orders)} дрібних)")
            
            return significant_orders
            
        except Exception as e:
            logger.error(f"Помилка перевірки виконаних ордерів для {self.exchange.id}: {e}")
            return []

    def _format_decimal(self, value: float, precision: int = 8) -> str:
        if value is None:
            return "0"
        try:
            formatted = f"{value:.{precision}f}"
            formatted = formatted.rstrip('0').rstrip('.')
            return formatted if formatted else "0"
        except:
            return str(value)

    def _normalize_order(self, order: dict) -> dict:
        try:
            filled = float(order.get('filled', order.get('amount', 0)))
            
            price = float(order.get('average', order.get('price', 0)))
            
            cost = float(order.get('cost', filled * price))
            
            return {
                'id': order.get('id'),
                'symbol': order.get('symbol'),
                'side': order.get('side'),
                'amount': filled,
                'price': price,
                'cost': cost,
                'timestamp': order.get('timestamp'),
                'datetime': order.get('datetime')
            }
        except Exception as e:
            logger.error(f"Помилка нормалізації ордера: {e}")
            return {}
