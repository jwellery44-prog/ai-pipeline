from __future__ import annotations

import asyncio
import time
from typing import Optional

from ai_clients import nanobana_client, reve_client
from config import settings
from database import update_job_status, update_product_generated_images
from logging_config import logger
from storage import (
    resolve_product_image,
    upload_file_to_storage,
    upload_processed_image,
    upload_processed_image_variant,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _generate_variant(
    reve_url: str,
    product_id: str,
    variant_index: int,
    prompt: str,
) -> Optional[str]:
    """
    Run a single Nanobana generation + Supabase upload for one variant.

    This coroutine is designed to be gathered concurrently with the other
    three variants.  Any exception is caught, logged, and converted to
    ``None`` so one slow or failing variant never cancels the others.

    Parameters
    ----------
    reve_url : str
        Public URL of the Reve background-removed image.
    product_id : str
        UUID of the parent product row (used for storage path and logging).
    variant_index : int
        1-based index (1–4).  Drives the storage path and log messages.
    prompt : str
        The Nanobana generation prompt specific to this variant.

    Returns
    -------
    str | None
        Public Supabase Storage URL of the uploaded variant, or *None* on
        failure (so callers can filter without crashing).
    """
    try:
        logger.info(
            f"Variant {variant_index}/4 — starting Nanobana generation",
            extra={"product_id": product_id, "variant": variant_index},
        )

        # ── Nanobana generation (network-bound async) ────────────────────
        image_bytes: bytes = await nanobana_client.enhance_image(
            reve_url, prompt=prompt
        )

        # ── Upload to Supabase Storage (sync SDK → run in thread) ────────
        public_url: str = await asyncio.to_thread(
            upload_processed_image_variant,
            image_bytes,
            product_id,
            variant_index,
        )

        logger.info(
            f"Variant {variant_index}/4 — uploaded successfully: {public_url}",
            extra={"product_id": product_id, "variant": variant_index},
        )
        return public_url

    except Exception as exc:
        # Isolated failure — log full traceback and return None, do NOT re-raise.
        logger.error(
            f"Variant {variant_index}/4 FAILED for product {product_id}: {exc}",
            extra={"product_id": product_id, "variant": variant_index},
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Product pipeline  (used by the /process and /process/{id} API endpoints)
# ---------------------------------------------------------------------------

async def process_product_image(product: dict) -> list[str]:
    """
    Full AI pipeline for a single product — produces 4 concurrent variants.

    Steps
    -----
    1. Download the raw image from Supabase Storage.
    2. Reve — background removal (single call, result shared by all variants).
    3. Upload Reve output to a temporary Storage path so Nanobana can reach it.
    4. Concurrently generate 4 scene-enhanced variants via Nanobana
       (each uses a distinct prompt: stone / velvet / marble / charcoal).
    5. Upload each variant to ``products/processed/{id}_v{n}.png``
       (steps 4 & 5 are interleaved per-variant inside ``_generate_variant``).
    6. Persist the ordered list of public URLs to ``products.generated_image_urls``;
       also write the first successful URL to ``products.image_url`` for
       backward-compatibility with callers that only read that column.

    Returns
    -------
    list[str]
        Non-empty list of public URLs for every successfully generated
        variant (1–4 items).  Raises RuntimeError if ALL variants fail.
    """
    product_id: str = product["id"]
    start = time.time()

    logger.info("Pipeline started (4-variant mode)", extra={"product_id": product_id})

    # ── Step 1: Download raw image ───────────────────────────────────────
    logger.info("Step 1/4 — downloading raw image from storage", extra={"product_id": product_id})
    image_bytes = resolve_product_image(product)

    # ── Step 2: Background removal (Reve) ────────────────────────────────
    logger.info("Step 2/4 — removing background (Reve)", extra={"product_id": product_id})
    reve_output: bytes = await reve_client.remove_background(image_bytes)

    # ── Step 3: Upload Reve result to temp path (Nanobana needs a URL) ───
    logger.info(
        "Step 3/4 — uploading Reve output to temporary storage path",
        extra={"product_id": product_id},
    )
    reve_url: str = await asyncio.to_thread(
        upload_file_to_storage,
        reve_output,
        settings.PROCESSED_BUCKET_NAME,
        f"products/temp/reve_{product_id}.png",
    )

    # ── Step 4 & 5: Generate + upload 4 variants concurrently ────────────
    logger.info(
        "Step 4/4 — generating 4 variants concurrently via Nanobana",
        extra={"product_id": product_id},
    )
    prompts: list[str] = settings.NANOBANA_VARIANT_PROMPTS

    variant_results: list[Optional[str]] = await asyncio.gather(
        _generate_variant(reve_url, product_id, 1, prompts[0]),
        _generate_variant(reve_url, product_id, 2, prompts[1]),
        _generate_variant(reve_url, product_id, 3, prompts[2]),
        _generate_variant(reve_url, product_id, 4, prompts[3]),
        return_exceptions=False,  # exceptions are already absorbed inside _generate_variant
    )

    # Filter out any variants that returned None (individual failures)
    successful_urls: list[str] = [url for url in variant_results if url is not None]

    if not successful_urls:
        raise RuntimeError(
            f"All 4 Nanobana variants failed for product {product_id}. "
            "Check logs above for per-variant error details."
        )

    logger.info(
        f"{len(successful_urls)}/4 variants generated successfully",
        extra={"product_id": product_id, "urls": successful_urls},
    )

    # ── Step 6: Persist results to Supabase ──────────────────────────────
    # generated_image_urls ← full ordered list (None slots already removed)
    # image_url            ← first successful variant (backwards-compat)
    logger.info(
        f"Writing {len(successful_urls)} variant URL(s) to Supabase for product {product_id}",
        extra={"product_id": product_id},
    )
    await update_product_generated_images(
        product_id,
        successful_urls,
        update_image_url=True,
    )
    logger.info(
        f"Supabase DB write complete for product {product_id}",
        extra={"product_id": product_id},
    )

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(
        f"Pipeline complete in {elapsed_ms}ms — {len(successful_urls)} variant(s) stored",
        extra={"product_id": product_id},
    )
    return successful_urls


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
