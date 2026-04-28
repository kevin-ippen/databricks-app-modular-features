-- Research Library schema — PostgreSQL (Lakebase compatible)
-- Run once at app startup via initialize_schema()

CREATE TABLE IF NOT EXISTS collections (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    created_by      VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collection_docs (
    collection_id   INTEGER REFERENCES collections(id) ON DELETE CASCADE,
    doc_id          VARCHAR(255) NOT NULL,
    added_at        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (collection_id, doc_id)
);

CREATE TABLE IF NOT EXISTS annotations (
    id              SERIAL PRIMARY KEY,
    doc_id          VARCHAR(255) NOT NULL,
    chunk_id        VARCHAR(255),
    user_id         VARCHAR(255) NOT NULL,
    note            TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS search_history (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(255) NOT NULL,
    query           TEXT NOT NULL,
    mode            VARCHAR(50),
    result_count    INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id         VARCHAR(255) PRIMARY KEY,
    persona         VARCHAR(50) DEFAULT 'researcher',
    theme           VARCHAR(20) DEFAULT 'dark',
    default_sources TEXT[],
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_annotations_doc ON annotations(doc_id);
CREATE INDEX IF NOT EXISTS idx_search_history_user ON search_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_collections_user ON collections(created_by);
