CREATE TABLE IF NOT EXISTS conversations (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    message_count INT DEFAULT 0,
    summary TEXT,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES conversations(session_id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
