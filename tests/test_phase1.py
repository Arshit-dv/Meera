"""
Meera - Phase 1 Unit and Sanity Tests
Validates settings, provider contract, RAM checks, and core message formatting.
"""
import unittest
from unittest.mock import MagicMock

from config.settings import DEFAULT_MODEL_KEY, MODELS
from model.manager import ModelManager, get_available_ram_mb
from model.provider import ChatMessage, GenerationRequest, GenerationResponse, ModelProvider
from agent.core import AgentCore


class DummyProvider(ModelProvider):
    def __init__(self):
        self._is_loaded = False

    def load(self) -> bool:
        self._is_loaded = True
        return True

    def unload(self) -> bool:
        self._is_loaded = False
        return True

    def is_loaded(self) -> bool:
        return self._is_loaded

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(content=f"Echo: {request.messages[-1].content}")

    def stream(self, request: GenerationRequest):
        from model.provider import StreamChunk
        yield StreamChunk(delta=f"Echo: {request.messages[-1].content}")

    def health(self):
        return {"loaded": self._is_loaded, "backend": "dummy"}


class TestPhase1(unittest.TestCase):
    def test_settings_defined(self):
        self.assertIn("qwen3-1.7b", MODELS)
        self.assertIn("qwen3-4b", MODELS)
        self.assertEqual(DEFAULT_MODEL_KEY, "qwen3-1.7b")

    def test_ram_detection(self):
        ram_mb = get_available_ram_mb()
        self.assertGreater(ram_mb, 0)
        print(f"Detected available RAM: {ram_mb} MB")

    def test_agent_core_with_mock_provider(self):
        manager = ModelManager(default_model_key="qwen3-1.7b")
        dummy_provider = DummyProvider()
        manager._provider = dummy_provider

        agent = AgentCore(model_manager=manager)
        response = agent.chat("Hello Meera")
        self.assertEqual(response, "Echo: Hello Meera")
        self.assertEqual(len(agent.history), 2)
        self.assertEqual(agent.history[0].role, "user")
        self.assertEqual(agent.history[1].role, "assistant")

    def test_agent_core_context_building(self):
        agent = AgentCore()
        context = agent.build_context("Test message")
        self.assertEqual(context[0].role, "system")
        self.assertEqual(context[-1].role, "user")
        self.assertEqual(context[-1].content, "Test message")


if __name__ == "__main__":
    unittest.main()
