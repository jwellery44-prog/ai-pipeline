import asyncio

from app.logging import logger


async def worker_loop() -> None:
    """
    Background worker loop.

    Current setup uses /process endpoint directly — no separate job queue.
    This coroutine stays alive so FastAPI lifespan can cancel it on shutdown.
    """
    logger.info("Worker started (API-driven mode — polling disabled)")
    # Nothing to poll right now; jobs are triggered via POST /process.
    # Sleeping in a long interval keeps the coroutine alive without busy-looping.
    # If we add a job-queue later, replace this with actual poll logic.
    while True:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("Worker loop cancelled, shutting down gracefully")
            break