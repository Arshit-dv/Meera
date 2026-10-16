"""
Meera - Model Manager and Provider Unit Tests
Validates ModelProvider contracts, ModelManager RAM guardrails, and request serialization.
"""
import unittest

from config.settings import DEFAULT_MODEL_KEY, MODELS
from model.manager import ModelManager, get_available_ram_mb
from model.provider import ChatMessage, GenerationRequest, GenerationResponse, ModelProvider, StreamChunk


class MockProvider(ModelProvider):
    def __init__(self):
        self._loaded = False

    def load(self) -> bool:
        self._loaded = True
        return True

    def unload(self) -> bool:
        self._loaded = False
        return True

    def is_loaded(self) -> bool:
        return self._loaded

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(content=f"Response for {len(request.messages)} messages")

    def stream(self, request: GenerationRequest):
        yield StreamChunk(delta="Echo: ")
        yield StreamChunk(delta=request.messages[-1].content)

    def health(self):
        return {"loaded": self._loaded, "backend": "mock"}


class TestModelArchitecture(unittest.TestCase):
    def setUp(self):
        self.manager = ModelManager(default_model_key="qwen3-1.7b")
        self.mock_provider = MockProvider()
        self.manager._provider = self.mock_provider

    def test_provider_contract_lifecycle(self):
        self.assertFalse(self.mock_provider.is_loaded())
        self.assertTrue(self.mock_provider.load())
        self.assertTrue(self.mock_provider.is_loaded())
        self.assertTrue(self.mock_provider.unload())
        self.assertFalse(self.mock_provider.is_loaded())

    def test_ram_detection(self):
        ram_mb = get_available_ram_mb()
        self.assertIsInstance(ram_mb, int)
        self.assertGreater(ram_mb, 0)

    def test_generation_request(self):
        req = GenerationRequest(
            messages=[ChatMessage(role="user", content="Ping")],
            temperature=0.5,
            max_tokens=64,
        )
        res = self.manager.generate(req)
        self.assertIn("Response for 1 messages", res.content)

    def test_streaming_generation(self):
        req = GenerationRequest(
            messages=[ChatMessage(role="user", content="TestStream")],
            stream=True,
        )
        chunks = [c.delta for c in self.manager.stream(req)]
        self.assertEqual("".join(chunks), "Echo: TestStream")

    def test_health_telemetry(self):
        health = self.manager.health()
        self.assertIn("available_ram_mb", health)
        self.assertIn("is_loaded", health)
        self.assertIn("default_model", health)


if __name__ == "__main__":
    unittest.main()
