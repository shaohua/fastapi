-- VS Code Extension Stats - Single Table Schema
-- Simple, denormalized approach for easy querying

CREATE TABLE extension_stats (
    id BIGSERIAL PRIMARY KEY,
    extension_id TEXT NOT NULL,           -- "github.copilot"
    name TEXT NOT NULL,                   -- "GitHub Copilot" 
    publisher TEXT NOT NULL,              -- "GitHub"
    description TEXT,
    version TEXT,
    install_count BIGINT,
    rating NUMERIC(3,2),
    rating_count INTEGER,
    tags TEXT[] DEFAULT '{}',
    categories TEXT[] DEFAULT '{}',
    captured_at TIMESTAMPTZ NOT NULL,
    
    -- Prevent duplicate snapshots
    CONSTRAINT unique_ext_snapshot UNIQUE (extension_id, captured_at)
);

-- Essential indexes for fast queries
CREATE INDEX idx_ext_stats_ext_time ON extension_stats (extension_id, captured_at DESC);
CREATE INDEX idx_ext_stats_captured ON extension_stats (captured_at DESC);
CREATE INDEX idx_ext_stats_installs ON extension_stats (install_count DESC);

-- Optional: Add a partial index for recent data (last 30 days)
-- CREATE INDEX idx_ext_stats_recent ON extension_stats (extension_id, captured_at DESC) 
-- WHERE captured_at >= NOW() - INTERVAL '30 days';
