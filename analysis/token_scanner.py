import asyncio
from typing import List, Dict, Optional
import ccxt
from .candlestick_analyzer import CandlestickAnalyzer
from config import MAX_VOLUME_USDT, MIN_AMPLITUDE_PERCENT, MIN_CANDLES_COUNT
import time
import pandas as pd

class TokenScanner:
    def __init__(self, exchange):
        self.exchange = exchange
        self.analyzer = CandlestickAnalyzer()
    
    async def scan_all_low_turnover_tokens(self) -> List[Dict]:
        """
        Сканування токенів на біржі з використанням ТОЇ Ж логіки, що й в /debug
        ТЕСТОВИЙ РЕЖИМ: обмежено до перших 200 монет
        """
        print(f"\n Початок тестового сканування токенів на {self.exchange.exchange.id}...")
        print(f" Критерії: Амплітуда >{MIN_AMPLITUDE_PERCENT}%, Оборот ≤${MAX_VOLUME_USDT:,}/24h")
        print(f" Період: останні 30 днів (денні свічки)")
        print(f" Використовується: середній щоденний оборот за 30 днів")
        print(f" ТЕСТОВИЙ РЕЖИМ: перевірка перших 200 монет")
        print(f" Це може зайняти 2-3 хвилини...")
        
        start_time = time.time()
        
        try:
            markets = self.exchange.exchange.load_markets()
            usdt_pairs = [symbol for symbol in markets.keys() if symbol.endswith('/USDT')]
            
            print(f" Знайдено {len(usdt_pairs)} USDT пар на біржі")
            
            if not usdt_pairs:
                return []
            
           
            print(f" Буде проаналізовано перших {len(usdt_pairs)} монет для тесту")
            
            filtered_tokens = []
            
            for i, symbol in enumerate(usdt_pairs, 1):
                try:
                    if i % 10 == 0:
                        elapsed = time.time() - start_time
                        tokens_per_sec = i / elapsed if elapsed > 0 else 0
                        print(f"    Аналізовано {i}/{len(usdt_pairs)} токенів ({elapsed:.0f}с, {tokens_per_sec:.1f} ток/с)")
                        print(f"    Знайдено {len(filtered_tokens)} підходящих токенів")
                    
                    try:
                        ohlcv_data = self.exchange.get_ohlcv(symbol, '1d', 35)
                    except Exception as e:
                        continue
                    
                    if not ohlcv_data or len(ohlcv_data) < 30:
                        continue
                    
                    df = pd.DataFrame(ohlcv_data)
                    
                    if len(df) < 30:
                        continue
                    
                    df = df.tail(30).reset_index(drop=True)
                    
                    high_amplitude_days = 0
                    total_turnover = 0
                    recent_high_days = []
                    amplitudes = []
                    
                    for idx in range(len(df)):
                        row = df.iloc[idx]
                        
                        open_price = float(row['open'])
                        high = float(row['high'])
                        low = float(row['low'])
                        volume_tokens = float(row['volume'])
                        close = float(row.get('close', open_price))
                        
                        if open_price <= 0:
                            continue
                        
                        amplitude = ((high - low) / open_price) * 100
                        amplitudes.append(amplitude)
                        
                        avg_price = (high + low) / 2
                        daily_turnover = volume_tokens * avg_price
                        total_turnover += daily_turnover
                        
                        if amplitude >= MIN_AMPLITUDE_PERCENT:
                            high_amplitude_days += 1
                            
                            try:
                                timestamp = int(row['timestamp'])
                                date = pd.Timestamp(timestamp, unit='ms').strftime('%Y-%m-%d')
                                body_change = ((close - open_price) / open_price) * 100
                                
                                recent_high_days.append({
                                    'date': date,
                                    'amplitude': round(amplitude, 1),
                                    'body_change': round(body_change, 1),
                                    'turnover_usdt': round(daily_turnover, 0)
                                })
                            except:
                                pass
                    
                    if not amplitudes:
                        continue
                    
                    avg_daily_turnover = total_turnover / len(df)
                    
                    if (high_amplitude_days >= MIN_CANDLES_COUNT and 
                        avg_daily_turnover <= MAX_VOLUME_USDT):
                        
                        current_price = float(df.iloc[-1]['close'])
                        
                        month_start_price = float(df.iloc[0]['open'])
                        if month_start_price > 0:
                            price_change = ((current_price - month_start_price) / month_start_price) * 100
                        else:
                            price_change = 0
                        
                        try:
                            last_day = df.iloc[-1]
                            today_volume_tokens = float(last_day['volume'])
                            today_high = float(last_day['high'])
                            today_low = float(last_day['low'])
                            today_avg_price = (today_high + today_low) / 2
                            today_volume_usdt = today_volume_tokens * today_avg_price
                        except:
                            today_volume_usdt = None
                        
                        avg_amplitude = sum(amplitudes) / len(amplitudes)
                        max_amplitude = max(amplitudes)
                        
                        turnover_24h = avg_daily_turnover 
                        try:
                            ticker = self.exchange.get_ticker(symbol)
                            if ticker and 'turnover_24h' in ticker:
                                turnover_24h = ticker['turnover_24h']
                        except:
                            pass
                        
                        token_info = {
                            'symbol': symbol,
                            'current_price': current_price,
                            'month_price_change': round(price_change, 2),
                            'turnover_24h': round(turnover_24h, 2),
                            'avg_daily_turnover': round(avg_daily_turnover, 2),
                            'today_volume_usdt': round(today_volume_usdt, 2) if today_volume_usdt else None,
                            'high_amplitude_candles_count': high_amplitude_days,
                            'max_amplitude': round(max_amplitude, 1),
                            'avg_amplitude': round(avg_amplitude, 1),
                            'recent_high_amplitude_days': recent_high_days[-5:],  
                            'total_turnover_30d': round(total_turnover, 2),
                            'test_mode': True  
                        }
                        
                        filtered_tokens.append(token_info)
                        print(f"    Знайдено: {symbol} ({high_amplitude_days} днів, "
                              f"середній оборот ${avg_daily_turnover:,.0f}/день, "
                              f"24h оборот ${turnover_24h:,.0f})")
                    
                except Exception as e:
                    continue
                
                await asyncio.sleep(0.2)
            
            filtered_tokens.sort(key=lambda x: x['high_amplitude_candles_count'], reverse=True)
            
            elapsed_time = time.time() - start_time
            print(f"\n Тестове сканування завершено за {elapsed_time:.0f} секунд.")
            print(f" Проаналізовано токенів: {len(usdt_pairs)}")
            print(f" Знайдено підходящих: {len(filtered_tokens)} токенів")
            
            if filtered_tokens:
                print("\n Топ знахідок:")
                for i, token in enumerate(filtered_tokens[:10], 1):
                    today_vol = f", сьогодні ${token['today_volume_usdt']:,.0f}" if token.get('today_volume_usdt') else ""
                    print(f"   {i}. {token['symbol']}: {token['high_amplitude_candles_count']} днів, "
                          f"середній оборот ${token['avg_daily_turnover']:,.0f}/день{today_vol}")
            
            if filtered_tokens:
                for token in filtered_tokens:
                    token['note'] = f"Тестовий режим (перші 200 монет)"
            
            return filtered_tokens
            
        except Exception as e:
            print(f" Помилка сканування: {e}")
            import traceback
            traceback.print_exc()
            return []