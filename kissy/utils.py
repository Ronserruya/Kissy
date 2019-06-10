import os
import asyncio
from contextlib import asynccontextmanager

from aiohttp import ClientTimeout

try:
    TERMINAL_WIDTH = os.get_terminal_size(0).columns
    BAR_WIDTH = int(TERMINAL_WIDTH * 0.5)
except OSError:  # This doesn't work in pycharm, so fallback to None
    TERMINAL_WIDTH = None
    BAR_WIDTH = None


async def retryable_get_request(session, link: str, timeout: float, retry_count: int, *args, **kwargs):
    """Kissanime and rapidvideo will often not connect after some requests,
    retrying the same request seems to solve it immediately"""
    for i in range(retry_count):
        try:
            async with session.get(link, *args, timeout=ClientTimeout(total=timeout), **kwargs) as resp:
                page, status = await resp.text(), resp.status
        except asyncio.TimeoutError:
            if i == retry_count - 1:
                raise
            await asyncio.sleep(1)
        else:
            return page, status


@asynccontextmanager
async def get_connection(queue: asyncio.Queue):
    """Used to limit parallel ep downloads"""
    item = await queue.get()
    try:
        yield item
    finally:
        await queue.put(item)
