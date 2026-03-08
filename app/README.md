# AI Pipeline — Codebase Guide

## Directory Structure

```
app/
├── main.py              # FastAPI app — routes, startup/shutdown
├── config.py            # All settings (env vars + defaults)
├── logging.py           # JSON structured logging setup
├── worker.py            # Background worker loop
├── db/
│   └── repository.py    # All Supabase database operations
└── services/
    ├── ai.py            # Reve and Nanobana API clients
    ├── pipeline.py      # Core pipeline orchestration
    └── storage.py       # Supabase Storage upload/download
```

---

## File-by-File Breakdown

### `main.py` — API Entry Point

The FastAPI application. Defines three HTTP endpoints:

| Endpoint | What it does |
|---|---|
| `GET /health` | Returns `{ status: ok }` — used by uptime monitors / load balancers |
| `POST /process` | Accepts a new image upload + `title` + `jewellery_type`, creates a DB row, uploads the raw image, then queues the AI pipeline in the background. Returns `product_id` immediately. |
| `POST /process/{image_id}` | Re-processes an existing product by ID. Optionally accepts a new image to replace the stored one. |
| `GET /product/{product_id}` | Fetch the current state of a product — includes `generated_image_urls` once processing is done. |

Also handles CORS (so the frontend at `jwellery.arpitray.in` can call these endpoints) and a safety-net middleware that ensures CORS headers are attached even on unexpected 500 errors.

On startup it spawns `worker_loop` as a background asyncio task. On shutdown it cancels it cleanly.

---

### `config.py` — Settings

Single `Settings` class powered by **pydantic-settings**. All values come from the `.env` file (or environment variables in production).

Key groups:
- **Supabase**: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- **AI keys**: `REVE_API_KEY`, `NANOBANA_API_KEY`
- **Prompts**: `NANOBANA_VARIANT_PROMPT_1` through `_4` — the text instructions sent to Nanobana for each of the 4 image variants. Can be overridden per-deployment via env vars.
- **Limits**: `MAX_FILE_SIZE_BYTES` (10 MB), `ALLOWED_MIME_TYPES`, timeouts, retry counts
- **Storage paths**: which Supabase bucket and folder raw/processed images live in

A single `settings` singleton is created at import time and shared across the entire app.

---

### `logging.py` — Structured Logging

Sets up a JSON formatter so every log line is a structured JSON object:

```json
{
  "timestamp": "2026-03-08T10:29:15.890633",
  "level": "INFO",
  "message": "Pipeline started",
  "module": "pipeline",
  "function": "process_product_image"
}
```

This makes it easy to query logs in production (Supabase logs, Datadog, etc.). Noisy `httpx` request-level logs are suppressed to `WARNING`.

---

### `worker.py` — Background Worker

A long-running asyncio coroutine started when the app boots. 

Currently in **API-driven mode** — meaning jobs are triggered directly via `POST /process` rather than being polled from a queue. The loop just `sleep`s forever so the FastAPI lifespan manager can cancel it cleanly on shutdown.

It contains scaffolding for a future **queue-polling mode** (semaphore, stale-job reset, concurrency backoff) if you switch to a dedicated jobs table with a `status` column.

---

### `db/repository.py` — Database Layer

All Supabase PostgREST interactions. Nothing outside this file touches the database directly.

| Function | What it does |
|---|---|
| `get_supabase()` | Returns the singleton Supabase client, creating it lazily on first use |
| `create_product()` | Inserts a new row into the products table, returns it |
| `fetch_job_by_id()` | Fetch a single row by UUID |
| `fetch_pending_job()` | Atomically claim the oldest `pending` job (optimistic lock — safe under concurrent workers) |
| `reset_stale_jobs()` | Find jobs stuck in `processing` beyond the timeout, reset them to `pending` |
| `update_job_status()` | Write a status transition (`pending` → `processing` → `done` / `error`) |
| `update_product_image_url()` | Write the raw or processed image URL to the product row |
| `update_product_generated_images()` | Write the list of 4 variant URLs to `generated_image_urls` (JSONB column) |

