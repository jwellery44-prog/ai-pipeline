from contextlib import asynccontextmanager
import asyncio

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import create_product, fetch_job_by_id, update_product_image_url
from logging_config import logger
from pipeline import process_product_image
from storage import upload_raw_image
from worker import worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(worker_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("Worker stopped.")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ai-pipeline-frontend.vercel.app",
        # "https://yourdomain.com",  # add production origin(s) here
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ensure_cors_headers(request, call_next):
    """Ensure the Access-Control-Allow-Origin header is present on all responses.

    This is a safety-net to ensure browsers don't block error responses when
    the CORS middleware might not attach headers (for example during
    unexpected exceptions). It complements the standard CORSMiddleware.
    """
    try:
        response = await call_next(request)
    except Exception as exc:
        # Return a minimal JSON 500 response so the browser gets a body.
        from fastapi.responses import JSONResponse

        response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)

    # If the header isn't already set by CORSMiddleware, set it to the
    # allowed frontend origin so the browser can read the response.
    if "Access-Control-Allow-Origin" not in response.headers:
        response.headers["Access-Control-Allow-Origin"] = "https://ai-pipeline-frontend.vercel.app"
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# ---------------------------------------------------------------------------
# POST /process  — upload an image and run the full pipeline immediately
# ---------------------------------------------------------------------------

@app.post("/process", status_code=202)
async def process_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Raw jewellery image (JPEG / PNG / WebP, max 10 MB)"),
    title: str = "Untitled",
    jewellery_type: str = "",
):
    """
    Upload an image and kick off the AI pipeline in one step.

    Steps
    -----
    1. Validate + read the uploaded file.
    2. Create a new product row (auto-generated UUID).
    3. Store the raw image at ``plant-images/products/{id}.jpg``.
    4. Run Reve → Nanobana → upload processed PNG in the background.
    5. Write the processed URL back to ``products.image_url``.

    Returns immediately with the new ``product_id`` and ``raw_image_url``.
    Poll ``GET /product/{product_id}`` (or check Supabase) for the result.
    """
    # ── Validate file ───────────────────────────────────────────────────
    content_type = (file.content_type or "image/jpeg").split(";")[0].strip()
    if content_type not in settings.ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{content_type}'. "
                   f"Allowed: {settings.ALLOWED_MIME_TYPES}",
        )

    raw_bytes = await file.read()
    if len(raw_bytes) > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(raw_bytes):,} bytes). "
                   f"Max: {settings.MAX_FILE_SIZE_BYTES:,} bytes.",
        )

    # ── Create product row ─────────────────────────────────────────────
    product = await create_product(title=title, jewellery_type=jewellery_type)
    product_id: str = product["id"]

    # ── Upload raw image to storage ─────────────────────────────────
    raw_url = upload_raw_image(raw_bytes, product_id, content_type)
    await update_product_image_url(product_id, raw_url)
    product = {**product, "image_url": raw_url}

    logger.info(
        "New product created and raw image uploaded",
        extra={"product_id": product_id, "raw_url": raw_url},
    )

    # ── Queue AI pipeline ───────────────────────────────────────────
    background_tasks.add_task(_run_product_pipeline, product)

    return {
        "message": "Uploaded. Processing started in background.",
        "product_id": product_id,
        "raw_image_url": raw_url,
    }


# ---------------------------------------------------------------------------
# POST /process/{image_id}  — process an existing product (optionally re-upload)
# ---------------------------------------------------------------------------

@app.post("/process/{image_id}")
async def process_image(
    image_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(default=None),
):
    """
    Trigger AI processing for an existing product by its UUID.

    Optionally attach a ``file`` to replace the stored raw image first.
    If no file is sent, ``products.image_url`` must already be set.
    """
    product = await fetch_job_by_id(image_id)
    if not product:
        raise HTTPException(
            status_code=404,
            detail=f"Product '{image_id}' not found in table '{settings.DB_TABLE_NAME}'.",
        )

    if file is not None:
        content_type = (file.content_type or "image/jpeg").split(";")[0].strip()
        if content_type not in settings.ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{content_type}'. "
                       f"Allowed: {settings.ALLOWED_MIME_TYPES}",
            )
        raw_bytes = await file.read()
        if len(raw_bytes) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large ({len(raw_bytes):,} bytes). "
                       f"Max: {settings.MAX_FILE_SIZE_BYTES:,} bytes.",
            )
        raw_url = upload_raw_image(raw_bytes, image_id, content_type)
        await update_product_image_url(image_id, raw_url)
        product = {**product, "image_url": raw_url}

    elif not product.get("image_url"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Product '{image_id}' has no image. "
                "Attach a 'file' field or use POST /process to upload a new one."
            ),
        )

    background_tasks.add_task(_run_product_pipeline, product)
    logger.info("Processing queued", extra={"product_id": image_id})
    return {
        "message": "Processing queued.",
        "product_id": image_id,
        "title": product.get("title"),
        "raw_image_url": product.get("image_url"),
    }


