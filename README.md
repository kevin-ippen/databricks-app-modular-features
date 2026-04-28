# Databricks App Modular Features

A collection of patterns and reference implementations for building AI-powered Databricks Apps. Extracted from real projects, parameterized for reuse, and organized as composable modules.

**What this is**: Reference code you can study, adapt, and integrate. Some modules are near-production-ready and can be dropped in with minimal changes. Others are starting points that demonstrate an architecture — expect to adapt the logic for your domain.

**What this isn't**: A framework, a library with semver guarantees, or something you `pip install`. It's a repo of working patterns you fork and own.

## Feature Catalog

### Foundation

Core infrastructure modules. These are small, well-tested, and closest to "just copy it."

| # | Module | Lines | Effort to adopt | What it does |
|---|--------|-------|-----------------|-------------|
| 1 | **Auth & Identity** | ~100 | Copy-paste | OBO token extraction, SP fallback chain, FMAPI client builder. Standard Databricks Apps auth pattern. |
| 2 | **Lakebase Client** | ~400 | Moderate | Async PostgreSQL with OAuth token refresh. The token lifecycle is non-trivial — this saves you from discovering the 60-minute expiry the hard way. |
| 3 | **Config & Settings** | ~60 | Copy-paste | Pydantic BaseSettings template with Databricks Apps auto-injection. Change the defaults and go. |
| 4 | **LLM Client** | ~120 | Copy-paste | FMAPI routing (OpenAI SDK → Databricks endpoint) with Anthropic fallback for local dev. |

### Features

Larger modules with varying levels of production-readiness. The "Effort" column is honest about what's involved.

| # | Feature | Lines | Effort to adopt | Notes |
|---|---------|-------|-----------------|-------|
| 5 | **Chat** | ~2,100 | Moderate-High | SSE streaming backend + React hooks + UI components. The SSE event protocol and `useChat` hook are the real value — solid and reusable. The React components (`ChatMessage`, `ChatInput`) are functional but bare-bones: no syntax highlighting, no rich markdown, minimal styling. Plan to build your own UI on top of the hook. |
| 6 | **Voice I/O** | ~2,000 | Significant | Full voice loop (VAD → ASR → TTS). The `speech_normalizer.py` and `audioUtils.ts` are genuinely production-ready standalone utilities — use them directly. The conversation loop hook demonstrates the architecture but you'll tune VAD thresholds, filler phrases, and playback for your UX. Requires deploying your own TTS + ASR model serving endpoints first. |
| 7 | **Conversation Memory** | ~280 | Low | Clean async memory layer with auto-summarization. Wire up your Lakebase connection and it works. One of the more plug-and-play features. |
| 8 | **Semantic Search** | ~660 | Significant | The architecture (filter extraction → query rewriting → VS → re-ranking) is the value — not the specific filters. The regex patterns, intent keywords, and ranking weights are generic placeholders. You'll rewrite the filter logic and weight tuning entirely for your domain. Think of this as an annotated blueprint. |
| 9 | **RAG Retriever** | ~740 | Moderate | Multi-query decomposition + citation-aware response generation. The decomposition and citation logic are reusable. You'll configure your Vector Search index and tune the grounding prompt. |
| 10 | **File Processing** | ~770 | Low-Moderate | Multi-format parser (PDF/CSV/Excel/JSON/code) with schema detection. The parser is genuinely useful as-is. The UC Volume storage layer needs your paths configured. |
| 11 | **Chart Auto-generation** | ~800 | Low | Frontend-only. Compiles SQL results into Vega-Lite specs with automatic chart type selection. 11 chart types, rule-based heuristics. Works standalone — no backend required. |
| 12 | **User Collections & Annotations** | ~480 | Moderate | Generic collection/annotation/preference CRUD backed by Lakebase. Despite the name in the directory (`research-library`), this is a domain-agnostic pattern: user-curated folders of items with inline notes, search history, and per-user settings. Adapt the schema for your objects. |
| 13 | **Genie Integration** | ~700 | Moderate | Multi-space routing + conversation polling. The Genie API interaction (start conversation → poll → extract results) is the hard part — this handles it. You bring your own space IDs and routing keywords. You need Genie Spaces configured in your workspace first. |
| 14 | **Agent Router** | ~1,050 | Significant | LangGraph supervisor with intent classification, retry, and agent exclusion. This is a reference architecture — it provides the orchestration skeleton but **not** the agents themselves. Your actual routing keywords, agent implementations, and graph shape will be different. Study the patterns, then build your own. |
| 15 | **Knowledge Graph** | ~550 | Moderate | Entity/relationship CRUD with Lakebase. The storage and query layer is clean. The harder problem it doesn't solve is *extraction* — deciding what entities to create and when. That's your application logic. |

### Effort Guide

- **Copy-paste**: Change defaults/config, wire into your app. Under an hour.
- **Low**: Minor configuration and integration. A few hours.
- **Moderate**: Understand the pattern, configure for your domain, test integration. A day or two.
- **Significant**: Study the architecture, adapt core logic for your use case, likely rewrite portions. Best treated as a detailed reference rather than a drop-in.

## How to Use This Repo

1. **Browse the catalog** — pick features relevant to your app
2. **Read the feature code** — each module is self-contained in its directory
3. **Check [ARCHITECTURE.md](ARCHITECTURE.md)** for the dependency graph and composition patterns
4. **Copy what you need** — fork the module into your project, adapt imports, configure
5. **Parameterize for your environment** — env vars or `databricks.yml` variables

### Example: Add Chat + Voice to an existing app

```python
# app.py
from fastapi import FastAPI
from foundation.auth import get_databricks_token, get_user_id
from foundation.config import Settings
from features.chat.backend.router import create_chat_router
from features.voice_io.backend.tts import create_tts_router
from features.voice_io.backend.asr import create_asr_router

app = FastAPI()
app.include_router(create_chat_router(chat_handler=my_llm_handler), prefix="/api/chat")
app.include_router(create_tts_router(endpoint_name="my-tts"), prefix="/api/tts")
app.include_router(create_asr_router(endpoint_name="my-asr"), prefix="/api/asr")
```

```yaml
# databricks.yml
variables:
  serving_endpoint:
    default: databricks-claude-sonnet-4-6
  tts_endpoint:
    default: my-tts-endpoint
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

## Repo Structure

```
databricks.yml           # DAB config — variables, targets, resources
foundation/              # Shared infrastructure (auth, lakebase, config, llm)
features/                # Feature modules (chat, voice, search, files, etc.)
examples/                # (planned) Runnable example apps composing features
docs/                    # Architecture, dependency map
```

## Docs

- [FEATURES.md](FEATURES.md) — Detailed per-feature documentation with API surfaces and code snippets
- [ARCHITECTURE.md](ARCHITECTURE.md) — Dependency graph, composition patterns, DAB variable reference

## Design Principles

- **Domain-agnostic** — No hardcoded business logic. Catalog names, endpoint names, space IDs, keywords — all parameterized.
- **DAB-native** — Designed for multi-target deployment (dev/staging/prod) via `databricks bundle deploy`.
- **Composable** — Features are additive. No feature assumes another is present unless listed in its dependency table.
- **FastAPI + React** — Backend is always FastAPI. Frontend is always React + TypeScript. One stack.
- **Honest about readiness** — Some modules are production-ready utilities. Others are reference architectures showing how to solve a class of problem. The catalog above is explicit about which is which.
