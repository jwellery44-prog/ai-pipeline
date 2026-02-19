import asyncio
from config import settings
from logging_config import logger
from database import fetch_pending_job
from pipeline import process_job

async def worker_loop():
    """
    Main worker loop that polls for pending jobs.
    """
    logger.info("Worker started.")
    
    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_JOBS)
    
    while True:
        try:
            # Check for available slot
            if semaphore.locked():
                await asyncio.sleep(1)
                continue
                
            # Fetch job
            job = await fetch_pending_job()
            
            if job:
                # Acquire semaphore and spawn task
                await semaphore.acquire()
                asyncio.create_task(run_job_with_semaphore(job, semaphore))
            else:
                # No jobs, sleep
                await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
                
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(5)

async def run_job_with_semaphore(job, semaphore):
    """
    Wrapper to release semaphore after job completion.
    """
    try:
        await process_job(job)
    finally:
        semaphore.release()
