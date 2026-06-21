-- migrations/add_ai_generation_logs.sql

CREATE TABLE IF NOT EXISTS ai_generation_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id UUID REFERENCES products(id) ON DELETE SET NULL,
  wholesaler_id TEXT,
  triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'failed')),
  trigger_source TEXT NOT NULL CHECK (trigger_source IN ('new_upload', 'reprocess'))
);

-- Index for the daily-count query: filter by wholesaler, status, and date range
CREATE INDEX IF NOT EXISTS idx_ai_generation_logs_daily_count
  ON ai_generation_logs (wholesaler_id, status, triggered_at);
