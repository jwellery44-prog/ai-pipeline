from __future__ import annotations

import time

from ai_clients import nanobana_client, reve_client
from database import update_job_status, update_product_image_url
from logging_config import logger
from storage import resolve_product_image, upload_processed_image, upload_file_to_storage
from config import settings


# ---------------------------------------------------------------------------
# Product pipeline  (used by the /process/{image_id} API endpoint)
# ---------------------------------------------------------------------------

async def process_product_image(product: dict) -> str:
    """
    Full AI pipeline for a single product.

    Steps
    -----
    1. Download raw image from Supabase Storage (plant-images/products/...).
    2. Reve  — background removal.
    3. Nanobana — image enhancement.
    4. Upload processed PNG to Supabase Storage (products/processed/).
    5. Write the new public URL back to ``products.image_url``.

    Returns the public URL of the processed image.
    """
    product_id: str = product["id"]
    start = time.time()

    logger.info("Pipeline started", extra={"product_id": product_id})

    # 1. Fetch raw image from Supabase Storage --------------------------------
    logger.info("Step 1/4 — downloading raw image from storage", extra={"product_id": product_id})
    image_bytes = resolve_product_image(product)

    # 2. Background removal (Reve) -------------------------------------------
    logger.info("Step 2/4 — removing background (Reve)", extra={"product_id": product_id})
    reve_output = await reve_client.remove_background(image_bytes)

    # 2.1 Nanobana requires a public URL for the background-removed image.
    # We upload it to a temporary path to keep the processed folder clean.
    reve_url = upload_file_to_storage(
        reve_output,
        settings.PROCESSED_BUCKET_NAME,
        f"products/temp/reve_{product_id}.png"
    )

    # 3. Enhancement (Nanobana) ----------------------------------------------
    logger.info("Step 3/4 — enhancing image (Nanobana)", extra={"product_id": product_id})
    final_image = await nanobana_client.enhance_image(reve_url)

    # 4. Upload processed result ---------------------------------------------
    logger.info("Step 4/4 — uploading FINAL processed image", extra={"product_id": product_id})
    processed_url = upload_processed_image(final_image, product_id)

    # 5. Persist processed URL back to products table ------------------------
    await update_product_image_url(product_id, processed_url)

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(
        f"Pipeline complete in {elapsed_ms}ms",
        extra={"product_id": product_id, "processed_url": processed_url},
    )
    return processed_url


# ---------------------------------------------------------------------------
# Worker pipeline  (used by the background worker loop)
# ---------------------------------------------------------------------------

async def process_job(job: dict) -> None:
    """
    Worker-facing pipeline wrapper.  Expects a job dict with at least
    ``id`` and ``raw_url`` and updates job status cols on completion.
    """
    job_id = job["id"]
    raw_url = job.get("raw_url")
    start = time.time()

    logger.info("Worker job started", extra={"job_id": job_id})

    try:
        from storage import download_image  # local import to avoid circular at module level

        logger.info("Step 1/4 — downloading image", extra={"job_id": job_id})
        image_bytes = await download_image(raw_url)

        logger.info("Step 2/4 — removing background (Reve)", extra={"job_id": job_id})
        reve_output = await reve_client.remove_background(image_bytes)

        # Upload intermediate for Nanobana
        reve_url = upload_file_to_storage(
            reve_output,
            settings.PROCESSED_BUCKET_NAME,
            f"products/temp/reve_{job_id}.png"
        )

        logger.info("Step 3/4 — enhancing image (Nanobana)", extra={"job_id": job_id})
        final_image = await nanobana_client.enhance_image(reve_url)

        logger.info("Step 4/4 — uploading FINAL processed image", extra={"job_id": job_id})
        processed_url = upload_processed_image(final_image, job_id)

        elapsed_ms = int((time.time() - start) * 1000)
        await update_job_status(
            job_id,
            status="done",
            processed_url=processed_url,
            processing_time_ms=elapsed_ms,
        )
        logger.info(f"Worker job complete in {elapsed_ms}ms", extra={"job_id": job_id})

    except Exception as exc:
        logger.error(f"Worker job failed: {exc}", extra={"job_id": job_id})
        await update_job_status(job_id, status="error", error_message=str(exc))
