import asyncio
from functools import wraps

def run_async(func):
   
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    return wrapper

async def run_sync(func, *args, **kwargs):
   
    return await asyncio.to_thread(func, *args, **kwargs)

async def run_sync_with_timeout(func, timeout, *args, **kwargs):

    return await asyncio.wait_for(
        asyncio.to_thread(func, *args, **kwargs),
        timeout=timeout
    )