"""
Meera - Background Task Worker & Recurring Cron Job Scheduler
Provides lightweight, zero-dependency background thread scheduling for periodic jobs,
heartbeats, and delayed agent tasks.
"""
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

logger = logging.getLogger("meera.skills.scheduler")


@dataclass
class ScheduledTask:
    id: str
    name: str
    task_type: str            # 'cron' (recurring interval) or 'timer' (one-shot delay)
    interval_seconds: float
    action: Optional[Callable[[], Any]] = None
    prompt: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_run: float = 0.0
    next_run: float = 0.0
    run_count: int = 0
    max_runs: Optional[int] = None
    status: str = "running"   # 'running', 'completed', 'cancelled', 'error'
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "task_type": self.task_type,
            "interval_seconds": self.interval_seconds,
            "prompt": self.prompt,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_count": self.run_count,
            "status": self.status,
            "last_error": self.last_error,
        }


class TaskScheduler:
    """
    Lightweight, thread-safe recurring cron and background task orchestrator.
    Uses a single background worker thread and threading.Event for minimal resource consumption.
    """

    def __init__(self):
        self._tasks: Dict[str, ScheduledTask] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._is_running = False

    def start(self) -> None:
        """Starts the background worker thread."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._run_loop,
                name="MeeraSchedulerWorker",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info("[SCHEDULER] Background task worker started")

    def stop(self) -> None:
        """Stops the scheduler and terminates the worker thread."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False
            self._stop_event.set()
            if self._worker_thread:
                self._worker_thread.join(timeout=2.0)
                self._worker_thread = None
            logger.info("[SCHEDULER] Background task worker stopped")

    def schedule_cron(
        self,
        name: str,
        interval_seconds: float,
        action: Optional[Callable[[], Any]] = None,
        prompt: Optional[str] = None,
        max_runs: Optional[int] = None,
        task_id: Optional[str] = None,
    ) -> ScheduledTask:
        """Registers a recurring interval job."""
        tid = task_id or f"cron_{uuid.uuid4().hex[:6]}"
        now = time.time()
        task = ScheduledTask(
            id=tid,
            name=name,
            task_type="cron",
            interval_seconds=interval_seconds,
            action=action,
            prompt=prompt,
            created_at=now,
            last_run=0.0,
            next_run=now + interval_seconds,
            max_runs=max_runs,
            status="running",
        )
        with self._lock:
            self._tasks[tid] = task
        logger.info(f"[SCHEDULER] Scheduled recurring task '{name}' (every {interval_seconds}s)")
        return task

    def schedule_timer(
        self,
        name: str,
        delay_seconds: float,
        action: Optional[Callable[[], Any]] = None,
        prompt: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> ScheduledTask:
        """Registers a one-shot delayed task."""
        tid = task_id or f"timer_{uuid.uuid4().hex[:6]}"
        now = time.time()
        task = ScheduledTask(
            id=tid,
            name=name,
            task_type="timer",
            interval_seconds=delay_seconds,
            action=action,
            prompt=prompt,
            created_at=now,
            last_run=0.0,
            next_run=now + delay_seconds,
            max_runs=1,
            status="running",
        )
        with self._lock:
            self._tasks[tid] = task
        logger.info(f"[SCHEDULER] Scheduled one-shot timer '{name}' (in {delay_seconds}s)")
        return task

    def cancel_task(self, task_id: str) -> bool:
        """Cancels a scheduled task."""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = "cancelled"
                return True
        return False

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> List[ScheduledTask]:
        with self._lock:
            return list(self._tasks.values())

    def _run_loop(self) -> None:
        """Internal daemon loop checking and executing due tasks."""
        while not self._stop_event.is_set():
            now = time.time()
            due_tasks: List[ScheduledTask] = []

            with self._lock:
                for task in self._tasks.values():
                    if task.status == "running" and now >= task.next_run:
                        due_tasks.append(task)

            for task in due_tasks:
                self._execute_task(task, now)

            # Sleep in short increments to allow graceful shutdown
            self._stop_event.wait(1.0)

    def _execute_task(self, task: ScheduledTask, execute_time: float) -> None:
        try:
            logger.debug(f"[SCHEDULER] Executing task '{task.name}' ({task.id})")
            if task.action:
                task.action()
            task.last_run = execute_time
            task.run_count += 1
            task.last_error = None

            # Handle completion or next schedule
            if task.task_type == "timer" or (task.max_runs and task.run_count >= task.max_runs):
                task.status = "completed"
            else:
                task.next_run = execute_time + task.interval_seconds

        except Exception as e:
            logger.error(f"[SCHEDULER] Error executing task '{task.name}': {e}")
            task.last_error = str(e)
            task.status = "error"
