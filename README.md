# MEERA — Autonomous Personal AI Agent

```
================================================================================
MEERA (PERSONAL AI AGENT ARCHITECTURE)
Local-First // Zero Third-Party Web Dependencies // Resource-Conscious
Platform: Windows 10/11 (64-bit) // NVIDIA CUDA or CPU Inference
================================================================================
```

**Meera** is an autonomous, modular, local-first personal AI agent engineered to run efficiently on consumer Windows hardware. Built with a strict **zero third-party web dependency** rule, Meera uses Python's standard library for its networking, process lifecycle, persistent SQLite memory, and operating system bindings.

It provides a fast, privacy-first, OpenAI-compatible local API server alongside a built-in Obsidian Dark web console featuring a Top Floating Island, an Agent Command Center sidebar, and session persistence.

---

## ◈ Key Architectural Features

- **Local-First & Privacy-Preserving**: All reasoning, chat history, and long-term memory run 100% offline on your local machine. No telemetry or external cloud API calls.
- **Hardware-Adaptive RAM & VRAM Sentry**: Zero-overhead Windows memory checks via `ctypes.windll.kernel32.GlobalMemoryStatusEx` ensure safe model execution and prevent Out-Of-Memory (OOM) system freezes.
- **5-Minute Idle Auto-Unload**: Automatically unloads backend model inference processes after 300 seconds of inactivity, returning VRAM and system memory back to Windows.
- **Persistent SQLite Memory Engine**: Full multi-session persistence with SQLite WAL mode, automatic session titling, token budget enforcement, and long-term memory fact injection into context.
- **Universal OpenAI API Compatibility**: Exposes standard `/v1/chat/completions` and `/v1/models` endpoints, enabling drop-in integration with Open WebUI, Cursor, Continue, or custom AI frontends.
- **Standard Library Only Backend**: Built natively on Python standard library modules (`http.server`, `socketserver`, `sqlite3`, `ctypes`, `json`, `urllib`). No Flask, FastAPI, Uvicorn, or Node.js required.

---

## ⬡ Hardware Requirements

Meera is optimized for standard consumer laptops and desktops:

| Metric | Minimum Specification | Recommended Specification |
| :--- | :--- | :--- |
| **Operating System** | Windows 10 / 11 (64-bit) | Windows 11 (64-bit) |
| **System RAM** | 8 GB RAM (>= 2.0 GB free) | 16 GB+ RAM |
| **GPU / VRAM** | 4 GB VRAM (e.g. GTX 1650, RTX 2050/3050) | 6 GB+ VRAM (RTX 3060/4060+) or CPU fallback |
| **Python** | Python 3.10 or higher | Python 3.11 / 3.12 |
| **Inference Engine** | `llama.cpp` Windows build | `llama.cpp` Windows CUDA build |

---

## ▤ Project Structure

```
Meera/
├── agent/
│   ├── __init__.py
│   └── core.py               # Context window builder & session orchestrator
├── api/
│   ├── __init__.py
│   └── server.py             # Native ThreadedTCPServer, OpenAI API & SSE streamer
├── config/
│   ├── __init__.py
│   └── settings.py           # Hardware configs, model paths, RAM thresholds, ports
├── memory/
│   ├── __init__.py
│   ├── context.py            # Token budgeter, auto-titler, context summarizer
│   ├── models.py             # Dataclasses (Session, Message, LongTermMemory)
│   └── sqlite.py             # WAL SQLite engine & session CRUD
├── model/
│   ├── __init__.py
│   ├── llama_cpp.py          # llama-server subprocess manager & SSE client
│   ├── manager.py            # On-demand loader, Windows RAM sentry, idle reaper
│   └── provider.py           # Abstract Base Classes (ModelProvider, ChatMessage)
├── models/                   # Local GGUF model weights (gitignored)
├── runtime/llama.cpp/        # llama.cpp release binaries (gitignored)
├── storage/                  # SQLite persistent database (memory.db, gitignored)
├── ui/                       # Vanilla HTML/CSS/JS frontend interface
├── tests/                    # Unit and integration test suites
├── main.py                   # Main CLI & Server entry point
└── AGENTS.md                 # System specifications & roadmap
```

---

## ▲ Quick Start Guide

### 1. Clone the Repository
```powershell
git clone https://github.com/<your-username>/Meera.git
cd Meera
```

