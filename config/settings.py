"""
Meera - Configuration Settings
Defines hardware, model, paths, and runtime parameters.
"""
from dataclasses import dataclass
from pathlib import Path
import sys

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
RUNTIME_DIR = BASE_DIR / "runtime" / "llama.cpp"
LOGS_DIR = BASE_DIR / "logs"
CACHE_DIR = BASE_DIR / "cache"
STORAGE_DIR = BASE_DIR / "storage"
MEMORY_DB_PATH = STORAGE_DIR / "memory.db"
WORKSPACE_DIR = BASE_DIR / "workspace"


@dataclass(frozen=True)
class ModelConfig:
    name: str
    filename: str
    context_size: int = 1024
    gpu_layers: int = 999          # Full GPU offload for RTX 2050
    threads: int = 4               # 4 cores for inference, leaves 2 physical cores free for Windows
    min_ram_free_mb: int = 500     # Minimum free system RAM needed to load safely
    flash_attn: bool = True        # FlashAttention for Ampere/Turing architectures
    batch_size: int = 512          # Prompt processing batch size
    ubatch_size: int = 256         # Micro-batch size for smooth throughput
    cache_type_k: str = "q8_0"     # Quantized KV cache keys to save VRAM bandwidth
    cache_type_v: str = "q8_0"     # Quantized KV cache values to save VRAM bandwidth


@dataclass(frozen=True)
class ServerConfig:
    llama_host: str = "127.0.0.1"
    llama_port: int = 8081
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    idle_timeout_seconds: int = 300  # Auto-unload after 5 minutes of inactivity
    prewarm: bool = True             # Pre-load model on startup to eliminate first-prompt delay


@dataclass(frozen=True)
class MemoryConfig:
    db_path: Path = MEMORY_DB_PATH
    max_sliding_window_turns: int = 6        # Last 6 messages preserved verbatim
    context_token_ceiling: int = 1024        # Hard context ceiling
    auto_summarize_threshold: int = 8        # Trigger context summary when history exceeds 8 turns
    max_long_term_memories_inject: int = 5    # Top long-term memories injected into prompt


# Available models in Meera
MODELS = {
    "qwen3-1.7b": ModelConfig(
        name="Qwen3-1.7B-Q4_K_M",
        filename="Qwen3-1.7B-Q4_K_M.gguf",
        context_size=1024,
        gpu_layers=999,
        threads=4,
        min_ram_free_mb=400,
        flash_attn=True,
        batch_size=512,
        ubatch_size=256,
        cache_type_k="q8_0",
        cache_type_v="q8_0",
    ),
    "qwen3-4b": ModelConfig(
        name="Qwen3-4B-Q4_K_M",
        filename="Qwen3-4B-Q4_K_M.gguf",
        context_size=1024,
        gpu_layers=999,
        threads=4,
        min_ram_free_mb=800,
        flash_attn=True,
        batch_size=512,
        ubatch_size=256,
        cache_type_k="q8_0",
        cache_type_v="q8_0",
    ),
}

# Default Active Model Selection
DEFAULT_MODEL_KEY = "qwen3-1.7b"

# Agent Personality / System Prompt
DEFAULT_SYSTEM_PROMPT = (
    "You are Meera, a local-first, resource-conscious, capable personal AI agent. "
    "You are precise, helpful, and concise in reasoning, coding, and everyday tasks."
)
