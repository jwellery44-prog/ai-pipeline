import os
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Default prompts for the 4 concurrently generated image variants.
# Each variant presents the jewellery on a distinct backdrop at a unique angle.
# Override any of these via the corresponding env var (e.g. NANOBANA_VARIANT_PROMPT_2).
# ---------------------------------------------------------------------------

_VARIANT_PROMPT_1 = (
    "STRICT IMAGE COMPOSITING TASK. "
    "Place the jewellery on a dark navy-blue sculpted stone surface. "
    "Classic front-facing display angle — jewellery perfectly centred. "
    "Soft directional studio lighting from the upper-left. "
    "Deep, moody, luxurious atmosphere. No background distractions. "
    "Preserve every detail, texture, reflection, and gemstone of the jewellery exactly. "
    "Do NOT modify the jewellery design, colour, or proportions. "
    "Professional luxury product photography."
)

_VARIANT_PROMPT_2 = (
    "STRICT IMAGE COMPOSITING TASK. "
    "Place the jewellery on a deep burgundy-red velvet cushion surface. "
    "Present at a gentle 45-degree angle — front-left perspective. "
    "Warm golden studio lighting from the upper-right. "
    "Shallow depth of field; soft bokeh background haze. "
    "Luxury jewellery boutique aesthetic. "
    "Preserve every detail, texture, reflection, and gemstone of the jewellery exactly. "
    "Do NOT modify the jewellery design, colour, or proportions. "
    "Professional luxury product photography."
)

_VARIANT_PROMPT_3 = (
    "STRICT IMAGE COMPOSITING TASK. "
    "Place the jewellery on a pristine white Carrara marble surface with subtle grey veining. "
    "Slight overhead / elevated perspective — camera angled 30 degrees above horizontal. "
    "Bright diffused natural daylight; clean, airy, editorial feel. "
    "Minimal composition — jewellery as the sole subject. "
    "High-fashion editorial campaign style. "
    "Preserve every detail, texture, reflection, and gemstone of the jewellery exactly. "
    "Do NOT modify the jewellery design, colour, or proportions. "
    "Professional luxury product photography."
)

_VARIANT_PROMPT_4 = (
    "STRICT IMAGE COMPOSITING TASK. "
    "Place the jewellery floating and centred against a deep charcoal-black gradient background. "
    "Subtle warm amber and gold light accents rim the edges. "
    "Dramatic side-profile angle — jewellery rotated approximately 60 degrees. "
    "Single hard spotlight from directly above creating a defined shadow below. "
    "Premium luxury advertisement style — bold and dramatic. "
    "Preserve every detail, texture, reflection, and gemstone of the jewellery exactly. "
    "Do NOT modify the jewellery design, colour, or proportions. "
    "Professional luxury product photography."
)


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    
    # AI Models
    REVE_API_KEY: str
    REVE_PROMPT: str = ""
    NANOBANA_API_KEY: str
    NANOBANA_PROMPT: str = ""

    # ---------------------------------------------------------------------------
    # Variant prompts — used by the concurrent 4-image generation step.
    # These can be overridden via environment variables.
    # ---------------------------------------------------------------------------
    NANOBANA_VARIANT_PROMPT_1: str = _VARIANT_PROMPT_1
    NANOBANA_VARIANT_PROMPT_2: str = _VARIANT_PROMPT_2
    NANOBANA_VARIANT_PROMPT_3: str = _VARIANT_PROMPT_3
    NANOBANA_VARIANT_PROMPT_4: str = _VARIANT_PROMPT_4

    # Convenience property ─ returns all 4 prompts as an ordered list
    @property
    def NANOBANA_VARIANT_PROMPTS(self) -> list[str]:
        return [
            self.NANOBANA_VARIANT_PROMPT_1,
            self.NANOBANA_VARIANT_PROMPT_2,
            self.NANOBANA_VARIANT_PROMPT_3,
            self.NANOBANA_VARIANT_PROMPT_4,
        ]

    # App Config
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    
    # Worker Config
    POLL_INTERVAL_SECONDS: int = 2
    MAX_CONCURRENT_JOBS: int = 5
    MAX_RETRIES: int = 3
    PROCESSING_TIMEOUT_SECONDS: int = 300
    
    # Database Config
    DB_TABLE_NAME: str = "images"            # override via DB_TABLE_NAME in .env

    # Storage Config
    RAW_BUCKET_NAME: str = "plant-images"    # Supabase bucket holding raw product images
    RAW_STORAGE_FOLDER: str = "products"     # Folder inside raw bucket
    PROCESSED_BUCKET_NAME: str = "plant-images"
    PROCESSED_STORAGE_FOLDER: str = "products/processed"  # Output folder
    ALLOWED_MIME_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp"]
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10MB

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