---

### `services/ai.py` — AI API Clients

Two clients, one per external AI service:

#### `ReveClient` — Background Removal
Sends the raw jewellery image (as base64 JSON) to the Reve API. Reve removes the background and returns a clean PNG. Used in Step 2 of the pipeline.

#### `NanobanaClient` — Scene Enhancement
Takes a URL of the background-removed image and a scene prompt, submits a generation task to Nanobana, then **polls** for completion (up to 5 minutes, checking every 5 seconds). Once done, downloads and returns the final image bytes. Used (×4 concurrently) in Step 4 of the pipeline.

Both clients share `_request_with_retry` — a helper that automatically retries on `429 Too Many Requests` or `5xx` server errors with exponential back-off.

Module-level singletons `reve_client` and `nanobana_client` are imported by `pipeline.py`.

---

### `services/pipeline.py` — Pipeline Orchestration

The core of the system. Two functions:

#### `process_product_image(product)` — used by API endpoints
Runs the full 4-variant AI pipeline for a product:

```
Step 1  Download raw image from Supabase Storage
   ↓
Step 2  Send to Reve → get background-removed PNG
   ↓
Step 3  Upload Reve result to a temp Storage path
        (Nanobana needs a public URL, not raw bytes)
   ↓
Step 4  Launch 4 Nanobana calls concurrently (asyncio.gather)
        Each uses a different scene prompt:
          Variant 1 — dark navy stone surface
          Variant 2 — burgundy velvet cushion
          Variant 3 — white Carrara marble
          Variant 4 — charcoal-black gradient
   ↓
Step 5  Each variant is uploaded to Storage as it completes
   ↓
Step 6  All 4 URLs written to products.generated_image_urls in DB
        First URL also written to products.image_url (backwards compat)
```

Any single variant failing does **not** abort the others — it returns `None` and is filtered out. The pipeline only raises if **all 4** fail.

#### `process_job(job)` — used by worker (queue mode)
Simpler single-output version: download → Reve → Nanobana (one call) → upload → write status. Used if you enable the job-queue worker.

---

### `services/storage.py` — Storage Layer

All Supabase Storage interactions. Nothing outside this file touches storage directly.

| Function | What it does |
|---|---|
| `upload_raw_image()` | Upload the original image before any processing (`products/{id}.jpg`) |
| `upload_processed_image()` | Upload single processed result (`products/processed/{id}.png`) |
| `upload_processed_image_variant()` | Upload one of the 4 variants (`products/processed/{id}_v{n}.png`) |
| `upload_file_to_storage()` | Generic upload to any bucket/path — used for the Reve temp file |
| `download_from_storage()` | Download by bucket + path (works for private buckets too) |
| `download_image()` | Download from any public HTTP/HTTPS URL with MIME + size validation |
| `resolve_product_image()` | Given a product dict, figure out where its raw image is and download it |

---

## End-to-End Request Flow

```
Client → POST /process  (uploads image file)
           │
           ▼
        main.py validates file, creates DB row, uploads raw image
           │
           ▼ (background task)
        pipeline.py: process_product_image()
           │
           ├─ storage.py: download raw image
           ├─ ai.py ReveClient: remove background
           ├─ storage.py: upload Reve temp file
           │
           ├─ ai.py NanobanaClient ×4 (concurrent)
           │     variant 1 → upload → URL
           │     variant 2 → upload → URL
           │     variant 3 → upload → URL
           │     variant 4 → upload → URL
           │
           └─ db/repository.py: write 4 URLs to products table
           
Client → GET /product/{id}   ← poll here for generated_image_urls
```

---

## How to Run

From the repo root:

```powershell
# Development (auto-reload on file changes)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Production
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

> Use `--workers 1` — the pipeline uses module-level singletons (Supabase client, httpx) that are not fork-safe. For horizontal scaling, deploy multiple containers instead of multiple workers per container.
