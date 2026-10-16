# MEERA — AGENT ARCHITECTURE, CONSTRAINTS & PROJECT ROADMAP

```
================================================================================
MEERA (PERSONAL AI AGENT ARCHITECTURE)
Target: Windows 11 // ASUS TUF Gaming F17 // Local-First // Resource-Conscious
Specification: Zero Third-Party Web Dependencies // Pure Python Standard Library
================================================================================
```

---

## 1. Executive Summary & Vision

**Meera** is an autonomous, modular, local-first personal AI agent engineered from scratch to run efficiently on resource-constrained Windows hardware. Unlike heavy cloud-dependent systems or resource-bloated Python stacks, Meera adheres to a **zero third-party web dependency** rule, using Python's standard library for its networking, process lifecycle, persistent SQLite memory, and operating system bindings.

Meera provides a fast, privacy-preserving, OpenAI-compatible local API server alongside an interface built with clean Vanilla HTML/CSS/JS, featuring a Top Floating Island, an Agent Command Center sidebar, and an Obsidian Dark aesthetic.

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
4. **CPU Thread Allocation**: Inference threads are hard-capped at `4` threads, leaving 2 physical cores and 8 hyperthreads free for Windows desktop responsiveness and DWM.

---

## 3. Core Architectural Modules

```
Meera/
├── agent/
│   ├── __init__.py
│   └── core.py               # Context window builder & session orchestrator
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
├── permissions/
│   ├── __init__.py
│   ├── manager.py            # PermissionManager & confirmation token lifecycle
│   └── policy.py             # SecurityPolicy, workspace boundary guard & blocked command filters
├── docs/
│   ├── Meera_Project_Continuation_Document.docx
│   └── Meera_Project_Continuation_Document.pdf
├── skills/
│   ├── __init__.py
│   ├── manifest.py           # SkillManifest contract & prompt extension schema
│   ├── coding.py             # Code synthesis & architecture manifest
│   ├── academic.py           # Academic & research assistant manifest
│   ├── career.py             # Career strategist & interview manifest
│   ├── registry.py           # SkillRegistry, zero-overhead intent routing
│   ├── scheduler.py          # Background task worker daemon & recurring cron scheduler
│   ├── academic_surfer.py    # Zero-dependency LMS & calendar feed synchronizer
│   ├── teams_connector.py    # Microsoft OAuth2 Device Code connector & channel alert sentry
│   └── orchestrator.py       # MultiAgentOrchestrator & SubAgent context isolation
├── storage/
│   ├── library/              # Local persistent document vault (PDFs, lab manuals)
│   └── memory.db             # Local SQLite database (WAL mode, gitignored)
├── workspace/                # Isolated agent user workspace (sandbox for tasks/files)
├── tools/
│   ├── __init__.py
│   ├── base.py               # BaseTool ABC & ToolResult contract
│   ├── computational.py      # PREPARE tier: PythonEvalTool scratchpad
│   ├── filesystem.py         # READ tier: ListDirectoryTool, ReadFileTool, SearchFilesTool
│   ├── mcp.py                # Native JSON-RPC Model Context Protocol client adapter
│   ├── registry.py           # ToolRegistry, compact schema builder & execution dispatcher
│   └── system.py             # ACT tier: RunCommandTool shell executor
├── ui/
│   ├── assets/               # Deployed background artwork & assets
│   ├── app.js                # Session manager, SQLite API sync, SSE consumer, keyboard shortcuts
│   ├── index.html            # Top floating island, shrinkable sidebar command center, chat canvas
│   └── style.css             # Obsidian dark theme, typography tokens, fixed centered console dock
├── tests/
│   ├── __init__.py
│   ├── test_model.py         # Subprocess loader checks
│   ├── test_phase1.py        # Core contracts & RAM sentry tests
│   ├── test_phase2.py        # UI & OpenAI endpoint tests
│   ├── test_phase3.py        # SQLite persistent memory & context budget tests
│   ├── test_phase4.py        # Guardrailed tools, permissions & MCP tests
│   └── test_phase5.py        # Skills engine, cron task worker & multi-agent orchestrator tests
├── main.py                   # Main CLI & Server entry point
├── AGENTS.md                 # System specifications & project tracking
└── README.md                 # Engineering architecture & comprehensive documentation
```

