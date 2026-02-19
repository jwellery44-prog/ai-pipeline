from __future__ import annotations

import mimetypes
from urllib.parse import urlparse

import httpx
from supabase import Client, create_client

from config import settings
from logging_config import logger

supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_ROLE_KEY,
)


def _ensure_bucket(bucket_name: str) -> None:
    """
    Create *bucket_name* as a public bucket if it does not already exist.
    Safe to call on every upload — it is a no-op when the bucket exists.
    """
    try:
        existing = [b.name for b in supabase.storage.list_buckets()]
        if bucket_name not in existing:
            supabase.storage.create_bucket(bucket_name, options={"public": True})
            logger.info(f"Created storage bucket '{bucket_name}'")
    except Exception as exc:
        # Non-fatal: log and let the subsequent upload surface the real error.
        logger.warning(f"Could not verify/create bucket '{bucket_name}': {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _storage_path_from_image_url(image_url: str) -> tuple[str, str]:
    """
    Given either a full Supabase storage URL or a relative storage path,
    return (bucket_name, object_path).

    Examples
    --------
    Full URL  → "https://<host>/storage/v1/object/public/plant-images/products/abc.jpg"
                returns ("plant-images", "products/abc.jpg")
    Relative  → "products/abc.jpg"
                returns (settings.RAW_BUCKET_NAME, "products/abc.jpg")
    """
    parsed = urlparse(image_url)

    # Supabase storage URL pattern: /storage/v1/object/{public|sign}/{bucket}/{path}
    if parsed.scheme in ("http", "https") and "/storage/v1/object/" in parsed.path:
        parts = parsed.path.split("/storage/v1/object/")[-1].split("/", 2)
        # parts[0] = "public" or "sign", parts[1] = bucket, parts[2] = object path
        if len(parts) >= 3:
            return parts[1], parts[2]

    # Treat as a relative path within the default raw bucket
    return settings.RAW_BUCKET_NAME, image_url


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

async def download_image(url: str) -> bytes:
    """Download an image from a public HTTP/HTTPS URL with size + MIME validation."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30.0, follow_redirects=True)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if content_type not in settings.ALLOWED_MIME_TYPES:
                raise ValueError(f"Unsupported MIME type: {content_type!r}")

            content = response.content
            if len(content) > settings.MAX_FILE_SIZE_BYTES:
                raise ValueError(
                    f"File too large: {len(content)} bytes "
                    f"(limit {settings.MAX_FILE_SIZE_BYTES} bytes)"
                )

            return content

    except Exception as exc:
        logger.error(f"Failed to download image from {url}: {exc}")
        raise


def download_from_storage(bucket: str, path: str) -> bytes:
    """
    Download an object from Supabase Storage using the service-role key.
    Works for both public and private buckets.

    Returns raw bytes of the file.
    """
    try:
        data = supabase.storage.from_(bucket).download(path)
        logger.info(f"Downloaded {path!r} from bucket {bucket!r} ({len(data)} bytes)")
        return data
    except Exception as exc:
        logger.error(f"Storage download failed — bucket={bucket!r} path={path!r}: {exc}")
        raise


def resolve_product_image(product: dict) -> bytes:
    """
    Download the raw image for a product record.

    Resolution order
    ----------------
    1. Use ``image_url`` column if set — parse bucket + path from it.
    2. Fall back to ``{RAW_STORAGE_FOLDER}/{product_id}`` in ``RAW_BUCKET_NAME``.

    Returns raw image bytes.
    """
    product_id: str = product["id"]
    image_url: str | None = product.get("image_url")

    if image_url:
        bucket, path = _storage_path_from_image_url(image_url)
        logger.info(
            f"Resolving image from storage: bucket={bucket!r} path={path!r}",
            extra={"product_id": product_id},
        )
        return download_from_storage(bucket, path)

    # Fallback: derive path from product ID inside the configured folder
    fallback_path = f"{settings.RAW_STORAGE_FOLDER}/{product_id}"
    logger.warning(
        f"image_url is NULL for product {product_id!r}; "
        f"trying fallback path {fallback_path!r} in bucket {settings.RAW_BUCKET_NAME!r}",
        extra={"product_id": product_id},
    )
    return download_from_storage(settings.RAW_BUCKET_NAME, fallback_path)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def upload_processed_image(file_content: bytes, product_id: str) -> str:
    """
    Upload a processed image to Supabase Storage.

    Stored at: ``{PROCESSED_STORAGE_FOLDER}/{product_id}.png``
    in bucket:  ``{PROCESSED_BUCKET_NAME}``

    Returns the public URL of the uploaded object.
    """
    path = f"{settings.PROCESSED_STORAGE_FOLDER}/{product_id}.png"

    try:
        _ensure_bucket(settings.PROCESSED_BUCKET_NAME)
        supabase.storage.from_(settings.PROCESSED_BUCKET_NAME).upload(
            path=path,
            file=file_content,
            file_options={"content-type": "image/png", "upsert": "true"},
        )

        public_url = (
            f"{settings.SUPABASE_URL}/storage/v1/object/public/"
            f"{settings.PROCESSED_BUCKET_NAME}/{path}"
        )

        logger.info(
            f"Uploaded processed image → {public_url}",
            extra={"product_id": product_id},
        )
        return public_url

    except Exception as exc:
        logger.error(
            f"Failed to upload processed image for product {product_id}: {exc}",
            extra={"product_id": product_id},
        )
        raise


def upload_raw_image(file_content: bytes, product_id: str, content_type: str = "image/jpeg") -> str:
    """
    Upload a raw/original image to Supabase Storage before processing.

    Stored at: ``{RAW_STORAGE_FOLDER}/{product_id}<ext>``
    in bucket:  ``{RAW_BUCKET_NAME}``

    Returns the public URL so it can be saved to ``products.image_url``.
    """
    ext_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    ext = ext_map.get(content_type, ".jpg")
    path = f"{settings.RAW_STORAGE_FOLDER}/{product_id}{ext}"

    try:
        _ensure_bucket(settings.RAW_BUCKET_NAME)
        supabase.storage.from_(settings.RAW_BUCKET_NAME).upload(
            path=path,
            file=file_content,
            file_options={"content-type": content_type, "upsert": "true"},
        )

        public_url = (
            f"{settings.SUPABASE_URL}/storage/v1/object/public/"
            f"{settings.RAW_BUCKET_NAME}/{path}"
        )
        logger.info(
            f"Uploaded raw image → {public_url}",
            extra={"product_id": product_id},
        )
        return public_url

    except Exception as exc:
        logger.error(
            f"Failed to upload raw image for product {product_id}: {exc}",
            extra={"product_id": product_id},
        )
        raise

