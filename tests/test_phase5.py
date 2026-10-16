"""
Meera - Phase 5 Skills Engine & Multi-Agent Orchestration Tests
Validates:
1. SkillManifest & SkillRegistry (dormant zero-overhead vs active injection, keyword auto-routing)
2. TaskScheduler (background thread, cron routines, delayed timers, task cancellation)
3. SubAgent & MultiAgentOrchestrator (isolated context windows, plan execution, results synthesis)
4. AgentCore integration with active skills
5. HTTP REST endpoints for skills, tasks, and multi-agent delegation
"""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.request

from agent.core import AgentCore
from api.server import MeeraAPIServer
from config.settings import ServerConfig
from memory.sqlite import SQLiteMemoryStore
from model.manager import ModelManager
from model.provider import ChatMessage, GenerationRequest, GenerationResponse, ModelProvider
from skills.academic import get_academic_skill
from skills.career import get_career_skill
from skills.coding import get_coding_skill
from skills.manifest import SkillManifest
from skills.orchestrator import MultiAgentOrchestrator, SubAgent, SubAgentTask
from skills.registry import SkillRegistry
from skills.scheduler import ScheduledTask, TaskScheduler


class MockSkillProvider(ModelProvider):
    def __init__(self, canned_reply: str = "Mock response from agent"):
        self.canned_reply = canned_reply

    def load(self) -> bool:
        return True

    def unload(self) -> bool:
        return True

    def is_loaded(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(content=self.canned_reply)

    def stream(self, request: GenerationRequest):
        from model.provider import StreamChunk
        yield StreamChunk(delta=self.canned_reply)

    def health(self):
        return {"loaded": True, "backend": "mock_skill"}


class TestPhase5SkillsEngine(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()

    def test_default_skills_registered(self):
        skills = self.registry.list_skills()
        skill_ids = [s.id for s in skills]
        self.assertIn("coding", skill_ids)
        self.assertIn("academic", skill_ids)
        self.assertIn("career", skill_ids)

    def test_zero_token_overhead_when_dormant(self):
        # When no skill is active and query does not trigger auto-routing
        ext = self.registry.get_prompt_extension("What is the weather today?")
        self.assertEqual(ext, "", "Dormant skills must yield zero token prompt extension")

    def test_explicit_skill_activation(self):
        self.assertTrue(self.registry.activate_skill("coding"))
        self.assertIsNotNone(self.registry.active_skill)
        self.assertEqual(self.registry.active_skill.id, "coding")

        ext = self.registry.get_prompt_extension()
        self.assertIn("CODE SYNTHESIS & ARCHITECTURE", ext)

        # Deactivation
        self.assertTrue(self.registry.activate_skill("none"))
        self.assertIsNone(self.registry.active_skill)
        self.assertEqual(self.registry.get_prompt_extension(), "")

    def test_keyword_auto_routing(self):
        academic_query = "Please review my research paper thesis and analyze citation methodology"
        matched = self.registry.auto_detect_skill(academic_query)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.id, "academic")

        coding_query = "Please implement an algorithm with refactor and debugging"
        matched = self.registry.auto_detect_skill(coding_query)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.id, "coding")


class TestPhase5TaskScheduler(unittest.TestCase):
    def setUp(self):
        self.scheduler = TaskScheduler()
        self.scheduler.start()

    def tearDown(self):
        self.scheduler.stop()

    def test_one_shot_timer(self):
        executed = threading.Event()

        task = self.scheduler.schedule_timer(
            name="test_timer",
            delay_seconds=0.1,
            action=lambda: executed.set(),
        )

        self.assertEqual(task.task_type, "timer")
        self.assertEqual(task.status, "running")

        # Wait for execution
        fired = executed.wait(timeout=2.0)
        self.assertTrue(fired, "Timer action should execute within timeout")
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.run_count, 1)

    def test_recurring_cron(self):
        counter = [0]
        event = threading.Event()

        def increment():
            counter[0] += 1
            if counter[0] >= 2:
                event.set()

        task = self.scheduler.schedule_cron(
            name="test_cron",
            interval_seconds=0.1,
            action=increment,
            max_runs=2,
        )

        event.wait(timeout=2.0)
        self.assertGreaterEqual(counter[0], 2)
        self.assertEqual(task.status, "completed")

    def test_cancel_task(self):
        task = self.scheduler.schedule_timer(
            name="to_cancel",
            delay_seconds=10.0,
        )
        self.assertEqual(task.status, "running")
        ok = self.scheduler.cancel_task(task.id)
        self.assertTrue(ok)
        self.assertEqual(task.status, "cancelled")