---

## 4. Key Learnings & Architectural Insights

### A. Subprocess Lifecycle on Windows
- **Process Group Termination**: Standard `process.terminate()` on Windows can leave orphaned worker threads or GPU context handles. Always ensure full process shutdown to cleanly release VRAM.
- **Port Conflict Safeguards**: `llama-server.exe` runs on port `8081` by default while Meera API runs on `8000`. Socket bindings use `allow_reuse_address = True`.
- **Pre-Warming**: Running on-demand loading in a background thread on server startup completely eliminates the cold-start delay for the first user query while keeping the server responsive immediately.

### B. Token Budget Allocation (1024 Token Context Ceiling)
Because RTX 2050 has a 4 GB GDDR6 ceiling, context length is strictly capped at 1024 tokens. The context is partitioned deterministically:
- **System Persona**: ~120 tokens.
- **Long-Term Memory Injection**: ~100 tokens (up to 5 verified user facts/preferences).
- **Session Summary Checkpoint**: ~150 tokens (extractive or model-generated summary of prior turns).
- **Sliding Message Window**: ~350 tokens (last 6 turns preserved verbatim).
- **Generation Headroom**: ~300 tokens reserved for model output.
- **Token Estimation Heuristic**: Standard library approximation:
  `max(len(text)/3.5, len(text.split())*1.3) + 1`
  Avoids pulling heavy tokenizers into the Python process.

### C. SQLite Persistence & Multi-Threading
- **WAL Mode Engine**: Python's `sqlite3` must be configured with `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;` for concurrent reading while writing.
- **Threading Synchronization**: In a multi-threaded HTTP server (`socketserver.ThreadingMixIn`), transactions must be guarded with a `threading.RLock()` to prevent SQLite database lock errors.
- **Foreign Key Integrity**: `PRAGMA foreign_keys=ON;` enforces cascade deletions (`ON DELETE CASCADE`) so cleaning a session automatically purges messages and summaries.

### D. UI Layout & Centered Stability
- **Zero Horizontal Jitter**: The chat messages canvas and bottom console dock are fixed center-anchored (`left: 50%; transform: translateX(-50%)`). Toggling the sidebar (`Ctrl+B`) expands/collapses the navigation pane without displacing the user's typing focus.
- **Dual Persistence Strategy**: The UI synchronizes with the backend SQLite database (`/api/sessions`) and gracefully falls back to `localStorage` if the server is offline.
- **Chat Deletion Verification**: Permanent session removal requires affirmative confirmation dialog approval to prevent accidental message loss.
- **Pinned Conversations**: High-priority chats can be pinned to remain anchored at the top of the history index with dedicated visual status markers.
- **Project Workspaces & Chat Grouping**: Chats can be created inside or assigned to dedicated Projects (`projects` SQLite table & `/api/projects` REST endpoints). The sidebar automatically organizes and groups chats under their respective project cards with customizable color accents.
- **Chat Renaming**: Inline double-click and dedicated action button (`✎`) allow instant session title updates with immediate backend persistence via `POST /api/sessions/<id>/title`.

### E. Guardrailed Tool Execution & Compact Schemas
- **Compact Tool Signatures**: Standard JSON schema consumes hundreds of tokens. Meera uses a single-line signature format (`[READ] read_file(path*:string, max_lines:integer)`) to preserve headroom under the 1024 context ceiling.
- **Three-Tier Permission Enforcement**:
  - `READ`: Autonomous filesystem inspection constrained strictly within the workspace directory.
  - `PREPARE`: Sandboxed Python computational scratchpad with safe built-ins.
  - `ACT`: High-impact shell execution requiring affirmative confirmation token approval.
