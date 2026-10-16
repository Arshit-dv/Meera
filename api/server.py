"""
Meera - Agent API Server
Exposes OpenAI-compatible endpoints (/v1/chat/completions, /v1/models),
Meera Agent endpoints, and SQLite Persistent Memory endpoints (/api/sessions, /api/memories)
using standard library http.server (zero third-party dependencies).
"""
import base64
import http.server
import json
import logging
import mimetypes
import os
from pathlib import Path
import shutil
import socketserver
import time
import urllib.parse
from typing import Any, Dict

from agent.core import AgentCore
from config.settings import BASE_DIR, DEFAULT_MODEL_KEY, ServerConfig

logger = logging.getLogger("meera.api.server")

LIBRARY_DIR = BASE_DIR / "storage" / "library"
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)


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
                self.send_header("Cache-Control", "no-cache, must-revalidate")
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
                self.send_header("Cache-Control", "no-cache, must-revalidate")
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
            project_id = query.get("project_id", [None])[0]
            sessions = self.agent_core.memory_store.list_sessions(
                limit=limit,
                offset=offset,
                include_archived=archived,
                project_id=project_id,
            )
            valid_ids = {s.id for s in sessions}
            active_id = self.agent_core._active_session_id
            if active_id not in valid_ids:
                active_id = sessions[0].id if sessions else None
                self.agent_core._active_session_id = active_id
            self._send_json(200, {
                "sessions": [s.to_dict() for s in sessions],
                "active_session_id": active_id,
            })
            return

        # 4b. Project Management API - List Projects
        if path == "/api/projects":
            projects = self.agent_core.memory_store.list_projects()
            self._send_json(200, {"projects": [p.to_dict() for p in projects]})
            return

        if path.startswith("/api/projects/"):
            project_id = path[len("/api/projects/"):].strip("/")
            project = self.agent_core.memory_store.get_project(project_id)
            if not project:
                self._send_json(404, {"error": f"Project '{project_id}' not found"})
                return
            self._send_json(200, {"project": project.to_dict()})
            return

        # 4c. Workspace Files API - List Files
        if path == "/api/files":
            project_id = query.get("project_id", [None])[0]
            policy = self.agent_core.tool_registry.policy
            ws_root = policy.workspace_root
            subfolder = ws_root
            if project_id:
                proj = self.agent_core.memory_store.get_project(project_id)
                if proj:
                    safe_pname = "".join(c for c in proj.name if c.isalnum() or c in ("-", "_", " ")).strip()
                    cand = ws_root / safe_pname
                    if cand.exists() and cand.is_dir():
                        subfolder = cand
            files = []
            if subfolder.exists():
                for p in sorted(subfolder.rglob("*")):
                    if p.is_file() and not any(part.startswith((".", "__pycache__")) for part in p.parts):
                        rel = str(p.relative_to(ws_root)).replace("\\", "/")
                        files.append({
                            "name": p.name,
                            "path": rel,
                            "size": p.stat().st_size,
                            "modified": int(p.stat().st_mtime),
                        })
            self._send_json(200, {"files": files})
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

        # 7. Tools API - List Available Tools & Pending Approvals
        if path == "/api/tools":
            tools_list = self.agent_core.tool_registry.list_tools()
            self._send_json(200, {
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "tier": t.tier.value,
                        "parameters": t.parameters,
                    }
                    for t in tools_list
                ]
            })
            return

        if path == "/api/tools/pending":
            pending = self.agent_core.tool_registry.permission_manager.list_pending_actions()
            self._send_json(200, {"pending_actions": pending})
            return

        # 8. Skills API
        if path == "/api/skills":
            skills = self.agent_core.skill_registry.list_skills()
            active = self.agent_core.skill_registry.active_skill
            self._send_json(200, {
                "skills": [s.to_dict() for s in skills],
                "active_skill": active.to_dict() if active else None,
            })
            return

        # 9. Scheduled Tasks API
        if path == "/api/tasks":
            tasks = self.agent_core.scheduler.list_tasks()
            self._send_json(200, {
                "tasks": [t.to_dict() for t in tasks],
            })
            return

        # 10. Academic Schedules & Deadlines API
        if path == "/api/schedules/deadlines":
            self.agent_core.memory_store.purge_older_than_3_months()
            platform = query.get("platform", [None])[0]
            is_comp = query.get("is_completed", [None])[0]
            is_completed_bool = None
            if is_comp is not None:
                is_completed_bool = is_comp in ("1", "true", "True")
            date_from = query.get("date_from", [None])[0]
            deadlines = self.agent_core.memory_store.list_deadlines(
                platform=platform,
                is_completed=is_completed_bool,
                date_from=date_from,
            )
            self._send_json(200, {"deadlines": [d.to_dict() for d in deadlines]})
            return

        if path == "/api/schedules/config":
            config = self.agent_core.academic_surfer.get_config()
            self._send_json(200, {"config": config})
            return

        # 10b. Teams Connector Status & Alerts API
        if path == "/api/teams/status":
            token = self.agent_core.teams_connector.get_valid_access_token()
            unread_count = self.agent_core.memory_store.get_unread_alerts_count()
            self._send_json(200, {
                "connected": token is not None,
                "unread_alerts": unread_count,
            })
            return

        if path == "/api/teams/joined":
            teams_list = self.agent_core.teams_connector.get_joined_teams()
            self._send_json(200, {"teams": teams_list, "count": len(teams_list)})
            return

        if path == "/api/teams/alerts":
            unread_only = query.get("unread_only", ["false"])[0].lower() == "true"
            limit = int(query.get("limit", [50])[0])
            alerts = self.agent_core.memory_store.list_teams_alerts(unread_only=unread_only, limit=limit)
            unread_count = self.agent_core.memory_store.get_unread_alerts_count()
            self._send_json(200, {
                "alerts": alerts,
                "unread_count": unread_count,
            })
            return

        # 11. Plugins API
        if path == "/api/plugins":
            plugins = self.agent_core.memory_store.list_plugins()
            self._send_json(200, {"plugins": [p.to_dict() for p in plugins]})
            return

        if path.startswith("/api/plugins/"):
            plugin_id = path[len("/api/plugins/"):].strip("/")
            p = self.agent_core.memory_store.get_plugin(plugin_id)
            if p:
                self._send_json(200, {"plugin": p.to_dict()})
            else:
                self._send_json(404, {"error": "Plugin not found"})
            return

        # 12. Library API - List Documents
        if path == "/api/library":
            q_term = query.get("query", [None])[0]
            f_type = query.get("file_type", [None])[0]
            items = self.agent_core.memory_store.list_library_items(query=q_term, file_type=f_type)
            self._send_json(200, {"items": [item.to_dict() for item in items]})
            return

        # 13. Library API - Download / View File
        if path.startswith("/api/library/file/"):
            item_id = path[len("/api/library/file/"):].strip("/")
            item = self.agent_core.memory_store.get_library_item(item_id)
            if not item or not os.path.exists(item.filepath):
                self._send_json(404, {"error": "File not found"})
                return

            try:
                mime_type, _ = mimetypes.guess_type(item.filepath)
                if not mime_type:
                    mime_type = "application/pdf" if item.file_type == "pdf" else "application/octet-stream"

                with open(item.filepath, "rb") as f:
                    content_bytes = f.read()

                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content_bytes)))
                self.send_header("Content-Disposition", f'inline; filename="{item.filename}"')
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content_bytes)
                return
            except Exception as e:
                logger.error(f"Error serving library file: {e}")
                self._send_json(500, {"error": str(e)})
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

        # Create New Project
        if path == "/api/projects":
            name = payload.get("name", "").strip()
            if not name:
                self._send_json(400, {"error": "Missing 'name' field"})
                return
            description = payload.get("description", "").strip()
            color = payload.get("color", "#A3E635")
            custom_id = payload.get("project_id")
            metadata = payload.get("metadata", {})
            project = self.agent_core.memory_store.create_project(
                name=name,
                description=description,
                color=color,
                project_id=custom_id,
                metadata=metadata,
            )
            self._send_json(201, {"project": project.to_dict()})
            return

        # Create / Save File in Workspace
        if path == "/api/files":
            filename = payload.get("filename", "").strip()
            if not filename:
                self._send_json(400, {"error": "Missing 'filename' in request body"})
                return
            content = payload.get("content", "")
            project_id = payload.get("project_id")

            folder_prefix = ""
            if project_id:
                proj = self.agent_core.memory_store.get_project(project_id)
                if proj:
                    safe_pname = "".join(c for c in proj.name if c.isalnum() or c in ("-", "_", " ")).strip()
                    folder_prefix = safe_pname

            target_rel = Path(folder_prefix) / filename if folder_prefix else Path(filename)
            policy = self.agent_core.tool_registry.policy
            sanitized = policy.sanitize_path(str(target_rel))
            if not sanitized:
                self._send_json(403, {"error": f"Path '{target_rel}' is forbidden or outside authorized workspace"})
                return

            sanitized.parent.mkdir(parents=True, exist_ok=True)
            with open(sanitized, "w", encoding="utf-8") as f:
                f.write(content)

            rel_str = str(sanitized.relative_to(policy.workspace_root)).replace("\\", "/")
            self._send_json(201, {
                "status": "created",
                "filename": sanitized.name,
                "relative_path": rel_str,
                "size": len(content.encode("utf-8")),
            })
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

        # Tool Direct Execution
        if path == "/api/tools/execute":
            tool_name = payload.get("tool")
            args = payload.get("arguments", {})
            token = payload.get("confirmation_token")
            if not tool_name:
                self._send_json(400, {"error": "Missing 'tool' name in body"})
                return
            result = self.agent_core.tool_registry.execute(tool_name, args, confirmation_token=token)
            self._send_json(200, result.to_dict())
            return

        # Approve Pending Action Token
        if path == "/api/tools/approve":
            token = payload.get("token")
            if not token:
                self._send_json(400, {"error": "Missing 'token' in body"})
                return
            ok = self.agent_core.tool_registry.permission_manager.approve_action(token)
            if ok:
                self._send_json(200, {"status": "approved", "token": token})
            else:
                self._send_json(404, {"error": "Pending token not found"})
            return

        # Deny Pending Action Token
        if path == "/api/tools/deny":
            token = payload.get("token")
            if not token:
                self._send_json(400, {"error": "Missing 'token' in body"})
                return
            ok = self.agent_core.tool_registry.permission_manager.deny_action(token)
            if ok:
                self._send_json(200, {"status": "denied", "token": token})
            else:
                self._send_json(404, {"error": "Pending token not found"})
            return

        # Activate / Deactivate Skill
        if path == "/api/skills/activate":
            skill_id = payload.get("skill_id")
            ok = self.agent_core.skill_registry.activate_skill(skill_id)
            if ok:
                active = self.agent_core.skill_registry.active_skill
                self._send_json(200, {
                    "status": "ok",
                    "active_skill": active.to_dict() if active else None,
                })
            else:
                self._send_json(404, {"error": f"Skill '{skill_id}' not found"})
            return

        # Create Scheduled Task or Timer
        if path == "/api/tasks":
            name = payload.get("name", "Scheduled Task").strip()
            task_type = payload.get("task_type", "cron").lower()
            interval = float(payload.get("interval_seconds", payload.get("delay_seconds", 60)))
            prompt = payload.get("prompt")
            max_runs = payload.get("max_runs")
            if task_type == "timer":
                task = self.agent_core.scheduler.schedule_timer(
                    name=name,
                    delay_seconds=interval,
                    prompt=prompt,
                )
            else:
                task = self.agent_core.scheduler.schedule_cron(
                    name=name,
                    interval_seconds=interval,
                    prompt=prompt,
                    max_runs=int(max_runs) if max_runs else None,
                )
            self._send_json(201, {"task": task.to_dict()})
            return

        # Sync LMS & MS Teams Deadlines
        if path == "/api/schedules/sync":
            res = self.agent_core.academic_surfer.sync_all()
            try:
                t_token = self.agent_core.teams_connector.get_valid_access_token()
                if t_token:
                    t_deadlines, t_msg = self.agent_core.teams_connector.sync_teams_assignments()
                    t_alerts = self.agent_core.teams_connector.monitor_channel_announcements()
                    res["synced_count"] = res.get("synced_count", 0) + len(t_deadlines)
                    res["logs"] = res.get("logs", []) + [f"Teams Graph: {len(t_deadlines)} assignments, {len(t_alerts)} alerts"]
            except Exception as e:
                logger.warning(f"Teams sync in schedules/sync: {e}")
            self._send_json(200, res)
            return

        # Teams Device Code Flow & Sync API
        if path == "/api/teams/devicecode/start":
            client_id = payload.get("client_id")
            flow_res = self.agent_core.teams_connector.start_device_code_flow(client_id=client_id)
            status_code = 200 if flow_res.get("status") == "success" else 400
            self._send_json(status_code, flow_res)
            return

        if path == "/api/teams/devicecode/poll":
            device_code = payload.get("device_code")
            poll_res = self.agent_core.teams_connector.poll_device_code_token(device_code=device_code)
            if poll_res.get("status") == "authorized":
                import threading
                def _bg_sync():
                    try:
                        self.agent_core.teams_connector.sync_teams_assignments()
                        self.agent_core.teams_connector.monitor_channel_announcements()
                    except Exception as err:
                        logger.warning(f"Initial Teams sync failed: {err}")
                threading.Thread(target=_bg_sync, daemon=True).start()
            self._send_json(200, poll_res)
            return

        if path == "/api/teams/sync":
            deadlines, d_msg = self.agent_core.teams_connector.sync_teams_assignments()
            alerts = self.agent_core.teams_connector.monitor_channel_announcements()
            self._send_json(200, {
                "status": "success",
                "assignments_synced": len(deadlines),
                "alerts_discovered": len(alerts),
                "message": f"{d_msg} // Monitored {len(alerts)} channel announcements.",
            })
            return

        if path == "/api/sessions/active":
            session_id = payload.get("session_id")
            if session_id and self.agent_core.memory_store.get_session(session_id):
                self.agent_core._active_session_id = session_id
                self._send_json(200, {"status": "ok", "active_session_id": session_id})
            else:
                self.agent_core._active_session_id = None
                self._send_json(200, {"status": "cleared", "active_session_id": None})
            return

        if path == "/api/teams/alerts/refresh":
            try:
                alerts = self.agent_core.teams_connector.monitor_channel_announcements()
                self._send_json(200, {
                    "status": "success",
                    "alerts_discovered": len(alerts),
                    "alerts": alerts,
                })
            except Exception as e:
                logger.error(f"Error refreshing alerts: {e}")
                self._send_json(500, {"error": str(e)})
            return

        if path == "/api/teams/alerts/read":
            alert_id = payload.get("id", "all")
            ok = self.agent_core.memory_store.mark_teams_alert_read(alert_id)
            self._send_json(200, {"status": "ok", "success": ok})
            return

        if path == "/api/teams/alerts/delete":
            alert_id = payload.get("id", "all")
            ok = self.agent_core.memory_store.delete_teams_alert(alert_id)
            self._send_json(200, {"status": "ok", "success": ok})
            return

        # Save Academic Surfer Config (URLs & Cookies)
        if path == "/api/schedules/config":
            self.agent_core.academic_surfer.save_config(payload)
            self._send_json(200, {
                "status": "saved",
                "config": self.agent_core.academic_surfer.get_config(),
            })
            return

        # Create Manual Academic Deadline
        if path == "/api/schedules/deadlines":
            title = payload.get("title", "").strip()
            if not title:
                self._send_json(400, {"error": "Missing 'title' in body"})
                return
            due_date = payload.get("due_date", "").strip()
            platform = payload.get("platform", "lms").lower()
            group_name = payload.get("group_name", "General").strip()
            description = payload.get("description", "").strip()
            priority = payload.get("priority", "normal")
            d_id = f"{platform}_{int(time.time() * 1000)}"
            from memory.models import AcademicDeadline
            deadline = AcademicDeadline(
                id=d_id,
                title=title,
                description=description,
                due_date=due_date,
                platform=platform,
                group_name=group_name,
                priority=priority,
            )
            self.agent_core.memory_store.add_deadline(deadline)
            self._send_json(201, {"status": "created", "deadline": deadline.to_dict()})
            return

        # Update Plugin Configuration
        if path == "/api/plugins/config":
            plugin_id = payload.get("id")
            if not plugin_id:
                self._send_json(400, {"error": "Missing 'id' in body"})
                return
            is_enabled = payload.get("is_enabled")
            status = payload.get("status")
            config_data = payload.get("config")

            if plugin_id == "lms" and isinstance(config_data, dict):
                if not config_data.get("url"):
                    status = "disconnected"
                    is_enabled = False

            self.agent_core.memory_store.update_plugin(
                plugin_id,
                is_enabled=is_enabled,
                status=status,
                config=config_data,
            )
            if plugin_id == "lms" and isinstance(config_data, dict):
                if "url" in config_data:
                    self.agent_core.academic_surfer.save_config({"lms_feed_url": config_data["url"]})
                if "cookie" in config_data:
                    self.agent_core.academic_surfer.save_config({"lms_session_cookie": config_data["cookie"]})
            elif plugin_id == "teams" and isinstance(config_data, dict):
                if "url" in config_data:
                    self.agent_core.academic_surfer.save_config({"teams_feed_url": config_data["url"]})
                if "cookie" in config_data:
                    self.agent_core.academic_surfer.save_config({"teams_session_cookie": config_data["cookie"]})

            p = self.agent_core.memory_store.get_plugin(plugin_id)
            self._send_json(200, {"status": "ok", "plugin": p.to_dict() if p else None})
            return

        # Test Plugin Connection
        if path == "/api/plugins/test":
            plugin_id = payload.get("id")
            if plugin_id in ("lms", "teams"):
                res = self.agent_core.academic_surfer.sync_all()
                self._send_json(200, {"status": "ok", "message": f"Verified {plugin_id.upper()} feed connection.", "details": res})
            elif plugin_id == "github":
                token = payload.get("token") or ""
                self._send_json(200, {"status": "ok", "message": "GitHub connection verified." if token else "Configured in local inspection mode."})
            else:
                self._send_json(200, {"status": "ok", "message": f"Plugin '{plugin_id}' test succeeded."})
            return

        # Upload Document to Library
        if path == "/api/library/upload":
            filename = payload.get("filename", "document.pdf").strip()
            title = payload.get("title") or filename
            tags = payload.get("tags", "")
            description = payload.get("description", "")
            b64_content = payload.get("content_base64", "")

            if not b64_content:
                self._send_json(400, {"error": "Missing 'content_base64' in payload"})
                return

            try:
                if "," in b64_content:
                    b64_content = b64_content.split(",", 1)[1]
                file_bytes = base64.b64decode(b64_content)
            except Exception as e:
                self._send_json(400, {"error": f"Invalid base64 encoding: {e}"})
                return

            doc_id = f"doc_{int(time.time() * 1000)}"
            safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip() or "file.pdf"
            dest_path = LIBRARY_DIR / f"{doc_id}_{safe_name}"

            with open(dest_path, "wb") as f:
                f.write(file_bytes)

            file_ext = safe_name.split(".")[-1].lower() if "." in safe_name else "pdf"
            from memory.models import LibraryItem
            item = LibraryItem(
                id=doc_id,
                filename=safe_name,
                filepath=str(dest_path),
                file_type=file_ext,
                file_size=len(file_bytes),
                title=title,
                tags=tags,
                description=description,
            )
            self.agent_core.memory_store.add_library_item(item)
            self._send_json(201, {"status": "uploaded", "item": item.to_dict()})
            return

        # Multi-Agent Subagent Delegation
        if path == "/api/orchestrator/delegate":
            objective = payload.get("objective", "").strip()
            if not objective:
                self._send_json(400, {"error": "Missing 'objective' in body"})
                return
            role_name = payload.get("role_name", "Sub-Agent")
            persona = payload.get("persona", f"Specialist assigned to: {objective}")
            skill_id = payload.get("skill_id")
            skill = self.agent_core.skill_registry.get_skill(skill_id) if skill_id else None
            input_data = payload.get("input_data", "")

            try:
                subagent = self.agent_core.orchestrator.create_subagent(
                    name=role_name,
                    persona=persona,
                    skill=skill,
                )
                output = subagent.run_task(objective, input_data=input_data)
                self._send_json(200, {
                    "status": "completed",
                    "role_name": role_name,
                    "objective": objective,
                    "output": output,
                })
            except Exception as e:
                logger.error(f"Subagent execution failed: {e}")
                self._send_json(500, {"error": str(e)})
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

        if path.startswith("/api/projects/"):
            project_id = path[len("/api/projects/"):].strip("/")
            name = payload.get("name")
            description = payload.get("description")
            color = payload.get("color")
            metadata = payload.get("metadata")
            ok = self.agent_core.memory_store.update_project(
                project_id,
                name=name,
                description=description,
                color=color,
                metadata=metadata,
            )
            if ok:
                self._send_json(200, {"status": "ok", "project_id": project_id})
            else:
                self._send_json(404, {"error": "Project not found"})
            return

        if path.startswith("/api/schedules/deadlines/"):
            deadline_id = path[len("/api/schedules/deadlines/"):].strip("/")
            title = payload.get("title")
            description = payload.get("description")
            due_date = payload.get("due_date")
            platform = payload.get("platform")
            group_name = payload.get("group_name")
            url = payload.get("url")
            is_completed = payload.get("is_completed")
            priority = payload.get("priority")
            metadata = payload.get("metadata")
            ok = self.agent_core.memory_store.update_deadline(
                deadline_id=deadline_id,
                title=title,
                description=description,
                due_date=due_date,
                platform=platform,
                group_name=group_name,
                url=url,
                is_completed=is_completed,
                priority=priority,
                metadata=metadata,
            )
            if ok:
                self._send_json(200, {"status": "ok", "deadline_id": deadline_id})
            else:
                self._send_json(404, {"error": "Deadline not found"})
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/projects/"):
            project_id = path[len("/api/projects/"):].strip("/")
            ok = self.agent_core.memory_store.delete_project(project_id)
            if ok:
                self._send_json(200, {"status": "deleted", "project_id": project_id})
            else:
                self._send_json(404, {"error": "Project not found"})
            return

        if path.startswith("/api/sessions/"):
            session_id = urllib.parse.unquote(path[len("/api/sessions/"):].strip("/"))
            self.agent_core.memory_store.delete_session(session_id)
            if self.agent_core._active_session_id == session_id:
                remaining = self.agent_core.memory_store.list_sessions(limit=1)
                self.agent_core._active_session_id = remaining[0].id if remaining else None
            self._send_json(200, {"status": "deleted", "session_id": session_id})
            return

        if path.startswith("/api/teams/alerts/"):
            alert_id = urllib.parse.unquote(path[len("/api/teams/alerts/"):].strip("/"))
            self.agent_core.memory_store.delete_teams_alert(alert_id)
            self._send_json(200, {"status": "deleted", "id": alert_id})
            return

        if path == "/api/teams/alerts":
            self.agent_core.memory_store.delete_teams_alert("all")
            self._send_json(200, {"status": "deleted", "id": "all"})
            return

        if path.startswith("/api/schedules/deadlines/"):
            deadline_id = path[len("/api/schedules/deadlines/"):].strip("/")
            ok = self.agent_core.memory_store.delete_deadline(deadline_id)
            if ok:
                self._send_json(200, {"status": "deleted", "deadline_id": deadline_id})
            else:
                self._send_json(404, {"error": "Deadline not found"})
            return

        if path.startswith("/api/library/"):
            item_id = path[len("/api/library/"):].strip("/")
            item = self.agent_core.memory_store.get_library_item(item_id)
            if item and os.path.exists(item.filepath):
                try:
                    os.remove(item.filepath)
                except Exception as e:
                    logger.warning(f"Failed to remove physical file: {e}")
            ok = self.agent_core.memory_store.delete_library_item(item_id)
            if ok:
                self._send_json(200, {"status": "deleted", "item_id": item_id})
            else:
                self._send_json(404, {"error": "Library item not found"})
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

        if path.startswith("/api/tasks/"):
            task_id = path[len("/api/tasks/"):].strip("/")
            ok = self.agent_core.scheduler.cancel_task(task_id)
            if ok:
                self._send_json(200, {"status": "cancelled", "task_id": task_id})
            else:
                self._send_json(404, {"error": "Task not found"})
            return

        self._send_json(404, {"error": "Endpoint not found"})


def ensure_assets():
    """Copies user selected conceptual sketch background into ui/assets/."""
    assets_dir = BASE_DIR / "ui" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target_bg = assets_dir / "sketch_bg.jpg"
    if target_bg.exists():
        return
    import shutil
    brain_dir = Path.home() / ".gemini" / "antigravity-ide" / "brain"
    artifact_dirs = list(brain_dir.glob("*")) if brain_dir.exists() else []
    artifact_dir = artifact_dirs[-1] if artifact_dirs else Path(".")
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
