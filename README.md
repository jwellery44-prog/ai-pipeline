# AI Jewellery Image Pipeline

A FastAPI backend that takes a raw jewellery photo, removes the background via **Reve AI**, then concurrently generates **4 professionally styled variants** via **Nanobana AI** and stores every result in **Supabase Storage**.

---

## Architecture

```
Upload Image
     │
     ▼
POST /process
     │
     ├── 1. Validate file (MIME, size)
     ├── 2. Create product row in Supabase DB
     ├── 3. Upload raw image → plant-images/products/{id}.jpg
     └── 4. Queue background pipeline
                  │
                  ▼
         ┌─────────────────────────────────────────────┐
         │           BACKGROUND PIPELINE               │
         │                                             │
         │  Step 1 — Download raw image from storage   │
         │  Step 2 — Reve AI: remove background        │
         │  Step 3 — Upload bg-removed to temp path    │
         │                                             │
         │  Step 4 — asyncio.gather (true concurrency) │
         │   ├── Variant 1: Stone backdrop             │
         │   ├── Variant 2: Velvet backdrop            │
         │   ├── Variant 3: Marble backdrop            │
         │   └── Variant 4: Charcoal backdrop          │
         │       (each: Nanobana generate → upload)    │
         │                                             │
         │  Step 5 — Write URLs to Supabase:           │
         │   • generated_image_urls (JSONB array)      │
         │   • image_url (first variant, compat)       │
         └─────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Server | FastAPI + Uvicorn |
| Background Removal | Reve AI (`api.reve.com`) |
| Image Generation | Nanobana AI (`api.nanobananaapi.ai`) |
| Database | Supabase (PostgreSQL) |
| File Storage | Supabase Storage |
| Config | Pydantic Settings + `.env` |
| HTTP Client | httpx (async) |

---

## Prerequisites

- Python 3.11+
- A Supabase project
- Reve AI API key
- Nanobana AI API key

---

## Setup

### 1. Clone & create virtual environment

```bash
git clone <repo-url>
cd ai-pipeline
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```dotenv
# Supabase
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>

# Database
DB_TABLE_NAME=products

# Storage
RAW_BUCKET_NAME=plant-images
RAW_STORAGE_FOLDER=products
PROCESSED_BUCKET_NAME=plant-images
PROCESSED_STORAGE_FOLDER=products/processed

# Reve AI
REVE_API_KEY=<your-reve-key>
REVE_PROMPT="Remove the background completely..."

# Nanobana AI
NANOBANA_API_KEY=<your-nanobana-key>
NANOBANA_PROMPT=""   # unused when 4-variant mode is active

# Optional: override any individual variant prompt
# NANOBANA_VARIANT_PROMPT_1="..."
# NANOBANA_VARIANT_PROMPT_2="..."
# NANOBANA_VARIANT_PROMPT_3="..."
# NANOBANA_VARIANT_PROMPT_4="..."

# App
ENVIRONMENT=development
LOG_LEVEL=INFO
MAX_RETRIES=3
PROCESSING_TIMEOUT_SECONDS=300
```

### 4. Run the Supabase migration

In the **Supabase Dashboard → SQL Editor**, run:

```sql
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS generated_image_urls jsonb NOT NULL DEFAULT '[]'::jsonb;
```

This adds the JSONB array column that stores all 4 generated image URLs. Existing rows default to `[]`.

### 5. Start the server

```bash
uvicorn main:app --reload --port 8000
```

---

## API Reference

### `POST /process`

Upload a raw jewellery image and start the full pipeline.

**Request** — `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File | Yes | JPEG / PNG / WebP, max 10 MB |
| `title` | string | No | Product name (default: `"Untitled"`) |
| `jewellery_type` | string | No | e.g. `"ring"`, `"necklace"` |

**Response** — `202 Accepted`

```json
{
  "message": "Uploaded. Processing started in background.",
  "product_id": "550e8400-e29b-41d4-a716-446655440000",
  "raw_image_url": "https://…/plant-images/products/550e8400….jpg"
}
```

Returns immediately. Processing runs in the background.

---

### `GET /product/{product_id}`

Poll this endpoint to check processing status and retrieve results.

**Response — while processing** (`generated_image_urls` is empty):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Gold Ring",
  "jewellery_type": "ring",
  "image_url": "https://…/products/550e8400….jpg",
  "generated_image_urls": [],
  "created_at": "2026-02-24T10:00:00Z",
  "updated_at": "2026-02-24T10:00:01Z"
}
```

