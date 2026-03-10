from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.config import build_variant_prompts, settings
from app.db.repository import update_job_status, update_product_generated_images
from app.logging import logger
from app.services.ai import nanobana_client, reve_client
from app.services.storage import (
    download_image,
    resolve_product_image,
    upload_file_to_storage,
    upload_processed_image,
    upload_processed_image_variant,
)

async def _generate_variant(
    reve_url: str,
    product_id: str,
    variant_index: int,
    prompt: str,
) -> Optional[str]:
    """Run single Nanobana generation + upload for one variant."""
    try:
        logger.info(f"Variant {variant_index} — starting", extra={"product_id": product_id})

        image_bytes = await nanobana_client.enhance_image(reve_url, prompt=prompt)

        # Upload runs in a thread because the Supabase storage SDK is synchronous.
        public_url = await asyncio.to_thread(
            upload_processed_image_variant, image_bytes, product_id, variant_index
        )

        logger.info(f"Variant {variant_index} — done: {public_url}", extra={"product_id": product_id})
        return public_url

    except Exception as exc:
        # Return None so the other variants can still finish successfully.
        logger.error(f"Variant {variant_index} FAILED: {exc}", extra={"product_id": product_id}, exc_info=True)
        return None

async def process_product_image(product: dict) -> list[str]:
    """
    Full AI pipeline for a product — produces 4 concurrent variants.

    Steps:
    1. Download raw image from storage
    2. Reve background removal
    3. Upload Reve output to temp path
    4. Generate 4 variants concurrently via Nanobana
    5. Upload each variant
    6. Persist URLs to database

    Returns list of successful variant URLs. Raises if all fail.
    """
    product_id = product["id"]
    start = time.time()

    variant_count = 1 if settings.TEST_MODE else 4
    logger.info(f"Pipeline started ({'TEST — 1 variant' if settings.TEST_MODE else '4-variant mode'})", extra={"product_id": product_id})

    # Step 1: Download raw image
    logger.info("Step 1/4 — downloading raw image", extra={"product_id": product_id})
    image_bytes = resolve_product_image(product)

    # Step 2: Background removal
    logger.info("Step 2/4 — removing background (Reve)", extra={"product_id": product_id})
    reve_output = await reve_client.remove_background(image_bytes)

    # Step 3: Upload Reve result
    logger.info("Step 3/4 — uploading Reve output", extra={"product_id": product_id})
    reve_url = await asyncio.to_thread(
        upload_file_to_storage,
        reve_output,
        settings.PROCESSED_BUCKET_NAME,
        f"products/temp/reve_{product_id}.png",
    )

    # Step 4 & 5: Generate + upload 4 variants
    logger.info("Step 4/4 — generating 4 variants", extra={"product_id": product_id})
    # Build prompts with product-specific data so the AI knows exactly what
    # jewellery item it is placing — improves accuracy and reduces design drift.
    title = product.get("title", "")
    jewellery_type = product.get("jewellery_type", "")
    prompts = build_variant_prompts(title, jewellery_type)
    logger.info(
        f"Prompts built for '{title}' ({jewellery_type})",
        extra={"product_id": product_id},
    )

    # In TEST_MODE only 1 variant is generated to avoid burning API credits.
    # Flip TEST_MODE=false in .env when ready to go full 4-variant.
    active_prompts = prompts[:variant_count]
    results = await asyncio.gather(
        *[_generate_variant(reve_url, product_id, i + 1, p) for i, p in enumerate(active_prompts)]
    )

    # Filter out any None values from variants that failed.
    # A partial success (e.g. 3/4) is still useful for the frontend.
    successful_urls = [url for url in results if url is not None]

    if not successful_urls:
        raise RuntimeError(f"All {variant_count} variant(s) failed for product {product_id}")

    logger.info(f"{len(successful_urls)}/{variant_count} variants generated", extra={"product_id": product_id})

    # Step 6: Persist to database
    await update_product_generated_images(product_id, successful_urls, update_image_url=True)

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(f"Pipeline complete in {elapsed_ms}ms", extra={"product_id": product_id})

    return successful_urls


async def process_job(job: dict) -> None:
    """Worker-facing pipeline wrapper for job queue processing."""
    job_id = job["id"]
    raw_url = job.get("raw_url")
    start = time.time()

    logger.info("Worker job started", extra={"job_id": job_id})

    try:
        logger.info("Step 1/4 — downloading image", extra={"job_id": job_id})
        image_bytes = await download_image(raw_url)

        logger.info("Step 2/4 — removing background (Reve)", extra={"job_id": job_id})
        reve_output = await reve_client.remove_background(image_bytes)

        reve_url = upload_file_to_storage(
            reve_output, settings.PROCESSED_BUCKET_NAME, f"products/temp/reve_{job_id}.png"
        )

        logger.info("Step 3/4 — enhancing image (Nanobana)", extra={"job_id": job_id})
        final_image = await nanobana_client.enhance_image(reve_url)

        logger.info("Step 4/4 — uploading processed image", extra={"job_id": job_id})
        processed_url = upload_processed_image(final_image, job_id)

        elapsed_ms = int((time.time() - start) * 1000)
        await update_job_status(job_id, status="done", processed_url=processed_url, processing_time_ms=elapsed_ms)
        logger.info(f"Worker job complete in {elapsed_ms}ms", extra={"job_id": job_id})

    except Exception as exc:
        logger.error(f"Worker job failed: {exc}", extra={"job_id": job_id})
        await update_job_status(job_id, status="error", error_message=str(exc))
