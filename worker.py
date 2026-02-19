import asyncio

from config import settings
from logging_config import logger


async def worker_loop() -> None:
    """
    Background worker loop.

    The current setup uses the ``products`` table directly via the
    ``POST /process`` API endpoint — there is no separate job-queue table
    with a ``status`` column, so polling is disabled.

    This coroutine stays alive (sleeping) so the FastAPI lifespan context
    manager can cancel it cleanly on shutdown.  If you add a dedicated
    jobs table in the future, re-enable polling here.
    """
    logger.info(
        "Worker started (API-driven mode — polling disabled; "
        "processing is triggered via POST /process)"
    )
    while True:
        await asyncio.sleep(3600)  # just keep the task alive


    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_JOBS)
    cycle = 0
    consecutive_errors = 0

    # Run an initial stale-job sweep on startup
    try:
        await reset_stale_jobs(settings.PROCESSING_TIMEOUT_SECONDS)
    except APIError as exc:
        logger.critical(
            f"FATAL: Cannot reach table '{settings.DB_TABLE_NAME}' — "
            f"check DB_TABLE_NAME in .env. PostgREST code: {exc.code}",
            exc_info=exc,
        )
        # Don't exit — allow time for the user to fix config and reload
        await asyncio.sleep(_FATAL_BACKOFF_MAX)

    while True:
        try:
            cycle += 1

            # Periodic stale-job reset
            if cycle % _STALE_RESET_EVERY_N_CYCLES == 0:
                await reset_stale_jobs(settings.PROCESSING_TIMEOUT_SECONDS)

            # Back-pressure: if all slots are occupied, wait before polling
            if semaphore.locked():
                await asyncio.sleep(1)
                continue

            job = await fetch_pending_job()
            consecutive_errors = 0  # successful poll — reset error counter

            if job:
                await semaphore.acquire()
                asyncio.create_task(_run_with_semaphore(job, semaphore))
            else:
                await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

        except APIError as exc:
            # Fatal configuration error — log clearly and back off hard so
            # logs don't flood. Uvicorn --reload will restart when .env changes.
            logger.critical(
                f"FATAL DB error (code={exc.code}): {exc.message}. "
                f"Verify DB_TABLE_NAME='{settings.DB_TABLE_NAME}' in .env. "
                f"Backing off {_FATAL_BACKOFF_MAX}s.",
            )
            await asyncio.sleep(_FATAL_BACKOFF_MAX)

        except Exception as exc:
            consecutive_errors += 1
            backoff = min(_TRANSIENT_BACKOFF_BASE * consecutive_errors, 60)
            logger.error("Worker loop error", exc_info=exc, extra={"backoff_seconds": backoff})
            await asyncio.sleep(backoff)


async def _run_with_semaphore(job: dict, semaphore: asyncio.Semaphore) -> None:
    """Run a single job and release the semaphore slot when done."""
    try:
        await process_job(job)
    finally:
        semaphore.release()
