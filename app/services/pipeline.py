from __future__ import annotations

import asyncio
import io
import time
from typing import Optional

from PIL import Image

from app.config import build_variant_prompts, settings
from app.db.repository import update_job_status, update_product_generated_images
from app.logging import logger
from app.services.ai import nanobana_client, nanobana_client2, reve_client
from app.services.storage import (
    download_image,
    resolve_product_image,
    upload_file_to_storage,
    upload_processed_image,
    upload_processed_image_variant,
)


def adjust_aspect_ratio(image_bytes: bytes, target_ratio: str) -> bytes:
    """Pad the input image to a specific aspect ratio (e.g. '1:1' square)."""
    if not target_ratio or target_ratio == "none":
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))
        orig_format = img.format or "PNG"

        # Convert palette/grayscale images to RGBA to preserve transparency
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")

        width, height = img.size

        if target_ratio == "1:1":
            max_dim = max(width, height)
            # Create a transparent background for PNG/RGBA, or white for RGB
            bg_color = (255, 255, 255, 0) if img.mode == "RGBA" else (255, 255, 255)
            new_img = Image.new(img.mode, (max_dim, max_dim), bg_color)
            # Center the original image on the new canvas
            offset = ((max_dim - width) // 2, (max_dim - height) // 2)
            new_img.paste(img, offset)

            # If saving as JPEG, mode must be RGB (cannot be RGBA)
            save_format = orig_format
            if save_format.upper() in ("JPEG", "JPG") and new_img.mode == "RGBA":
                # Convert RGBA to RGB on a white background
                rgb_img = Image.new("RGB", new_img.size, (255, 255, 255))
                rgb_img.paste(new_img, mask=new_img.split()[3])  # paste using alpha channel as mask
                new_img = rgb_img
                save_format = "JPEG"

            out_bytes = io.BytesIO()
            new_img.save(out_bytes, format=save_format)
            return out_bytes.getvalue()

    except Exception as exc:
        logger.warning(f"Failed to adjust aspect ratio: {exc}")

    return image_bytes


async def _generate_variant(
    reve_url: str,
    product_id: str,
    variant_index: int,
    prompt: str,
) -> Optional[str]:
    """Run single Nanobana 2 (2K) generation + upload for one variant."""
    try:
        logger.info(f"Variant {variant_index} — starting (2K)", extra={"product_id": product_id})

        # Use Nanobana 2 (/generate-2) which natively outputs 2K images.
        image_bytes = await nanobana_client2.enhance_image(reve_url, prompt=prompt)

        # Upload runs in a thread because the Supabase storage SDK is synchronous.
        public_url = await asyncio.to_thread(
            upload_processed_image_variant, image_bytes, product_id, variant_index
        )

        logger.info(f"Variant {variant_index} — done (2K): {public_url}", extra={"product_id": product_id})
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

    variant_count = settings.IMAGE_GENERATION_COUNT
    logger.info(f"Pipeline started ({variant_count}-variant mode)", extra={"product_id": product_id})

    # Step 1: Download raw image
    logger.info("Step 1/4 — downloading raw image", extra={"product_id": product_id})
    image_bytes = resolve_product_image(product)

    # Adjust aspect ratio if configured
    if settings.TARGET_ASPECT_RATIO and settings.TARGET_ASPECT_RATIO != "none":
        image_bytes = adjust_aspect_ratio(image_bytes, settings.TARGET_ASPECT_RATIO)


    # Step 2: Background removal (conditional)
    reve_was_used = False
    if settings.REVE_REMOVE_BACKGROUND:
        logger.info("REVE_REMOVE_BACKGROUND=True → calling Reve background removal", extra={"product_id": product_id})
        reve_output = await reve_client.remove_background(image_bytes)
        reve_was_used = True
    else:
        logger.info("REVE_REMOVE_BACKGROUND=False → Reve bypassed, using original image", extra={"product_id": product_id})
        reve_output = image_bytes

    # Step 3: Upload image for Nanobana to consume via URL
    logger.info("Step 3/4 — uploading image to temp path", extra={"product_id": product_id})
    reve_url = await asyncio.to_thread(
        upload_file_to_storage,
        reve_output,
        settings.PROCESSED_BUCKET_NAME,
        f"products/temp/reve_{product_id}.png",
    )

    # Step 4 & 5: Generate + upload 4 variants at 2K resolution via Nanobana 2.
    logger.info("Step 4/4 — generating 4 variants (Nanobana 2, 2K)", extra={"product_id": product_id})
    # Build prompts with product-specific data so the AI knows exactly what
    # jewellery item it is placing — improves accuracy and reduces design drift.
    title = product.get("title", "")
    jewellery_type = product.get("jewellery_type", "")
    prompts = build_variant_prompts(title, jewellery_type)
    logger.info(
        f"Prompts built for '{title}' ({jewellery_type})",
        extra={"product_id": product_id},
    )

    # Generates IMAGE_GENERATION_COUNT variants to control API credit usage.
    # Change IMAGE_GENERATION_COUNT in .env to adjust the number of generated images.
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

    # Append Reve background-removed image as the last extra image
    # (only when Reve actually ran — no point appending the original again).
    if reve_was_used:
        try:
            reve_permanent_url = await asyncio.to_thread(
                upload_processed_image_variant, reve_output, product_id, variant_count + 1
            )
            successful_urls.append(reve_permanent_url)
            logger.info("Reve cutout appended as extra image", extra={"product_id": product_id})
        except Exception as exc:
            logger.warning(f"Failed to upload Reve cutout — skipping: {exc}", extra={"product_id": product_id})
    else:
        logger.info("Reve was bypassed — skipping cutout append", extra={"product_id": product_id})

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

        # Adjust aspect ratio if configured
        if settings.TARGET_ASPECT_RATIO and settings.TARGET_ASPECT_RATIO != "none":
            image_bytes = adjust_aspect_ratio(image_bytes, settings.TARGET_ASPECT_RATIO)


        if settings.REVE_REMOVE_BACKGROUND:
            logger.info("REVE_REMOVE_BACKGROUND=True → calling Reve background removal", extra={"job_id": job_id})
            reve_output = await reve_client.remove_background(image_bytes)
        else:
            logger.info("REVE_REMOVE_BACKGROUND=False → Reve bypassed, using original image", extra={"job_id": job_id})
            reve_output = image_bytes

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