- **Native MCP Adapter**: Implements standard JSON-RPC 2.0 client over stdio pipes without third-party frameworks.

### F. Zero-Overhead Skills Engine & Intent Routing
- **Zero Token Footprint When Dormant**: Dormant skills consume 0 tokens from the system context window. Only when activated explicitly or auto-detected does the agent inject ~60-80 tokens of focused behavioral guidelines.
- **Lightweight Intent Heuristic**: Keyword scoring routes queries to specialized domains (e.g. coding, academic research, career) without requiring an extra LLM classification turn.

### G. Multi-Agent Context Isolation & Orchestrator
- **Dedicated Sub-Agent Contexts**: Multi-agent tasks run in independent `SubAgent` contexts rather than cramming multiple personas into one 1024-token prompt.
- **Synthesis Aggregator**: `MultiAgentOrchestrator` coordinates sequential or parallel sub-agent workers and synthesizes their observations into a single executive briefing.

### H. Lightweight Background Task Worker & Cron Scheduler
- **Zero-Dependency Daemon Threading**: Uses a single daemon worker thread with `threading.Event(1.0)` sleep checks to run recurring cron jobs, heartbeats, and one-shot delay timers.
- **Minimal CPU Footprint**: Zero busy waiting, negligible CPU cycles, and instant cancellation.

### I. Microsoft Device Code OAuth2 & Academic Channel Sentry
- **RFC 8628 Flow**: Implemented entirely via standard library `urllib.request` with zero third-party Azure SDKs. Seamless authentication via official Microsoft client ID.
- **Silent Token Renewal**: Background worker silently refreshes access tokens before expiration, maintaining continuous synchronization without user re-authentication.
- **Channel Announcement Sentry**: Scans enrolled class channels and routes high-priority notices (exams, schedule changes) directly to the Alerts tab with deduplication.

### J. Knowledge Library Vault & Document Context Injection
- **Local Persistent Vault**: Standalone storage (`storage/library/`) for course syllabi, lab manuals, and research PDFs.
- **Zero-Dependency File Handling**: Pure standard library base64 encoding/decoding and MIME type detection.
- **Ask Meera Integration**: One-click prompt context injection allows instant semantic query and summarization of uploaded documents within the active chat session.

### K. 90-Day Academic Retention Policy & Vendor-Neutral Design
- **Automated Retention Sentry**: Prunes academic records older than 90 days and filters out past academic years (`2024`, `2025`, `24-25`) to keep the calendar matrix relevant and fast.
- **Vendor-Neutral Terminology**: Clean decoupling of UI and API labels (`Coursework`, `Assignments`, `Refresh`, `Sync`) ensures flexibility across different LMS and institutional platforms.

---

## 5. Design Principles & Style Guidelines

1. **Zero Emojis**: Strictly prohibited across the entire project (UI, terminal logs, code comments, and documentation). Use classic typographic glyphs (`◈`, `⬡`, `▤`, `◷`, `▲`, `[UI]`, `[API]`, `[STATUS]`) to preserve a luxury, professional brand feel.
2. **Zero Third-Party Web Frameworks**: No Flask, FastAPI, Uvicorn, or Node.js. The HTTP server is built natively on `http.server` and `socketserver.ThreadingMixIn`.
3. **Rock-Solid Centered UI Layout**: The chat messages container and bottom input console dock are center-anchored (`left: 50%; transform: translateX(-50%)`). Expanding or collapsing the sidebar will never shift the typing input box horizontally.
4. **Authentic Dark Mode Aesthetics**: Frosted glass panels (`rgba(12, 16, 26, 0.95)` with `backdrop-filter`), high-contrast typography (`0.98rem`, line-height `1.74`), and ambient background artwork with edge fading.
5. **Lightweight & Resource-Efficiency First (Core Directive)**: Whenever creating any tool or skill for Meera, the foremost priority is to make it as lightweight, minimal-overhead, and resource-efficient as possible, while maintaining strict industry-standard and professional engineering. Avoid bloat, preserve system memory and VRAM, and minimize token footprint under the 1024 context budget.
6. **Strict Workspace Sandboxing & Protected Path Isolation**: The agent's filesystem inspection and terminal execution are strictly sandboxed within the dedicated `workspace/` directory. The agent is explicitly forbidden from accessing, listing, or reading internal engine components, including `models/`, `runtime/`, `storage/`, `.git/`, and `AGENTS.md`.

