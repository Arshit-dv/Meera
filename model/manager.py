"""
Meera - Model and Resource Manager
Enforces resource awareness, RAM headroom checks, on-demand loading, and idle auto-unloading.
"""
import ctypes
import logging
import threading
import time
from typing import Any, Dict, Iterator, Optional

from config.settings import (
    DEFAULT_MODEL_KEY,
    MODELS,
    ModelConfig,
    ServerConfig,
)
from model.llama_cpp import LlamaCppServerProvider
from model.provider import GenerationRequest, GenerationResponse, ModelProvider, StreamChunk

logger = logging.getLogger("meera.model.manager")


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_available_ram_mb() -> int:
    """Returns available physical RAM in MiB on Windows without external dependencies."""
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullAvailPhys / (1024 * 1024))
    except Exception as e:
        logger.warning(f"Could not read Windows memory status: {e}")
    return 2048  # Safe fallback estimate


class ModelManager:
    """
    Manages model selection, resource headroom validation, on-demand lifecycle,
    and idle unloading.
    """

    def __init__(
        self,
        default_model_key: str = DEFAULT_MODEL_KEY,
        server_config: Optional[ServerConfig] = None,
    ):
        self.server_config = server_config or ServerConfig()
        self.active_model_key = default_model_key
        self.active_config: ModelConfig = MODELS.get(default_model_key, MODELS[DEFAULT_MODEL_KEY])
        self._provider: Optional[ModelProvider] = None
        self._last_used_timestamp: float = 0.0
        self._lock = threading.Lock()
        self._cleanup_timer: Optional[threading.Timer] = None

    def _get_provider(self) -> ModelProvider:
        if self._provider is None:
            self._provider = LlamaCppServerProvider(
                model_config=self.active_config,
                server_config=self.server_config,
            )
        return self._provider

    def check_resources(self, model_config: Optional[ModelConfig] = None) -> Dict[str, Any]:
        """Checks if current RAM headroom is sufficient for the target model."""
        config = model_config or self.active_config
        avail_ram = get_available_ram_mb()
        safe = avail_ram >= config.min_ram_free_mb
        return {
            "available_ram_mb": avail_ram,
            "required_min_ram_mb": config.min_ram_free_mb,
            "safe_to_load": safe,
            "model_name": config.name,
        }

    def ensure_loaded(self) -> bool:
        """Ensures the active model is loaded, verifying memory headroom first."""
        with self._lock:
            provider = self._get_provider()
            if provider.is_loaded():
                self._touch()
                return True

            resource_status = self.check_resources()
            if not resource_status["safe_to_load"]:
                logger.warning(
                    f"Insufficient RAM to load {self.active_config.name}. "
                    f"Available: {resource_status['available_ram_mb']}MB, Required: {resource_status['required_min_ram_mb']}MB"
                )
                # If currently on 4B and out of RAM, fallback to 1.7B
                if self.active_model_key != "qwen3-1.7b":
                    logger.info("Falling back to lightweight model qwen3-1.7b...")
                    self.switch_model("qwen3-1.7b")
                    provider = self._get_provider()

            success = provider.load()
            if success:
                self._touch()
                self._schedule_idle_check()
            return success

    def switch_model(self, model_key: str) -> bool:
        """Switches the active model, unloading any current instance first."""
        with self._lock:
            if model_key not in MODELS:
                raise ValueError(f"Unknown model key: {model_key}. Available: {list(MODELS.keys())}")

            if model_key == self.active_model_key and self._provider and self._provider.is_loaded():
                return True

            self.unload()
            self.active_model_key = model_key
            self.active_config = MODELS[model_key]
            self._provider = LlamaCppServerProvider(
                model_config=self.active_config,
                server_config=self.server_config,
            )
            return True

    def unload(self) -> bool:
        """Unloads the active model to free RAM/VRAM."""
        with self._lock:
            if self._cleanup_timer:
                self._cleanup_timer.cancel()
                self._cleanup_timer = None

            if self._provider:
                res = self._provider.unload()
                self._provider = None
                return res
            return True

    def _touch(self) -> None:
        self._last_used_timestamp = time.time()

    def _schedule_idle_check(self) -> None:
        if self._cleanup_timer:
            self._cleanup_timer.cancel()

        def _check_idle():
            with self._lock:
                idle_time = time.time() - self._last_used_timestamp
                if idle_time >= self.server_config.idle_timeout_seconds:
                    logger.info(f"Model idle for {int(idle_time)}s. Auto-unloading to free memory.")
                    if self._provider:
                        self._provider.unload()
                        self._provider = None
                else:
                    # Reschedule remaining time
                    remaining = self.server_config.idle_timeout_seconds - idle_time
                    self._cleanup_timer = threading.Timer(max(remaining, 10), _check_idle)
                    self._cleanup_timer.daemon = True
                    self._cleanup_timer.start()

        self._cleanup_timer = threading.Timer(self.server_config.idle_timeout_seconds, _check_idle)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Resource-safe generation."""
        if not self.ensure_loaded():
            raise RuntimeError("Could not load model due to resource constraints or startup error.")
        self._touch()
        provider = self._get_provider()
        return provider.generate(request)

    def stream(self, request: GenerationRequest) -> Iterator[StreamChunk]:
        """Resource-safe streaming generation."""
        if not self.ensure_loaded():
            raise RuntimeError("Could not load model due to resource constraints or startup error.")
        self._touch()
        provider = self._get_provider()
        for chunk in provider.stream(request):
            yield chunk
        self._touch()

    def health(self) -> Dict[str, Any]:
        """Returns runtime, model, and memory health status."""
        avail_ram = get_available_ram_mb()
        provider_health = self._provider.health() if self._provider else {
            "loaded": False,
            "model": self.active_config.name,
            "backend": "llama.cpp",
        }
        return {
            "active_model": self.active_model_key,
            "available_ram_mb": avail_ram,
            "provider": provider_health,
        }
