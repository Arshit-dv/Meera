# MEERA — AGENT ARCHITECTURE, CONSTRAINTS & PROJECT ROADMAP

```
================================================================================
MEERA (PERSONAL AI AGENT ARCHITECTURE)
Target: Windows 11 // ASUS TUF Gaming F17 // Local-First // Resource-Conscious
================================================================================
```

---

## 1. Executive Summary & Vision

**Meera** is an autonomous, modular, local-first personal AI agent engineered from scratch to run efficiently on resource-constrained Windows hardware. Unlike heavy cloud-dependent systems or resource-bloated Python stacks, Meera adheres to a **zero third-party web dependency** rule, using Python's standard library for its networking, process lifecycle, and operating system bindings.

Meera provides a fast, privacy-preserving, OpenAI-compatible local API server alongside an interface built with clean Vanilla HTML/CSS/JS, featuring a Top Floating Island, an Agent Command Center sidebar, and a classic, professional dark aesthetic.

---

## 2. Hardware Constraints & Operational Guardrails

All architecture decisions in Meera are strictly tailored to the host system profile:

| Metric / Component | Specification | Operational Constraint |
| :--- | :--- | :--- |
| **Machine** | ASUS TUF Gaming F17 | Windows 11 64-bit |
| **CPU** | Intel Core i5-11400H @ 2.70GHz | 6 Cores, 12 Threads (Thread allocation capped at 4) |
| **System RAM** | ~7.73 GiB Usable | Model loading blocked if available RAM < 2.0 GiB |
| **GPU / VRAM** | NVIDIA GeForce RTX 2050 (4 GB GDDR6) | Dedicated VRAM budget: ~2.5 GB max for weights + KV cache |
| **CUDA Driver** | CUDA 12.4 | `llama-server.exe` (CUDA 12 release build) |

### Memory & Process Guardrails
1. **Native Windows RAM Sentry**: Uses `ctypes.windll.kernel32.GlobalMemoryStatusEx` for zero-overhead, sub-millisecond RAM checks.
2. **5-Minute Idle Auto-Unload**: If no generation requests are received for 300 seconds, `ModelManager` unloads `llama-server.exe` to return ~1.5 GB VRAM and system memory back to Windows.
3. **Context Length Ceiling**: Context is locked at **1024 tokens** to prevent KV-cache VRAM explosion on the RTX 2050. `AgentCore` enforces a multi-turn sliding window history.

---

## 3. Core Architectural Modules

```
Meera/
├── agent/
│   ├── __init__.py
│   └── core.py               # Conversation context, sliding window, chat generation
├── api/
│   ├── __init__.py
│   └── server.py             # ThreadedTCPServer, OpenAI endpoint, SSE streamer, asset deployer
├── config/
│   ├── __init__.py
│   └── settings.py           # Hardware configs, model paths, RAM thresholds, port mappings
├── memory/
│   ├── __init__.py
│   ├── context.py            # Token estimator, auto-titler, summarizer, context builder
│   ├── models.py             # Dataclasses (Session, Message, SessionSummary, LongTermMemory)
│   └── sqlite.py             # WAL SQLite engine, thread-safe session & memory CRUD
├── model/
│   ├── __init__.py
│   ├── llama_cpp.py          # llama-server subprocess manager & streaming SSE client
│   ├── manager.py            # On-demand loader, Windows memory checker, auto-idle reaper
│   └── provider.py           # Abstract Base Classes (ModelProvider, ChatMessage, StreamChunk)
├── storage/
│   └── memory.db             # Local SQLite database (WAL mode)
├── ui/
│   ├── assets/               # Deployed background artwork & assets
│   ├── app.js                # Session manager, SQLite API sync, SSE consumer, keyboard shortcuts
│   ├── index.html            # Top floating island, shrinkable sidebar command center, chat canvas
│   └── style.css             # Obsidian dark theme, typography tokens, fixed centered console dock
├── main.py                   # Main CLI & Server entry point
└── AGENTS.md                 # System specifications & project tracking
```

---

## 4. Design Principles & Style Guidelines

1. **Zero Emojis**: Strictly prohibited across the entire project (UI, terminal logs, code comments, and documentation). Use classic typographic glyphs (`◈`, `⬡`, `▤`, `◷`, `▲`, `[UI]`, `[API]`, `[STATUS]`) to preserve a luxury, professional brand feel.
2. **Zero Third-Party Web Frameworks**: No Flask, FastAPI, Uvicorn, or Node.js. The HTTP server is built natively on `http.server` and `socketserver.ThreadingMixIn`.
3. **Rock-Solid Centered UI Layout**: The chat messages container and bottom input console dock are center-anchored (`left: 50%; transform: translateX(-50%)`). Expanding or collapsing the sidebar will never shift the typing input box horizontally.
4. **Authentic Dark Mode Aesthetics**: Frosted glass panels (`rgba(12, 16, 26, 0.95)` with `backdrop-filter`), high-contrast typography (`0.98rem`, line-height `1.74`), and ambient background artwork with edge fading.

---

## 5. Development Roadmap & Phase Status

- [x] **Phase 0: Runtime Verification & Model Baselines**
  - Confirmed `llama.cpp` CUDA 12 execution on RTX 2050.
  - Locked `Qwen3-1.7B-Q4_K_M.gguf` as default baseline model at 1024 context.

- [x] **Phase 1: Agent Core & Model Provider Architecture**
  - Built abstract provider contract (`model/provider.py`).
  - Implemented `LlamaCppServerProvider` subprocess lifecycle manager.
  - Created `ModelManager` with native Windows RAM detection and auto-idle unloading.
  - Implemented `AgentCore` with 1024-token sliding window context builder.
  - Created OpenAI-compatible HTTP server (`/v1/chat/completions`, `/v1/models`, `/health`).

- [x] **Phase 2: User Interface & Command Center**
  - Developed full Web UI with streaming token-by-token SSE parsing.
  - Implemented Top Floating Island (Skills, Tools, Files, Telemetry status).
  - Built Agent Command Center sidebar with Chats, Tasks, Schedules, and Alerts tabs.
  - Pinned center-anchored typing dock with zero horizontal jitter on sidebar toggle (`Ctrl+B`).
  - Integrated Ethereal Monochrome ambient background artwork.

- [x] **Phase 3: SQLite Persistent Memory Engine**
  - Local SQLite database schema (`storage/memory.db`) with WAL mode and foreign keys.
  - Multi-session chat persistence, metadata tagging, and auto-title generation.
  - Token budget sentry and periodic context summarization to prevent 1024-token overflow.
  - Long-term memory store (user preferences, facts, project context) injected into system prompt.
  - REST endpoints for sessions (`/api/sessions`) and long-term memories (`/api/memories`).

- [ ] **Phase 4: Guardrailed Tool Execution Model**
  - Three-tier permission architecture:
    - **READ**: Filesystem inspection within workspace (autonomous).
    - **PREPARE**: Python REPL computational scratchpad (sandboxed).
    - **ACT**: Shell command execution (requires explicit confirmation).
  - Native Model Context Protocol (MCP) client adapter.

- [ ] **Phase 5: Skills Engine & Multi-Agent Orchestration**
  - Skill manifests (Academic research, Code synthesis, Career strategist).
  - Background task worker and recurring cron job scheduler.
