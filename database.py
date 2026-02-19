from supabase import create_client, Client
from config import settings
from logging_config import logger
from datetime import datetime

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

async def fetch_pending_job():
    """
    Fetch a single pending job and lock it by setting status to 'processing'.
    """
    try:
        # Optimistic locking: update a row that is pending and return it
        # We use rpc or direct update. Since Supabase-js doesn't support
        # atomic "select for update" easily in the js client without rpc,
        # we will use a stored procedure if possible, but for now we'll try
        # a direct update approach which is "good enough" for low concurrency
        # or rely on the return value.
        
        # A robust way without stored procedure:
        # 1. Select pending jobs (limit 1)
        # 2. Update that specific job
        # But this has race conditions.
        
        # Better approach for Supabase/Postgres:
        # Update... Returning *
        
        response = supabase.table("images") \
            .update({
                "status": "processing",
                "processing_started_at": datetime.utcnow().isoformat()
            }) \
            .eq("status", "pending") \
            .limit(1) \
            .select() \
            .execute()
            
        if response.data and len(response.data) > 0:
            job = response.data[0]
            logger.info(f"Locked job {job['id']}", extra={"job_id": job['id']})
            return job
            
        return None
        
    except Exception as e:
        logger.error(f"Error fetching pending job: {e}")
        return None

async def update_job_status(job_id: str, status: str, processed_url: str = None, error_message: str = None, processing_time_ms: int = None):
    """
    Update the status of a job.
    """
    try:
        data = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if processed_url:
            data["processed_url"] = processed_url
            
        if error_message:
            data["error_message"] = error_message
            
        if processing_time_ms:
            data["processing_time_ms"] = processing_time_ms
            
        supabase.table("images").update(data).eq("id", job_id).execute()
        logger.info(f"Updated job {job_id} to status {status}", extra={"job_id": job_id})
        
    except Exception as e:
        logger.error(f"Error updating job {job_id}: {e}", extra={"job_id": job_id})
        # This is a critical failure (DB update failed after processing).
        # We should probably alert or retry here, but keeping it simple for now.
        raise e
