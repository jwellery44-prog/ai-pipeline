from pydantic_settings import BaseSettings

# Each string below is the exact prompt sent to Nanobana for one variant.
# They're intentionally verbose — the AI tends to drift from the original
# jewellery design if the instruction isn't specific enough.
VARIANT_PROMPTS = [
    (
        "STRICT IMAGE COMPOSITING TASK. "
        "Place the jewellery on a dark navy-blue sculpted stone surface. "
        "Classic front-facing display angle — jewellery perfectly centred. "
        "Soft directional studio lighting from the upper-left. "
        "Deep, moody, luxurious atmosphere. No background distractions. "
        "Preserve every detail, texture, reflection, and gemstone of the jewellery exactly. "
        "Do NOT modify the jewellery design, colour, or proportions. "
        "Professional luxury product photography."
    ),
    (
        "STRICT IMAGE COMPOSITING TASK. "
        "Place the jewellery on a deep burgundy-red velvet cushion surface. "
        "Present at a gentle 45-degree angle — front-left perspective. "
        "Warm golden studio lighting from the upper-right. "
        "Shallow depth of field; soft bokeh background haze. "
        "Luxury jewellery boutique aesthetic. "
        "Preserve every detail, texture, reflection, and gemstone of the jewellery exactly. "
        "Do NOT modify the jewellery design, colour, or proportions. "
        "Professional luxury product photography."
    ),
    (
        "STRICT IMAGE COMPOSITING TASK. "
        "Place the jewellery on a pristine white Carrara marble surface with subtle grey veining. "
        "Slight overhead / elevated perspective — camera angled 30 degrees above horizontal. "
        "Bright diffused natural daylight; clean, airy, editorial feel. "
        "Minimal composition — jewellery as the sole subject. "
        "High-fashion editorial campaign style. "
        "Preserve every detail, texture, reflection, and gemstone of the jewellery exactly. "
        "Do NOT modify the jewellery design, colour, or proportions. "
        "Professional luxury product photography."
    ),
    (
        "STRICT IMAGE COMPOSITING TASK. "
        "Place the jewellery floating and centred against a deep charcoal-black gradient background. "
        "Subtle warm amber and gold light accents rim the edges. "
        "Dramatic side-profile angle — jewellery rotated approximately 60 degrees. "
        "Single hard spotlight from directly above creating a defined shadow below. "
        "Premium luxury advertisement style — bold and dramatic. "
        "Preserve every detail, texture, reflection, and gemstone of the jewellery exactly. "
        "Do NOT modify the jewellery design, colour, or proportions. "
        "Professional luxury product photography."
    ),
]


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str  # service role bypasses RLS, keep this secret

    # AI Models
    REVE_API_KEY: str
    REVE_PROMPT: str = ""
    NANOBANA_API_KEY: str
    NANOBANA_PROMPT: str = ""  # only used in single-variant mode; ignored in 4-variant flow

    # Variant prompts (can be overridden via env vars)
    NANOBANA_VARIANT_PROMPT_1: str = VARIANT_PROMPTS[0]
    NANOBANA_VARIANT_PROMPT_2: str = VARIANT_PROMPTS[1]
    NANOBANA_VARIANT_PROMPT_3: str = VARIANT_PROMPTS[2]
    NANOBANA_VARIANT_PROMPT_4: str = VARIANT_PROMPTS[3]

    @property
    def NANOBANA_VARIANT_PROMPTS(self) -> list[str]:
        # Collected as a list so pipeline.py can just zip() over it.
        return [
            self.NANOBANA_VARIANT_PROMPT_1,
            self.NANOBANA_VARIANT_PROMPT_2,
            self.NANOBANA_VARIANT_PROMPT_3,
            self.NANOBANA_VARIANT_PROMPT_4,
        ]

    # App
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Worker
    POLL_INTERVAL_SECONDS: int = 2
    MAX_CONCURRENT_JOBS: int = 5
    MAX_RETRIES: int = 3
    PROCESSING_TIMEOUT_SECONDS: int = 300  # 5 minutes before a stuck job is reset

    # Database
    DB_TABLE_NAME: str = "images"

    # Storage
    RAW_BUCKET_NAME: str = "plant-images"
    RAW_STORAGE_FOLDER: str = "products"
    PROCESSED_BUCKET_NAME: str = "plant-images"  # same bucket, different folder
    PROCESSED_STORAGE_FOLDER: str = "products/processed"
    ALLOWED_MIME_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp"]
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

    class Config:
        env_file = ".env"
        extra = "ignore"  # silently drop any unknown keys from .env


settings = Settings()
