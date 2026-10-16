"""
Meera - Native Model Context Protocol (MCP) Client Adapter
Enables Meera to dynamically discover and invoke external MCP server tools
via standard JSON-RPC 2.0 over stdio (zero third-party dependencies).
"""
import json
import logging
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from permissions.policy import PermissionTier
from tools.base import BaseTool, ToolResult

logger = logging.getLogger("meera.tools.mcp")


class MCPToolWrapper(BaseTool):
    """Wraps an external MCP tool as a first-class Meera BaseTool."""

    def __init__(self, mcp_client: "MCPClient", name: str, description: str, schema: Dict[str, Any]):
        super().__init__(
            name=name,
            description=f"[MCP] {description}",
            tier=PermissionTier.PREPARE,  # External MCP tools default to PREPARE
            parameters=schema,
        )
        self.mcp_client = mcp_client

    def execute(self, **kwargs) -> ToolResult:
        return self.mcp_client.call_tool(self.name, kwargs)


class MCPClient:
    """
    Native Python standard library JSON-RPC 2.0 client for Model Context Protocol servers.
    """

    def __init__(self, server_command: Optional[List[str]] = None):
        self.server_command = server_command
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._is_initialized = False

    def start(self) -> bool:
        """Launches the MCP server subprocess and performs initialization handshake."""
        if not self.server_command:
            return False

        try:
            self._process = subprocess.Popen(
                self.server_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            # 1. Initialize request
            init_resp = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "MeeraAgent", "version": "1.0.0"},
                },
            )
            if not init_resp:
                logger.error("[MCP] Initialization handshake failed")
                return False

            # 2. Initialized notification
            self._send_notification("notifications/initialized", {})
            self._is_initialized = True
            logger.info("[MCP] Connected and initialized MCP server successfully")
            return True

        except Exception as e:
            logger.error(f"[MCP] Failed to start MCP process: {e}")
            return False

    def _send_request(self, method: str, params: Dict[str, Any], timeout_seconds: float = 10.0) -> Optional[Dict[str, Any]]:
        if not self._process or self._process.poll() is not None:
            return None

        with self._lock:
            self._request_id += 1
            req_id = self._request_id
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            try:
                line = json.dumps(payload) + "\n"
                self._process.stdin.write(line)
                self._process.stdin.flush()

                # Read response
                response_line = self._process.stdout.readline()
                if not response_line:
                    return None
                resp_json = json.loads(response_line)
                return resp_json.get("result")
            except Exception as e:
                logger.error(f"[MCP] Error in request '{method}': {e}")
                return None

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        if not self._process or self._process.poll() is not None:
            return
        with self._lock:
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
            try:
                line = json.dumps(payload) + "\n"
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except Exception:
                pass

    def list_tools(self) -> List[Dict[str, Any]]:
        """Queries MCP server for available tools."""
        res = self._send_request("tools/list", {})
        if res and "tools" in res:
            return res["tools"]
        return []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Invokes an MCP tool via JSON-RPC tools/call."""
        start_time = time.perf_counter()
        res = self._send_request("tools/call", {"name": name, "arguments": arguments})
        elapsed = (time.perf_counter() - start_time) * 1000

        if not res:
            return ToolResult(
                success=False,
                output="",
                error=f"MCP tool call '{name}' failed or timed out",
                execution_time_ms=elapsed,
            )

        content_items = res.get("content", [])
        text_outputs = []
        for item in content_items:
            if item.get("type") == "text":
                text_outputs.append(item.get("text", ""))

        output_str = "\n".join(text_outputs) if text_outputs else "(No text output)"
        is_error = res.get("isError", False)

        return ToolResult(
            success=not is_error,
            output=output_str,
            error="MCP returned an error status" if is_error else None,
            execution_time_ms=elapsed,
        )

    def to_meera_tools(self) -> List[BaseTool]:
        """Converts discovered MCP tools into native Meera tools."""
        tools_data = self.list_tools()
        tools_list: List[BaseTool] = []
        for t in tools_data:
            name = t.get("name", "unnamed_mcp_tool")
            desc = t.get("description", "External MCP tool")
            schema = t.get("inputSchema", {})
            wrapper = MCPToolWrapper(self, name, desc, schema)
            tools_list.append(wrapper)
        return tools_list

    def stop(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
