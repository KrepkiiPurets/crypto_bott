# discord_bot.py

import asyncio
import logging
from datetime import datetime
from discord.ext import tasks

import discord
from discord.ext import commands
from discord import SelectOption, ButtonStyle, Interaction

from config import DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID
from core.shared_data import SharedData
from core.delisting_service import DelistingService
from exchanges import get_exchange_instance
from config import get_exchange_keys, get_all_configured_exchanges


async def run_sync(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents)


shared = SharedData()
delisting_service = DelistingService(shared)

scan_results = {}


async def send_notification_to_discord(message: str, user_id: int = None):
    if DISCORD_CHANNEL_ID:
        channel = bot.get_channel(int(DISCORD_CHANNEL_ID))
        if channel:
            if len(message) > 2000:
                message = message[:1997] + "..."
            await channel.send(message)
            logger.info(f"📨 Сповіщення відправлено в Discord")
        else:
            logger.warning(f"⚠️ Канал {DISCORD_CHANNEL_ID} не знайдено")
    else:
        logger.warning("⚠️ DISCORD_CHANNEL_ID не встановлено")


shared.register_notification_callback(send_notification_to_discord)


class MainMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
    
    @discord.ui.button(label="📊 Баланс", style=ButtonStyle.primary)
    async def balance_button(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Виберіть біржу:", view=ExchangeSelectView("balance"))
    
    @discord.ui.button(label="⚠️ Делістинг", style=ButtonStyle.danger)
    async def delisting_button(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Виберіть біржу:", view=ExchangeSelectView("delisting"))
    
    @discord.ui.button(label="📋 Ордери", style=ButtonStyle.secondary)
    async def orders_button(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Виберіть біржу:", view=ExchangeSelectView("orders"))
    
    @discord.ui.button(label="🔍 Сканування", style=ButtonStyle.success)
    async def scan_button(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Виберіть біржу:", view=ExchangeSelectView("scan"))
    
    @discord.ui.button(label="📅 Статистика", style=ButtonStyle.primary)
    async def stats_button(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Виберіть біржу:", view=ExchangeSelectView("stats"))
    
    @discord.ui.button(label="💰 Продаж", style=ButtonStyle.danger)
    async def sell_button(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Виберіть біржу:", view=ExchangeSelectView("sell"))
    
    @discord.ui.button(label="🔔 Сповіщення", style=ButtonStyle.secondary)
    async def notifications_button(self, interaction: Interaction, button: discord.ui.Button):
        await self.handle_notifications(interaction)
    
    async def handle_notifications(self, interaction: Interaction):
        from notifications import NotificationManager
        nm = NotificationManager()
        is_enabled = nm.is_enabled(interaction.user.id)
        
        embed = discord.Embed(
            title="🔔 Керування сповіщеннями",
            description=f"**Поточний статус:** {'🟢 Увімкнено' if is_enabled else '🔴 Вимкнено'}\n\n"
                       f"📊 Сповіщення приходять після кожної автоматичної перевірки (кожні 10 хвилин).",
            color=discord.Color.green() if is_enabled else discord.Color.red()
        )
        
        view = NotificationsView(is_enabled)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ExchangeSelectView(discord.ui.View):
    def __init__(self, action: str):
        super().__init__(timeout=60)
        self.action = action
        self.add_item(ExchangeSelect(action))


class ExchangeSelect(discord.ui.Select):
    
    def __init__(self, action: str):
        self.action = action
        
        exchanges = get_all_configured_exchanges()
        options = [
            SelectOption(label=name, value=key, description=f"Вибрати {name}")
            for name, key in exchanges.items()
        ]
        
        super().__init__(placeholder="Оберіть біржу...", options=options, min_values=1, max_values=1)
    
    async def callback(self, interaction: Interaction):
        exchange_key = self.values[0]
        display_name = None
        
        for name, key in get_all_configured_exchanges().items():
            if key == exchange_key:
                display_name = name
                break
        
        if self.action == "balance":
            await self.handle_balance(interaction, exchange_key, display_name)
        elif self.action == "delisting":
            await self.handle_delisting(interaction, exchange_key, display_name)
        elif self.action == "orders":
            await self.handle_orders(interaction, exchange_key, display_name)
        elif self.action == "scan":
            await self.handle_scan(interaction, exchange_key, display_name)
        elif self.action == "stats":
            await self.handle_stats(interaction, exchange_key, display_name)
        elif self.action == "sell":
            await self.handle_sell_selection(interaction, exchange_key, display_name)
    
    async def handle_balance(self, interaction: Interaction, exchange_key: str, display_name: str):
        await interaction.response.send_message(f"🔄 Отримую баланс з {display_name}...")
        
        try:
            keys = get_exchange_keys(exchange_key)
            if not keys:
                await interaction.followup.send(f"❌ API ключі для {display_name} не знайдено")
                return
            
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
            user_id = interaction.user.id
            cached = shared.get_balance_cache(user_id, exchange_key)
            
            if cached:
                user_coins_set, user_coins_details = cached
                logger.info(f"📦 Використовую спільний кеш для {display_name}")
                total = None
                coins = None
            else:
                balance = exchange.get_balance()
                total = balance['total_usdt']
                coins = balance['coins']
                
                user_coins_set = set()
                user_coins_details = {}
                for coin, data in coins.items():
                    if coin != 'USDT' and data['amount'] > 0:
                        user_coins_set.add(coin)
                        user_coins_details[coin] = data
                
                shared.update_balance_cache(user_id, exchange_key, user_coins_set, user_coins_details)
            
            if not coins and total is None:
                balance = exchange.get_balance()
                total = balance['total_usdt']
                coins = balance['coins']
            
            if not coins:
                await interaction.followup.send(f"💰 **Баланс {display_name}:**\n📭 Порожній")
                return
            
            embed = discord.Embed(
                title=f"💰 Баланс {display_name}",
                description=f"📈 **Загальна сума:** ${total:,.2f} USDT",
                color=discord.Color.green()
            )
            
            sorted_coins = list(coins.items())[:15]
            for coin, data in sorted_coins:
                percentage = (data['usdt_value'] / total * 100) if total > 0 else 0
                embed.add_field(
                    name=coin,
                    value=f"{data['amount']:.4f} (${data['usdt_value']:,.2f} | {percentage:.1f}%)",
                    inline=False
                )
            
            if len(coins) > 15:
                embed.set_footer(text=f"📋 ... та ще {len(coins) - 15} монет")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Помилка: {str(e)[:200]}")
    
    async def handle_delisting(self, interaction: Interaction, exchange_key: str, display_name: str):
        await interaction.response.send_message(f"🔍 **Ручна перевірка монет на делістинг ({display_name})...**")
        
        try:
            keys = get_exchange_keys(exchange_key)
            if not keys:
                await interaction.followup.send(f"❌ API ключі для {display_name} не знайдено")
                return
            
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
            user_id = interaction.user.id
            cached = shared.get_balance_cache(user_id, exchange_key)
            
            if cached:
                user_coins_set, user_coins_details = cached
                logger.info(f"📦 Використовую спільний кеш для {display_name}")
                user_coins = user_coins_details
            else:
                balance = exchange.get_balance()
                user_coins = {}
                for coin, data in balance['coins'].items():
                    if coin != 'USDT' and data['amount'] > 0:
                        user_coins[coin] = data
                
                shared.update_balance_cache(user_id, exchange_key, set(user_coins.keys()), user_coins)
            
            if not user_coins:
                await interaction.followup.send(f"📭 У вас немає монет на {display_name}")
                return
            
            await interaction.followup.send(f"💰 Знайдено {len(user_coins)} монет. Перевіряю оголошення...")
            
            from analysis.delisting_checker import DelistingChecker
            checker = DelistingChecker()
            
            try:
                result = await checker.check_exchange_delistings(exchange_key, set(user_coins.keys()))
                found_tokens = result.get(exchange_key, set())
                
                if found_tokens:
                    embed = discord.Embed(
                        title=f"⚠️ УВАГА! Делістинг на {display_name}",
                        description=f"**Знайдені монети ({len(found_tokens)}):**",
                        color=discord.Color.red()
                    )
                    
                    for token in sorted(found_tokens):
                        if token in user_coins:
                            amount = user_coins[token]['amount']
                            value = user_coins[token]['usdt_value']
                            embed.add_field(name=token, value=f"{amount:.4f} (${value:,.2f})", inline=False)
                        else:
                            embed.add_field(name=token, value="Баланс невідомий", inline=False)
                    
                    embed.set_footer(text="💡 Для продажу використайте кнопку нижче")
                    
                    view = SellButtonView(exchange_key, display_name, found_tokens)
                    await interaction.followup.send(embed=embed, view=view)
                else:
                    await interaction.followup.send(f"✅ **Ваші монети на {display_name} в безпеці!**")
                    
            finally:
                await checker.close()
                
        except Exception as e:
            await interaction.followup.send(f"❌ Помилка: {str(e)[:200]}")
    
    async def handle_orders(self, interaction: Interaction, exchange_key: str, display_name: str):
        await interaction.response.send_message(f"📋 **Перевірка ордерів на {display_name}...**")
        
        try:
            keys = get_exchange_keys(exchange_key)
            if not keys:
                await interaction.followup.send(f"❌ API ключі для {display_name} не знайдено")
                return
            
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
            orders = exchange.get_open_orders()
            
            if not orders:
                await interaction.followup.send(f"📭 **На {display_name} немає відкритих лімітних ордерів**")
                return
            
            embed = discord.Embed(
                title=f"📋 Відкриті лімітні ордери на {display_name}",
                description=f"**Всього ордерів:** {len(orders)}",
                color=discord.Color.blue()
            )
            
            total_value = 0
            for i, order in enumerate(orders[:10], 1):
                symbol = order.get('symbol', 'Невідомо')
                side = order.get('side', 'unknown').upper()
                amount = float(order.get('amount', 0))
                price = float(order.get('price', 0))
                value = amount * price
                emoji = "📤" if side == 'SELL' else "📥"
                total_value += value
                
                embed.add_field(
                    name=f"{emoji} {i}. {symbol}",
                    value=f"Тип: {side}\nКількість: {amount:.4f}\nЦіна: ${price:.6f}\nСума: ${value:.2f}",
                    inline=False
                )
            
            if len(orders) > 10:
                embed.set_footer(text=f"📋 ... та ще {len(orders) - 10} ордерів\n💰 Загальна сума: ${total_value:.2f}")
            else:
                embed.set_footer(text=f"💰 Загальна сума: ${total_value:.2f}")
            
            view = CancelOrdersButton(exchange_key, display_name)
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Помилка: {str(e)[:200]}")
    
    async def handle_scan(self, interaction: Interaction, exchange_key: str, display_name: str):
        await interaction.response.send_message(f"🔍 **Сканування токенів на {display_name}...**\n⏳ Це може зайняти 2-3 хвилини.")
        
        try:
            keys = get_exchange_keys(exchange_key)
            if not keys:
                await interaction.edit_original_response(content=f"❌ API ключі для {display_name} не знайдено")
                return
            
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
            
            user_id = interaction.user.id
            cached = shared.get_balance_cache(user_id, exchange_key)
            
            if cached:
                user_coins_set, _ = cached
                user_coins = user_coins_set
            else:
                balance = await asyncio.wait_for(
                    asyncio.to_thread(exchange.get_balance),
                    timeout=45
                )
                user_coins = {coin for coin, data in balance['coins'].items() 
                            if coin != 'USDT' and data['amount'] > 0}
                shared.update_balance_cache(user_id, exchange_key, user_coins, {})
            
            from analysis.token_scanner import TokenScanner
            scanner = TokenScanner(exchange)
            filtered_tokens = await scanner.scan_all_low_turnover_tokens()
            
            for token in filtered_tokens:
                symbol = token['symbol'].replace('/USDT', '')
                token['in_portfolio'] = symbol in user_coins
            
            if not filtered_tokens:
                await interaction.edit_original_response(content=f"❌ Не знайдено токенів, що відповідають критеріям на {display_name}")
                return
            
            scan_results[interaction.user.id] = {
                'tokens': filtered_tokens,
                'exchange': display_name,
                'page': 0,
                'total_pages': (len(filtered_tokens) + 9) // 10
            }
            
            await send_scan_page(interaction, interaction.user.id, 0)
            
        except Exception as e:
            error_msg = str(e)[:200]
            logger.error(f"❌ Помилка сканування {display_name}: {error_msg}")
            try:
                await interaction.edit_original_response(content=f"❌ Помилка сканування: {error_msg}")
            except:
                await interaction.followup.send(f"❌ Помилка сканування: {error_msg}")
    
    async def handle_stats(self, interaction: Interaction, exchange_key: str, display_name: str):
        await interaction.response.send_message(f"📅 Отримую статистику для {display_name}...")
        
        try:
            keys = get_exchange_keys(exchange_key)
            if not keys:
                await interaction.followup.send(f"❌ API ключі для {display_name} не знайдено")
                return
            
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
            current_balance = exchange.get_balance()
            current_total = current_balance['total_usdt']
            
            from database.db_handler import DatabaseHandler
            db = DatabaseHandler()
            
            current_month = datetime.now().strftime('%Y-%m')
            previous_balance = db.get_monthly_balance(interaction.user.id, exchange_key, current_month)
            
            embed = discord.Embed(
                title=f"📅 Статистика {display_name}",
                color=discord.Color.gold()
            )
            embed.add_field(name="📊 Поточний баланс", value=f"${current_total:,.2f} USDT", inline=False)
            
            if previous_balance:
                old_total = previous_balance['total_balance']
                change = current_total - old_total
                change_percent = (change / old_total * 100) if old_total > 0 else 0
                emoji = "📈" if change >= 0 else "📉"
                sign = "+" if change >= 0 else ""
                
                embed.add_field(name="📅 На початок місяця", value=f"${old_total:,.2f} USDT", inline=False)
                embed.add_field(name=f"{emoji} Зміна", value=f"{sign}${change:,.2f} ({sign}{change_percent:.1f}%)", inline=False)
                embed.set_footer(text=f"📆 Період: {current_month}")
            else:
                embed.add_field(name="❌ Немає даних", value="Скористайтеся кнопкою нижче для збереження", inline=False)
                
                view = SaveStatsButton(exchange_key, display_name)
                await interaction.followup.send(embed=embed, view=view)
                return
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Помилка: {str(e)[:200]}")
    
    async def handle_sell_selection(self, interaction: Interaction, exchange_key: str, display_name: str):
        try:
            await interaction.response.defer(ephemeral=False)
            
            keys = get_exchange_keys(exchange_key)
            if not keys:
                await interaction.followup.send(f"❌ API ключі для {display_name} не знайдено", ephemeral=True)
                return
            
            exchange = get_exchange_instance(
                exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
            user_id = interaction.user.id
            cached = shared.get_balance_cache(user_id, exchange_key)
            
            if cached:
                _, user_coins = cached
            else:
                balance = exchange.get_balance()
                user_coins = {coin: data for coin, data in balance['coins'].items() 
                            if coin != 'USDT' and data['amount'] > 0}
                shared.update_balance_cache(user_id, exchange_key, set(user_coins.keys()), user_coins)
            
            if not user_coins:
                await interaction.followup.send(f"📭 У вас немає монет на {display_name}", ephemeral=True)
                return
            
            coins_list = "\n".join([f"• **{coin}**: {data['amount']:.4f} (${data['usdt_value']:.2f})" 
                                for coin, data in list(user_coins.items())[:15]])
            if len(user_coins) > 15:
                coins_list += f"\n• ... та ще {len(user_coins) - 15} монет"
            
            embed = discord.Embed(
                title=f"💰 Продаж на {display_name}",
                description=f"**Знайдено монет для продажу:** {len(user_coins)}\n\n{coins_list}",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Виберіть відсоток від поточної ціни")
            
            view = PercentageSelectView(exchange_key, display_name, user_coins)
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            error_msg = str(e)[:200]
            logger.error(f"❌ Помилка: {error_msg}")
            await interaction.followup.send(f"❌ Помилка: {error_msg}", ephemeral=True)


class PercentageSelectView(discord.ui.View):
    def __init__(self, exchange_key: str, display_name: str, user_coins: dict):
        super().__init__(timeout=60)
        self.exchange_key = exchange_key
        self.display_name = display_name
        self.user_coins = user_coins
    
    @discord.ui.select(
        placeholder="Виберіть відсоток від поточної ціни",
        options=[
            SelectOption(label="+5%", value="105", description="Продати на 5% вище ціни"),
            SelectOption(label="+10%", value="110", description="Продати на 10% вище ціни"),
            SelectOption(label="+15%", value="115", description="Продати на 15% вище ціни"),
            SelectOption(label="+20%", value="120", description="Продати на 20% вище ціни"),
            SelectOption(label="+25%", value="125", description="Продати на 25% вище ціни"),
            SelectOption(label="+30%", value="130", description="Продати на 30% вище ціни"),
            SelectOption(label="+50%", value="150", description="Продати на 50% вище ціни"),
            SelectOption(label="По ринку", value="market", description="Продати за поточною ринковою ціною"),
        ]
    )
    async def percentage_select(self, interaction: Interaction, select: discord.ui.Select):
        percentage = int(select.values[0]) if select.values[0] != "market" else "market"
        
        view = ConfirmSellView(self.exchange_key, self.display_name, self.user_coins, percentage)
        await interaction.response.edit_message(
            content=f"✅ Вибрано: **{select.values[0]}**\n"
                   f"📊 Буде виставлено лімітні ордери на продаж ВСІХ {len(self.user_coins)} монет.\n\n"
                   f"⚠️ **Підтвердіть дію:**",
            view=view,
            embed=None
        )


class ConfirmSellView(discord.ui.View):
    def __init__(self, exchange_key: str, display_name: str, user_coins: dict, percentage):
        super().__init__(timeout=60)
        self.exchange_key = exchange_key
        self.display_name = display_name
        self.user_coins = user_coins
        self.percentage = percentage
    
    @discord.ui.button(label="✅ Підтвердити продаж", style=discord.ButtonStyle.danger)
    async def confirm_sell(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🔄 Виставляю ордери на продаж...", view=None)
        
        results = {"success": [], "failed": [], "skipped": []}
        
        for token, data in self.user_coins.items():
            try:
                amount = data['amount']
                symbol = f"{token}/USDT"
                
                keys = get_exchange_keys(self.exchange_key)
                exchange = get_exchange_instance(
                    self.exchange_key,
                    api_key=keys['api_key'],
                    api_secret=keys['secret'],
                    password=keys.get('password')
                )
                
                ticker = exchange.get_ticker(symbol)
                current_price = ticker['last']
                
                if current_price <= 0:
                    results["skipped"].append(f"{token} (ціна = 0)")
                    continue
                
                if self.percentage == "market":
                    order = exchange.create_market_sell_order(symbol, amount)
                    if order:
                        results["success"].append(f"{token} (ринок, {amount:.4f})")
                    else:
                        results["failed"].append(f"{token}")
                else:
                    order_price = current_price * (self.percentage / 100)
                    order = exchange.create_limit_sell_order(symbol, amount, order_price)
                    if order:
                        results["success"].append(f"{token} (+{self.percentage - 100}%, {amount:.4f} @ ${order_price:.6f})")
                    else:
                        results["failed"].append(f"{token}")
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                error_msg = str(e)
                if "offline" in error_msg.lower():
                    results["skipped"].append(f"{token} (пара неактивна)")
                else:
                    results["failed"].append(f"{token} ({error_msg[:50]})")
        
        embed = discord.Embed(
            title=f"📊 Результати продажу на {self.display_name}",
            color=discord.Color.green() if results["success"] else discord.Color.red()
        )
        
        if results["success"]:
            embed.add_field(name="✅ Успішно виставлено", value="\n".join(results["success"][:10]), inline=False)
            if len(results["success"]) > 10:
                embed.add_field(name="📋 ...", value=f"та ще {len(results['success']) - 10}", inline=False)
        
        if results["failed"]:
            embed.add_field(name="❌ Не вдалося", value="\n".join(results["failed"][:10]), inline=False)
        
        if results["skipped"]:
            embed.add_field(name="⏭️ Пропущено", value="\n".join(results["skipped"][:10]), inline=False)
        
        embed.set_footer(text="Перевірте ордери в меню '📋 Ордери'")
        
        try:
            new_balance = exchange.get_balance()
            new_coins = {coin: data for coin, data in new_balance['coins'].items() 
                        if coin != 'USDT' and data['amount'] > 0}
            shared.update_balance_cache(interaction.user.id, self.exchange_key, 
                                        set(new_coins.keys()), new_coins)
        except:
            pass
        
        await interaction.edit_original_response(content=None, embed=embed)
    
    @discord.ui.button(label="❌ Скасувати", style=discord.ButtonStyle.secondary)
    async def cancel_sell(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Продаж скасовано", view=None)


async def send_scan_page(interaction: Interaction, user_id: int, page: int = 0):
    data = scan_results.get(user_id)
    if not data:
        await interaction.response.send_message("❌ Результати сканування не знайдено", ephemeral=True)
        return
    
    tokens = data['tokens']
    exchange = data['exchange']
    total_pages = data['total_pages']
    
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    data['page'] = page
    
    start = page * 10
    end = min(start + 10, len(tokens))
    page_tokens = tokens[start:end]
    
    total = len(tokens)
    portfolio_count = sum(1 for t in tokens if t.get('in_portfolio'))
    
    embed = discord.Embed(
        title=f"📊 Результати сканування {exchange}",
        description=f"**Сторінка {page + 1}/{total_pages}** (токени {start + 1}-{end} з {total})\n"
                f"**Знайдено токенів:** {total}\n**🏆 У портфелі:** {portfolio_count}",
        color=discord.Color.purple()
    )
    
    for i, token in enumerate(page_tokens, start=start + 1):
        days = token['high_amplitude_candles_count']
        marker = " 🏆" if token.get('in_portfolio') else ""
        embed.add_field(
            name=f"{i}. {token['symbol']}",
            value=f"{days} днів{marker}",
            inline=False
        )
    
    view = PaginationView(user_id, total_pages, page)
    
    try:
        await interaction.response.edit_message(embed=embed, view=view)
    except:
        try:
            await interaction.edit_original_response(embed=embed, view=view)
        except:
            await interaction.followup.send(embed=embed, view=view)


class NotificationsView(discord.ui.View):
    def __init__(self, is_enabled: bool):
        super().__init__(timeout=60)
        self.is_enabled = is_enabled
        
        self.enable_button.disabled = is_enabled
        self.disable_button.disabled = not is_enabled
    
    @discord.ui.button(label="🔔 Увімкнути", style=discord.ButtonStyle.green)
    async def enable_button(self, interaction: Interaction, button: discord.ui.Button):
        from notifications import NotificationManager
        nm = NotificationManager()
        nm.set_enabled(interaction.user.id, True)
        
        embed = discord.Embed(
            title="✅ Сповіщення ввімкнено!",
            description="Тепер ви будете отримувати сповіщення про ST монети.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)
    
    @discord.ui.button(label="🔕 Вимкнути", style=discord.ButtonStyle.red)
    async def disable_button(self, interaction: Interaction, button: discord.ui.Button):
        from notifications import NotificationManager
        nm = NotificationManager()
        nm.set_enabled(interaction.user.id, False)
        
        embed = discord.Embed(
            title="🔕 Сповіщення вимкнено",
            description="Ви більше не будете отримувати сповіщення про ST монети.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)
    
    @discord.ui.button(label="❌ Закрити", style=discord.ButtonStyle.secondary)
    async def close_button(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.message.delete()


class PaginationView(discord.ui.View):
    def __init__(self, user_id: int, total_pages: int, current_page: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.total_pages = total_pages
        self.current_page = current_page
        
        self.prev_page.disabled = (current_page == 0)
        self.next_page.disabled = (current_page == total_pages - 1)
    
    async def update_message(self, interaction: Interaction, page: int):
        data = scan_results.get(self.user_id)
        if not data:
            await interaction.response.send_message("❌ Результати сканування не знайдено", ephemeral=True)
            return
        
        tokens = data['tokens']
        exchange = data['exchange']
        total_pages = data['total_pages']
        
        if page < 0:
            page = 0
        if page >= total_pages:
            page = total_pages - 1
        
        data['page'] = page
        
        start = page * 10
        end = min(start + 10, len(tokens))
        page_tokens = tokens[start:end]
        
        total = len(tokens)
        portfolio_count = sum(1 for t in tokens if t.get('in_portfolio'))
        
        embed = discord.Embed(
            title=f"📊 Результати сканування {exchange}",
            description=f"**Сторінка {page + 1}/{total_pages}** (токени {start + 1}-{end} з {total})\n"
                       f"**Знайдено токенів:** {total}\n**🏆 У портфелі:** {portfolio_count}",
            color=discord.Color.purple()
        )
        
        for i, token in enumerate(page_tokens, start=start + 1):
            days = token['high_amplitude_candles_count']
            marker = " 🏆" if token.get('in_portfolio') else ""
            embed.add_field(
                name=f"{i}. {token['symbol']}",
                value=f"{days} днів{marker}",
                inline=False
            )
        
        self.prev_page.disabled = (page == 0)
        self.next_page.disabled = (page == total_pages - 1)
        self.current_page = page
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="◀️ Попередня", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ці результати не для вас!", ephemeral=True)
            return
        await self.update_message(interaction, self.current_page - 1)
    
    @discord.ui.button(label="▶️ Наступна", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ці результати не для вас!", ephemeral=True)
            return
        await self.update_message(interaction, self.current_page + 1)
    
    @discord.ui.button(label="❌ Закрити", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ці результати не для вас!", ephemeral=True)
            return
        await interaction.message.delete()


class SellButtonView(discord.ui.View):
    def __init__(self, exchange_key, display_name, tokens):
        super().__init__(timeout=60)
        self.exchange_key = exchange_key
        self.display_name = display_name
        self.tokens = tokens
    
    @discord.ui.button(label="💰 Продати всі", style=ButtonStyle.danger)
    async def sell_all(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Починаю продаж...")
        
        sold = []
        failed = []
        
        for token in self.tokens:
            try:
                keys = get_exchange_keys(self.exchange_key)
                exchange = get_exchange_instance(
                    self.exchange_key,
                    api_key=keys['api_key'],
                    api_secret=keys['secret'],
                    password=keys.get('password')
                )
                
                user_id = interaction.user.id
                cached = shared.get_balance_cache(user_id, self.exchange_key)
                
                if cached:
                    _, user_coins = cached
                    if token not in user_coins:
                        failed.append(f"{token} (немає в балансі)")
                        continue
                    amount = user_coins[token]['amount']
                else:
                    balance = exchange.get_balance()
                    if token not in balance['coins']:
                        failed.append(f"{token} (немає в балансі)")
                        continue
                    amount = balance['coins'][token]['amount']
                
                symbol = f"{token}/USDT"
                ticker = exchange.get_ticker(symbol)
                
                order = exchange.create_market_sell_order(symbol, amount)
                if order:
                    sold.append(token)
                    try:
                        new_balance = exchange.get_balance()
                        new_user_coins = {}
                        for coin, data in new_balance['coins'].items():
                            if coin != 'USDT' and data['amount'] > 0:
                                new_user_coins[coin] = data
                        shared.update_balance_cache(user_id, self.exchange_key, 
                                                    set(new_user_coins.keys()), new_user_coins)
                    except:
                        pass
                else:
                    failed.append(token)
                    
                await asyncio.sleep(0.5)
                
            except Exception as e:
                failed.append(f"{token} ({str(e)[:30]})")
        
        result = f"✅ Продано: {', '.join(sold) if sold else 'немає'}\n"
        if failed:
            result += f"❌ Не вдалося: {', '.join(failed)}\n🔴 Продайте вручну на сайті біржі!"
        
        await interaction.followup.send(result)


class CancelOrdersButton(discord.ui.View):
    def __init__(self, exchange_key, display_name):
        super().__init__(timeout=60)
        self.exchange_key = exchange_key
        self.display_name = display_name
    
    @discord.ui.button(label="🗑️ Скасувати всі ордери", style=ButtonStyle.danger)
    async def cancel_all(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"🗑️ Знімаю всі ордери на {self.display_name}...")
        
        try:
            keys = get_exchange_keys(self.exchange_key)
            exchange = get_exchange_instance(
                self.exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
            orders = exchange.get_open_orders()
            
            if not orders:
                await interaction.followup.send(f"📭 Немає ордерів для зняття")
                return
            
            cancelled = 0
            failed = 0
            
            for order in orders:
                try:
                    if exchange.cancel_order(order.get('id'), order.get('symbol')):
                        cancelled += 1
                    else:
                        failed += 1
                    await asyncio.sleep(0.3)
                except:
                    failed += 1
            
            await interaction.followup.send(f"✅ Знято: {cancelled}\n❌ Помилок: {failed}")
            
        except Exception as e:
            await interaction.followup.send(f"❌ Помилка: {str(e)[:200]}")


class SaveStatsButton(discord.ui.View):
    def __init__(self, exchange_key, display_name):
        super().__init__(timeout=60)
        self.exchange_key = exchange_key
        self.display_name = display_name
    
    @discord.ui.button(label="💾 Зберегти поточний баланс", style=ButtonStyle.primary)
    async def save_stats(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"💾 Зберігаю баланс для {self.display_name}...")
        
        try:
            keys = get_exchange_keys(self.exchange_key)
            exchange = get_exchange_instance(
                self.exchange_key,
                api_key=keys['api_key'],
                api_secret=keys['secret'],
                password=keys.get('password')
            )
            
            balance = exchange.get_balance()
            
            from database.db_handler import DatabaseHandler
            db = DatabaseHandler()
            
            db.save_monthly_balance(interaction.user.id, self.exchange_key, balance['total_usdt'], balance['coins'])
            
            await interaction.followup.send(f"✅ **Баланс збережено!**\nСума: ${balance['total_usdt']:,.2f} USDT")
            
        except Exception as e:
            await interaction.followup.send(f"❌ Помилка: {str(e)[:200]}")


async def init_balance_cache():
    logger.info("🔄 Ініціалізація спільного кешу балансів...")
    
    configured_exchanges = get_all_configured_exchanges()
    users = shared.get_all_users()
    
    for user_id in users:
        for display_name, exchange_key in configured_exchanges.items():
            try:
                keys = get_exchange_keys(exchange_key)
                if not keys:
                    continue
                
                logger.info(f"  🔄 {exchange_key}: отримую баланс...")
                
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
                
                balance_data = await asyncio.wait_for(
                    asyncio.to_thread(exchange.get_balance),
                    timeout=45 if exchange_key == 'bingx' else 30
                )
                
                user_coins = set()
                coins_details = {}
                
                for coin, data in balance_data['coins'].items():
                    if coin != 'USDT' and data['amount'] > 0:
                        user_coins.add(coin)
                        coins_details[coin] = data
                
                shared.update_balance_cache(user_id, exchange_key, user_coins, coins_details)
                logger.info(f"  ✅ {exchange_key}: закешовано {len(user_coins)} монет")
                
            except Exception as e:
                logger.error(f"  ❌ Помилка ініціалізації кешу для {exchange_key}: {e}")
    
    shared.set_balance_cache_initialized()
    logger.info("✅ Ініціалізація спільного кешу балансів завершена")


@tasks.loop(minutes=10)
async def auto_delisting_check():
    if shared.delisting_check_running:
        return
    
    shared.delisting_check_running = True
    
    try:
        logger.info("🔍 Запуск автоматичної перевірки делістингу")
        
        configured_exchanges = get_all_configured_exchanges()
        users = shared.get_all_users()
        
        for user_id in users:
            all_found = {}
            
            for display_name, exchange_key in configured_exchanges.items():
                result = await delisting_service.check_single_exchange(user_id, exchange_key, display_name)
                if result:
                    all_found[exchange_key] = result
            
            if all_found and DISCORD_CHANNEL_ID:
                channel = bot.get_channel(int(DISCORD_CHANNEL_ID))
                if channel:
                    for exchange_key, result in all_found.items():
                        message = delisting_service.format_delisting_message(result, exchange_key)
                        if message:
                            await channel.send(message)
        
        logger.info("✅ Перевірка делістингу завершена")
        
    except Exception as e:
        logger.error(f"❌ Помилка перевірки делістингу: {e}")
    finally:
        shared.delisting_check_running = False


@tasks.loop(minutes=5)
async def auto_orders_check():
    if shared.delisting_check_running:
        return
    
    try:
        logger.info("📋 Перевірка виконаних ордерів...")
        
        configured_exchanges = get_all_configured_exchanges()
        users = shared.get_all_users()
        
        for user_id in users:
            for display_name, exchange_key in configured_exchanges.items():
                keys = get_exchange_keys(exchange_key)
                if not keys:
                    continue
                
                exchange = await asyncio.wait_for(
                    asyncio.to_thread(
                        get_exchange_instance,
                        exchange_key,
                        keys['api_key'],
                        keys['secret'],
                        keys.get('password')
                    ),
                    timeout=15
                )
                
                cache_key = f"last_orders_check_{user_id}_{exchange_key}"
                last_check = shared.last_orders_check.get(cache_key, 0)
                
                filled_orders = await asyncio.wait_for(
                    asyncio.to_thread(exchange.check_filled_orders, last_check),
                    timeout=30
                )
                
                if filled_orders and DISCORD_CHANNEL_ID:
                    channel = bot.get_channel(int(DISCORD_CHANNEL_ID))
                    if channel:
                        for order in filled_orders:
                            order_key = f"{user_id}_{exchange_key}_{order['id']}"
                            if order_key not in shared.sent_order_notifications:
                                message = format_filled_order_message(order, display_name)
                                await channel.send(message)
                                shared.sent_order_notifications[order_key] = datetime.now()
                
                if filled_orders:
                    shared.last_orders_check[cache_key] = int(datetime.now().timestamp() * 1000)
        
    except Exception as e:
        logger.error(f"❌ Помилка перевірки ордерів: {e}")


def format_filled_order_message(order: dict, exchange_name: str) -> str:
    symbol = order.get('symbol')
    amount = order.get('amount', 0)
    price = order.get('price', 0)
    total = order.get('cost', 0)
    
    if amount > 1000:
        amount_display = f"{amount:.0f}"
    elif amount > 100:
        amount_display = f"{amount:.1f}"
    else:
        amount_display = f"{amount:.4f}"
    
    return f"💰 **Монета продана!**\n\n**{symbol}**\nКількість: {amount_display}\nЦіна: ${price:.6f}\nОтримано: ${total:.2f} USDT\n**Біржа:** {exchange_name}"


async def init_balance_cache_background():
    await asyncio.sleep(3)
    await init_balance_cache()


@bot.event
async def on_ready():
    logger.info(f'✅ Discord бот запущено: {bot.user} (ID: {bot.user.id})')
    
    await bot.change_presence(activity=discord.Game(name="!menu | Crypto Bot"))
    
    asyncio.create_task(init_balance_cache_background())
    
    await asyncio.sleep(5)
    
    if not auto_delisting_check.is_running():
        auto_delisting_check.start()
        logger.info("🔄 Автоматичні перевірки делістингу запущено")
    
    if not auto_orders_check.is_running():
        auto_orders_check.start()
        logger.info("📋 Автоматична перевірка ордерів запущена")
    
    if DISCORD_CHANNEL_ID:
        channel = bot.get_channel(int(DISCORD_CHANNEL_ID))
        if channel:
            await channel.send("🤖 **Discord Crypto Bot запущено!**")
            await channel.send("✅ Автоматичні перевірки активовано")
            cache_info = f"📦 Кеш: {len(shared.user_coins_cache)} записів"
            await channel.send(cache_info)


@bot.command(name='menu')
async def show_menu(ctx):
    embed = discord.Embed(
        title="🤖 Crypto Bot - Головне меню",
        description="Натисніть кнопку для вибору дії",
        color=discord.Color.blue()
    )
    embed.add_field(name="📊 Баланс", value="Перегляд балансу на біржі", inline=True)
    embed.add_field(name="⚠️ Делістинг", value="Перевірка ST монет", inline=True)
    embed.add_field(name="📋 Ордери", value="Перегляд/скасування ордерів", inline=True)
    embed.add_field(name="🔍 Сканування", value="Аналіз токенів", inline=True)
    embed.add_field(name="📅 Статистика", value="Зміна балансу за місяць", inline=True)
    embed.add_field(name="💰 Продаж", value="Продаж монет", inline=True)
    
    await ctx.send(embed=embed, view=MainMenuView())


def run_discord_bot():
    if not DISCORD_BOT_TOKEN:
        logger.error("❌ DISCORD_BOT_TOKEN не встановлено в .env")
        return
    
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"❌ Помилка запуску Discord бота: {e}")


if __name__ == '__main__':
    run_discord_bot()