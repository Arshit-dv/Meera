"""
Meera - Phase 4 Guardrailed Tool Execution Tests
Validates SecurityPolicy, three-tier PermissionManager (READ, PREPARE, ACT),
filesystem inspection tools, Python scratchpad, system shell runner,
compact schema parsing, and API endpoints.
"""
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.request
import json

from agent.core import AgentCore
from api.server import MeeraAPIServer
from config.settings import ServerConfig
from memory.sqlite import SQLiteMemoryStore
from model.provider import ChatMessage, GenerationRequest, GenerationResponse, ModelProvider
from permissions.manager import PermissionManager
from permissions.policy import PermissionTier, SecurityPolicy
from tools.base import ToolResult
from tools.computational import PythonEvalTool
from tools.filesystem import ListDirectoryTool, ReadFileTool, SearchFilesTool
from tools.registry import ToolRegistry
from tools.system import RunCommandTool


class ToolMockProvider(ModelProvider):
    """Simulates an LLM calling a tool on turn 1 and answering on turn 2."""
    def __init__(self, tool_call_str: str, final_reply: str):
        self.tool_call_str = tool_call_str
        self.final_reply = final_reply
        self.turn_count = 0

    def load(self) -> bool:
        return True

    def unload(self) -> bool:
        return True

    def is_loaded(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.turn_count += 1
        last_msg = request.messages[-1].content
        if "[OBSERVATION:" in last_msg:
            return GenerationResponse(content=self.final_reply)
        return GenerationResponse(content=self.tool_call_str)

    def stream(self, request: GenerationRequest):
        from model.provider import StreamChunk
        resp = self.generate(request)
        yield StreamChunk(delta=resp.content)

    def health(self):
        return {"loaded": True, "backend": "tool_mock"}


class TestPhase4ToolsAndPermissions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_dir = Path(self.temp_dir.name)
        # Create test workspace files
        (self.workspace_dir / "test_file.txt").write_text("Hello from Meera Phase 4\nSecond line", encoding="utf-8")
        (self.workspace_dir / "subfolder").mkdir()
        (self.workspace_dir / "subfolder" / "nested.py").write_text("def hello(): pass", encoding="utf-8")

        self.policy = SecurityPolicy(workspace_root=self.workspace_dir)
        self.perm_mgr = PermissionManager(policy=self.policy)
        self.registry = ToolRegistry(permission_manager=self.perm_mgr)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_security_policy_boundaries(self):
        # 1. Inside workspace path
        safe_path = self.policy.sanitize_path("test_file.txt")
        self.assertIsNotNone(safe_path)
        self.assertTrue(self.policy.is_path_within_workspace(safe_path))

        # 2. Outside workspace traversal
        outside = self.policy.sanitize_path("../../Windows/System32")
        self.assertIsNone(outside)

        # 3. Blocked dangerous command detection
        self.assertFalse(self.policy.is_command_safe("rmdir /s /q C:\\Users"))
        self.assertFalse(self.policy.is_command_safe("format D:"))
        self.assertTrue(self.policy.is_command_safe("python --version"))

    def test_permission_tiers(self):
        # READ Tier: Autonomous
        auth_read, _ = self.perm_mgr.authorize(PermissionTier.READ, "read_file", {"path": "test_file.txt"})
        self.assertTrue(auth_read)

        # PREPARE Tier: Autonomous
        auth_prep, _ = self.perm_mgr.authorize(PermissionTier.PREPARE, "python_eval", {"code": "2 + 2"})
        self.assertTrue(auth_prep)

        # ACT Tier: Confirmation Required
        auth_act, reason = self.perm_mgr.authorize(PermissionTier.ACT, "run_command", {"command": "git status"})
        self.assertFalse(auth_act)
        self.assertIn("CONFIRMATION_REQUIRED", reason)

        # Extract token and approve
        token = reason.split("Token: ")[-1].strip()
        self.assertTrue(self.perm_mgr.approve_action(token))

        # Now authorize with approved token
        auth_approved, _ = self.perm_mgr.authorize(
            PermissionTier.ACT,
            "run_command",
            {"command": "git status"},
            confirmation_token=token,
        )
        self.assertTrue(auth_approved)

    def test_filesystem_tools(self):
        list_tool = ListDirectoryTool(policy=self.policy)
        res_list = list_tool.execute(path=".")
        self.assertTrue(res_list.success)
        self.assertIn("test_file.txt", res_list.output)
        self.assertIn("subfolder", res_list.output)

        read_tool = ReadFileTool(policy=self.policy)
        res_read = read_tool.execute(path="test_file.txt")
        self.assertTrue(res_read.success)
        self.assertIn("Hello from Meera Phase 4", res_read.output)

        # Read out-of-bounds file should fail safely
        res_fail = read_tool.execute(path="../../outside.txt")
        self.assertFalse(res_fail.success)

    def test_python_eval_scratchpad(self):
        eval_tool = PythonEvalTool()
        res = eval_tool.execute(code="[x**2 for x in range(5)]")
        self.assertTrue(res.success)
        self.assertIn("[0, 1, 4, 9, 16]", res.output)

    def test_tool_call_parsing(self):
        # 1. Standard bracket syntax
        text1 = 'Let me inspect the files: [TOOL: list_directory(path="subfolder")]'
        parsed1 = self.registry.parse_tool_call(text1)
        self.assertIsNotNone(parsed1)
        self.assertEqual(parsed1[0], "list_directory")
        self.assertEqual(parsed1[1].get("path"), "subfolder")

        # 2. Python eval expression syntax
        text2 = '[TOOL: python_eval(code="100 * 5")]'
        parsed2 = self.registry.parse_tool_call(text2)
        self.assertIsNotNone(parsed2)
        self.assertEqual(parsed2[0], "python_eval")
        self.assertEqual(parsed2[1].get("code"), "100 * 5")

    def test_agent_core_tool_loop(self):
        mock_provider = ToolMockProvider(
            tool_call_str='[TOOL: python_eval(code="sum([10, 20, 30]))"]',
            final_reply="The computed sum is 60.",
        )
        from model.manager import ModelManager
        model_mgr = ModelManager(default_model_key="qwen3-1.7b")
        model_mgr._provider = mock_provider

        db_path = self.workspace_dir / "agent_tool_test.db"
        memory_store = SQLiteMemoryStore(db_path=db_path)
        agent = AgentCore(
            model_manager=model_mgr,
            memory_store=memory_store,
            tool_registry=self.registry,
        )

        response = agent.chat("What is the sum of 10, 20, and 30?")
        self.assertEqual(response, "The computed sum is 60.")
        self.assertEqual(mock_provider.turn_count, 2)


class TestPhase4ToolsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.workspace_dir = Path(cls.temp_dir.name)
        cls.db_path = cls.workspace_dir / "api_tool_test.db"
        cls.store = SQLiteMemoryStore(db_path=cls.db_path)

        from model.manager import ModelManager
        cls.model_mgr = ModelManager(default_model_key="qwen3-1.7b")
        cls.model_mgr._provider = ToolMockProvider("Echo", "Done")

        policy = SecurityPolicy(workspace_root=cls.workspace_dir)
        cls.registry = ToolRegistry(PermissionManager(policy=policy))
        cls.agent = AgentCore(model_manager=cls.model_mgr, memory_store=cls.store, tool_registry=cls.registry)
        cls.server_config = ServerConfig(api_port=8093)
        cls.server = MeeraAPIServer(agent_core=cls.agent, config=cls.server_config)

        cls.server_thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.store.close()
        cls.temp_dir.cleanup()

    def test_get_tools_endpoint(self):
        url = f"http://127.0.0.1:{self.server_config.api_port}/api/tools"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("tools", data)
            tool_names = [t["name"] for t in data["tools"]]
            self.assertIn("list_directory", tool_names)
            self.assertIn("python_eval", tool_names)
            self.assertIn("run_command", tool_names)

    def test_execute_tool_endpoint(self):
        url = f"http://127.0.0.1:{self.server_config.api_port}/api/tools/execute"
        payload = json.dumps({
            "tool": "python_eval",
            "arguments": {"code": "3 * 7"},
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["output"], "21")


if __name__ == "__main__":
    unittest.main()
