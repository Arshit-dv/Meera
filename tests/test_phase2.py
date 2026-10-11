"""
Meera - Phase 2 Web UI & API Tests
Verifies that static assets, /v1/models, /health, and the UI index are properly served.
"""
import threading
import time
import unittest
import urllib.request
import json

from agent.core import AgentCore
from api.server import MeeraAPIServer
from config.settings import ServerConfig
from model.manager import ModelManager


class TestPhase2WebUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use port 8090 for testing to avoid conflicts
        cls.config = ServerConfig(api_port=8090)
        cls.manager = ModelManager()
        cls.agent = AgentCore(model_manager=cls.manager)
        cls.server = MeeraAPIServer(agent_core=cls.agent, config=cls.config)
        
        cls.server_thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_serve_index_html(self):
        url = f"http://127.0.0.1:{self.config.api_port}/"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("Meera — Personal AI Agent", content)
            self.assertIn("telemetry-bar", content)

    def test_serve_css(self):
        url = f"http://127.0.0.1:{self.config.api_port}/ui/style.css"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "text/css")

    def test_serve_js(self):
        url = f"http://127.0.0.1:{self.config.api_port}/ui/app.js"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "application/javascript")

    def test_health_endpoint(self):
        url = f"http://127.0.0.1:{self.config.api_port}/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertIn("meera", data)


if __name__ == "__main__":
    unittest.main()
