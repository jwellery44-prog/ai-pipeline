from database import update_job_status
from storage import download_image, upload_processed_image
from ai_clients import reve_client, nanobana_client
from logging_config import logger
import time
import asyncio

async def process_job(job: dict):
    """
    Orchestrate the full processing pipeline for a single job.
    """
    job_id = job["id"]
    raw_url = job["raw_url"]
    start_time = time.time()
    
    logger.info(f"Starting processing for job {job_id}", extra={"job_id": job_id})
    
    try:
        # 1. Download Image
        logger.info("Step 1: Downloading image...", extra={"job_id": job_id})
        image_content = await download_image(raw_url)
        
        # 2. Reve (Background Removal)
        logger.info("Step 2: Removing background (Reve)...", extra={"job_id": job_id})
        reve_output = await reve_client.remove_background(image_content)
        
        # 3. Nanobana (Enhancement)
        logger.info("Step 3: Enhancing image (Nanobana)...", extra={"job_id": job_id})
        final_image = await nanobana_client.enhance_image(reve_output)
        
        # 4. Upload Result
        logger.info("Step 4: Uploading processed image...", extra={"job_id": job_id})
        public_url = await upload_processed_image(final_image, f"{job_id}.png", job_id)
        
        # 5. Update DB
        processing_time = int((time.time() - start_time) * 1000)
        await update_job_status(
            job_id, 
            status="done", 
            processed_url=public_url, 
            processing_time_ms=processing_time
        )
        logger.info(f"Job {job_id} completed successfully in {processing_time}ms", extra={"job_id": job_id})
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", extra={"job_id": job_id})
        await update_job_status(
            job_id, 
            status="error", 
            error_message=str(e)
        )
