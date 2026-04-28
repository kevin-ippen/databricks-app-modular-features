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

| Feature | Lines | Effort | Notes |
|---------|-------|--------|-------|
| **Voice I/O** | ~2,000 | Significant | Full voice conversation loop: VAD → ASR → streaming chat → sentence-level TTS → playback with interrupt. `speech_normalizer.py` and `audioUtils.ts` are production-ready standalone utilities. The conversation hook demonstrates the architecture — tune VAD, filler phrases, and playback for your UX. Requires TTS + ASR model serving endpoints. |
| **Chat** | ~2,100 | Moderate-High | SSE streaming backend + React hooks + UI components. The event protocol and `useChat` hook are the real value — solid and reusable. The React components (`ChatMessage`, `ChatInput`) are functional but bare-bones: no syntax highlighting, minimal styling. Build your own UI on top of the hook. |
| **Image Generation & Vision** | ~550 | Low-Moderate | FMAPI Responses API client for text-to-image, image-to-image, and vision analysis. Sync + async, FastAPI endpoints (generate, analyze, file upload), React hook + preview component. Requires an FMAPI endpoint supporting image generation (e.g., GPT-5.x). |
| **Genie Integration** | ~700 | Moderate | Multi-space routing + conversation polling. The Genie API interaction (start conversation → poll → extract results) is the hard part — this handles it. You bring your own space IDs and routing keywords. |
| **Agent Router** | ~1,050 | Significant | LangGraph supervisor with intent classification, retry, and agent exclusion. Reference architecture — provides the orchestration skeleton but **not** the agents themselves. Study the patterns, then build your own. |
| **RAG Retriever** | ~740 | Moderate | Multi-query decomposition + citation-aware response generation. The decomposition and citation logic are reusable. Configure your Vector Search index and tune the grounding prompt. |
| **Semantic Search** | ~660 | Significant | Architecture (filter extraction → query rewriting → VS → re-ranking) is the value — not the specific filters. Regex patterns, intent keywords, and ranking weights are generic placeholders you'll rewrite for your domain. Annotated blueprint. |
| **Conversation Memory** | ~280 | Low | Async memory layer with auto-summarization. Wire up your Lakebase connection and it works. One of the more plug-and-play features. |
| **Message Feedback** | ~385 | Low | Thumbs up/down on chat messages. Lakebase-backed upsert (one reaction per user per message), per-conversation aggregation, time-series stats. |
| **Knowledge Graph** | ~550 | Moderate | Entity/relationship CRUD with Lakebase. Storage and query layer is clean. The harder problem it doesn't solve is *extraction* — deciding what entities to create and when. |
| **File Processing** | ~770 | Low-Moderate | Multi-format parser (PDF/CSV/Excel/JSON/code) with schema detection. The parser is genuinely useful as-is. UC Volume storage layer needs your paths configured. |
| **Chart Auto-generation** | ~800 | Low | Frontend-only. Compiles SQL results into Vega-Lite specs with automatic chart type selection. 11 chart types, rule-based heuristics. No backend required. |
| **User Collections & Annotations** | ~480 | Moderate | Generic collection/annotation/preference CRUD backed by Lakebase. Domain-agnostic pattern: user-curated folders of items with inline notes, search history, and per-user settings. |
| **Data Table** | ~235 | Copy-paste | Sortable React table with type-aware cell formatting (money, percent, number, date). Column config via props, inline styles, zero CSS deps. |
| **Markdown Renderer** | ~100 | Copy-paste | react-markdown + remark-gfm + rehype-raw with CSS variable theming. Custom renderers for headings, code blocks, links, tables. Light/dark mode. |
| **Health Check** | ~60 | Copy-paste | `/health` endpoint with optional dependency checks (Lakebase, FMAPI, etc.). Returns healthy/degraded with per-check results. |

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
