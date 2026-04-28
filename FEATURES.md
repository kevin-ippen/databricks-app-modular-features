# Feature Details

Detailed documentation for each of the 15 modules. For each feature: what it does, API surface, env vars needed, Databricks resources required, and integration pattern.

All features are domain-agnostic. Business-specific values (catalog names, endpoint names, Genie space IDs, search filter patterns, ranking weights) are parameterized via environment variables or DAB variables in `databricks.yml`.

---

## Foundation Modules

### [1] Auth & Identity

**What it does**: Extracts user identity and tokens from Databricks Apps request headers (OBO), with fallback to PAT and Service Principal. Builds authenticated clients for FMAPI.

**API Surface**:

```python
# Get the right token (OBO → PAT → SP fallback)
def get_databricks_token(request: Optional[Request] = None) -> str: ...

# Extract user identity
def get_user_id(request: Request) -> str: ...
def get_user_email(request: Request) -> Optional[str]: ...

# Build an authenticated async OpenAI client pointing at FMAPI
def get_async_openai_client(token: str) -> AsyncOpenAI: ...

# Typed identity model
class Identity(BaseModel):
    email: Optional[str]
    display_name: Optional[str]
    auth_type: Literal["obo", "pat"]
    token_source: TokenSource
```

**Env vars**: `DATABRICKS_HOST`, `DATABRICKS_TOKEN` (optional, for local dev)

**Databricks resources**: None (uses built-in Apps headers)

**Key insight**: In Databricks Apps, the platform injects `x-forwarded-access-token` and `x-forwarded-email` headers. This module provides a clean extraction layer with fallback for local development.

---

### [2] Lakebase Client

**What it does**: Manages PostgreSQL connections to Lakebase with OAuth token injection and automatic refresh. Handles the Databricks-specific pattern where tokens expire every 60 minutes.

**API Surface**:

```python
# Async connection (lightweight, one-shot queries)
async def get_async_connection() -> asyncpg.Connection: ...

# Schema auto-initialization at startup
async def initialize_schema(ddl_path: str) -> None: ...

# Background token refresh (call from lifespan)
async def start_token_refresh(interval_seconds: int = 3000) -> None: ...

# SQLAlchemy engine (for ORM-based apps)
def create_engine_with_token_refresh(connection_string: str) -> Engine: ...
```

**Env vars**: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`

**Databricks resources**: Lakebase database (provisioned or autoscaling), attached as app resource

**Key insight**: Lakebase uses OAuth tokens as passwords. Tokens expire in 60 minutes. This module refreshes every 50 minutes in a background task and injects fresh tokens into every connection.

---

### [3] Config & Settings

**What it does**: Pydantic BaseSettings that auto-reads Databricks Apps environment variables. Separates workspace credentials from app-specific config.

**API Surface**:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App identity
    app_name: str = "My App"
    debug: bool = False

    # Unity Catalog
    catalog: str = "my_catalog"

    # FMAPI
    serving_endpoint: str = "databricks-claude-sonnet-4-6"

    # Workspace (auto-injected in Apps)
    databricks_host: Optional[str] = None
    databricks_token: Optional[str] = None

    # Lakebase (auto-injected when database resource is attached)
    pghost: Optional[str] = None
    pgport: str = "5432"
    pgdatabase: str = "databricks_postgres"

    @property
    def pg_connection_string(self) -> Optional[str]: ...

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

@lru_cache()
def get_settings() -> Settings: ...
```

**Env vars**: All settings are read from environment (auto-injected by Databricks Apps platform)

**Databricks resources**: None

**Key insight**: Databricks Apps auto-injects `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, `PGHOST`, etc. This pattern lets the same code work locally (via `.env`) and deployed (via platform injection).

---

### [4] LLM Client

**What it does**: Unified LLM interface that routes to Databricks FMAPI when deployed, falls back to Anthropic SDK for local development. Handles model name mapping.

**API Surface**:

```python
@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int

