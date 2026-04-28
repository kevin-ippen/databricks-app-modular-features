-- Trace logging schema for Lakebase (PostgreSQL).
--
-- Create this table in your Lakebase database before enabling
-- log persistence in StructuredLogger. Table name is configurable
-- via the `table` parameter -- this file uses "app_logs" as default.

CREATE TABLE IF NOT EXISTS app_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    level TEXT NOT NULL,
    component TEXT,
    request_id TEXT,
    message TEXT,
    extra JSONB,
    error JSONB,
    duration_ms DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_request_id ON app_logs(request_id);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON app_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_level ON app_logs(level);
