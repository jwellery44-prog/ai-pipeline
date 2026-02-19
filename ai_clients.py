import httpx
import asyncio
from config import settings
from logging_config import logger

class AIClient:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

    async def post_image(self, image_content: bytes, endpoint: str, data: dict = None, retry_count: int = 0) -> bytes:
        """
        Generic method to post an image to an AI service and return the processed image bytes.
        """
        files = {"file": ("image.png", image_content, "image/png")}
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}{endpoint}",
                    headers=self.headers,
                    files=files,
                    data=data
                )
                
                if response.status_code == 429 or response.status_code >= 500:
                    # Retryable error
                    if retry_count < settings.MAX_RETRIES:
                        wait_time = 2 ** retry_count  # Exponential backoff
                        logger.warning(f"AI Service error {response.status_code}, retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        return await self.post_image(image_content, endpoint, data, retry_count + 1)
                
                response.raise_for_status()
                return response.content
                
        except httpx.RequestError as e:
            if retry_count < settings.MAX_RETRIES:
                wait_time = 2 ** retry_count
                logger.warning(f"Network error {e}, retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
                return await self.post_image(image_content, endpoint, data, retry_count + 1)
            raise e
            
class ReveClient(AIClient):
    def __init__(self):
        # Assuming a hypothetical URL for Reve, needs actual URL from documentation if available
        # But for now using a placeholder or user provided structure.
        # User prompt implies "Reve API CALL".
        super().__init__(settings.REVE_API_KEY, "https://api.reve.ai/v1") 

    async def remove_background(self, image_content: bytes) -> bytes:
        return await self.post_image(
            image_content, 
            "/remove-background",
            data={"prompt": settings.REVE_PROMPT}
        )

class NanobanaClient(AIClient):
    def __init__(self):
        # Assuming a hypothetical URL for Nanobana
        super().__init__(settings.NANOBANA_API_KEY, "https://api.nanobana.ai/v1")

    async def enhance_image(self, image_content: bytes) -> bytes:
        return await self.post_image(
            image_content, 
            "/enhance", 
            data={"prompt": settings.NANOBANA_PROMPT}
        )

reve_client = ReveClient()
nanobana_client = NanobanaClient()
