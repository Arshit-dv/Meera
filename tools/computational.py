"""
Meera - Computational Tools (PREPARE Tier)
Sandboxed Python computational scratchpad for calculations, parsing, and data transformations.
"""
import io
import math
import sys
import time
import traceback
from typing import Any, Dict

from permissions.policy import PermissionTier
from tools.base import BaseTool, ToolResult


class PythonEvalTool(BaseTool):
    """
    Executes Python code in a sandboxed computational scratchpad.
    Captures printed outputs and returns evaluation results safely.
    """

    def __init__(self):
        super().__init__(
            name="python_eval",
            description="Run Python code scratchpad for calculations, string transformations, and data analysis",
            tier=PermissionTier.PREPARE,
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code snippet to execute"},
                },
                "required": ["code"],
            },
        )

    def execute(self, code: str, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout

        # Safe environment for calculations
        safe_globals: Dict[str, Any] = {
            "__builtins__": {
                "abs": abs,
                "all": all,
                "any": any,
                "bin": bin,
                "bool": bool,
                "chr": chr,
                "dict": dict,
                "divmod": divmod,
                "enumerate": enumerate,
                "filter": filter,
                "float": float,
                "format": format,
                "frozenset": frozenset,
                "hex": hex,
                "int": int,
                "isinstance": isinstance,
                "len": len,
                "list": list,
                "map": map,
                "max": max,
                "min": min,
                "oct": oct,
                "ord": ord,
                "pow": pow,
                "print": print,
                "range": range,
                "reversed": reversed,
                "round": round,
                "set": set,
                "sorted": sorted,
                "str": str,
                "sum": sum,
                "tuple": tuple,
                "zip": zip,
            },
            "math": math,
        }
        local_scope: Dict[str, Any] = {}

        try:
            sys.stdout = stdout_capture
            # Attempt eval if single expression, else exec
            try:
                result_val = eval(code.strip(), safe_globals, local_scope)
                if result_val is not None:
                    print(repr(result_val))
            except SyntaxError:
                exec(code, safe_globals, local_scope)

            sys.stdout = old_stdout
            output = stdout_capture.getvalue().strip()
            if not output:
                output = "(Code executed successfully with no output)"

            return ToolResult(
                success=True,
                output=output,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:
            sys.stdout = old_stdout
            err_msg = traceback.format_exc(limit=2)
            return ToolResult(
                success=False,
                output="",
                error=f"Python execution error: {e}\n{err_msg}",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        finally:
            sys.stdout = old_stdout
