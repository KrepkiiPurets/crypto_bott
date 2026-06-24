import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
from config import MIN_AMPLITUDE_PERCENT, MIN_CANDLES_COUNT, MAX_VOLUME_USDT

class CandlestickAnalyzer:
    
    @staticmethod
    def calculate_candle_amplitude(open_price: float, high: float, low: float) -> float:
        """
        Розрахувати амплітуду свічки у відсотках.
        Амплітуда = (high - low) / open * 100
        """
        if open_price == 0:
            return 0
        
        return ((high - low) / open_price) * 100
    
    @staticmethod
    def calculate_turnover(volume_tokens: float, avg_price: float) -> float:
        """
        Розрахувати оборот (turnover) в USDT
        Turnover = Volume (in tokens) * Average Price
        """
        return volume_tokens * avg_price
    
    @staticmethod
    def filter_tokens_by_criteria(ohlcv_data: List[Dict], symbol: str, 
                                  exchange_instance,
                                  min_amplitude: float = MIN_AMPLITUDE_PERCENT, 
                                  max_turnover_usdt: float = MAX_VOLUME_USDT,
                                  min_candles: int = MIN_CANDLES_COUNT) -> Optional[Dict]:
        """
        Фільтрація токенів за критеріями:
        - Мінімум min_candles свічок з амплітудою > min_amplitude%
        - Оборот (turnover) торгів ≤ max_turnover_usdt/24h
        - Аналіз за останні 30 днів
        """
        
        if not ohlcv_data or len(ohlcv_data) < 30:
            print(f"Для {symbol}: недостатньо даних ({len(ohlcv_data) if ohlcv_data else 0})")
            return None
        
        try:
            df = pd.DataFrame(ohlcv_data)
            
            required_columns = ['open', 'high', 'low', 'volume', 'close', 'timestamp']
            if not all(col in df.columns for col in required_columns):
                print(f"Для {symbol}: відсутні необхідні колонки")
                return None
            
            df_last_month = df.tail(30).copy()
            
            if len(df_last_month) < 30:
                print(f"Для {symbol}: недостатньо даних за останній місяць ({len(df_last_month)})")
                return None
            
            df_last_month['avg_price'] = (df_last_month['high'] + df_last_month['low']) / 2
            df_last_month['turnover_usdt'] = df_last_month['volume'] * df_last_month['avg_price']
            
            avg_daily_turnover = df_last_month['turnover_usdt'].mean()
            
            if avg_daily_turnover > max_turnover_usdt:
                print(f"Для {symbol}: оборот ${avg_daily_turnover:,.0f} > ${max_turnover_usdt:,.0f}")
                return None
            
            min_acceptable_turnover = 100  
            if avg_daily_turnover < min_acceptable_turnover:
                print(f"Для {symbol}: занадто низький оборот ${avg_daily_turnover:,.0f}")
                return None
            
            try:
                ticker = exchange_instance.get_ticker(symbol)
                turnover_24h = ticker['turnover_24h']
                current_price = ticker['last']
                
                print(f"📊 {symbol}: 24h оборот = ${turnover_24h:,.0f}, поточна ціна = ${current_price:.6f}")
                
                if turnover_24h > max_turnover_usdt:
                    print(f"Для {symbol}: 24h оборот ${turnover_24h:,.0f} > ${max_turnover_usdt:,.0f}")
                    return None
                    
            except Exception as e:
                print(f"Не вдалося отримати тікер для {symbol}: {e}")
                turnover_24h = avg_daily_turnover
                current_price = df_last_month.iloc[-1]['close']
            
            df_last_month['amplitude'] = df_last_month.apply(
                lambda row: CandlestickAnalyzer.calculate_candle_amplitude(
                    row['open'], row['high'], row['low']
                ), axis=1
            )
            
            high_amplitude_candles = df_last_month[df_last_month['amplitude'] >= min_amplitude]
            
            print(f"{symbol}: {len(high_amplitude_candles)} днів з амплітудою >{min_amplitude}%, "
                  f"середній оборот ${avg_daily_turnover:,.0f}/день, "
                  f"24h оборот ${turnover_24h:,.0f}")
            
            if len(high_amplitude_candles) < min_candles:
                print(f"Для {symbol}: лише {len(high_amplitude_candles)} днів з амплітудою >{min_amplitude}% "
                      f"(потрібно {min_candles})")
                return None
            
            today_volume_usdt = None
            try:
                today_volume_usdt = exchange_instance.get_today_volume_usdt(symbol)
                if today_volume_usdt:
                    print(f"{symbol}: об'єм сьогодні = ${today_volume_usdt:,.0f}")
            except Exception as e:
                print(f"Не вдалося отримати об'єм за сьогодні для {symbol}: {e}")
            
            month_start_price = df_last_month.iloc[0]['open']
            
            if month_start_price == 0:
                return None
            
            price_change = ((current_price - month_start_price) / month_start_price) * 100
            
            if len(high_amplitude_candles) > 0:
                top_amplitude_days = high_amplitude_candles.nlargest(5, 'amplitude')
                recent_days = []
                
                for _, day in top_amplitude_days.iterrows():
                    try:
                        body_change = ((day['close'] - day['open']) / day['open']) * 100
                        day_turnover = day['turnover_usdt']
                        recent_days.append({
                            'date': datetime.fromtimestamp(day['timestamp']/1000).strftime('%d.%m'),
                            'amplitude': round(day['amplitude'], 1),
                            'body_change': round(body_change, 1),
                            'turnover': round(day_turnover, 0),
                            'volume_tokens': round(day['volume'], 0)
                        })
                    except Exception:
                        continue
            else:
                recent_days = []
            
            stats = {
                'total_days_analyzed': len(df_last_month),
                'high_amplitude_days': len(high_amplitude_candles),
                'avg_amplitude': float(df_last_month['amplitude'].mean()),
                'max_amplitude': float(high_amplitude_candles['amplitude'].max()) if len(high_amplitude_candles) > 0 else 0,
                'avg_daily_turnover': float(avg_daily_turnover),
                'turnover_24h': float(turnover_24h),
                'today_volume_usdt': float(today_volume_usdt) if today_volume_usdt else None
            }
            
            return {
                'symbol': symbol,
                'current_price': float(current_price),
                'month_price_change': round(float(price_change), 2),
                'avg_daily_turnover': round(float(avg_daily_turnover), 2),
                'turnover_24h': round(float(turnover_24h), 2),
                'today_volume_usdt': round(float(today_volume_usdt), 2) if today_volume_usdt else None,
                'high_amplitude_candles_count': int(len(high_amplitude_candles)),
                'max_amplitude': round(float(high_amplitude_candles['amplitude'].max()), 1) if len(high_amplitude_candles) > 0 else 0,
                'avg_amplitude': round(float(df_last_month['amplitude'].mean()), 1),
                'recent_high_amplitude_days': recent_days,
                'stats': stats,
                'min_amplitude_used': min_amplitude,
                'min_candles_used': min_candles
            }
            
        except Exception as e:
            print(f"Помилка аналізу {symbol}: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    def analyze_token_detailed(ohlcv_data: List[Dict], symbol: str) -> Dict:
        """
        Детальний аналіз токена для дебагу
        """
        if not ohlcv_data or len(ohlcv_data) < 30:
            return {'error': 'Недостатньо даних'}
        
        try:
            df = pd.DataFrame(ohlcv_data).tail(30)
            
            results = []
            total_turnover = 0
            
            for idx, row in df.iterrows():
                amplitude = CandlestickAnalyzer.calculate_candle_amplitude(
                    row['open'], row['high'], row['low']
                )
                avg_price = (row['high'] + row['low']) / 2
                turnover = row['volume'] * avg_price
                body_change = ((row['close'] - row['open']) / row['open']) * 100
                
                total_turnover += turnover
                
                date = datetime.fromtimestamp(row['timestamp']/1000).strftime('%Y-%m-%d')
                
                results.append({
                    'date': date,
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume_tokens': row['volume'],
                    'turnover_usdt': turnover,
                    'amplitude': round(amplitude, 2),
                    'body_change': round(body_change, 2),
                    'is_high_amplitude': amplitude >= MIN_AMPLITUDE_PERCENT
                })
            
            avg_daily_turnover = total_turnover / len(results)
            high_amplitude_days = sum(1 for r in results if r['is_high_amplitude'])
            
            return {
                'symbol': symbol,
                'analysis': results,
                'summary': {
                    'total_days': len(results),
                    'high_amplitude_days': high_amplitude_days,
                    'avg_amplitude': sum(r['amplitude'] for r in results) / len(results),
                    'avg_daily_turnover': avg_daily_turnover,
                    'total_turnover': total_turnover
                }
            }
            
        except Exception as e:
            return {'error': str(e)}