def chat(
    model: str,          # e.g., "databricks-claude-sonnet-4-6" or "claude-sonnet-4-20250514"
    messages: list[dict],
    max_tokens: int = 1000,
    temperature: float = 0.3,
) -> LLMResponse: ...

# Async streaming variant
async def stream_chat(
    model: str,
    messages: list[dict],
    max_tokens: int = 4096,
) -> AsyncGenerator[str, None]: ...
```

**Env vars**: `DATABRICKS_HOST` (presence triggers FMAPI mode), `ANTHROPIC_API_KEY` (fallback)

**Databricks resources**: Foundation Model API (pay-per-token, no endpoint to create)

**Key insight**: If `DATABRICKS_HOST` is set, use OpenAI SDK pointing at `{host}/serving-endpoints`. Otherwise, use Anthropic SDK directly. Model name mapping handles the translation (e.g., `claude-sonnet-4-20250514` → `databricks-claude-sonnet-4`).

---

## Features

### [5] Chat

**What it does**: Server-Sent Events (SSE) streaming for real-time chat. Backend emits typed events; frontend hook consumes them and accumulates message state.

**Backend API Surface**:

```python
# Event types
class EventType(str, Enum):
    TEXT_DELTA = "text.delta"        # Incremental text content
    TOOL_CALL = "tool.call"          # Function being invoked
    TOOL_OUTPUT = "tool.output"      # Function result summary
    THINKING_STEP = "thinking.step"  # Agent reasoning visibility
    METADATA = "metadata"            # Execution metadata
    FOLLOWUPS = "followups"          # Suggested follow-up questions

# FastAPI SSE endpoint
@router.post("/stream")
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    """Stream chat response as SSE events."""
    ...

# Follow-up suggestion generation
async def generate_followups(
    messages: list[dict],
    response: str,
    max_suggestions: int = 3,
) -> list[str]: ...
```

**Frontend API Surface**:

```typescript
// useChat hook
function useChat(config: { endpoint: string }) {
  return {
    messages: Message[];
    isStreaming: boolean;
    followups: string[];
    sendMessage: (content: string, files?: File[]) => Promise<void>;
    cancelStream: () => void;
  }
}

// Event consumption
interface StreamEvent {
  type: "text.delta" | "tool.call" | "thinking.step" | "followups" | "metadata";
  data: string | object;
}
```

**Env vars**: `SERVING_ENDPOINT`

**Databricks resources**: Foundation Model API endpoint

---

### [6] Voice I/O

**What it does**: End-to-end voice conversation. User speaks → ASR transcribes → chat streams response → TTS synthesizes sentence-by-sentence → user hears response with natural pacing.

**Backend API Surface**:

```python
# ASR endpoint
@router.post("/transcribe")
async def transcribe_audio(file: UploadFile) -> TranscriptionResult:
    """Accept audio file (webm/wav/mp3), return transcribed text."""
    ...

# TTS endpoint
@router.post("/synthesize")
async def synthesize_speech(request: TTSRequest) -> StreamingResponse:
    """Accept text, return WAV audio. Normalizes text for natural prosody."""
    ...

# Speech normalizer (preprocesses text for TTS)
def normalize_for_speech(text: str, audience: str = "business") -> str:
    """$45.99 → '45 dollars and 99 cents', SQL → 'sequel', AI/BI → 'A I B I'"""
    ...
```

**Frontend API Surface**:

```typescript
// Voice conversation state machine
type VoiceState = "idle" | "listening" | "transcribing" | "streaming" | "speaking";

function useVoiceConversation(config: {
  asrEndpoint: string;
  ttsEndpoint: string;
  chatEndpoint: string;
  playbackSpeed?: number; // default 1.25
}) {
  return {
    state: VoiceState;
    startListening: () => void;
    stopListening: () => void;
    interrupt: () => void;   // Stop playback, return to listening
    volumeLevel: number;     // 0-1, for VAD visualization
  }
}

