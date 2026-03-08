import asyncio

from app.logging import logger


async def worker_loop() -> None:
    """
    Background worker loop.

    Current setup uses /process endpoint directly — no separate job queue.
    This coroutine stays alive so FastAPI lifespan can cancel it on shutdown.
    """
    logger.info("Worker started (API-driven mode — polling disabled)")
    while True:
        await asyncio.sleep(3600)
