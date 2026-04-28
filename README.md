# Databricks App Modular Features

Production-tested, drop-in features for Databricks Apps. Composable modules you can adopt individually, deployed via Databricks Asset Bundles (DABs).

Each feature is **opinionated** — one implementation, battle-tested in production. No framework soup, no decision paralysis. Pick a module, parameterize it for your domain, deploy with `databricks bundle deploy`.

## Feature Catalog

### Foundation (pick what your features need)

| # | Module | What it does | Complexity |
|---|--------|-------------|------------|
| 1 | **Auth & Identity** | OBO token extraction, SP fallback chain, user identity from JWT, FMAPI client builder | Low |
| 2 | **Lakebase Client** | Async PostgreSQL with OAuth token injection, background token refresh, auto-create schema | Medium |
| 3 | **Config & Settings** | Pydantic BaseSettings with Databricks Apps auto-injection | Low |
| 4 | **LLM Client** | Unified FMAPI (OpenAI-compatible) with model alias mapping, Anthropic fallback for local dev | Low |

### Features (pick what you want)

| # | Feature | What it does | Backend | Frontend | Depends on |
|---|---------|-------------|---------|----------|------------|
| 5 | **Chat** | SSE-streamed conversation with typed events, follow-up suggestions, thinking visibility | FastAPI SSE endpoint | useChat hook, ChatMessage, ChatInput, ThinkingSection | [4] LLM |
| 6 | **Voice I/O** | Full voice loop: VAD → ASR → streaming chat → sentence-level TTS → playback with interrupt | TTS endpoint, ASR endpoint, speech normalizer | useVoiceConversation, VoiceOverlay, audioUtils | [5] Chat |
| 7 | **Conversation Memory** | Per-user persistent history + auto-summarization every 12 messages via Haiku | Lakebase-backed memory layer | — | [2] Lakebase, [4] LLM |
| 8 | **Semantic Search** | NL filter extraction → query rewriting → Vector Search → intent-aware re-ranking | Search router with hybrid BM25+semantic | — | [4] LLM |
| 9 | **RAG Retriever** | Multi-query decomposition → Vector Search → reranking → citation-aware response with [1][2] refs | Retriever service | — | [4] LLM |
| 10 | **File Processing** | Multi-format parsing (PDF/CSV/Excel/JSON/code), schema detection, UC Volume storage, file preview | Parser + storage + FastAPI routes | — | [1] Auth |
| 11 | **Chart Auto-generation** | SQL results → Vega-Lite spec (auto type selection by column types + cardinality) | Optional LLM chart advisor | VegaLiteChart, compileVegaLiteSpec | standalone |
| 12 | **Research Library** | Collections CRUD, document annotations, search history, user preferences | Lakebase service + FastAPI routes | — | [2] Lakebase |
| 13 | **Genie Integration** | Multi-space routing by domain keywords, conversation polling, result formatting | Genie client + formatter | — | [1] Auth |
| 14 | **Agent Router** | LangGraph multi-agent supervisor with intent classification, retry logic, agent exclusion | Graph + supervisor + state | — | [4] LLM |
| 15 | **Knowledge Graph** | Entity/relationship extraction and storage, usage counting, optional VS semantic lookup | Lakebase-backed graph service | — | [2] Lakebase |

## How to Use This Repo

1. **Pick features** from the catalog above
2. **Check dependencies** — see [ARCHITECTURE.md](ARCHITECTURE.md) for the full dependency graph
3. **Copy the module** into your app (each feature is self-contained in its directory)
4. **Parameterize** — swap catalog names, endpoint names, Genie space IDs via env vars or `databricks.yml` variables
5. **Deploy** — `databricks bundle deploy -t dev`

### Example: Add Chat + Voice to an existing app

```python
# app.py
from fastapi import FastAPI
from foundation.auth import get_databricks_token, get_user_id
from foundation.config import Settings
from features.chat.backend.router import chat_router
from features.voice_io.backend.tts import tts_router
from features.voice_io.backend.asr import asr_router

app = FastAPI()
app.include_router(chat_router, prefix="/api/chat")
app.include_router(tts_router, prefix="/api/tts")
app.include_router(asr_router, prefix="/api/asr")
```

```yaml
# databricks.yml (parameterized per-target)
variables:
  serving_endpoint:
    default: databricks-claude-sonnet-4-6
  tts_endpoint:
    default: my-tts-endpoint
  asr_endpoint:
    default: my-asr-endpoint
  catalog:
    default: my_catalog

targets:
  dev:
    default: true
    variables:
      catalog: dev_catalog
  prod:
    variables:
      catalog: prod_catalog
```

```yaml
# app.yaml
command: ["uvicorn", "app:app", "--host=0.0.0.0", "--port=8000"]
env:
  - name: SERVING_ENDPOINT
    value: ${var.serving_endpoint}
  - name: TTS_ENDPOINT
    value: ${var.tts_endpoint}
  - name: ASR_ENDPOINT
    value: ${var.asr_endpoint}
  - name: CATALOG
    value: ${var.catalog}
```

## Repo Structure

```
databricks.yml           # DAB config — variables, targets, resources
foundation/              # Shared infrastructure (auth, lakebase, config, llm)
features/                # Drop-in features (chat, voice, search, files, etc.)
examples/                # Runnable example apps composing multiple features
docs/                    # Architecture, dependency map
```

## Docs

- [FEATURES.md](FEATURES.md) — Detailed per-feature documentation with API surfaces
- [ARCHITECTURE.md](ARCHITECTURE.md) — Dependency graph, composition patterns, example apps

## Design Principles

- **Domain-agnostic** — No hardcoded business logic. Every domain-specific value (catalog names, endpoint names, space IDs, keywords) is parameterized via env vars or DAB variables.
- **DAB-native** — Each example app includes a `databricks.yml` with multi-target support (dev/staging/prod). Deploy with `databricks bundle deploy -t <target>`.
- **Composable** — Features are additive. Start with Chat, add Voice later, add Memory when you need persistence. No feature assumes another is present unless listed in its dependency table.
- **FastAPI + React** — Backend is always FastAPI. Frontend is always React + TypeScript + Vite. One stack, no options to bikeshed.
