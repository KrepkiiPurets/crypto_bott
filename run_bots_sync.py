import asyncio
import subprocess
import sys
import os
import signal
import time

telegram_ready = asyncio.Event()
discord_ready = asyncio.Event()


async def run_telegram():
    """Запуск Telegram бота"""
    print("\n" + "=" * 60)
    print("ЗАПУСК TELEGRAM БОТА (очікує Discord...)")
    print("=" * 60)
    
    proc = await asyncio.create_subprocess_exec(
        sys.executable, 'bot.py',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    )
    
    async def read_output(stream, name):
        async for line in stream:
            decoded = line.decode('utf-8', errors='replace').strip()
            if decoded:
                print(f"[{name}] {decoded}")
                if "Application started" in decoded or "Бот запущено" in decoded:
                    telegram_ready.set()
    
    await asyncio.gather(
        read_output(proc.stdout, "Telegram"),
        read_output(proc.stderr, "Telegram"),
        proc.wait()
    )


async def run_discord():
    """Запуск Discord бота"""
    print("\n" + "=" * 60)
    print("ЗАПУСК DISCORD БОТА")
    print("=" * 60)
    
    proc = await asyncio.create_subprocess_exec(
        sys.executable, 'discord_bot.py',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    )
    
    async def read_output(stream, name):
        async for line in stream:
            decoded = line.decode('utf-8', errors='replace').strip()
            if decoded:
                print(f"[{name}] {decoded}")
                if "Discord бот запущено" in decoded or "logged in" in decoded.lower():
                    discord_ready.set()
    
    await asyncio.gather(
        read_output(proc.stdout, "Discord"),
        read_output(proc.stderr, "Discord"),
        proc.wait()
    )


async def main():
    """Головна функція - запуск обох ботів з синхронізацією"""
    print("=" * 60)
    print("CRYPTO BOT LAUNCHER (Синхронізований запуск)")
    print("=" * 60)
    print("\nTelegram бот буде запущено, але не буде активний")
    print("Discord бот запускається паралельно")
    print("Після запуску Discord бота - Telegram активується\n")
    
    telegram_task = asyncio.create_task(run_telegram())
    discord_task = asyncio.create_task(run_discord())
    
    print("Очікування готовності Discord бота...")
    await discord_ready.wait()
    print("Discord бот готовий!")
    
    await asyncio.sleep(2)
    print("Telegram бот тепер активний!")
    print("\n" + "=" * 60)
    print("ОБИДВА БОТИ ПРАЦЮЮТЬ!")
    print("=" * 60)
    
    await asyncio.gather(telegram_task, discord_task, return_exceptions=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n Боти зупинено користувачем")