"""
Meera - Microsoft Teams & Graph API Connector
Implements Microsoft Device Code OAuth2 Flow (100% Free, Zero-Bloat, Standard Library).
Fetches assignments from the Teams Education Assignments tab and monitors course
channel announcements for the Meera Alerts tab.
"""
from datetime import datetime, timedelta
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from memory.models import AcademicDeadline
from memory.sqlite import SQLiteMemoryStore

logger = logging.getLogger("meera.skills.teams_connector")

# Official Microsoft Teams Public Client ID (Pre-authorized across all M365 Tenants)
DEFAULT_CLIENT_ID = "1fec8e78-bce4-4aaf-ab1b-5451cc387264"

# Key Microsoft Identity & Graph Endpoints (Organizations / School Tenant)
MS_DEVICE_CODE_URL = "https://login.microsoftonline.com/organizations/oauth2/v2.0/devicecode"
MS_TOKEN_URL = "https://login.microsoftonline.com/organizations/oauth2/v2.0/token"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Pre-authorized Microsoft Graph Scope
SCOPES = "https://graph.microsoft.com/.default offline_access"


class TeamsConnector:
    """
    Connects Meera to Microsoft Teams using the official Device Code authorization flow.
    Enables autonomous syncing of student assignments and professor channel announcements.
    """

    def __init__(self, memory_store: Optional[SQLiteMemoryStore] = None):
        self.memory_store = memory_store or SQLiteMemoryStore()

    # ==========================================
    # 1. DEVICE CODE FLOW (LOGIN & REFRESH)
    # ==========================================

    def start_device_code_flow(self, client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Initiates the Microsoft Device Code login flow.
        Returns the user code and verification URL to display to the user.
        """
        saved_cid = self._get_saved_client_id()
        if saved_cid == "04b07795-8ddb-461a-bbee-02f9e1bf7b46":
            saved_cid = DEFAULT_CLIENT_ID
        cid = client_id or saved_cid or DEFAULT_CLIENT_ID
        params = {
            "client_id": cid,
            "scope": SCOPES,
        }
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            MS_DEVICE_CODE_URL,
            data=data,
            headers={
                "User-Agent": "Mozilla/5.0 Meera-Agent/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                # Save the pending device code and client ID into memory store
                self.memory_store.set_academic_config("teams_pending_device_code", result.get("device_code", ""))
                self.memory_store.set_academic_config("teams_client_id", cid)
                return {
                    "status": "success",
                    "user_code": result.get("user_code"),
                    "device_code": result.get("device_code"),
                    "verification_uri": result.get("verification_uri", "https://login.microsoft.com/device"),
                    "expires_in": result.get("expires_in", 900),
                    "interval": result.get("interval", 5),
                    "message": result.get("message", "Open the link and enter the code."),
                }
        except Exception as e:
            logger.error(f"Failed to start device code flow: {e}")
            return {"status": "error", "error": str(e)}

    def poll_device_code_token(self, device_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Polls Microsoft Identity for authorization completion.
        If user completed sign-in, saves access_token and refresh_token locally.
        """
        cfg = self.memory_store.get_academic_config()
        d_code = device_code or cfg.get("teams_pending_device_code", "")
        cid = cfg.get("teams_client_id", DEFAULT_CLIENT_ID)
        if not cid or cid == "04b07795-8ddb-461a-bbee-02f9e1bf7b46":
            cid = DEFAULT_CLIENT_ID

        if not d_code:
            return {"status": "error", "error": "No pending device code found. Please start login first."}

        params = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": cid,
            "device_code": d_code,
        }
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            MS_TOKEN_URL,
            data=data,
            headers={
                "User-Agent": "Mozilla/5.0 Meera-Agent/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                token_resp = json.loads(resp.read().decode("utf-8"))
                access_token = token_resp.get("access_token")
                refresh_token = token_resp.get("refresh_token")
                expires_in = int(token_resp.get("expires_in", 3600))
                expires_at = time.time() + expires_in

                if access_token:
                    self.memory_store.set_academic_config("teams_access_token", access_token)
                    if refresh_token:
                        self.memory_store.set_academic_config("teams_refresh_token", refresh_token)
                    self.memory_store.set_academic_config("teams_token_expires_at", str(expires_at))
                    self.memory_store.set_academic_config("teams_auth_status", "connected")
                    # Update plugins table
                    self.memory_store.update_plugin(
                        "teams",
                        is_enabled=True,
                        status="connected",
                        config={"auth_type": "device_code", "client_id": cid},
                    )
                    return {"status": "authorized", "message": "Successfully authorized with Microsoft Teams!"}

                return {"status": "pending", "message": "Authorization pending..."}

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_code = err_json.get("error", "")
                if err_code == "authorization_pending":
                    return {"status": "pending", "message": "Waiting for you to enter code at login.microsoft.com/device"}
                elif err_code == "code_expired":
                    return {"status": "expired", "message": "Login code expired. Please generate a new code."}
                elif err_code == "bad_verification_code":
                    return {"status": "error", "message": "Invalid verification code."}
                return {"status": "error", "error": err_json.get("error_description", err_code)}
            except Exception:
                return {"status": "error", "error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_valid_access_token(self) -> Optional[str]:
        """
        Retrieves a valid access token. Automatically refreshes it if expired.
        """
        cfg = self.memory_store.get_academic_config()
        access_token = cfg.get("teams_access_token")
        refresh_token = cfg.get("teams_refresh_token")
        expires_at_str = cfg.get("teams_token_expires_at", "0")
        cid = cfg.get("teams_client_id", DEFAULT_CLIENT_ID)

        try:
            expires_at = float(expires_at_str)
        except Exception:
            expires_at = 0.0

        # If token is still valid (with 60-second buffer), return it
        if access_token and time.time() < (expires_at - 60):
            return access_token

        # If expired but we have a refresh token, perform silent renewal
        if refresh_token:
            return self._refresh_token(refresh_token, cid)

        return None

    def _refresh_token(self, refresh_token: str, client_id: str) -> Optional[str]:
        """Silently refreshes the access token using the refresh_token."""
        params = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            MS_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                token_resp = json.loads(resp.read().decode("utf-8"))
                new_access = token_resp.get("access_token")
                new_refresh = token_resp.get("refresh_token", refresh_token)
                expires_in = int(token_resp.get("expires_in", 3600))
                expires_at = time.time() + expires_in

                if new_access:
                    self.memory_store.set_academic_config("teams_access_token", new_access)
                    self.memory_store.set_academic_config("teams_refresh_token", new_refresh)
                    self.memory_store.set_academic_config("teams_token_expires_at", str(expires_at))
                    return new_access
        except Exception as e:
            logger.warning(f"Silent token refresh failed: {e}")
        return None

    # ==========================================
    # 2. TEAMS ASSIGNMENTS SYNCHRONIZER
    # ==========================================

    def sync_teams_assignments(self) -> Tuple[List[AcademicDeadline], str]:
        """
        Pulls authentic student assignments directly from Microsoft Teams Education Assignments,
        active course class assignments, Planner, and To-Do tasks.
        Chat channel messages are strictly reserved for Alerts.
        """
        token = self.get_valid_access_token()
        if not token:
            logger.info("[TEAMS SYNC] Not authenticated with Microsoft Teams yet.")
            return [], "Not authenticated with Microsoft Teams. Please click 'Link via Microsoft Device Code'."

        logger.info("[TEAMS SYNC] Authenticated! Querying assignments across Microsoft Graph...")
        deadlines: List[AcademicDeadline] = []
        diagnostics = []

        now_dt = datetime.now()
        week_ago_str = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        today_str = now_dt.strftime("%Y-%m-%d")
        fall_cutoff_str = "2026-08-01"

        try:
            # 1. Direct Student Education Assignments (/education/me/assignments)
            try:
                direct_assignments = self._get_graph_data("/education/me/assignments", token)
                if direct_assignments:
                    diagnostics.append(f"EduDirect: {len(direct_assignments)}")
                    for a in direct_assignments:
                        a_id = a.get("id")
                        title = a.get("displayName") or "Untitled Assignment"
                        desc = self._clean_instructions(a.get("instructions", {}).get("content", ""))
                        due_dt = a.get("dueDateTime") or ""
                        formatted_due = self._format_due_datetime(due_dt)
                        if not formatted_due or formatted_due[:4] < "2026" or formatted_due[:10] < fall_cutoff_str or formatted_due[:10] < week_ago_str:
                            continue
                        status = (a.get("status") or "").lower()
                        is_completed = status in ("submitted", "returned", "completed")
                        # Drop completed assignments whose due date has already passed
                        if is_completed and formatted_due[:10] < today_str:
                            continue
                        deadlines.append(
                            AcademicDeadline(
                                id=f"teams_edu_{a_id}",
                                title=title,
                                description=desc,
                                due_date=formatted_due,
                                platform="teams",
                                group_name="Teams Education",
                                url=a.get("webUrl", "https://teams.microsoft.com/#/school/assignments"),
                                is_completed=is_completed,
                                priority="high" if any(k in title.lower() for k in ("exam", "quiz", "test", "final")) else "normal",
                            )
                        )
            except Exception as e:
                logger.debug(f"/education/me/assignments query: {e}")

            # 2. Check Enrolled Class Teams (/education/classes/{id}/assignments & /me/joinedTeams)
            teams = self._get_graph_data("/me/joinedTeams", token)
            channel_deadlines_count = 0
            if teams:
                sorted_teams = self._prioritize_teams(teams)
                team_names = [t.get("displayName", "Unnamed Team") for t in sorted_teams]
                logger.info(f"[TEAMS SYNC] Discovered {len(teams)} Enrolled Course Teams. Prioritized order: {', '.join(team_names[:6])}")
                diagnostics.append(f"Teams ({len(teams)}): {', '.join(team_names[:3])}")
                
                for team in sorted_teams:
                    # Strictly skip archived / past-semester teams
                    if self._score_team(team) < 0:
                        continue
                    team_id = team.get("id")
                    team_name = team.get("displayName") or "Course Team"

                    # 2a. Check official Class Assignments for this active class
                    try:
                        cls_assignments = self._get_graph_data(f"/education/classes/{team_id}/assignments", token)
                        if cls_assignments:
                            diagnostics.append(f"{team_name}: {len(cls_assignments)}")
                            for a in cls_assignments:
                                a_id = a.get("id")
                                title = a.get("displayName") or "Class Assignment"
                                desc = self._clean_instructions(a.get("instructions", {}).get("content", ""))
                                due_dt = a.get("dueDateTime") or ""
                                formatted_due = self._format_due_datetime(due_dt)
                                if not formatted_due or formatted_due[:4] < "2026" or formatted_due[:10] < fall_cutoff_str or formatted_due[:10] < week_ago_str:
                                    continue
                                status = (a.get("status") or "").lower()
                                is_completed = status in ("submitted", "returned", "completed")
                                if is_completed and formatted_due[:10] < today_str:
                                    continue
                                deadlines.append(
                                    AcademicDeadline(
                                        id=f"teams_edu_{a_id}",
                                        title=title,
                                        description=desc,
                                        due_date=formatted_due,
                                        platform="teams",
                                        group_name=team_name,
                                        url=a.get("webUrl", "https://teams.microsoft.com/#/school/assignments"),
                                        is_completed=is_completed,
                                        priority="high" if any(k in title.lower() for k in ("exam", "quiz", "test", "final")) else "normal",
                                    )
                                )
                    except Exception:
                        pass

                    # 2b. Check Course Channels for Official Assignment Cards
                    try:
                        channels = self._get_graph_data(f"/teams/{team_id}/channels", token)
                        for ch in (channels or [])[:4]:
                            channel_id = ch.get("id")
                            channel_name = ch.get("displayName") or "General"
                            messages = self._get_graph_data(
                                f"/teams/{team_id}/channels/{channel_id}/messages?$top=35",
                                token,
                            )
                            for msg in (messages or []):
                                extracted = self._extract_deadline_from_message(msg, team_name, channel_name)
                                if extracted and extracted.due_date and extracted.due_date[:4] >= "2026" and extracted.due_date[:10] >= fall_cutoff_str and extracted.due_date[:10] >= week_ago_str:
                                    deadlines.append(extracted)
                                    channel_deadlines_count += 1
                    except Exception as err:
                        logger.debug(f"Channel assignment check: {err}")

            # 3. Microsoft 365 Academic Calendar Events (/me/events)
            cal_events = self._get_graph_data("/me/events?$top=50&$select=id,subject,bodyPreview,start,end,categories,webLink,isAllDay", token)
            cal_deadlines_count = 0
            for ev in cal_events:
                subj = ev.get("subject") or ""
                if not subj:
                    continue
                body_prev = ev.get("bodyPreview") or ""
                end_info = ev.get("end", {})
                start_info = ev.get("start", {})
                due_dt = end_info.get("dateTime", "") or start_info.get("dateTime", "")
                formatted_due = self._format_due_datetime(due_dt)
                if not formatted_due or formatted_due[:4] < "2026" or formatted_due[:10] < fall_cutoff_str or formatted_due[:10] < week_ago_str:
                    continue

                subj_lower = subj.lower()
                # Exclude past terms
                if any(y in subj_lower for y in ("2023", "2024", "2025", "24-25", "25-26", "spring 26", "winter 26")):
                    continue

                is_academic = any(k in subj_lower for k in ("assignment", "quiz", "exam", "test", "midterm", "final", "due", "submission", "presentation", "project", "review", "viva", "cat", "fat", "da"))
                if is_academic or "assignment" in str(ev.get("categories", [])).lower():
                    cal_deadlines_count += 1
                    is_exam = any(k in subj_lower for k in ("exam", "quiz", "test", "midterm", "final", "viva", "cat", "fat"))
                    deadlines.append(
                        AcademicDeadline(
                            id=f"teams_cal_{ev.get('id')}",
                            title=subj,
                            description=body_prev[:240] or "Teams Calendar Scheduled Item",
                            due_date=formatted_due,
                            platform="teams",
                            group_name="Teams Calendar",
                            url=ev.get("webLink", "https://teams.microsoft.com"),
                            is_completed=False,
                            priority="high" if is_exam else "normal",
                        )
                    )
            diagnostics.append(f"Calendar: {cal_deadlines_count}")

            # 4. Check Planner Tasks (/me/planner/tasks)
            planner_tasks = self._get_graph_data("/me/planner/tasks", token)
            for t in planner_tasks:
                t_id = t.get("id")
                title = t.get("title") or "Planner Task"
                due_dt = t.get("dueDateTime") or ""
                formatted_due = self._format_due_datetime(due_dt)
                if not formatted_due or formatted_due[:4] < "2026" or formatted_due[:10] < fall_cutoff_str or formatted_due[:10] < week_ago_str:
                    continue
                percent = t.get("percentComplete", 0)
                is_completed = percent >= 100
                if is_completed and formatted_due[:10] < today_str:
                    continue
                if any(y in title.lower() for y in ("2023", "2024", "2025", "24-25", "25-26", "spring 26", "winter 26")):
                    continue
                deadlines.append(
                    AcademicDeadline(
                        id=f"teams_planner_{t_id}",
                        title=title,
                        description="Teams Planner / Group Task",
                        due_date=formatted_due,
                        platform="teams",
                        group_name="Teams Tasks",
                        url="https://teams.microsoft.com",
                        is_completed=is_completed,
                        priority="high" if t.get("priority", 5) <= 3 else "normal",
                    )
                )

            # 5. Check To-Do Lists (/me/todo/lists)
            todo_lists = self._get_graph_data("/me/todo/lists", token)
            for tl in todo_lists:
                lid = tl.get("id")
                tasks = self._get_graph_data(f"/me/todo/lists/{lid}/tasks?$top=50", token)
                for tk in tasks:
                    due_info = tk.get("dueDateTime", {})
                    due_dt = due_info.get("dateTime", "") if isinstance(due_info, dict) else ""
                    formatted_due = self._format_due_datetime(due_dt)
                    if not formatted_due or formatted_due[:4] < "2026" or formatted_due[:10] < fall_cutoff_str or formatted_due[:10] < week_ago_str:
                        continue
                    status = tk.get("status", "").lower()
                    is_completed = status == "completed"
                    if is_completed and formatted_due[:10] < today_str:
                        continue
                    title = tk.get("title") or "To-Do Task"
                    if any(y in title.lower() for y in ("2023", "2024", "2025", "24-25", "25-26", "spring 26", "winter 26")):
                        continue
                    deadlines.append(
                        AcademicDeadline(
                            id=f"teams_todo_{tk.get('id')}",
                            title=title,
                            description=self._clean_instructions(tk.get("body", {}).get("content", "")),
                            due_date=formatted_due,
                            platform="teams",
                            group_name=f"To-Do: {tl.get('displayName', 'Tasks')}",
                            url="https://to-do.office.com",
                            is_completed=is_completed,
                            priority="high" if tk.get("importance") == "high" else "normal",
                        )
                    )

            # Deduplicate by title & due_date and strictly enforce Fall 2026 active semester
            unique_deadlines: Dict[str, AcademicDeadline] = {}
            for d in deadlines:
                if not d.due_date or d.due_date[:4] < "2026" or d.due_date[:10] < fall_cutoff_str or d.due_date[:10] < week_ago_str:
                    continue
                # Exclude past years and prior semesters
                t_lower = (d.title or "").lower()
                g_lower = (d.group_name or "").lower()
                if any(y in t_lower or y in g_lower for y in ("2023", "2024", "2025", "24-25", "25-26", "spring 26", "winter 26", "even 26")):
                    continue
                # Drop completed tasks whose due date has passed
                if d.is_completed and d.due_date[:10] < today_str:
                    continue
                key = f"{d.title}_{d.due_date}"
                if key not in unique_deadlines:
                    unique_deadlines[key] = d

            final_list = list(unique_deadlines.values())
            summary_info = " // ".join(diagnostics)
            if final_list:
                self.memory_store.upsert_deadlines(final_list)
                return final_list, f"Successfully synced {len(final_list)} assignments and events from Teams ({summary_info})."

            return [], f"Scanned Teams endpoints ({summary_info}). No upcoming assignments found."

        except Exception as e:
            logger.error(f"Error syncing Teams assignments: {e}")
            return [], f"Teams assignments fetch error: {str(e)}"

    # ==========================================
    # 3. PROFESSOR CHANNEL ANNOUNCEMENT SENTRY
    # ==========================================

    def _score_team(self, team: Dict[str, Any]) -> int:
        """Scores a course team to prioritize current active semester courses over past years."""
        name = (team.get("displayName") or "").lower()
        score = 0
        # High priority for current academic year (2026-2027) & current Fall semester
        if any(k in name for k in ("fall", "2026-27", "2026_27", "26-27", "26_27", "fall 26", "fall-26", "fall26", "fall_2026", "odd 26", "sem 5", "sem 7")):
            score += 250
        elif any(k in name for k in ("2026", "26")):
            score += 50

        # Heavily penalize previous semesters and past academic years
        if any(k in name for k in (
            "spring 26", "spring-26", "spring26", "spring_26",
            "winter 26", "winter-26", "winter26", "winter_26",
            "even 26", "even-26",
            "24-25", "2024-25", "2024", "24_25", "fall 24", "winter 24", "fall-24", "fall_24",
            "25-26", "2025-26", "2025", "25_26", "fall 25", "winter 25", "fall-25", "fall_25",
            "23-24", "2023", "23_24"
        )):
            score -= 300

        # Favor active course keywords
        if any(k in name for k in ("theory", "lab", "compiler", "statistics", "probability", "cse", "ece", "project", "class")):
            score += 30
        return score

    def _prioritize_teams(self, teams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sorts enrolled teams so current-semester courses come first."""
        return sorted(teams, key=self._score_team, reverse=True)

    def _extract_attachment_info(self, attachments: List[Dict[str, Any]]) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Recursively extracts text content, title, and explicit dueDateTime from Teams message attachments
        (Adaptive Cards, O365 connector cards, files).
        Returns (combined_text, extracted_title, explicit_due_datetime).
        """
        collected_text = []
        extracted_title = None
        explicit_due = None

        def walk_node(node: Any):
            nonlocal extracted_title, explicit_due
            if isinstance(node, dict):
                for due_key in ("dueDateTime", "dueDate", "due_date"):
                    if due_key in node and isinstance(node[due_key], str) and node[due_key]:
                        explicit_due = explicit_due or node[due_key]
                for title_key in ("title", "displayName", "name"):
                    if title_key in node and isinstance(node[title_key], str) and node[title_key]:
                        val = node[title_key].strip()
                        if val and not extracted_title and len(val) >= 4 and not val.endswith((".png", ".jpg", ".gif")):
                            extracted_title = val
                        collected_text.append(val)
                for text_key in ("text", "value", "description", "subtitle"):
                    if text_key in node and isinstance(node[text_key], str) and node[text_key]:
                        collected_text.append(node[text_key].strip())
                if "facts" in node and isinstance(node["facts"], list):
                    for fact in node["facts"]:
                        if isinstance(fact, dict):
                            fname = str(fact.get("name", ""))
                            fval = str(fact.get("value", ""))
                            collected_text.append(f"{fname}: {fval}")
                            if any(k in fname.lower() for k in ("due", "deadline", "date")):
                                explicit_due = explicit_due or fval

                for v in node.values():
                    walk_node(v)
            elif isinstance(node, list):
                for item in node:
                    walk_node(item)

        for att in attachments:
            if not isinstance(att, dict):
                continue
            name = att.get("name")
            if name:
                collected_text.append(name)
                if not extracted_title:
                    extracted_title = name

            content = att.get("content")
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    walk_node(parsed)
                except Exception:
                    clean = self._strip_html(content)
                    if clean:
                        collected_text.append(clean)
            elif isinstance(content, (dict, list)):
                walk_node(content)

        return " ".join(collected_text), extracted_title, explicit_due

    def monitor_channel_announcements(self) -> List[Dict[str, Any]]:
        """
        Scans recent messages in current-semester course channels for important professor announcements
        (e.g., assignment alerts, due dates, cancellations, exam dates) from the past 7 days.
        """
        token = self.get_valid_access_token()
        if not token:
            return []

        discovered_alerts: List[Dict[str, Any]] = []
        alert_keywords = re.compile(
            r"\b(assignment|due|submission|quiz|exam|midterm|test|deadline|cancelled|class|lab|rescheduled|important|project|task|da-?[1-9]|cat-?[1-9]|fat|viva|lecture|meeting|attendance|session|link|notice|slides|notes)\b",
            re.IGNORECASE,
        )

        try:
            teams = self._get_graph_data("/me/joinedTeams", token)
            sorted_teams = self._prioritize_teams(teams)
            for team in sorted_teams[:12]:
                # Strictly skip archived / past-year teams (negative score)
                if self._score_team(team) < 0:
                    continue

                team_id = team.get("id")
                team_name = team.get("displayName") or "Course Team"

                channels = self._get_graph_data(f"/teams/{team_id}/channels", token)
                for ch in channels[:3]:
                    channel_id = ch.get("id")
                    channel_name = ch.get("displayName") or "General"

                    messages = self._get_graph_data(
                        f"/teams/{team_id}/channels/{channel_id}/messages?$top=20",
                        token,
                    )

                    for msg in messages:
                        body_content = msg.get("body", {}).get("content", "")
                        clean_text = self._strip_html(body_content)
                        attachments = msg.get("attachments") or []
                        att_text, _, _ = self._extract_attachment_info(attachments)
                        combined = f"{clean_text} {att_text}".strip()
                        if not combined or len(combined) < 12:
                            continue

                        if alert_keywords.search(combined):
                            author_info = msg.get("from", {}).get("user", {})
                            author_name = author_info.get("displayName") or "Instructor"
                            created_dt = msg.get("createdDateTime", "")
                            cutoff_dt = datetime.now() - timedelta(days=7)
                            week_ago_iso = cutoff_dt.strftime("%Y-%m-%d")
                            msg_timestamp = None
                            if created_dt:
                                try:
                                    clean_dt_str = created_dt.replace("Z", "").split("+")[0].split(".")[0]
                                    msg_dt = datetime.fromisoformat(clean_dt_str)
                                    if msg_dt >= cutoff_dt:
                                        msg_timestamp = msg_dt.timestamp()
                                except Exception:
                                    pass

                            # Strictly skip any announcement older than 7 days
                            if not msg_timestamp or (created_dt and created_dt[:10] < week_ago_iso):
                                continue

                            discovered_alerts.append({
                                "id": f"alert_msg_{msg.get('id', int(time.time()))}",
                                "team_name": team_name,
                                "channel_name": channel_name,
                                "author": author_name,
                                "snippet": combined[:280] + ("..." if len(combined) > 280 else ""),
                                "timestamp": created_dt,
                                "created_at": msg_timestamp,
                            })

            if discovered_alerts:
                self.memory_store.upsert_teams_alerts(discovered_alerts)
            return discovered_alerts

        except Exception as e:
            logger.warning(f"Error monitoring channel messages: {e}")
            return []

    def _extract_deadline_from_message(self, msg: Dict[str, Any], team_name: str, channel_name: str) -> Optional[AcademicDeadline]:
        """Extracts an AcademicDeadline from a Teams channel message if it is an official assignment or course notice."""
        subj = msg.get("subject") or ""
        body_content = msg.get("body", {}).get("content", "")
        clean_body = self._strip_html(body_content)

        attachments = msg.get("attachments") or []
        att_text, att_title, explicit_due = self._extract_attachment_info(attachments)

        # Genuine assignments created by professors must have an assignment card or assignment keywords in subject/content
        has_official_card = any(
            "card" in str(att.get("contentType", "")).lower() or
            "assignment" in str(att.get("name", "")).lower() or
            "assignment" in str(att.get("contentType", "")).lower()
            for att in attachments if isinstance(att, dict)
        )
        is_assignment = (
            has_official_card or
            "assignment" in subj.lower() or
            "assignments" in subj.lower() or
            "assignments for lab" in clean_body.lower() or
            "assignment" in (att_title or "").lower() or
            explicit_due is not None
        )

        if not is_assignment:
            return None

        combined_text = f"{subj} {clean_body} {att_text}".strip()
        msg_id = msg.get("id") or str(int(time.time() * 1000))
        created_dt = msg.get("createdDateTime", "")

        due_date = self._parse_due_date_from_text(combined_text, created_dt, explicit_due)
        # Must have an explicit due date and be for current academic year (>= 2026)
        if not due_date or due_date[:4] < "2026":
            return None

        now_dt = datetime.now()
        week_ago_str = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        if due_date[:10] < "2026-08-01" or due_date[:10] < week_ago_str:
            return None

        if att_title and len(att_title) >= 4 and (not subj or subj.lower().strip() in ("assignment", "new assignment", "assignments", "notice")):
            title = att_title[:70]
        elif subj and len(subj) >= 4:
            title = subj[:70]
        elif att_title and len(att_title) >= 4:
            title = att_title[:70]
        else:
            first_sentence = clean_body.split("\n")[0].split(".")[0].strip() if clean_body else ""
            if not first_sentence and att_text:
                first_sentence = att_text.split("\n")[0].split(".")[0].strip()
            title = first_sentence[:65] if len(first_sentence) >= 6 else "Assignments for Lab"

        # Exclude past semester tags in title or team
        t_low = title.lower()
        tm_low = team_name.lower()
        if any(y in t_low or y in tm_low for y in ("2023", "2024", "2025", "24-25", "25-26", "spring 26", "winter 26", "spring-26", "winter-26")):
            return None

        is_exam = any(k in combined_text.lower() for k in ("exam", "quiz", "test", "midterm", "final", "viva", "cat", "fat"))

        clean_snippet = clean_body[:200] if clean_body else att_text[:200]
        return AcademicDeadline(
            id=f"teams_msg_{msg_id}",
            title=title,
            description=clean_snippet or f"Course assignment from {team_name}",
            due_date=due_date,
            platform="teams",
            group_name=team_name,
            url=msg.get("webUrl", "https://teams.microsoft.com"),
            is_completed=False,
            priority="high" if is_exam else "normal",
        )

    def _parse_due_date_from_text(self, text: str, fallback_created: str, explicit_due: Optional[str] = None) -> str:
        """Heuristically extracts a date string from notice text or explicit attachment info."""
        if explicit_due:
            formatted = self._format_due_datetime(explicit_due)
            if formatted:
                return formatted

        now = datetime.now()
        fall_cutoff_str = "2026-08-01"
        week_ago_str = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }

        # Check explicit hour / minute if mentioned like "23:59"
        target_hr, target_mn = 23, 59
        m_time = re.search(r'\b([01]?[0-9]|2[0-3]):([0-5][0-9])\b', text)
        if m_time:
            target_hr = int(m_time.group(1))
            target_mn = int(m_time.group(2))

        def _validate_date(y: int, m: int, d: int, hr: int = target_hr, mn: int = target_mn) -> str:
            if y < 2026:
                return ""
            try:
                dt = datetime(y, m, d, hr, mn)
                s = dt.strftime("%Y-%m-%d %H:%M")
                if s[:10] < fall_cutoff_str or s[:10] < week_ago_str:
                    return ""
                return s
            except Exception:
                return ""

        # 0. Look for standard date format in assignment cards: "20 Oct", "20 Oct Tuesday", "Oct 20"
        m_general = re.search(
            r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s*,?\s*(\d{4}))?\b',
            text,
            re.IGNORECASE,
        )
        if m_general:
            day = int(m_general.group(1))
            m_str = m_general.group(2).lower()[:3]
            month = months.get(m_str, now.month)
            year = int(m_general.group(3)) if m_general.group(3) else (now.year + 1 if month < now.month - 1 else now.year)
            res = _validate_date(year, month, day, target_hr, target_mn)
            if res:
                return res

        # 1. Look for explicit keyword date: "due on 20 oct", "dues on 20 oct", "due: 20th oct"
        m_phrase = re.search(
            r'(?:due|dues|deadline|submission|submit)\s+(?:on|by|before|is|date)?\s*[:\-]?\s*(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s*,?\s*(\d{4}))?',
            text,
            re.IGNORECASE,
        )
        if m_phrase:
            day = int(m_phrase.group(1))
            m_str = m_phrase.group(2).lower()[:3]
            month = months.get(m_str, now.month)
            year = int(m_phrase.group(3)) if m_phrase.group(3) else (now.year + 1 if month < now.month - 1 else now.year)
            res = _validate_date(year, month, day, target_hr, target_mn)
            if res:
                return res

        # 2. Look for explicit keyword date reversed: "due on oct 20", "dues on oct 20"
        m_phrase_rev = re.search(
            r'(?:due|dues|deadline|submission|submit)\s+(?:on|by|before|is|date)?\s*[:\-]?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?',
            text,
            re.IGNORECASE,
        )
        if m_phrase_rev:
            m_str = m_phrase_rev.group(1).lower()[:3]
            month = months.get(m_str, now.month)
            day = int(m_phrase_rev.group(2))
            year = int(m_phrase_rev.group(3)) if m_phrase_rev.group(3) else (now.year + 1 if month < now.month - 1 else now.year)
            res = _validate_date(year, month, day, target_hr, target_mn)
            if res:
                return res

        # 3. Look for 2-part dates: "due on 20/10", "due: 20-10", "due: 20.10"
        m_two_part = re.search(
            r'(?:due|dues|deadline|submission|submit)\s+(?:on|by|before|is|date)?\s*[:\-]?\s*(\d{1,2})[/\-.]([0-9]{1,2})\b',
            text,
            re.IGNORECASE,
        )
        if m_two_part:
            d = int(m_two_part.group(1))
            m = int(m_two_part.group(2))
            if 1 <= d <= 31 and 1 <= m <= 12:
                year = now.year + 1 if m < now.month - 1 else now.year
                res = _validate_date(year, m, d)
                if res:
                    return res

        # 4. Look for explicit numeric date: "due: 25/10/2026", "due date: 2026-10-25"
        m_due = re.search(
            r'(?:due|dues|deadline|submission|submit|last\s+date)\s*[:\-]?\s*([0-9]{1,4}[/\-.][0-9]{1,2}[/\-.][0-9]{1,4})',
            text,
            re.IGNORECASE,
        )
        if m_due:
            raw_d = m_due.group(1).replace(".", "-").replace("/", "-")
            parts = [int(p) for p in raw_d.split("-") if p.isdigit()]
            if len(parts) == 3:
                if parts[0] > 1900:  # YYYY-MM-DD
                    res = _validate_date(parts[0], parts[1], parts[2])
                    if res:
                        return res
                else:  # DD-MM-YYYY
                    y = parts[2] if parts[2] > 1900 else (2000 + parts[2] if parts[2] < 100 else parts[2])
                    res = _validate_date(y, parts[1], parts[0])
                    if res:
                        return res

        # 5. Pattern: "Oct 25" or "October 25" or "Oct 25, 2026"
        m = re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?', text, re.IGNORECASE)
        if m:
            m_str = m.group(1).lower()[:3]
            month = months.get(m_str, now.month)
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else (now.year + 1 if month < now.month - 1 else now.year)
            res = _validate_date(year, month, day)
            if res:
                return res

        # 6. Pattern: "25th Oct" or "25 Oct 2026"
        m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s*,?\s*(\d{4}))?', text, re.IGNORECASE)
        if m:
            day = int(m.group(1))
            m_str = m.group(2).lower()[:3]
            month = months.get(m_str, now.month)
            year = int(m.group(3)) if m.group(3) else (now.year + 1 if month < now.month - 1 else now.year)
            res = _validate_date(year, month, day)
            if res:
                return res

        # 7. Standard ISO or slash date anywhere in text: YYYY-MM-DD or DD/MM/YYYY
        m_iso = re.search(r'\b(202[6-9])[/-](\d{1,2})[/-](\d{1,2})\b', text)
        if m_iso:
            res = _validate_date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
            if res:
                return res

        m_dmy = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](202[6-9])\b', text)
        if m_dmy:
            res = _validate_date(int(m_dmy.group(3)), int(m_dmy.group(2)), int(m_dmy.group(1)))
            if res:
                return res

        # If no explicit deadline was found in the text or attachments, return empty string
        return ""

    def get_joined_teams(self) -> List[Dict[str, Any]]:
        """Returns the list of teams the user is currently joined in."""
        token = self.get_valid_access_token()
        if not token:
            return []
        teams = self._get_graph_data("/me/joinedTeams", token)
        return [
            {
                "id": t.get("id"),
                "name": t.get("displayName", "Unnamed Team"),
                "description": t.get("description", ""),
            }
            for t in teams
        ]

    # ==========================================
    # HELPER UTILITIES
    # ==========================================

    def _get_graph_data(self, endpoint: str, token: str) -> List[Dict[str, Any]]:
        """Makes an authenticated GET request to the Microsoft Graph API."""
        url = f"{GRAPH_BASE_URL}{endpoint}" if not endpoint.startswith("http") else endpoint
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 Meera-Agent/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("value", []) if isinstance(data, dict) else []
        except urllib.error.HTTPError as e:
            if "/education" in endpoint and e.code == 403:
                logger.debug(f"[GRAPH API] {endpoint} HTTP 403: Education SDS API restricted by tenant.")
            else:
                logger.warning(f"[GRAPH API] Request to {endpoint} returned: HTTP {e.code} {e.reason}")
            return []
        except Exception as e:
            logger.warning(f"[GRAPH API] Request to {endpoint} returned: {e}")
            return []

    def _strip_html(self, raw_html: Optional[str]) -> str:
        """Removes HTML tags from message content."""
        if not raw_html:
            return ""
        clean = re.sub(r"<[^>]+>", " ", str(raw_html))
        return re.sub(r"\s+", " ", clean).strip()

    def _clean_instructions(self, raw: str) -> str:
        clean = self._strip_html(raw)
        return clean[:300] if len(clean) > 300 else clean

    def _format_due_datetime(self, iso_str: str) -> str:
        if not iso_str:
            return ""
        try:
            clean = iso_str.split(".")[0].replace("Z", "").replace("T", " ").strip()
            now = datetime.now()
            ninety_days_ago_str = (now - timedelta(days=90)).strftime("%Y-%m-%d")

            # If already standard ISO YYYY-MM-DD:
            if re.match(r"^\d{4}-\d{2}-\d{2}", clean):
                res = clean[:16]
                if res[:4] < "2026" or res[:10] < ninety_days_ago_str:
                    return ""
                return res

            # If human date like "20 Oct 23:59", "20th Oct", "Oct 20, 2026":
            months = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            }
            # Pattern: 20 Oct [2026] [23:59]
            m1 = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s*,?\s*(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?', clean, re.IGNORECASE)
            if m1:
                d = int(m1.group(1))
                mo = months.get(m1.group(2).lower()[:3], now.month)
                y = int(m1.group(3)) if m1.group(3) else (now.year + 1 if mo < now.month - 1 else now.year)
                if y < 2026:
                    return ""
                hr = int(m1.group(4)) if m1.group(4) else 23
                mn = int(m1.group(5)) if m1.group(5) else 59
                res = datetime(y, mo, d, hr, mn).strftime("%Y-%m-%d %H:%M")
                if res[:10] < ninety_days_ago_str:
                    return ""
                return res

            # Pattern: Oct 20 [2026] [23:59]
            m2 = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?', clean, re.IGNORECASE)
            if m2:
                mo = months.get(m2.group(1).lower()[:3], now.month)
                d = int(m2.group(2))
                y = int(m2.group(3)) if m2.group(3) else (now.year + 1 if mo < now.month - 1 else now.year)
                if y < 2026:
                    return ""
                hr = int(m2.group(4)) if m2.group(4) else 23
                mn = int(m2.group(5)) if m2.group(5) else 59
                res = datetime(y, mo, d, hr, mn).strftime("%Y-%m-%d %H:%M")
                if res[:10] < ninety_days_ago_str:
                    return ""
                return res

            return ""
        except Exception:
            return ""

    def _get_saved_client_id(self) -> Optional[str]:
        cfg = self.memory_store.get_academic_config()
        cid = cfg.get("teams_client_id")
        if cid == "04b07795-8ddb-461a-bbee-02f9e1bf7b46":
            return DEFAULT_CLIENT_ID
        return cid or DEFAULT_CLIENT_ID
