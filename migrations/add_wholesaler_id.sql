-- Add wholesaler_id column to images table
ALTER TABLE images ADD COLUMN IF NOT EXISTS wholesaler_id TEXT;

-- Index for the daily-count query:
-- WHERE wholesaler_id = ? AND created_at >= ? AND generated_image_urls IS NOT NULL
CREATE INDEX IF NOT EXISTS idx_images_wholesaler_daily
  ON images (wholesaler_id, created_at)
  WHERE generated_image_urls IS NOT NULL;
