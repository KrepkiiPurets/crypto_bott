import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import re
from typing import Dict, Set, Optional, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class DelistingChecker:

    def __init__(self):
        self.cached_results = {}
        self.last_check_time = {}
        self.playwright = None
        self.browser = None
        self._lock = asyncio.Lock()

        self.EXCHANGE_CONFIG = {
            'gate': {
                'name': 'Gate.io',
                'url': 'https://www.gate.com/uk/announcements/delisted',
                'article_url_pattern': '/uk/announcements/article/',
                'timeout': 60000,
            },
            'mexc': {
                'name': 'MEXC',
                'url': 'https://www.mexc.com/uk-UA/announcements/delistings',
                'article_url_pattern': '/announcements/article/',
                'timeout': 60000,
            },
            'kucoin': {
                'name': 'KuCoin',
                'url': 'https://www.kucoin.com/announcement',
                'article_url_pattern': '/announcement/',
                'timeout': 50000,
            },
            'bingx': {
                'name': 'BingX',
                'url': 'https://bingx.com/ru-ru/support/notice-center/4515307429273',
                'article_url_pattern': '/support/articles/',
                'timeout': 60000,
            }
        }

    async def _ensure_browser(self):
        async with self._lock:
            if not self.playwright:
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage', '--no-sandbox']
                )
        return self.browser

    async def close(self):
        async with self._lock:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None

    async def fetch_page(self, url: str, exchange: str = None) -> Optional[str]:
        config = self.EXCHANGE_CONFIG.get(exchange, {})
        timeout = config.get('timeout', 30000)
        
        for attempt in range(2):
            try:
                browser = await self._ensure_browser()
                context = await browser.new_context()
                page = await context.new_page()
                page.set_default_timeout(timeout)
                
                await page.goto(url, wait_until='domcontentloaded', timeout=timeout)
                await page.wait_for_timeout(2000)
                
                html = await page.content()
                await page.close()
                await context.close()
                return html
                
            except Exception:
                if attempt == 1:
                    return None
                await asyncio.sleep(2)
        return None

    def _make_absolute_url(self, href: str, base_url: str) -> str:
        if href.startswith('http'):
            return href
        elif href.startswith('/'):
            parts = base_url.split('/')
            base = f"{parts[0]}//{parts[2]}"
            return base + href
        else:
            base = base_url.rstrip('/')
            return base + ('/' + href if not href.startswith('/') else href)

    def extract_tokens_from_text(self, text: str) -> Set[str]:
        tickers = re.findall(r'\b([A-Z0-9]{2,10})\b', text.upper())
        exclude_words = {'USDT', 'BTC', 'ETH', 'USD', 'EUR', 'BINGX', 'MEXC', 'KUCOIN', 'GATE', 
                        'SPOT', 'FUTURES', 'DELIST', 'DELISTING', 'HTTP', 'HTTPS', 'API'}
        
        valid = set()
        for t in tickers:
            if t not in exclude_words and len(t) >= 2 and re.search(r'[A-Z]', t):
                valid.add(t)
            if t.endswith('USDT') and len(t) > 4:
                base = t[:-4]
                if base not in exclude_words and len(base) >= 2:
                    valid.add(base)
        
        for match in re.findall(r'\b([A-Z0-9]{2,10})/USDT\b', text.upper()):
            if match not in exclude_words and len(match) >= 2:
                valid.add(match)
        
        return valid

    async def check_exchange_delistings(self, exchange: str, user_coins: Set[str]) -> Dict[str, Set[str]]:
        config = self.EXCHANGE_CONFIG.get(exchange)
        if not config:
            return {exchange: set()}

        cache_key = f"{exchange}_latest"
        if cache_key in self.cached_results:
            cache_time = self.last_check_time.get(cache_key, datetime.min)
            if (datetime.now() - cache_time).seconds < 3600:
                return self.cached_results[cache_key]

        logger.info(f"🔍 {config['name']}...")
        
        try:
           
            if exchange == 'kucoin':
                logger.info(f" Перевірка KuCoin...")
                
                browser = await self._ensure_browser()
                context = None
                page = None
                
                try:
                    context = await browser.new_context(
                        viewport={'width': 1920, 'height': 1080},
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        locale='uk-UA',
                        timezone_id='Europe/Kiev'
                    )
                    
                    page = await context.new_page()
                    page.set_default_timeout(60000)
                    
                    logger.info(f"    Завантажую сторінку оголошень...")
                    await page.goto(config['url'], wait_until='networkidle', timeout=60000)
                    await page.wait_for_timeout(5000)  
                    
                    html = await page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    article_links = soup.select('a.styles_wrapper__C3lA6')
                    
                    if not article_links:
                        logger.warning(f"    Не знайдено посилань на статті")
                        return {exchange: set()}
                    
                    logger.info(f"    Знайдено {len(article_links)} статей")
                    
                    keywords = ['DELIST', 'DELISTING', 'DELISTED', 'ST', 'ST-TOKEN']
                    
                    max_check = min(7, len(article_links))
                    article_url = None
                    
                    for i in range(max_check):
                        link = article_links[i]
                        href = link.get('href', '')
                        title_elem = link.select_one('h3')
                        
                        if title_elem:
                            title = title_elem.get_text().upper().strip()
                            logger.info(f"    Стаття {i+1}: '{title[:80]}...'")
                            words = title.split()
                            
                            found_keyword = None
                            for keyword in keywords:
                                if keyword.upper() in words:
                                    found_keyword = keyword
                                    break
                            
                            if found_keyword:
                                logger.info(f"    Знайдено ключове слово '{found_keyword}' в статті {i+1}")
                                article_url = self._make_absolute_url(href, config['url'])
                                break
                        else:
                            link_text = link.get_text().upper().strip()
                            if link_text:
                                logger.info(f"    Стаття {i+1} (без h3): '{link_text[:80]}...'")
                                words = link_text.split()
                                for keyword in keywords:
                                    if keyword.upper() in words:
                                        logger.info(f"    Знайдено ключове слово '{keyword}' в статті {i+1}")
                                        article_url = self._make_absolute_url(href, config['url'])
                                        break
                            
                            if article_url:
                                break
                    
                    if not article_url:
                        logger.info(f"    Статей з делістингом не знайдено серед перших {max_check}")
                        logger.info(f"    Перевірені заголовки:")
                        for i in range(min(5, len(article_links))):
                            link = article_links[i]
                            title_elem = link.select_one('h3')
                            if title_elem:
                                logger.info(f"      {i+1}. {title_elem.get_text().strip()[:70]}...")
                        return {exchange: set()}
                    
                    logger.info(f"    Знайдено статтю: {article_url}")
                    
                    await page.goto(article_url, wait_until='domcontentloaded', timeout=45000)
                    await page.wait_for_timeout(3000)  
                    
                    article_html = await page.content()
                    soup = BeautifulSoup(article_html, 'html.parser')
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    
                    article_text = soup.get_text(separator=' ', strip=True)
                    
                    delisted = self.extract_tokens_from_text(article_text)
                    user_upper = {c.upper() for c in user_coins}
                    
                    logger.info(f"   💰 Монети користувача ({len(user_upper)}): {sorted(user_upper)}")
                    if delisted:
                        logger.info(f"    Тікери зі статті (перші 30): {sorted(delisted)[:30]}")
                    else:
                        logger.info(f"    Тікерів зі статті не знайдено")
                    
                    found = delisted.intersection(user_upper)
                    
                    if found:
                        logger.info(f"    {config['name']}: ЗНАЙДЕНО {len(found)} монет: {found}")
                    else:
                        logger.info(f"    {config['name']}: співпадінь не знайдено")
                    
                    result = {exchange: found}
                    self.cached_results[cache_key] = result
                    self.last_check_time[cache_key] = datetime.now()
                    
                    await page.close()
                    await context.close()
                    return result
                    
                except Exception as e:
                    logger.error(f" Помилка KuCoin: {e}", exc_info=True)
                    return {exchange: set()}
                finally:
                    if page:
                        await page.close()
                    if context:
                        await context.close()

            elif exchange == 'gate':
                html = await self.fetch_page(config['url'], exchange)
                if not html:
                    return {exchange: set()}
                
                soup = BeautifulSoup(html, 'lxml')
                article_url = None
                for link in soup.find_all('a', href=True):
                    href = link.get('href', '')
                    if '/uk/announcements/article/' in href:
                        article_url = self._make_absolute_url(href, config['url'])
                        break
                
                if not article_url:
                    return {exchange: set()}
                
                logger.info(f"    Стаття: {article_url}")
                
                article_html = await self.fetch_page(article_url, exchange)
                if not article_html:
                    return {exchange: set()}
                
                soup = BeautifulSoup(article_html, 'lxml')
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                
                article_text = soup.get_text(separator=' ', strip=True)
                delisted = self.extract_tokens_from_text(article_text)
                user_upper = {c.upper() for c in user_coins}
                found = delisted.intersection(user_upper)
                
                logger.info(f"    Монети користувача ({len(user_upper)}): {sorted(user_upper)}")
                if delisted:
                    logger.info(f"    Тікери зі статті (перші 30): {sorted(delisted)[:30]}")
                
                if found:
                    logger.info(f"    {config['name']}: ЗНАЙДЕНО {len(found)} монет: {found}")
                else:
                    logger.info(f"    {config['name']}: співпадінь не знайдено")
                
                result = {exchange: found}
                self.cached_results[cache_key] = result
                self.last_check_time[cache_key] = datetime.now()
                return result

            elif exchange == 'mexc':
                browser = await self._ensure_browser()
                context = await browser.new_context()
                page = await context.new_page()
                
                try:
                    await page.goto(config['url'], wait_until='domcontentloaded', timeout=60000)
                    await page.wait_for_timeout(5000)
                    
                    html = await page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    article_url = None
                    for link in soup.select('.SearchResultItem_searchResultItem__wvVon a'):
                        href = link.get('href', '')
                        if '/announcements/article/' in href or '/uk-UA/announcements/article/' in href:
                            article_url = self._make_absolute_url(href, config['url'])
                            break
                    
                    if not article_url:
                        return {exchange: set()}
                    
                    logger.info(f"    Стаття: {article_url}")
                    
                    await page.goto(article_url, wait_until='domcontentloaded')
                    
                    for _ in range(20):
                        try:
                            await page.keyboard.press('Escape')
                        except:
                            pass
                        await asyncio.sleep(0.5)
                    
                    article_html = await page.content()
                    soup = BeautifulSoup(article_html, 'html.parser')
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    
                    article_text = soup.get_text(separator=' ', strip=True)
                    delisted = self.extract_tokens_from_text(article_text)
                    user_upper = {c.upper() for c in user_coins}
                    found = delisted.intersection(user_upper)
                    
                    logger.info(f"    Монети користувача ({len(user_upper)}): {sorted(user_upper)}")
                    if delisted:
                        logger.info(f"    Тікери зі статті (перші 30): {sorted(delisted)[:30]}")
                    
                    if found:
                        logger.info(f"    {config['name']}: ЗНАЙДЕНО {len(found)} монет: {found}")
                    else:
                        logger.info(f"    {config['name']}: співпадінь не знайдено")
                    
                    result = {exchange: found}
                    self.cached_results[cache_key] = result
                    self.last_check_time[cache_key] = datetime.now()
                    
                    await page.close()
                    await context.close()
                    return result
                    
                finally:
                    await page.close()
                    await context.close()

            elif exchange == 'bingx':
                browser = await self._ensure_browser()
                context = await browser.new_context()
                page = await context.new_page()
                
                try:
                    await page.goto(config['url'], wait_until='networkidle', timeout=60000)
                    
                    await page.wait_for_timeout(5000)
                    
                    try:
                        await page.wait_for_selector('.article-list', timeout=15000)
                        logger.info(f"    Знайдено список статей")
                    except:
                        logger.info(f"    Список статей не знайдено, пробую альтернативний пошук")
                    
                    html = await page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    article_url = None
                    
                    article_list = soup.find('ul', class_='article-list')
                    if article_list:
                        items = article_list.find_all('li', class_='article-item')
                        if items:
                            first_item = items[0]
                            link = first_item.find('a', href=True)
                            if link:
                                href = link.get('href')
                                if href:
                                    article_url = self._make_absolute_url(href, config['url'])
                                    logger.info(f"    Знайдено через article-list")
                    
                    if not article_url:
                        for link in soup.find_all('a', href=True):
                            href = link.get('href', '')
                            if '/support/articles/' in href and 'notice-center' not in href:
                                article_url = self._make_absolute_url(href, config['url'])
                                logger.info(f"    Знайдено через загальний пошук")
                                break
                    
                    if not article_url:
                        logger.error(f"    Не знайдено URL статті для BingX")
                        return {exchange: set()}
                    
                    logger.info(f"    Стаття: {article_url}")
                    
                    await page.goto(article_url, wait_until='domcontentloaded', timeout=30000)
                    await page.wait_for_timeout(3000)
                    
                    article_html = await page.content()
                    soup = BeautifulSoup(article_html, 'html.parser')
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    
                    article_text = soup.get_text(separator=' ', strip=True)
                    delisted = self.extract_tokens_from_text(article_text)
                    user_upper = {c.upper() for c in user_coins}
                    found = delisted.intersection(user_upper)
                    
                    logger.info(f"    Монети користувача ({len(user_upper)}): {sorted(user_upper)}")
                    if delisted:
                        logger.info(f"    Тікери зі статті (перші 30): {sorted(delisted)[:30]}")
                    
                    if found:
                        logger.info(f"    {config['name']}: ЗНАЙДЕНО {len(found)} монет: {found}")
                    else:
                        logger.info(f"    {config['name']}: співпадінь не знайдено")
                    
                    result = {exchange: found}
                    self.cached_results[cache_key] = result
                    self.last_check_time[cache_key] = datetime.now()
                    
                    await page.close()
                    await context.close()
                    return result
                    
                finally:
                    await page.close()
                    await context.close()

            else:
                return {exchange: set()}

        except Exception as e:
            logger.error(f" {config.get('name', exchange)}: {e}")
            return {exchange: set()}

    async def check_all_exchanges(self, user_coins_by_exchange: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
        tasks = []
        exchanges = []
        
        for exchange, coins in user_coins_by_exchange.items():
            if exchange in self.EXCHANGE_CONFIG and coins:
                tasks.append(self.check_exchange_delistings(exchange, coins))
                exchanges.append(exchange)
        
        if not tasks:
            return {}
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        combined = {}
        for i, result in enumerate(results):
            if i < len(exchanges) and isinstance(result, dict):
                combined.update(result)
        
        total = sum(len(f) for f in combined.values())
        if total:
            logger.info(f" Знайдено {total} монет у списках делістингу")
        
        return combined