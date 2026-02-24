import os
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Shared core directive — injected into every variant prompt.
# This block is the non-negotiable pixel-perfect compositing contract.
# ---------------------------------------------------------------------------

_CORE_DIRECTIVE = """
### TASK: PIXEL-PERFECT JEWELLERY COMPOSITING

[PRODUCT_ANALYSIS]: Automatically identify if input is NECKLACE, BANGLE, RING, or EARRING.
[MATERIAL_LOCK]: {Gold | Silver | Diamond | Platinum | Gemstone | Pearl}

### CORE DIRECTIVES:
- STRICTLY PRESERVE PIXELS: 100% detail retention of gemstones, facets, and metal textures.
- NO ALTERING / NO ADDING: Do NOT add extra metal, change the design, or modify the structure. The jewellery must remain MATHEMATICALLY IDENTICAL to the source.
- MANNEQUIN ALIGNMENT: Place the jewellery STRICTLY on a professional mannequin matching its category (e.g., Neck Bust for Necklace, Wrist for Bangle, Finger for Ring, Ear for Earring).
- ZERO STYLIZATION: No smoothing, no AI-enhancement, no blurring of edges.
- PHYSICAL INTERACTION: Generate ONLY realistic contact shadows and ambient occlusion where the metal meets the mannequin.
- LIGHTING: Match high-end studio lighting. Maintain the original colour temperature and luster of the [MATERIAL_LOCK].

### FINAL CHECK:
If the jewellery design is altered by even 1%, REJECT and revert to the original input image pixels. The background and mannequin are secondary; the product is the absolute priority.
""".strip()

# ---------------------------------------------------------------------------
# 4 variant prompts — each applies the full core directive above but renders
# from a distinct camera angle and backdrop for maximum visual variety.
# Override any via env var (e.g. NANOBANA_VARIANT_PROMPT_2).
# ---------------------------------------------------------------------------

_VARIANT_PROMPT_1 = (
    _CORE_DIRECTIVE + "\n\n"
    "### VARIANT 1 — FRONTAL HERO SHOT\n"
    "[User_Defined_Angle]: Direct front-facing view, camera perfectly level with the mannequin.\n"
    "Jewellery centred and fully visible. Clean, neutral dark-navy studio backdrop.\n"
    "Soft diffused key light from the upper-left, subtle fill from the right.\n"
    "This is the primary catalogue shot — maximum detail, zero distraction."
)

_VARIANT_PROMPT_2 = (
    _CORE_DIRECTIVE + "\n\n"
    "### VARIANT 2 — 45-DEGREE SIDE VIEW\n"
    "[User_Defined_Angle]: 45-degree side view, camera rotated left relative to the mannequin.\n"
    "Jewellery perspective matches the mannequin's anatomical contours at this angle precisely.\n"
    "Warm golden studio lighting from the upper-right; shallow depth of field with soft bokeh.\n"
    "Deep burgundy-red velvet backdrop. Showcases the jewellery's depth and profile."
)

_VARIANT_PROMPT_3 = (
    _CORE_DIRECTIVE + "\n\n"
    "### VARIANT 3 — MACRO CLOSE-UP\n"
    "[User_Defined_Angle]: Macro close-up, camera angled 30 degrees above horizontal.\n"
    "Extreme detail shot — gemstone facets, metal grain, engravings fully resolved.\n"
    "Bright diffused natural daylight; pristine white Carrara marble surface beneath.\n"
    "Fills the entire frame with the jewellery. Zero background distraction."
)

_VARIANT_PROMPT_4 = (
    _CORE_DIRECTIVE + "\n\n"
    "### VARIANT 4 — THREE-QUARTER ELEVATED VIEW\n"
    "[User_Defined_Angle]: Three-quarter view, camera elevated 20 degrees above eye level and rotated 30 degrees right.\n"
    "Dramatic deep charcoal-black gradient backdrop; warm amber and gold rim-light accents on edges.\n"
    "Single hard spotlight from directly above creating a sharp defined shadow below the mannequin.\n"
    "Premium luxury advertisement composition — bold, cinematic, editorial."
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
