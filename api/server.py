"""
Meera - Agent API Server
Exposes OpenAI-compatible endpoints (/v1/chat/completions, /v1/models),
Meera Agent endpoints, and SQLite Persistent Memory endpoints (/api/sessions, /api/memories)
using standard library http.server (zero third-party dependencies).
"""
import http.server
import json
import logging
from pathlib import Path
import socketserver
import time
import urllib.parse
from typing import Any, Dict

from agent.core import AgentCore
from config.settings import BASE_DIR, DEFAULT_MODEL_KEY, ServerConfig

logger = logging.getLogger("meera.api.server")


class MeeraAPIRequestHandler(http.server.BaseHTTPRequestHandler):
    agent_core: AgentCore = None
    server_config: ServerConfig = None

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        response_bytes = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Built-in Web UI Static Files
        if path in ("/", "/index.html"):
            ui_index = BASE_DIR / "ui" / "index.html"
            if ui_index.exists():
                with open(ui_index, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        if path.startswith("/ui/"):
            rel_path = path[4:].lstrip("/")
            if rel_path.endswith("sketch_bg.jpg"):
                ensure_assets()
            file_path = (BASE_DIR / "ui" / rel_path).resolve()
            if str(file_path).startswith(str((BASE_DIR / "ui").resolve())) and file_path.exists():
                mime_type = "text/plain"
                if file_path.suffix == ".css":
                    mime_type = "text/css"
                elif file_path.suffix == ".js":
                    mime_type = "application/javascript"
                elif file_path.suffix == ".html":
                    mime_type = "text/html"
                elif file_path.suffix == ".svg":
                    mime_type = "image/svg+xml"
                elif file_path.suffix in (".jpg", ".jpeg"):
                    mime_type = "image/jpeg"
                elif file_path.suffix == ".png":
                    mime_type = "image/png"
                elif file_path.suffix == ".webp":
                    mime_type = "image/webp"
                elif file_path.suffix == ".ico":
                    mime_type = "image/x-icon"

                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        # 2. Health & Telemetry
        if path in ("/health", "/api/health"):
            status = self.agent_core.status()
            self._send_json(200, {"status": "ok", "meera": status})
            return

        # 3. OpenAI Models Endpoint
        if path == "/v1/models":
            models_data = {
                "object": "list",
                "data": [
                    {
                        "id": "meera",
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "meera-agent",
                    },
                    {
                        "id": DEFAULT_MODEL_KEY,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "meera-agent",
                    },
                ],
            }
            self._send_json(200, models_data)
            return

        # 4. Memory API - List Sessions
        if path == "/api/sessions":
            limit = int(query.get("limit", [50])[0])
            offset = int(query.get("offset", [0])[0])
            archived = query.get("include_archived", ["false"])[0].lower() == "true"
            sessions = self.agent_core.memory_store.list_sessions(limit=limit, offset=offset, include_archived=archived)
            self._send_json(200, {
                "sessions": [s.to_dict() for s in sessions],
                "active_session_id": self.agent_core.active_session_id,
            })
            return

        # 5. Memory API - Get Specific Session & Messages
        if path.startswith("/api/sessions/"):
            session_id = path[len("/api/sessions/"):].strip("/")
            session = self.agent_core.memory_store.get_session(session_id)
            if not session:
                self._send_json(404, {"error": f"Session '{session_id}' not found"})
                return
            messages = self.agent_core.memory_store.get_messages(session_id)
            summary = self.agent_core.memory_store.get_latest_summary(session_id)
            self._send_json(200, {
                "session": session.to_dict(),
                "messages": [m.to_dict() for m in messages],
                "summary": summary.to_dict() if summary else None,
            })
            return

        # 6. Memory API - Long-Term Memories
        if path == "/api/memories":
            category = query.get("category", [None])[0]
            memories = self.agent_core.memory_store.list_long_term_memories(category=category)
            self._send_json(200, {"memories": [m.to_dict() for m in memories]})
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/reset":
            session_id = payload.get("session_id")
            self.agent_core.reset_conversation(session_id=session_id)
            self._send_json(200, {
                "status": "Conversation reset",
                "active_session_id": self.agent_core.active_session_id,
            })
            return

        # Create New Session
        if path == "/api/sessions":
            title = payload.get("title", "New Conversation")
            custom_id = payload.get("session_id")
            metadata = payload.get("metadata", {})
            session = self.agent_core.memory_store.create_session(session_id=custom_id, title=title, metadata=metadata)
            self.agent_core.active_session_id = session.id
            self._send_json(201, {"session": session.to_dict()})
            return

        # Manage Long-Term Memories
        if path == "/api/memories":
            category = payload.get("category", "fact")
            key = payload.get("key", "").strip()
            value = payload.get("value", "").strip()
            confidence = float(payload.get("confidence", 1.0))
            if not key or not value:
                self._send_json(400, {"error": "Fields 'key' and 'value' are required"})
                return
            mem = self.agent_core.memory_store.set_long_term_memory(
                category=category,
                key=key,
                value=value,
                confidence=confidence,
                source_session_id=payload.get("session_id"),
            )
            self._send_json(200, {"memory": mem.to_dict()})
            return

        # Update Session Title
        if path.startswith("/api/sessions/") and path.endswith("/title"):
            session_id = path[len("/api/sessions/"): -len("/title")].strip("/")
            title = payload.get("title", "").strip()
            if not title:
                self._send_json(400, {"error": "Missing 'title' field"})
                return
            ok = self.agent_core.memory_store.update_session(session_id, title=title)
            if ok:
                self._send_json(200, {"status": "ok", "session_id": session_id, "title": title})
            else:
                self._send_json(404, {"error": "Session not found"})
            return

        if path == "/api/chat":
            message = payload.get("message", "")
            if not message:
                self._send_json(400, {"error": "Missing 'message' field in body"})
                return

            session_id = payload.get("session_id") or self.agent_core.active_session_id
            self.agent_core.active_session_id = session_id

            try:
                reply = self.agent_core.chat(
                    user_message=message,
                    session_id=session_id,
                    temperature=payload.get("temperature", 0.7),
                    max_tokens=payload.get("max_tokens", 512),
                )
                self._send_json(200, {
                    "response": reply,
                    "session_id": session_id,
                    "history": self.agent_core.get_history(session_id),
                })
            except Exception as e:
                logger.error(f"Error handling /api/chat: {e}")
                self._send_json(500, {"error": str(e)})
            return

        if path == "/v1/chat/completions":
            messages = payload.get("messages", [])
            stream = payload.get("stream", False)
            session_id = payload.get("session_id") or payload.get("user") or self.agent_core.active_session_id
            self.agent_core.active_session_id = session_id

            if not messages:
                self._send_json(400, {"error": "Missing 'messages' array in request"})
                return

            last_user_msg = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user_msg = m.get("content", "")
                    break

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                try:
                    for chunk_text in self.agent_core.chat_stream(
                        last_user_msg,
                        session_id=session_id,
                        temperature=payload.get("temperature", 0.7),
                        max_tokens=payload.get("max_tokens", 512),
                    ):
                        chunk_obj = {
                            "id": f"chatcmpl-{int(time.time())}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": "meera",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk_text},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        self.wfile.write(f"data: {json.dumps(chunk_obj)}\n\n".encode("utf-8"))
                        self.wfile.flush()

                    # Final finish chunk
                    done_chunk = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "meera",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    self.wfile.write(f"data: {json.dumps(done_chunk)}\n\n".encode("utf-8"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except Exception as e:
                    logger.error(f"Streaming error: {e}")
                return
            else:
                try:
                    reply = self.agent_core.chat(
                        last_user_msg,
                        session_id=session_id,
                        temperature=payload.get("temperature", 0.7),
                        max_tokens=payload.get("max_tokens", 512),
                    )
                    openai_resp = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": "meera",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": reply},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                    self._send_json(200, openai_resp)
                except Exception as e:
                    logger.error(f"Error handling completions: {e}")
                    self._send_json(500, {"error": str(e)})
                return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_PATCH(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/sessions/"):
            session_id = path[len("/api/sessions/"):].strip("/")
            title = payload.get("title")
            is_archived = payload.get("is_archived")
            metadata = payload.get("metadata")
            ok = self.agent_core.memory_store.update_session(
                session_id,
                title=title,
                metadata=metadata,
                is_archived=is_archived,
            )
            if ok:
                self._send_json(200, {"status": "ok", "session_id": session_id})
            else:
                self._send_json(404, {"error": "Session not found"})
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/sessions/"):
            session_id = path[len("/api/sessions/"):].strip("/")
            ok = self.agent_core.memory_store.delete_session(session_id)
            if ok:
                if self.agent_core._active_session_id == session_id:
                    self.agent_core._active_session_id = None
                self._send_json(200, {"status": "deleted", "session_id": session_id})
            else:
                self._send_json(404, {"error": "Session not found"})
            return

        if path == "/api/memories":
            category = query.get("category", [None])[0]
            key = query.get("key", [None])[0]
            if not category or not key:
                self._send_json(400, {"error": "Query parameters 'category' and 'key' required"})
                return
            ok = self.agent_core.memory_store.delete_long_term_memory(category, key)
            if ok:
                self._send_json(200, {"status": "deleted", "category": category, "key": key})
            else:
                self._send_json(404, {"error": "Memory item not found"})
            return

        self._send_json(404, {"error": "Endpoint not found"})


def ensure_assets():
    """Copies user selected conceptual sketch background into ui/assets/."""
    assets_dir = BASE_DIR / "ui" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target_bg = assets_dir / "sketch_bg.jpg"
    import shutil
    artifact_dir = Path(r"C:\Users\Arshit\.gemini\antigravity-ide\brain\82935af1-14a8-4985-b1bc-9ca29c29e537")
    user_uploaded_dir = artifact_dir / ".user_uploaded"

    # 1. Ethereal monochrome conceptual sketch artwork
    calm_candidates = list(artifact_dir.glob("*calm_ethereal*.jpg"))
    if calm_candidates:
        try:
            shutil.copy2(calm_candidates[-1], target_bg)
            logger.info(f"Deployed Ethereal Monochrome artwork from {calm_candidates[-1]} to {target_bg}")
            return
        except Exception as e:
            logger.warning(f"Could not copy ethereal sketch art: {e}")

    # 2. Monochrome B&W artwork
    ethereal_candidates = list(artifact_dir.glob("*ethereal_bw*.jpg"))
    if ethereal_candidates:
        try:
            shutil.copy2(ethereal_candidates[-1], target_bg)
            logger.info(f"Deployed Monochrome B&W artwork from {ethereal_candidates[-1]} to {target_bg}")
            return
        except Exception as e:
            logger.warning(f"Could not copy monochrome B&W sketch art: {e}")

    # 3. Ambient graded artwork
    graded_candidates = list(artifact_dir.glob("*color_graded*.jpg"))
    if graded_candidates:
        try:
            shutil.copy2(graded_candidates[-1], target_bg)
            logger.info(f"Deployed Ambient Graded artwork from {graded_candidates[-1]} to {target_bg}")
            return
        except Exception as e:
            logger.warning(f"Could not copy graded sketch art: {e}")

    # 4. User uploaded target image
    user_candidates = list(user_uploaded_dir.glob("media_1791488831571.png"))
    if not user_candidates:
        user_candidates = sorted(list(user_uploaded_dir.glob("media_*.png")), key=lambda p: p.stat().st_mtime)
    
    if user_candidates:
        try:
            shutil.copy2(user_candidates[-1], target_bg)
            logger.info(f"Deployed Custom Conceptual artwork from {user_candidates[-1]} to {target_bg}")
            return
        except Exception as e:
            logger.warning(f"Could not copy custom sketch art: {e}")

    # Fallbacks
    abstract_candidates = list(artifact_dir.glob("*abstract_sil*.jpg"))
    if abstract_candidates:
        try:
            shutil.copy2(abstract_candidates[-1], target_bg)
            logger.info(f"Deployed Abstract Silhouette artwork to {target_bg}")
            return
        except Exception as e:
            logger.warning(f"Could not copy Abstract silhouette art: {e}")


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class MeeraAPIServer:
    """HTTP Server manager for Meera Agent API."""

    def __init__(self, agent_core: AgentCore, config: ServerConfig = None):
        self.agent_core = agent_core
        self.config = config or ServerConfig()
        self._server = None
        ensure_assets()

    def start(self):
        handler = MeeraAPIRequestHandler
        handler.agent_core = self.agent_core
        handler.server_config = self.config

        self._server = ThreadedTCPServer((self.config.api_host, self.config.api_port), handler)
        logger.info(f"Meera API server running on http://{self.config.api_host}:{self.config.api_port}")
        print(f"\n[WEB UI] http://{self.config.api_host}:{self.config.api_port}")
        print(f"[OPENAI API] http://{self.config.api_host}:{self.config.api_port}/v1/chat/completions")
        print(f"[TELEMETRY] http://{self.config.api_host}:{self.config.api_port}/health")
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        if self._server:
            logger.info("Stopping Meera API server...")
            self._server.shutdown()
            self._server.server_close()
            self._server = None
