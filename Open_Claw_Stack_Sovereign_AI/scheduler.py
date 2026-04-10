"""
Open Claw Stack — Autonomous Scheduler
=========================================
Runs agent tasks on a schedule — making the stack always-on.

Schedule:
  - Quick health check     : every 15 minutes
  - Security audit         : every 1 hour
  - Package vulnerability  : every 6 hours
  - Nightly full report    : midnight daily

Uses APScheduler (BackgroundScheduler — non-blocking, runs in daemon thread).
"""
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class StackScheduler:
    """
    Background task scheduler for autonomous always-on operation.
    Runs supervisor tasks on a timer without user intervention.
    """

    def __init__(self, supervisor, state, alert=None):
        self.supervisor = supervisor
        self.state      = state
        self.alert      = alert          # WebhookAlert (optional)
        self._scheduler = None
        self._running   = False
        self._lock      = threading.Lock()

    # ──────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────

    def start(self) -> bool:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron     import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            self._scheduler = BackgroundScheduler(
                timezone="UTC",
                job_defaults={"misfire_grace_time": 120, "coalesce": True, "max_instances": 1},
            )

            # Quick health: every 15 minutes
            self._scheduler.add_job(
                self._quick_health,
                IntervalTrigger(minutes=15),
                id="quick_health",
                name="Quick Health Check",
            )

            # Security audit: every hour
            self._scheduler.add_job(
                self._security_audit,
                IntervalTrigger(hours=1),
                id="security_audit",
                name="Hourly Security Audit",
            )

            # Package CVE scan: every 6 hours
            self._scheduler.add_job(
                self._package_scan,
                IntervalTrigger(hours=6),
                id="package_scan",
                name="Package CVE Scan",
            )

            # Nightly full report: midnight UTC
            self._scheduler.add_job(
                self._nightly_report,
                CronTrigger(hour=0, minute=0),
                id="nightly_report",
                name="Nightly Full Report",
            )

            self._scheduler.start()
            self._running = True
            logger.info("Scheduler: started — 4 jobs scheduled")
            return True

        except ImportError:
            logger.warning("Scheduler: APScheduler not installed — run: pip install apscheduler")
            return False
        except Exception as exc:
            logger.error(f"Scheduler: start failed: {exc}")
            return False

    def stop(self):
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler: stopped")

    # ──────────────────────────────────────────────
    # Scheduled Tasks
    # ──────────────────────────────────────────────

    def _run_task(self, task: str, label: str):
        """Execute a supervisor task in a background thread."""
        if self.state.pra_phase not in ("idle", "done", ""):
            logger.info(f"Scheduler: skipping '{label}' — task already running")
            return

        logger.info(f"Scheduler: running '{label}'")
        self.state.add_message("system", f"⏰ Scheduled: {label}", "system")

        def _exec():
            try:
                self.supervisor.run(task)
            except Exception as exc:
                logger.error(f"Scheduler: '{label}' failed: {exc}")
                if self.alert:
                    self.alert.alert_critical(
                        "Scheduled Task Failed",
                        f"**{label}** failed with error: {exc}",
                        agent="scheduler",
                    )

        t = threading.Thread(target=_exec, daemon=True, name=f"sched-{label[:10]}")
        t.start()

    def _quick_health(self):
        self._run_task(
            "Quick health check: CPU, RAM, network latency, and disk space.",
            "Quick Health Check",
        )

    def _security_audit(self):
        self._run_task(
            "Hourly security audit: scan for shadow AI, check open ports, review PHASR log, check firewall.",
            "Hourly Security Audit",
        )

    def _package_scan(self):
        self._run_task(
            "Package vulnerability scan: check for outdated pip packages and known CVEs.",
            "Package CVE Scan",
        )

    def _nightly_report(self):
        self._run_task(
            "Nightly full system report: all agents, all metrics, comprehensive health and security summary.",
            "Nightly Full Report",
        )

    # ──────────────────────────────────────────────
    # Status
    # ──────────────────────────────────────────────

    def get_jobs(self) -> list:
        if not self._scheduler:
            return []
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id":       job.id,
                "name":     job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else "N/A",
            })
        return jobs

    @property
    def running(self) -> bool:
        return self._running
