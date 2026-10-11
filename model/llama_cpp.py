"""
Meera - llama.cpp Runtime Provider
Manages the llama-server subprocess and handles inference over standard HTTP endpoints.
"""
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, Optional

from config.settings import LOGS_DIR, MODELS_DIR, RUNTIME_DIR, ModelConfig, ServerConfig
from model.provider import ChatMessage, GenerationRequest, GenerationResponse, ModelProvider, StreamChunk

logger = logging.getLogger("meera.model.llama_cpp")


class LlamaCppServerProvider(ModelProvider):
    """
    ModelProvider implementation that manages llama-server.exe as a background process.
    Uses standard library urllib (no third-party dependencies required).
    """

    def __init__(self, model_config: ModelConfig, server_config: Optional[ServerConfig] = None):
        self.model_config = model_config
        self.server_config = server_config or ServerConfig()
        self.server_exe = RUNTIME_DIR / "llama-server.exe"
        self.model_file = MODELS_DIR / model_config.filename
        self._process: Optional[subprocess.Popen] = None
        self._base_url = f"http://{self.server_config.llama_host}:{self.server_config.llama_port}"

    def load(self) -> bool:
        """Starts the llama-server process and waits until it is ready."""
        if self.is_loaded():
            logger.info("llama-server is already running.")
            return True

        if not self.server_exe.exists():
            raise FileNotFoundError(f"llama-server executable not found at {self.server_exe}")
        if not self.model_file.exists():
            raise FileNotFoundError(f"Model file not found at {self.model_file}")

        cmd = [
            str(self.server_exe),
            "-m", str(self.model_file),
            "-c", str(self.model_config.context_size),
            "-ngl", str(self.model_config.gpu_layers),
            "-t", str(self.model_config.threads),
            "--host", self.server_config.llama_host,
            "--port", str(self.server_config.llama_port),
        ]

        logger.info(f"Starting llama-server with model {self.model_config.name} (ctx: {self.model_config.context_size})...")

        # Windows-specific flags to prevent popup windows
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file_path = LOGS_DIR / "llama_server.log"
        self._log_file = open(log_file_path, "w", encoding="utf-8")

        self._process = subprocess.Popen(
            cmd,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

        # Wait for server readiness
        max_attempts = 40
        for attempt in range(max_attempts):
            time.sleep(0.5)
            if self._check_health():
                logger.info("llama-server is ready and healthy.")
                return True
            if self._process.poll() is not None:
                logger.error("llama-server process exited unexpectedly. Check logs/llama_server.log for details.")
                self._process = None
                return False

        logger.error("Timed out waiting for llama-server to become ready.")
        self.unload()
        return False

    def unload(self) -> bool:
        """Stops the llama-server process and frees resources."""
        if self._process is not None:
            logger.info("Stopping llama-server process...")
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except (subprocess.TimeoutExpired, Exception):
                self._process.kill()
            finally:
                self._process = None
                if hasattr(self, "_log_file") and self._log_file:
                    try:
                        self._log_file.close()
                    except Exception:
                        pass
                    self._log_file = None
            logger.info("llama-server stopped.")
            return True
        return True

    def is_loaded(self) -> bool:
        if self._process is None:
            return False
        if self._process.poll() is not None:
            self._process = None
            return False
        return self._check_health()

    def _check_health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._base_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("status") in ("ok", "loading model")
        except Exception:
            return False

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Executes non-streaming chat completion."""
        if not self.is_loaded():
            if not self.load():
                raise RuntimeError("Failed to load model runtime.")

        url = f"{self._base_url}/v1/chat/completions"
        payload = {
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.stop:
            payload["stop"] = request.stop

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                choice = result["choices"][0]
                content = choice["message"]["content"]
                finish_reason = choice.get("finish_reason", "stop")
                usage = result.get("usage", {})
                return GenerationResponse(content=content, finish_reason=finish_reason, usage=usage)
        except urllib.error.URLError as e:
            logger.error(f"Error communicating with llama-server: {e}")
            raise RuntimeError(f"Inference error: {e}")

    def stream(self, request: GenerationRequest) -> Iterator[StreamChunk]:
        """Streams chat completion chunk by chunk."""
        if not self.is_loaded():
            if not self.load():
                raise RuntimeError("Failed to load model runtime.")

        url = f"{self._base_url}/v1/chat/completions"
        payload = {
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        if request.stop:
            payload["stop"] = request.stop

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for line in resp:
                    decoded = line.decode("utf-8").strip()
                    if not decoded or not decoded.startswith("data:"):
                        continue
                    data_str = decoded[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_json = json.loads(data_str)
                        choices = chunk_json.get("choices", [])
                        if choices:
                            delta_content = choices[0].get("delta", {}).get("content", "")
                            finish_reason = choices[0].get("finish_reason")
                            if delta_content or finish_reason:
                                yield StreamChunk(delta=delta_content, finish_reason=finish_reason)
                    except json.JSONDecodeError:
                        continue
        except urllib.error.URLError as e:
            logger.error(f"Streaming error with llama-server: {e}")
            raise RuntimeError(f"Streaming error: {e}")

    def health(self) -> Dict[str, Any]:
        loaded = self.is_loaded()
        return {
            "backend": "llama.cpp",
            "model": self.model_config.name,
            "loaded": loaded,
            "context_size": self.model_config.context_size,
            "gpu_layers": self.model_config.gpu_layers,
            "endpoint": self._base_url,
        }
