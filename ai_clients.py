from __future__ import annotations

import asyncio
import base64
import json

import httpx

from config import settings
from logging_config import logger


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    max_retries: int,
    retry_count: int = 0,
    **kwargs,
) -> httpx.Response:
    """POST with exponential back-off on 429 / 5xx."""
    response = await client.post(url, headers=headers, **kwargs)

    if (response.status_code == 429 or response.status_code >= 500) and retry_count < max_retries:
        wait = 2 ** retry_count
        logger.warning(
            f"HTTP {response.status_code} from {url} — retrying in {wait}s "
            f"({retry_count + 1}/{max_retries})"
        )
        await asyncio.sleep(wait)
        return await _post_with_retry(
            client, url, headers=headers, max_retries=max_retries,
            retry_count=retry_count + 1, **kwargs
        )

    if not response.is_success:
        # Log the full response body so we can see the exact API error message
        try:
            body = response.json()
        except Exception:
            body = response.text
        logger.error(f"API error {response.status_code} from {url}: {body}")

    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# Reve  —  background removal
# ---------------------------------------------------------------------------
# curl -X POST https://api.reve.ai/v1/image/edit \
#   -H "Authorization: Bearer <key>" \
#   -F "image=@input.png" \
#   -F "prompt=..."
# Returns: raw image bytes (PNG)
# ---------------------------------------------------------------------------

class ReveClient:
    _BASE_URL = "https://api.reve.com/v1/image/edit"

    def __init__(self) -> None:
        self._headers = {"Authorization": f"Bearer {settings.REVE_API_KEY}"}

    async def remove_background(self, image_bytes: bytes) -> bytes:
        """
        Send an image to Reve for background removal.
        Returns the processed image as raw bytes.
        """
        # Encode image to base64
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        
        json_data = {
            "edit_instruction": settings.REVE_PROMPT,
            "reference_image": base64_image,
            "version": "latest"
        }

        try:
            async with httpx.AsyncClient(timeout=150.0) as client:
                response = await _post_with_retry(
                    client,
                    self._BASE_URL,
                    headers=self._headers,
                    json=json_data,
                    max_retries=settings.MAX_RETRIES,
                )
            
            # The subagent didn't specify the response format, 
            # let's check if it returns raw bytes or JSON with base64.
            # Most JSON-in APIs return JSON-out.
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data = response.json()
                # If it's a simple {image: base64} response
                if "image" in data:
                    return base64.b64decode(data["image"])
                # Fallback to the generic extractor (for Gemini/complex formats)
                return _extract_image_bytes(data)
            
            logger.info(f"Reve response: {response.status_code}, {len(response.content)} bytes")
            return response.content

        except Exception as exc:
            logger.error(f"Reve remove_background failed: {exc}")
            raise


# ---------------------------------------------------------------------------
# Nanobana  —  image enhancement / scene composition
# ---------------------------------------------------------------------------
# POST https://api.nanobananaapi.ai/api/v1/nanobanana/record-info
# Content-Type: application/json
# Body (Gemini-style):
# {
#   "contents": [{
#     "parts": [
#       {"inline_data": {"mime_type": "image/png", "data": "<BASE64>"}},
#       {"text": "<prompt>"}
#     ]
#   }]
# }
# Returns: JSON with candidates[0].content.parts containing inline_data or text URL
# ---------------------------------------------------------------------------

class NanobanaClient:
    _BASE_URL = "https://api.nanobananaapi.ai/api/v1/nanobanana/record-info"

    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.NANOBANA_API_KEY}",
            "Content-Type": "application/json",
        }

    async def enhance_image(self, image_bytes: bytes) -> bytes:
        """
        Send a background-removed image to Nanobana for scene enhancement.
        Accepts raw image bytes, returns processed image as raw bytes.
        """
        b64_data = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": b64_data,
                            }
                        },
                        {"text": settings.NANOBANA_PROMPT},
                    ]
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await _post_with_retry(
                    client,
                    self._BASE_URL,
                    headers=self._headers,
                    content=json.dumps(payload).encode(),
                    max_retries=settings.MAX_RETRIES,
                )

            result = response.json()
            logger.info(f"Nanobana response: {response.status_code}")
            return _extract_image_bytes(result)

        except Exception as exc:
            logger.error(f"Nanobana enhance_image failed: {exc}")
            raise


def _extract_image_bytes(response_json: dict) -> bytes:
    """
    Extract image bytes from a Nanobana (Gemini-style) response.

    Tries, in order:
    1. candidates[0].content.parts[*].inline_data.data  (base64 image)
    2. candidates[0].content.parts[*].text  (public URL — download it)
    3. Raw bytes if response was already binary (fallback).
    """
    try:
        candidates = response_json.get("candidates", [])
        if not candidates:
            raise ValueError(f"No candidates in Nanobana response: {response_json}")

        parts = candidates[0]["content"]["parts"]

        for part in parts:
            # ── base64 inline image ─────────────────────────────────────
            inline = part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])

            # ── public URL ──────────────────────────────────────────────
            text = part.get("text", "")
            if text.startswith("http"):
                import httpx as _httpx
                r = _httpx.get(text, timeout=60.0, follow_redirects=True)
                r.raise_for_status()
                return r.content

        raise ValueError(f"Could not extract image from Nanobana parts: {parts}")

    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected Nanobana response structure: {response_json}") from exc


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

reve_client = ReveClient()
nanobana_client = NanobanaClient()