### 2. Set Up the `llama.cpp` Runtime
1. Download the latest Windows release from the official [llama.cpp Releases](https://github.com/ggerganov/llama.cpp/releases) (e.g., `llama-bXXXX-bin-win-cuda-cu12.x-x64.zip` for NVIDIA GPUs, or `llama-bXXXX-bin-win-cpu-x64.zip` for CPU only).
2. Extract the contents directly into the `runtime/llama.cpp/` folder so that `llama-server.exe` resides at `runtime/llama.cpp/llama-server.exe`.

### 3. Download a Supported GGUF Model
Download any compatible GGUF quantized model and place it in the `models/` directory:
- **Recommended Baseline**: [Qwen2.5-1.5B-Instruct-Q4_K_M.gguf](https://huggingface.co/Qwen) or [Qwen3-1.7B-Q4_K_M.gguf](https://huggingface.co/) (~1.2 GB, fits easily within 4 GB VRAM).
- **Larger Alternative**: `Qwen2.5-3B` or `Qwen2.5-7B` (for GPUs with 6 GB+ VRAM).

### 4. Configure Settings (Optional)
Edit [config/settings.py](file:///c:/Users/Arshit/Desktop/Overlord/Meera/config/settings.py) to match your model filename, context size, and CPU thread allocation:
```python
# In config/settings.py
MODELS = {
    "qwen3-1.7b": ModelConfig(
        name="Qwen3-1.7B-Q4_K_M",
        filename="Qwen3-1.7B-Q4_K_M.gguf",
        context_size=1024,
        gpu_layers=999,          # Set to 0 for CPU-only inference
        threads=4,               # Adjust based on your CPU core count
    ),
}
```

---

## ◈ Running Meera

### Mode A: Web UI & Local API Server
Start the server:
```powershell
python main.py --server
```
Once started:
- **Agent Web Console**: Navigate to `http://127.0.0.1:8000` in any web browser.
- **OpenAI API Base URL**: `http://127.0.0.1:8000/v1`
- **Health & Telemetry**: `http://127.0.0.1:8000/health`

### Mode B: Interactive Terminal CLI
For a fast, command-line streaming session without opening a browser:
```powershell
python main.py
```
Special commands available in terminal mode:
- `/status` — View available system RAM, VRAM state, and model status.
- `/reset` — Clear conversation context.
- `exit` or `q` — Shut down Meera cleanly.

---

## ⬡ External Client Integration

Meera is fully compatible with OpenAI-compatible clients and tools.

### Python Example
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="not-needed",
)

response = client.chat.completions.create(
    model="meera",
    messages=[
        {"role": "user", "content": "Explain quantum computing concisely."}
    ],
    stream=True,
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### Open WebUI / Cursor / Continue
- **Base URL**: `http://127.0.0.1:8000/v1`
- **API Key**: `meera` (or any string)
- **Model**: `meera` or `qwen3-1.7b`

---

## ▤ REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Serves the built-in Vanilla HTML/CSS/JS Agent Web Console |
| `/v1/chat/completions` | `POST` | OpenAI-compatible chat completion (streaming & non-streaming) |
| `/v1/models` | `GET` | Lists available local models |
| `/health` | `GET` | System health check (RAM headroom, model state, session count) |
| `/api/sessions` | `GET` | Lists persistent chat sessions |
| `/api/sessions` | `POST` | Creates a new chat session |
| `/api/sessions/<id>` | `GET` | Retrieves session transcript and summaries |
| `/api/sessions/<id>` | `DELETE` | Deletes a session and associated history |
| `/api/memories` | `GET` | Lists long-term memory facts |
| `/api/memories` | `POST` | Adds or updates long-term memory facts |

---

## ▲ Testing & Verification

Run the test suite to verify provider contracts, memory engines, and server routes:
```powershell
python -m unittest discover tests
```

---

## ⬡ Development Roadmap

- [x] **Phase 0: Runtime Verification & Model Baselines**
- [x] **Phase 1: Agent Core & Model Provider Architecture**
- [x] **Phase 2: User Interface & Command Center**
- [x] **Phase 3: SQLite Persistent Memory Engine**
- [ ] **Phase 4: Guardrailed Tool Execution Model** (READ / PREPARE / ACT permission tiers & MCP adapters)
- [ ] **Phase 5: Skills Engine & Multi-Agent Orchestration**

---

## ◈ License

MIT License. Free for personal, academic, and commercial exploration.