# ---------------------------------------------------------------------------
# GET /product/{product_id}  — check result
# ---------------------------------------------------------------------------

@app.get("/product/{product_id}")
async def get_product(product_id: str):
    """Fetch the current state of a product including its processed image URL."""
    product = await fetch_job_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found.")
    return product


# ---------------------------------------------------------------------------
# Shared background task helper
# ---------------------------------------------------------------------------

async def _run_product_pipeline(product: dict) -> None:
    product_id = product["id"]
    try:
        processed_url = await process_product_image(product)
        logger.info(
            "Product pipeline finished",
            extra={"product_id": product_id, "processed_url": processed_url},
        )
    except Exception as exc:
        logger.error(
            "Product pipeline failed",
            extra={"product_id": product_id},
            exc_info=exc,
        )
    """
    Trigger AI processing for a product.

    Two modes
    ---------
    **With file upload** (multipart/form-data):
      Send the raw image as a ``file`` field. It is stored in
      ``plant-images/products/{image_id}.jpg`` and ``products.image_url``
      is updated before the AI pipeline runs.

    **Without file** (plain POST):
      ``products.image_url`` must already point to a file in Supabase Storage.

    Pipeline (both modes)
    ---------------------
    Reve (bg removal) → Nanobana (enhancement) → upload to
    ``plant-images/products/processed/{image_id}.png`` → update image_url.

    Returns 202 immediately; processing runs in the background.
    """
    # ── Validate product exists ───────────────────────────────────────────
    product = await fetch_job_by_id(image_id)
    if not product:
        raise HTTPException(
            status_code=404,
            detail=f"Product '{image_id}' not found in table '{settings.DB_TABLE_NAME}'.",
        )

    # ── Optional file upload — store raw image in Supabase Storage ────────
    if file is not None:
        content_type = (file.content_type or "image/jpeg").split(";")[0].strip()
        if content_type not in settings.ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type '{content_type}'. "
                       f"Allowed: {settings.ALLOWED_MIME_TYPES}",
            )

        raw_bytes = await file.read()
        if len(raw_bytes) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large ({len(raw_bytes):,} bytes). "
                       f"Max: {settings.MAX_FILE_SIZE_BYTES:,} bytes.",
            )

        raw_url = upload_raw_image(raw_bytes, image_id, content_type)
        await update_product_image_url(image_id, raw_url)
        product = {**product, "image_url": raw_url}
        logger.info("Raw image uploaded", extra={"product_id": image_id, "raw_url": raw_url})

    elif not product.get("image_url"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Product '{image_id}' has no image set. "
                "Upload one by adding a 'file' field to this request, e.g.:\n\n"
                "  curl -X POST http://localhost:8000/process/<id> "
                "-F 'file=@/path/to/image.jpg'"
            ),
        )

    # ── Queue pipeline ────────────────────────────────────────────────────
    background_tasks.add_task(_run_product_pipeline, product)
    logger.info("Processing queued", extra={"product_id": image_id})
    return {
        "message": "Processing queued.",
        "product_id": image_id,
        "title": product.get("title"),
        "raw_image_url": product.get("image_url"),
    }


async def _run_product_pipeline(product: dict) -> None:
    """Background task wrapper — logs errors so they surface in the app logs."""
    product_id = product["id"]
    try:
        processed_url = await process_product_image(product)
        logger.info(
            "Product pipeline finished",
            extra={"product_id": product_id, "processed_url": processed_url},
        )
    except Exception as exc:
        logger.error(
            "Product pipeline failed",
            extra={"product_id": product_id},
            exc_info=exc,
        )