// Audio utilities (vanilla TypeScript, zero dependencies)
function createWavBlob(samples: Float32Array, sampleRate: number): Blob;
function detectSentenceBoundary(text: string): number | null;
function computeVolume(analyserNode: AnalyserNode): number;
```

**Env vars**: `TTS_ENDPOINT`, `ASR_ENDPOINT`

**Databricks resources**: TTS model serving endpoint, ASR model serving endpoint

**Key insight**: The frontend does WAV construction in vanilla TypeScript (no Web Audio libraries). TTS calls happen per-sentence as the chat response streams — user hears the first sentence before the full response is complete. Filler phrases ("Hmm, let me look into that...") mask cold-start latency.

---

### [7] Conversation Memory

**What it does**: Persists conversation history in Lakebase. Loads last 10 turns + a running summary for LLM context injection. Auto-summarizes every 12 messages.

**API Surface**:

```python
class MemoryLayer:
    async def load_history_and_summary(self, session_id: str) -> Tuple[List[Dict], str]:
        """Returns (history, summary). History is [{role, content}] oldest-first."""
        ...

    async def save_turn(
        self, session_id: str, user_id: str, user_message: str, assistant_message: str
    ) -> int:
        """Persist messages. Returns new total message count."""
        ...

    async def maybe_summarize(
        self, session_id: str, message_count: int, async_openai_client, model: str = "databricks-claude-haiku-4-5"
    ) -> None:
        """Background Haiku call every 12 messages to distill context."""
        ...
