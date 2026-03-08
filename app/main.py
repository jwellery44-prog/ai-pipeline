import asyncio
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.repository import create_product, fetch_job_by_id, update_product_image_url
from app.logging import logger
from app.services.pipeline import process_product_image
from app.services.storage import upload_raw_image
from app.worker import worker_loop


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
        "https://jwellery.arpitray.in",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ensure_cors_headers(request, call_next):
    """Ensure CORS headers are present on all responses including errors."""
    try:
        response = await call_next(request)
    except Exception:
        response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)

    if "Access-Control-Allow-Origin" not in response.headers:
        response.headers["Access-Control-Allow-Origin"] = "https://ai-pipeline-frontend.vercel.app"
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


@app.post("/process", status_code=202)
async def process_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Raw jewellery image (JPEG/PNG/WebP, max 10MB)"),
    title: str = "Untitled",
    jewellery_type: str = "",
):
    """Upload an image and start the AI pipeline."""
    content_type = (file.content_type or "image/jpeg").split(";")[0].strip()
    if content_type not in settings.ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{content_type}'")

    raw_bytes = await file.read()
    if len(raw_bytes) > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large ({len(raw_bytes):,} bytes)")

    product = await create_product(title=title, jewellery_type=jewellery_type)
    product_id = product["id"]

    raw_url = upload_raw_image(raw_bytes, product_id, content_type)
    await update_product_image_url(product_id, raw_url)
    product = {**product, "image_url": raw_url}

    logger.info("Product created", extra={"product_id": product_id, "raw_url": raw_url})

    background_tasks.add_task(_run_product_pipeline, product)

    return {
        "message": "Uploaded. Processing started in background.",
        "product_id": product_id,
        "raw_image_url": raw_url,
    }


@app.post("/process/{image_id}")
async def process_image(
    image_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(default=None),
):
    """Trigger AI processing for an existing product."""
    product = await fetch_job_by_id(image_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{image_id}' not found")

    if file is not None:
        content_type = (file.content_type or "image/jpeg").split(";")[0].strip()
        if content_type not in settings.ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=415, detail=f"Unsupported file type '{content_type}'")

        raw_bytes = await file.read()
        if len(raw_bytes) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"File too large ({len(raw_bytes):,} bytes)")

        raw_url = upload_raw_image(raw_bytes, image_id, content_type)
        await update_product_image_url(image_id, raw_url)
        product = {**product, "image_url": raw_url}

    elif not product.get("image_url"):
        raise HTTPException(status_code=422, detail=f"Product '{image_id}' has no image")

    background_tasks.add_task(_run_product_pipeline, product)
    logger.info("Processing queued", extra={"product_id": image_id})

    return {
        "message": "Processing queued.",
        "product_id": image_id,
        "title": product.get("title"),
        "raw_image_url": product.get("image_url"),
    }


@app.get("/product/{product_id}")
async def get_product(product_id: str):
    """Fetch current state of a product."""
    product = await fetch_job_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    return product


async def _run_product_pipeline(product: dict) -> None:
    """Background task wrapper for the pipeline."""
    product_id = product["id"]
    try:
        generated_urls = await process_product_image(product)
        logger.info(f"Pipeline finished — {len(generated_urls)} variant(s)", extra={"product_id": product_id})
    except Exception as exc:
        logger.error("Product pipeline failed", extra={"product_id": product_id}, exc_info=exc)
