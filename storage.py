import httpx
from supabase import create_client, Client
from config import settings
from logging_config import logger
import io

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

async def download_image(url: str) -> bytes:
    """
    Download image from URL (Supabase Storage or Public URL).
    Enforces size and mime type limits.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            
            content_type = response.headers.get("content-type")
            if content_type not in settings.ALLOWED_MIME_TYPES:
                raise ValueError(f"Invalid MIME type: {content_type}")
                
            content = response.content
            if len(content) > settings.MAX_FILE_SIZE_BYTES:
                raise ValueError(f"File size exceeds limit: {len(content)} bytes")
                
            return content
            
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        raise e

async def upload_processed_image(file_content: bytes, original_filename: str, job_id: str) -> str:
    """
    Upload processed image to Supabase Storage.
    Returns the public URL.
    """
    try:
        # Create a unique filename: job_id/original_name OR just job_id.png
        # Let's use deterministic naming: {job_id}_processed.png
        filename = f"{job_id}_processed.png"
        path = f"{filename}"
        
        # Upload using Supabase Storage API
        res = supabase.storage.from_(settings.PROCESSED_BUCKET_NAME).upload(
            path=path,
            file=file_content,
            file_options={"content-type": "image/png", "upsert": "true"}
        )
        
        # Construct Public URL
        # Supabase Python client doesn't always return the full public URL comfortably in one go for private buckets, 
        # but for public buckets we can construct it.
        # Assuming standard Supabase storage URL structure:
        # {SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{PATH}
        
        public_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{settings.PROCESSED_BUCKET_NAME}/{path}"
        
        logger.info(f"Uploaded processed image to {public_url}", extra={"job_id": job_id})
        return public_url
        
    except Exception as e:
        logger.error(f"Failed to upload image for job {job_id}: {e}", extra={"job_id": job_id})
        raise e