---

## 6. Development Roadmap & Phase Status

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

- [x] **Phase 4: Guardrailed Tool Execution Model**
  - Three-tier permission architecture:
    - **READ**: Filesystem inspection within workspace (autonomous).
    - **PREPARE**: Python REPL computational scratchpad (sandboxed).
    - **ACT**: Shell command execution (requires explicit confirmation).
  - Native Model Context Protocol (MCP) client adapter (`tools/mcp.py`).
  - Tool execution feedback loops streamed directly into chat canvas.
  - REST endpoints for tool discovery and token approvals (`/api/tools`, `/api/tools/execute`, `/api/tools/approve`).

- [x] **Phase 5: Skills Engine & Multi-Agent Orchestration**
  - Skill manifests (Academic research, Code synthesis, Career strategist).
  - SkillRegistry with zero-token overhead when dormant and keyword intent auto-routing.
  - Background task worker daemon and recurring cron job scheduler (`TaskScheduler`).
  - Multi-agent orchestration protocol (`SubAgent`, `MultiAgentOrchestrator`) with isolated contexts.
  - REST endpoints for skills, tasks, and orchestration delegation (`/api/skills`, `/api/skills/activate`, `/api/tasks`, `/api/orchestrator/delegate`).

- [x] **Phase 6: Academic Surfer & Interactive Calendar Engine**
  - Zero-dependency LMS & Microsoft Teams calendar and assignments synchronizer (`skills/academic_surfer.py`).
  - Standard iCalendar (`.ics`/`webcal`) parser, authenticated session cookie support, and baseline fallback generator.
  - Interactive Month Calendar grid with day cells displaying event chips and platform color coding.
  - Platform-grouped upcoming task list (College LMS vs MS Teams) with courses/teams, due timestamps, priorities, and checkboxes.
  - Dedicated user-triggered synchronization button and REST endpoints (`/api/schedules/deadlines`, `/api/schedules/sync`, `/api/schedules/config`).

- [x] **Phase 7: Plugins Ecosystem & Knowledge Library Vault**
  - Connector Hub for College LMS, Microsoft Teams, GitHub, and Model Context Protocol (`/api/plugins`).
  - Local persistent document archive for PDFs, lab manuals, and course notes (`storage/library/` & `/api/library`).
  - Drag-and-drop document upload with pure standard-library base64 and binary handling.
  - Integrated "Ask Meera" document context injection for direct conversational analysis.

- [x] **Phase 8: Microsoft Teams Device Code Connector & Channel Announcement Sentry**
  - Free, zero-dependency Microsoft Device Code OAuth2 flow (`skills/teams_connector.py`) via standard library `urllib`.
  - Microsoft Graph Education Assignments synchronization directly into Schedules calendar view.
  - Course Channel Announcement Sentry scanning professor notices for exams, deadlines, and schedule changes into the Alerts tab.
  - Persistent token lifecycle with silent background renewal and local SQLite alerts archive (`teams_alerts`).
  - Integrated UI controls in Plugins configuration modal and interactive Alerts dropdown.

- [x] **Phase 9: Codebase Optimization, System Hardening & Vendor-Neutral UI**
  - Strict 90-day academic cutoff sentry and automated legacy year (`2024`, `2025`, `24-25`) purging in SQLite WAL database.
  - Complete vendor-neutral interface decoupling (`Coursework`, `Assignments`, `Refresh`, `Sync`).
  - Robust error handling and data resolution in streaming Web UI.
  - Dead code elimination, module cleanup, and comprehensive unit tests for `ModelManager` and `ModelProvider`.