```

**Schema**:

```sql
CREATE TABLE conversations (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    message_count INT DEFAULT 0,
    summary TEXT,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES conversations(session_id),
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

**Env vars**: Lakebase connection (via [2] Lakebase Client)

**Databricks resources**: Lakebase database

---

### [8] Semantic Search

**What it does**: Takes a natural language query, extracts structured filters (price ranges, categories, attributes), rewrites the query for better retrieval, queries Vector Search with metadata filters, and re-ranks results using multiple signals.

**API Surface**:

```python
# Search router
@router.get("/search")
async def search(
    q: str,                          # Natural language query
    limit: int = 20,
    intent_boost: bool = True,       # Apply intent-aware re-ranking
) -> SearchResults: ...

# NL filter extraction (configure patterns per domain)
def extract_filters(query: str, filter_patterns: dict) -> Tuple[str, Dict[str, Any]]:
    """Parse 'under $50 wireless headphones' → ('wireless headphones', {max_price: 50})"""
    ...

# Re-ranking weights (configurable per use case)
RANKING_WEIGHTS = {
    "vector_score": 0.50,
    "composite": 0.25,
    "intent_bonus": 0.15,
    "metadata_boost": 0.10,
}
```

**Env vars**: `VECTOR_SEARCH_ENDPOINT`, `VECTOR_SEARCH_INDEX`, `SERVING_ENDPOINT` (for query rewriting)

**Databricks resources**: Vector Search endpoint + Delta Sync index, Foundation Model API (for query rewriting)

**Key insight**: Pure vector similarity isn't enough. This module adds NL filter extraction (configurable regex + fuzzy matching), query rewriting (LLM expands terse queries into broader retrieval terms), and multi-signal re-ranking (vector distance + metadata signals + detected user intent). Filter patterns and ranking weights are parameterized per domain.

---

### [9] RAG Retriever

**What it does**: Decomposes complex questions into sub-queries, searches Vector Search with metadata filters, reranks results, and generates a grounded response with numbered citations.

**API Surface**:

```python
class InstructedRetriever:
    async def retrieve_and_answer(
        self,
        question: str,
        conversation_history: list[dict] = None,
        metadata_filters: dict = None,
    ) -> RAGResponse: ...

@dataclass
class RAGResponse:
    answer: str              # Grounded response with [1][2] citations
    sources: list[Source]    # Retrieved documents used
    sub_queries: list[str]   # Decomposed queries that were run

@dataclass
class Source:
    doc_id: str
    title: str
    chunk_text: str
    relevance_score: float
```

**Env vars**: `VECTOR_SEARCH_ENDPOINT`, `VECTOR_SEARCH_INDEX`, `SERVING_ENDPOINT`

**Databricks resources**: Vector Search endpoint + index, Foundation Model API

**Key insight**: Single questions often need multiple retrieval passes. "Compare Q1 vs Q2 marketing performance" becomes two sub-queries. The response is grounded — only includes information from retrieved documents, with [1][2] citations pointing back to sources.

---

### [10] File Processing & Preview

**What it does**: Parses uploaded files (PDF, CSV, Excel, JSON, code), detects schemas for structured data, extracts metadata, stores in UC Volumes, and serves previews via Files API.

**API Surface**:

```python
# File processor
class FileProcessor:
    def parse(self, file: UploadFile) -> ParsedFile:
        """Route to format-specific parser based on MIME type."""
        ...

@dataclass
class ParsedFile:
    content_type: str       # "pdf", "csv", "excel", "json", "code"
    text_preview: str       # First ~500 chars of content
    metadata: dict          # page_count, columns, encoding, etc.
    schema: Optional[dict]  # For structured data: column names, types, sample values

# File storage (UC Volumes)
class FileStorage:
    def upload(self, file: UploadFile, user_id: str) -> StoredFile:
        """Upload to /Volumes/{catalog}/{schema}/{volume}/{user_id}/{filename}"""
        ...

    def get_download_url(self, volume_path: str) -> str:
        """Generate Files API URL for streaming download."""
        ...

# FastAPI routes
@router.post("/upload")
async def upload_file(file: UploadFile, request: Request) -> StoredFile: ...

@router.get("/download/{file_id}")
async def download_file(file_id: str, request: Request) -> StreamingResponse: ...
```

**Env vars**: `CATALOG`, `FILE_VOLUME_PATH` (e.g., `/Volumes/my_catalog/my_schema/uploads`)

**Databricks resources**: UC Volume for file storage

---

### [11] Chart Auto-generation

**What it does**: Takes SQL query results (column names + rows) and compiles a Vega-Lite chart specification. Picks chart type automatically based on column types and cardinality.

**API Surface**:

```typescript
// Auto-compile a Vega-Lite spec from tabular data
function compileVegaLiteSpec(
  columns: Column[],
  rows: any[],
  options?: { chartType?: "auto" | "bar" | "line" | "scatter" | "pie" }
): VegaLiteSpec;

// Heuristics for chart type selection
// - 1 numeric + 1 categorical (cardinality < 20) → bar chart
// - 1 numeric + 1 date/time → line chart
// - 2 numeric → scatter plot
// - 1 numeric + 1 categorical (cardinality < 8) → pie chart

// React component
function VegaLiteChart({ spec, width, height }: Props): JSX.Element;
```

**Env vars**: None (standalone frontend module)

**Databricks resources**: None

**Key insight**: The chart type selection is rule-based, not LLM-based. Column type (date, categorical, numeric) + cardinality drives the decision. An optional LLM chart advisor can suggest more complex multi-series or faceted charts.

---

### [12] Research Library

**What it does**: User-curated document collections with inline annotations, search history tracking, and per-user preferences. All persisted in Lakebase.

**API Surface**:

```python
class ResearchLibraryService:
    # Collections
    def create_collection(self, user_id: str, name: str) -> Collection: ...
    def list_collections(self, user_id: str) -> list[Collection]: ...
    def add_doc_to_collection(self, collection_id: int, doc_id: str) -> None: ...

    # Annotations
    def create_annotation(self, user_id: str, doc_id: str, chunk_id: str, note: str) -> Annotation: ...
    def get_annotations(self, doc_id: str) -> list[Annotation]: ...

    # Search history
    def log_search(self, user_id: str, query: str, mode: str, result_count: int) -> None: ...
    def get_recent_searches(self, user_id: str, limit: int = 20) -> list[SearchEntry]: ...

    # Preferences
    def get_preferences(self, user_id: str) -> UserPreferences: ...
    def update_preferences(self, user_id: str, prefs: UserPreferences) -> None: ...
```

**Env vars**: Lakebase connection (via [2] Lakebase Client)

**Databricks resources**: Lakebase database

---

### [13] Genie Integration

**What it does**: Routes analytics questions to domain-specific Genie Spaces, polls for completion, and formats results for chart/table rendering.

**API Surface**:

```python
class GenieClient:
    def __init__(self, spaces: dict[str, str]):
        """spaces = {"sales": "space_id_1", "marketing": "space_id_2", ...}"""
        ...

    async def ask(
        self,
        question: str,
        space_id: Optional[str] = None,  # Auto-detect if not provided
    ) -> GenieResult: ...

    def detect_space(self, question: str) -> str:
        """Keyword-based space routing. Configurable keyword→space mapping."""
        ...

@dataclass
class GenieResult:
    answer: str
    sql_query: Optional[str]
    columns: list[str]
    rows: list[list]
    space_id: str
```

**Env vars**: `GENIE_SPACE_*` (one per domain, e.g., `GENIE_SPACE_SALES=01f12a...`)

**Databricks resources**: Genie Space(s) with configured instruction tables

**Key insight**: Keyword matching for space routing is surprisingly effective. Configure a keyword→space mapping (e.g., revenue/pipeline keywords → sales space, campaign/attribution → marketing space). More complex routing can use the LLM Client for intent classification.

---

### [14] Agent Router

**What it does**: LangGraph-based multi-agent supervisor that classifies user intent and routes to specialized agent nodes. Handles retries and fallback.

**API Surface**:

```python
# Intent classification
class IntentType(str, Enum):
    SQL = "sql"              # → Genie agent
    RAG = "rag"              # → Retriever agent
    WEBSEARCH = "websearch"  # → Web search agent
    GENERAL = "general"      # → General conversational agent

# Supervisor
class AgentSupervisor:
    def classify_intent(self, message: str, history: list[dict]) -> IntentType: ...
    async def route_and_execute(self, message: str, history: list[dict]) -> AgentResponse: ...

# LangGraph state
class AgentState(TypedDict):
    messages: list[dict]
    intent: IntentType
    active_agent: str
    retry_count: int
    excluded_agents: list[str]  # Agents that failed (won't retry)

# Graph construction
def build_agent_graph(agents: dict[str, AgentNode]) -> StateGraph:
    """Register agent nodes with conditional routing from supervisor."""
    ...
```

**Env vars**: `SERVING_ENDPOINT`

**Databricks resources**: Foundation Model API

**Key insight**: The retry pattern is critical — if an agent fails, it's excluded from the next attempt and the supervisor reroutes to an alternative. This prevents infinite loops while maximizing response quality.

---

### [15] Knowledge Graph

**What it does**: Extracts entities (tables, files, concepts, insights, queries) and relationships from conversations. Tracks usage frequency for relevance scoring.

**API Surface**:

```python
class KnowledgeGraphService:
    async def add_entity(
        self,
        entity_type: str,    # "table", "file", "concept", "insight", "query"
        name: str,
        description: str,
        source: str,         # "user_upload", "sql_result", "chat_extraction"
        metadata: dict = None,
    ) -> str: ...  # Returns entity_id

    async def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship: str,   # "derived_from", "related_to", "used_by", "contains"
        confidence: float = 1.0,
    ) -> None: ...

    async def search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None,
        limit: int = 10,
    ) -> list[KnowledgeEntity]: ...

    async def increment_usage(self, entity_id: str) -> None: ...
```

**Env vars**: Lakebase connection (via [2] Lakebase Client)

**Databricks resources**: Lakebase database, optionally Vector Search for semantic entity lookup
