"""
Meera - Academic & MS Teams Surfer Engine
Extracts assignments, deadlines, and upcoming tasks from College LMS and Microsoft Teams.
Zero third-party web dependencies (pure standard library: urllib.request, re, datetime).
"""
from datetime import datetime, timedelta
import hashlib
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from memory.models import AcademicDeadline
from memory.sqlite import SQLiteMemoryStore

logger = logging.getLogger("meera.skills.academic_surfer")


class AcademicSurfer:
    """
    Surfer and synchronizer for College LMS and Microsoft Teams calendars and assignments.
    Parses standard iCalendar (.ics / webcal) feeds and session-authenticated endpoints.
    """

    def __init__(self, memory_store: Optional[SQLiteMemoryStore] = None):
        self.memory_store = memory_store or SQLiteMemoryStore()

    def get_config(self) -> Dict[str, str]:
        """Returns the configured feed URLs and session credentials."""
        return self.memory_store.get_academic_config()

    def save_config(self, config: Dict[str, str]) -> None:
        """Saves feed URLs and credentials into SQLite."""
        for k, v in config.items():
            self.memory_store.set_academic_config(k, v)

    def sync_all(self) -> Dict[str, Any]:
        """
        Executes synchronization for both LMS and MS Teams.
        Returns a summary report of newly discovered or updated deadlines.
        """
        config = self.get_config()
        lms_feed_url = config.get("lms_feed_url", "").strip()
        lms_cookie = config.get("lms_session_cookie", "").strip()
        teams_feed_url = config.get("teams_feed_url", "").strip()
        teams_cookie = config.get("teams_session_cookie", "").strip()

        all_deadlines: List[AcademicDeadline] = []
        sync_logs: List[str] = []

        # 1. Sync College LMS
        lms_items, lms_log = self._sync_source(
            platform="lms",
            feed_url=lms_feed_url,
            cookie=lms_cookie,
            default_group="College LMS Portal",
        )
        all_deadlines.extend(lms_items)
        sync_logs.append(lms_log)

        # 2. Sync MS Teams
        teams_items, teams_log = self._sync_source(
            platform="teams",
            feed_url=teams_feed_url,
            cookie=teams_cookie,
            default_group="MS Teams Channels",
        )
        all_deadlines.extend(teams_items)
        sync_logs.append(teams_log)

        # 3. Upsert to persistent SQLite database
        saved_count = 0
        if all_deadlines:
            saved_count = self.memory_store.upsert_deadlines(all_deadlines)

        return {
            "status": "success",
            "synced_count": len(all_deadlines),
            "upserted_count": saved_count,
            "logs": sync_logs,
            "deadlines": [d.to_dict() for d in self.memory_store.list_deadlines()],
        }

    def _sync_source(
        self,
        platform: str,
        feed_url: str,
        cookie: str,
        default_group: str,
    ) -> Tuple[List[AcademicDeadline], str]:
        """Synchronizes an individual source feed or returns empty if not configured."""
        if not feed_url:
            return [], f"[{platform.upper()}] No feed URL configured."

        # Convert webcal:// to https://
        clean_url = feed_url
        if clean_url.startswith("webcal://"):
            clean_url = "https://" + clean_url[9:]

        req = urllib.request.Request(
            clean_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Meera/1.0 AcademicSurfer",
                "Accept": "text/calendar, application/json, text/plain, */*",
            },
        )
        if cookie:
            req.add_header("Cookie", cookie)

        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                
                # Check if iCal format
                if "BEGIN:VCALENDAR" in content or "BEGIN:VEVENT" in content:
                    items = self._parse_ics_content(content, platform, default_group)
                    return items, f"[{platform.upper()}] Fetched {len(items)} events from calendar feed."

                # Check if JSON format
                try:
                    data = json.loads(content)
                    items = self._parse_json_assignments(data, platform, default_group)
                    return items, f"[{platform.upper()}] Fetched {len(items)} items from JSON feed."
                except Exception:
                    pass

                return [], f"[{platform.upper()}] Unrecognized feed format at {clean_url}."
        except urllib.error.URLError as e:
            logger.warning(f"Failed to fetch {platform} feed: {e}")
            return [], f"[{platform.upper()}] Network connection error: {e.reason}"
        except Exception as e:
            logger.error(f"Error parsing {platform} feed: {e}")
            return [], f"[{platform.upper()}] Synchronization error: {str(e)}"

    def _parse_ics_content(self, ics_text: str, platform: str, default_group: str) -> List[AcademicDeadline]:
        """Parses iCalendar .ics format into AcademicDeadline dataclasses."""
        deadlines: List[AcademicDeadline] = []
        vevents = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics_text, re.DOTALL)

        for event_raw in vevents:
            # Extract fields
            summary = self._extract_ics_field(event_raw, "SUMMARY") or "Untitled Assignment"
            description = self._extract_ics_field(event_raw, "DESCRIPTION") or ""
            dtend = self._extract_ics_field(event_raw, "DTEND")
            dtstart = self._extract_ics_field(event_raw, "DTSTART")
            location = self._extract_ics_field(event_raw, "LOCATION") or ""
            categories = self._extract_ics_field(event_raw, "CATEGORIES") or ""
            url = self._extract_ics_field(event_raw, "URL") or ""
            uid = self._extract_ics_field(event_raw, "UID")

            due_str = dtend or dtstart or ""
            formatted_date = self._format_ics_date(due_str)

            # Determine course / group name
            group_name = location or categories or default_group
            # If summary contains brackets like "[CS401] Homework", extract course
            bracket_match = re.search(r"\[(.*?)\]", summary)
            if bracket_match:
                group_name = bracket_match.group(1).strip()
                summary = summary.replace(f"[{group_name}]", "").strip()

            if not uid:
                uid_hash = hashlib.md5(f"{platform}_{summary}_{formatted_date}".encode()).hexdigest()[:12]
                uid = f"{platform}_{uid_hash}"
            else:
                uid = f"{platform}_{uid.strip()}"

            ninety_days_ago_str = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            if not formatted_date or formatted_date[:4] < "2026" or formatted_date[:10] < ninety_days_ago_str:
                continue

            deadlines.append(
                AcademicDeadline(
                    id=uid,
                    title=summary,
                    description=description,
                    due_date=formatted_date,
                    platform=platform,
                    group_name=group_name,
                    url=url,
                    is_completed=False,
                    priority="high" if "exam" in summary.lower() or "quiz" in summary.lower() else "normal",
                )
            )

        return deadlines

    def _extract_ics_field(self, event_text: str, field_name: str) -> Optional[str]:
        """Extracts field value with potential multiline unfold."""
        pattern = rf"(?:^|\n){field_name}(?:;[^:]*)?:(.*?)(?=\n[A-Z0-9-]+:|\nEND:VEVENT|$)"
        match = re.search(pattern, event_text, re.DOTALL)
        if not match:
            return None
        val = match.group(1).replace("\r\n ", "").replace("\n ", "").strip()
        val = val.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";")
        return val

    def _format_ics_date(self, date_val: str) -> str:
        """Converts ICS date format (e.g. 20261015T180000Z or 20261015) to YYYY-MM-DDTHH:MM."""
        if not date_val:
            # Default to tomorrow
            return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT23:59")

        # Strip value parameters like VALUE=DATE:
        if ":" in date_val:
            date_val = date_val.split(":")[-1]

        date_val = date_val.strip()

        try:
            if "T" in date_val:
                dt_part = date_val.replace("Z", "")
                if len(dt_part) >= 15:
                    dt = datetime.strptime(dt_part[:15], "%Y%m%dT%H%M%S")
                    return dt.strftime("%Y-%m-%dT%H:%M")
                elif len(dt_part) >= 13:
                    dt = datetime.strptime(dt_part[:13], "%Y%m%dT%H%M")
                    return dt.strftime("%Y-%m-%dT%H:%M")
            elif len(date_val) >= 8:
                dt = datetime.strptime(date_val[:8], "%Y%m%d")
                return dt.strftime("%Y-%m-%dT23:59")
        except Exception:
            pass

        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT23:59")

    def _parse_json_assignments(self, data: Any, platform: str, default_group: str) -> List[AcademicDeadline]:
        """Parses common JSON assignment payloads."""
        deadlines: List[AcademicDeadline] = []
        items = data if isinstance(data, list) else data.get("assignments", data.get("events", []))

        for idx, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            title = it.get("title") or it.get("name") or f"Assignment #{idx+1}"
            desc = it.get("description", "")
            due = it.get("due_date") or it.get("dueDateTime") or it.get("deadline") or ""
            group = it.get("course_name") or it.get("team") or it.get("group") or default_group
            uid = str(it.get("id") or f"{platform}_{idx}_{int(datetime.now().timestamp())}")

            due_formatted = str(due)[:16] if due else (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT23:59")
            ninety_days_ago_str = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            if not due_formatted or due_formatted[:4] < "2026" or due_formatted[:10] < ninety_days_ago_str:
                continue

            deadlines.append(
                AcademicDeadline(
                    id=f"{platform}_{uid}",
                    title=title,
                    description=desc,
                    due_date=due_formatted,
                    platform=platform,
                    group_name=group,
                    url=it.get("url", ""),
                    is_completed=bool(it.get("is_completed", False)),
                )
            )
        return deadlines
