CREATE TABLE IF NOT EXISTS message_feedback (
    id SERIAL PRIMARY KEY,
    message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    reaction_type TEXT NOT NULL CHECK (reaction_type IN ('positive', 'negative')),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (message_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_conversation ON message_feedback(conversation_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON message_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON message_feedback(created_at);