class TestPhase5MultiAgentOrchestrator(unittest.TestCase):
    def setUp(self):
        self.mock_provider = MockSkillProvider("Subagent analyzed data successfully")
        self.model_mgr = ModelManager(provider=self.mock_provider)
        self.orchestrator = MultiAgentOrchestrator(model_manager=self.model_mgr)

    def test_subagent_isolated_execution(self):
        subagent = self.orchestrator.create_subagent(
            name="Researcher",
            persona="Specialized Academic Researcher",
            skill=get_academic_skill(),
        )

        output = subagent.run_task(
            objective="Analyze transformer attention mechanism",
            input_data="Paper abstract snippet",
        )
        self.assertEqual(output, "Subagent analyzed data successfully")

    def test_orchestrator_execute_plan_and_synthesize(self):
        tasks = [
            SubAgentTask(
                task_id="task_1",
                role_name="Architect",
                objective="Design data pipeline",
            ),
            SubAgentTask(
                task_id="task_2",
                role_name="Reviewer",
                objective="Review security vulnerabilities",
            ),
        ]

        results = self.orchestrator.execute_plan(tasks)
        self.assertEqual(len(results), 2)
        self.assertIn("task_1", results)
        self.assertIn("task_2", results)
        self.assertTrue(tasks[0].success)

        # Synthesis
        synthesis = self.orchestrator.synthesize_results("Build secure data pipeline", results)
        self.assertEqual(synthesis, "Subagent analyzed data successfully")


class TestPhase5IntegrationAndAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_phase5.db"
        cls.memory_store = SQLiteMemoryStore(db_path=cls.db_path)

        cls.mock_provider = MockSkillProvider("Integrated Phase 5 Answer")
        cls.model_mgr = ModelManager(provider=cls.mock_provider)

        cls.agent_core = AgentCore(
            model_manager=cls.model_mgr,
            memory_store=cls.memory_store,
        )

        cls.port = 8915
        cfg = ServerConfig(port=cls.port)
        cls.server = MeeraAPIServer(agent_core=cls.agent_core, config=cfg)
        cls.server_thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.agent_core.scheduler.stop()
        cls.temp_dir.cleanup()

    def _get(self, path: str):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, path: str, body: dict):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _delete(self, path: str):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_agent_core_skill_prompt_injection(self):
        # Baseline context has no skill prompt
        self.agent_core.skill_registry.activate_skill("none")
        ctx_dormant = self.agent_core.build_context("Hello")
        sys_dormant = ctx_dormant[0].content
        self.assertNotIn("CODE SYNTHESIS", sys_dormant)

        # Activate coding skill
        self.agent_core.skill_registry.activate_skill("coding")
        ctx_active = self.agent_core.build_context("Hello")
        sys_active = ctx_active[0].content
        self.assertIn("CODE SYNTHESIS & ARCHITECTURE", sys_active)

    def test_api_skills_endpoints(self):
        # GET /api/skills
        status, data = self._get("/api/skills")
        self.assertEqual(status, 200)
        self.assertIn("skills", data)
        self.assertTrue(len(data["skills"]) >= 3)

        # POST /api/skills/activate
        status, act_data = self._post("/api/skills/activate", {"skill_id": "career"})
        self.assertEqual(status, 200)
        self.assertEqual(act_data["status"], "ok")
        self.assertEqual(act_data["active_skill"]["id"], "career")

        # Verify active skill
        status, data = self._get("/api/skills")
        self.assertEqual(data["active_skill"]["id"], "career")

        # Deactivate
        status, deact_data = self._post("/api/skills/activate", {"skill_id": "none"})
        self.assertEqual(status, 200)
        self.assertIsNone(deact_data["active_skill"])

    def test_api_tasks_endpoints(self):
        # POST /api/tasks (create a timer)
        status, task_data = self._post("/api/tasks", {
            "name": "API Ping",
            "task_type": "timer",
            "delay_seconds": 60.0,
            "prompt": "Check server health",
        })
        self.assertEqual(status, 201)
        task_id = task_data["task"]["id"]
        self.assertEqual(task_data["task"]["name"], "API Ping")

        # GET /api/tasks
        status, list_data = self._get("/api/tasks")
        self.assertEqual(status, 200)
        ids = [t["id"] for t in list_data["tasks"]]
        self.assertIn(task_id, ids)

        # DELETE /api/tasks/<task_id>
        status, del_data = self._delete(f"/api/tasks/{task_id}")
        self.assertEqual(status, 200)
        self.assertEqual(del_data["status"], "cancelled")

    def test_api_orchestrator_delegate_endpoint(self):
        status, del_resp = self._post("/api/orchestrator/delegate", {
            "role_name": "CodeSynthesizer",
            "objective": "Build unit test",
            "skill_id": "coding",
            "input_data": "Function signature foo()",
        })
        self.assertEqual(status, 200)
        self.assertEqual(del_resp["status"], "completed")
        self.assertEqual(del_resp["role_name"], "CodeSynthesizer")
        self.assertIn("output", del_resp)


if __name__ == "__main__":
    unittest.main()