**Response — processing complete** (`generated_image_urls` has items):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Gold Ring",
  "jewellery_type": "ring",
  "image_url": "https://…/products/processed/550e8400…_v1.png",
  "generated_image_urls": [
    "https://…/products/processed/550e8400…_v1.png",
    "https://…/products/processed/550e8400…_v2.png",
    "https://…/products/processed/550e8400…_v3.png",
    "https://…/products/processed/550e8400…_v4.png"
  ],
  "created_at": "2026-02-24T10:00:00Z",
  "updated_at": "2026-02-24T10:02:30Z"
}
```

**Polling logic:** keep polling until `generated_image_urls.length > 0`.  
**Recommended interval:** every 5 seconds.

---

### `POST /process/{image_id}`

Re-trigger the pipeline for an existing product (optionally re-upload the image).

**Request** — `multipart/form-data` (file is optional)

**Response** — `202 Accepted`, same shape as `POST /process`.

---

### `GET /health`

```json
{ "status": "ok", "environment": "development" }
```

---

## Storage Layout

All files live in the `plant-images` Supabase Storage bucket:

```
plant-images/
├── products/
│   ├── {product_id}.jpg          ← raw upload
│   ├── temp/
│   │   └── reve_{product_id}.png ← Reve bg-removed (intermediate, reusable)
│   └── processed/
│       ├── {product_id}_v1.png   ← Variant 1: Stone (classic)
│       ├── {product_id}_v2.png   ← Variant 2: Velvet (boutique)
│       ├── {product_id}_v3.png   ← Variant 3: Marble (editorial)
│       └── {product_id}_v4.png   ← Variant 4: Charcoal (dramatic)
```

---

## The 4 Image Variants

Each variant uses a distinct professionally crafted prompt. All prompts strictly preserve the jewellery's original design, colour, and proportions.

| # | Scene | Backdrop | Angle | Lighting |
|---|---|---|---|---|
| 1 | **Stone — Classic** | Dark navy-blue sculpted stone | Front-facing, centred | Soft directional, upper-left |
| 2 | **Velvet — Boutique** | Burgundy-red velvet cushion | 45° front-left | Warm golden, upper-right, bokeh |
| 3 | **Marble — Editorial** | White Carrara marble | Overhead, 30° above horizontal | Bright diffused natural daylight |
| 4 | **Charcoal — Dramatic** | Deep charcoal-black gradient | Side-profile, ~60° rotation | Hard spotlight from above, amber rim |

To override any prompt, set the corresponding env var:

```dotenv
NANOBANA_VARIANT_PROMPT_1="Your custom prompt here..."
```

---

## Database Schema

### `products` table

| Column | Type | Description |
|---|---|---|
| `id` | `uuid` | Primary key, auto-generated |
| `title` | `text` | Product name |
| `jewellery_type` | `text` | Type of jewellery |
| `image_url` | `text` | First successful variant URL (backwards-compat) |
| `generated_image_urls` | `jsonb` | Array of up to 4 variant URLs — **added by migration** |
| `created_at` | `timestamptz` | Row creation time |
| `updated_at` | `timestamptz` | Last update time |

---

## Project Structure

```
ai-pipeline/
├── main.py              # FastAPI app, routes, CORS, lifespan
├── pipeline.py          # Core pipeline logic (4-variant concurrent generation)
├── ai_clients.py        # Reve & Nanobana API clients with retry logic
├── database.py          # Supabase DB helpers (create, fetch, update)
├── storage.py           # Supabase Storage helpers (upload, download)
├── config.py            # Pydantic settings + 4 variant prompts
├── worker.py            # Background worker loop
├── logging_config.py    # Structured JSON logging setup
├── requirements.txt     # Pinned dependencies
├── Dockerfile           # Container definition
├── .env                 # Local secrets (never commit)
└── migrations/
    └── add_generated_image_urls.sql   # Run once in Supabase SQL editor
```

---

## Frontend Integration

### Supabase JS type

```typescript
interface Product {
  id: string;
  title: string;
  jewellery_type: string | null;
  image_url: string | null;               // first variant — backwards-compat
  generated_image_urls: string[];         // [] while processing, up to 4 when done
  created_at: string;
  updated_at: string | null;
}
```

### Check if done

```typescript
const isDone = (p: Product) =>
  Array.isArray(p.generated_image_urls) && p.generated_image_urls.length > 0;
```

### Variant labels

```typescript
const VARIANT_LABELS = ['Stone — Classic', 'Velvet — Boutique', 'Marble — Editorial', 'Charcoal — Dramatic'];
```

### Realtime subscription

```typescript
supabase
  .channel('product-updates')
  .on('postgres_changes', {
    event: 'UPDATE',
    schema: 'public',
    table: 'products',
    filter: `id=eq.${productId}`,
  }, (payload) => {
    const updated = payload.new as Product;
    if (updated.generated_image_urls?.length > 0) {
      setVariants(updated.generated_image_urls);
    }
  })
  .subscribe();
```

---

## Docker

```bash
docker build -t ai-pipeline .
docker run -p 8000:8000 --env-file .env ai-pipeline
```

---

## Error Handling

- **One variant fails** — the other 3 continue. Failed variants are excluded from `generated_image_urls`. The pipeline only fails hard if **all 4** variants fail.
- **Reve fails** — entire pipeline fails, product row is not updated.
- **DB write fails** — logged, images are already in storage; reprocessing via `POST /process/{id}` will regenerate and re-persist.
- **Stale jobs** — the worker resets jobs stuck in `processing` beyond `PROCESSING_TIMEOUT_SECONDS` back to `pending` for automatic retry.
