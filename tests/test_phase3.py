"""
Meera - Phase 3 Persistent Memory Engine Tests
Validates SQLite schema, session CRUD, message history, auto-titling,
context window budgeting, long-term memory store, and API endpoints.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request

from agent.core import AgentCore
from api.server import MeeraAPIServer
from config.settings import MemoryConfig, ServerConfig
from memory.context import ContextManager, estimate_tokens, generate_auto_title
from memory.models import LongTermMemory, Message, Session
from memory.sqlite import SQLiteMemoryStore
from model.provider import ChatMessage, GenerationRequest, GenerationResponse, ModelProvider


class MockEchoProvider(ModelProvider):
    def __init__(self):
        self._loaded = True

    def load(self) -> bool:
        self._loaded = True
        return True

    def unload(self) -> bool:
        self._loaded = False
        return True

    def is_loaded(self) -> bool:
        return self._loaded

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        last = request.messages[-1].content
        return GenerationResponse(content=f"Echo: {last}")

    def stream(self, request: GenerationRequest):
        from model.provider import StreamChunk
        last = request.messages[-1].content
        yield StreamChunk(delta=f"Echo: {last}")

    def health(self):
        return {"loaded": True, "backend": "mock"}


class TestPhase3MemoryEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.db"
        self.store = SQLiteMemoryStore(db_path=self.db_path)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_session_lifecycle(self):
        # 1. Create
        session = self.store.create_session(title="Architectural Planning", metadata={"tag": "system"})
        self.assertIsNotNone(session.id)
        self.assertEqual(session.title, "Architectural Planning")
        self.assertEqual(session.metadata.get("tag"), "system")

        # 2. Get
        fetched = self.store.get_session(session.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "Architectural Planning")

        # 3. List
        sessions = self.store.list_sessions()
        self.assertEqual(len(sessions), 1)

        # 4. Update title
        self.store.update_session(session.id, title="Refined Architecture")
        updated = self.store.get_session(session.id)
        self.assertEqual(updated.title, "Refined Architecture")

        # 5. Delete
        deleted = self.store.delete_session(session.id)
        self.assertTrue(deleted)
        self.assertIsNone(self.store.get_session(session.id))

    def test_messages_persistence_and_cascade(self):
        session = self.store.create_session(title="Chat Session")
        
        # Add messages
        m1 = self.store.add_message(session.id, role="user", content="Hello Meera")
        m2 = self.store.add_message(session.id, role="assistant", content="Greetings. How may I assist you?")
        self.assertIsNotNone(m1.id)
        self.assertIsNotNone(m2.id)

        # Retrieve messages
        history = self.store.get_messages(session.id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].role, "user")
        self.assertEqual(history[0].content, "Hello Meera")
        self.assertEqual(history[1].role, "assistant")
        self.assertEqual(history[1].content, "Greetings. How may I assist you?")

        # Test cascading deletion when session is deleted
        self.store.delete_session(session.id)
        messages_after_delete = self.store.get_messages(session.id)
        self.assertEqual(len(messages_after_delete), 0)

    def test_long_term_memories(self):
        # Insert
        m1 = self.store.set_long_term_memory(
            category="preference",
            key="theme",
            value="Obsidian Dark",
            confidence=0.95,
        )
        self.assertEqual(m1.key, "theme")
        self.assertEqual(m1.value, "Obsidian Dark")

        # Upsert (update value on same category+key)
        m2 = self.store.set_long_term_memory(
            category="preference",
            key="theme",
            value="Graphite Lime",
            confidence=1.0,
        )
        self.assertEqual(m2.value, "Graphite Lime")

        # Retrieve
        fetched = self.store.get_long_term_memory("preference", "theme")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.value, "Graphite Lime")

        # Search
        results = self.store.search_long_term_memories("Graphite")
        self.assertEqual(len(results), 1)

        # Delete
        self.store.delete_long_term_memory("preference", "theme")
        self.assertIsNone(self.store.get_long_term_memory("preference", "theme"))

    def test_auto_title_generation(self):
        msg1 = "Explain the difference between CUDA and OpenCL for local inference"
        title1 = generate_auto_title(msg1)
        self.assertLessEqual(len(title1), 35)
        self.assertTrue(title1.startswith("Explain"))

        msg2 = "```python\nimport sys\n```"
        title2 = generate_auto_title(msg2)
        self.assertFalse(title2.startswith("```"))

    def test_context_manager_building_and_long_term_injection(self):
        ctx_mgr = ContextManager(memory_store=self.store)
        session = self.store.create_session(title="Context Test")
        
        # Inject preference into memory store
        self.store.set_long_term_memory("preference", "user_role", "Principal AI Architect")

        # Build context
        context = ctx_mgr.build_context(session.id, user_message="What is my primary role?")
        system_msg = context[0]
        self.assertEqual(system_msg.role, "system")
        self.assertIn("Principal AI Architect", system_msg.content)
        self.assertEqual(context[-1].role, "user")
        self.assertEqual(context[-1].content, "What is my primary role?")

    def test_agent_core_with_persistent_sqlite(self):
        from model.manager import ModelManager
        manager = ModelManager(default_model_key="qwen3-1.7b")
        manager._provider = MockEchoProvider()

        agent = AgentCore(model_manager=manager, memory_store=self.store)
        session_id = agent.active_session_id

        # First turn: should auto-title session
        reply1 = agent.chat("Analyze system performance on Windows 11")
        self.assertEqual(reply1, "Echo: Analyze system performance on Windows 11")

        session_obj = self.store.get_session(session_id)
        self.assertNotEqual(session_obj.title, "New Conversation")
        self.assertTrue(session_obj.title.startswith("Analyze"))

        # Verify messages in SQLite
        history = self.store.get_messages(session_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].content, "Analyze system performance on Windows 11")
        self.assertEqual(history[1].content, "Echo: Analyze system performance on Windows 11")


class TestPhase3APIServerEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "api_test_memory.db"
        cls.store = SQLiteMemoryStore(db_path=cls.db_path)

        from model.manager import ModelManager
        cls.model_mgr = ModelManager(default_model_key="qwen3-1.7b")
        cls.model_mgr._provider = MockEchoProvider()

        cls.agent = AgentCore(model_manager=cls.model_mgr, memory_store=cls.store)
        cls.server_config = ServerConfig(api_port=8092)
        cls.server = MeeraAPIServer(agent_core=cls.agent, config=cls.server_config)

        cls.server_thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.store.close()
        cls.temp_dir.cleanup()

    def test_sessions_api_endpoints(self):
        base_url = f"http://127.0.0.1:{self.server_config.api_port}"

        # 1. POST /api/sessions
        create_payload = json.dumps({"title": "Test API Session"}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/sessions",
            data=create_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            session_id = data["session"]["id"]
            self.assertEqual(data["session"]["title"], "Test API Session")

        # 2. GET /api/sessions
        with urllib.request.urlopen(f"{base_url}/api/sessions", timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("sessions", data)
            self.assertTrue(any(s["id"] == session_id for s in data["sessions"]))

        # 3. POST /api/chat with session_id
        chat_payload = json.dumps({
            "message": "Verify SQLite persistence via API",
            "session_id": session_id,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=chat_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["response"], "Echo: Verify SQLite persistence via API")
            self.assertEqual(data["session_id"], session_id)

        # 4. GET /api/sessions/<id>
        with urllib.request.urlopen(f"{base_url}/api/sessions/{session_id}", timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["session"]["id"], session_id)
            self.assertEqual(len(data["messages"]), 2)

        # 5. DELETE /api/sessions/<id>
        req = urllib.request.Request(f"{base_url}/api/sessions/{session_id}", method="DELETE")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "deleted")

    def test_memories_api_endpoints(self):
        base_url = f"http://127.0.0.1:{self.server_config.api_port}"

        # 1. POST /api/memories
        mem_payload = json.dumps({
            "category": "fact",
            "key": "gpu_hardware",
            "value": "RTX 2050 4GB",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/memories",
            data=mem_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["memory"]["key"], "gpu_hardware")
            self.assertEqual(data["memory"]["value"], "RTX 2050 4GB")

        # 2. GET /api/memories
        with urllib.request.urlopen(f"{base_url}/api/memories?category=fact", timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(any(m["key"] == "gpu_hardware" for m in data["memories"]))

        # 3. DELETE /api/memories?category=fact&key=gpu_hardware
        req = urllib.request.Request(
            f"{base_url}/api/memories?category=fact&key=gpu_hardware",
            method="DELETE",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
