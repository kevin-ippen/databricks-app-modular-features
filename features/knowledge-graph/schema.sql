CREATE TABLE IF NOT EXISTS knowledge_entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    embedding_id TEXT,
    metadata JSONB,
    source TEXT,
    usage_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_relations (
    relation_id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES knowledge_entities(entity_id),
    target_id TEXT REFERENCES knowledge_entities(entity_id),
    relationship TEXT NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON knowledge_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON knowledge_entities(name);
CREATE INDEX IF NOT EXISTS idx_relations_source ON knowledge_relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON knowledge_relations(target_id);
