"""
Open Claw Stack — Discord / Slack Webhook Alerts
===================================================
Sends real-time alerts to Discord or Slack when agents detect critical events.

Supported:
  - Discord webhooks (rich embeds with color coding)
  - Slack webhooks (block kit format)
  - Generic webhook (plain JSON POST)

Set DISCORD_WEBHOOK_URL in .env to activate.
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

# Severity → Discord embed color
SEVERITY_COLORS = {
    "info":     0x3B82F6,   # blue
    "warning":  0xF59E0B,   # amber
    "critical": 0xEF4444,   # red
    "success":  0x10B981,   # green
}

SEVERITY_ICONS = {
    "info":     "ℹ️",
    "warning":  "⚠️",
    "critical": "🚨",
    "success":  "✅",
}


class WebhookAlert:
    """
    Sends rich alert notifications to Discord or Slack.
    Non-blocking — firewall on error, never crashes the stack.
    """

    def __init__(
        self,
        discord_url: Optional[str] = None,
        slack_url:   Optional[str] = None,
        timeout:     int           = 5,
    ):
        self.discord_url = discord_url or os.getenv("DISCORD_WEBHOOK_URL", "")
        self.slack_url   = slack_url   or os.getenv("SLACK_WEBHOOK_URL",   "")
        self.timeout     = timeout
        self._sent_count = 0

    # ──────────────────────────────────────────────
    # Public Interface
    # ──────────────────────────────────────────────

    def send(
        self,
        title:    str,
        message:  str,
        severity: str = "info",
        agent:    str = "system",
        fields:   Optional[dict] = None,
    ) -> bool:
        """Send an alert to all configured webhook destinations."""
        success = False
        if self.discord_url:
            success |= self._send_discord(title, message, severity, agent, fields or {})
        if self.slack_url:
            success |= self._send_slack(title, message, severity, agent)
        if success:
            self._sent_count += 1
        return success

    def alert_critical(self, title: str, message: str, agent: str = "system") -> bool:
        return self.send(title, message, "critical", agent)

    def alert_warning(self, title: str, message: str, agent: str = "system") -> bool:
        return self.send(title, message, "warning", agent)

    def alert_info(self, title: str, message: str, agent: str = "system") -> bool:
        return self.send(title, message, "info", agent)

    # ──────────────────────────────────────────────
    # Discord
    # ──────────────────────────────────────────────

    def _send_discord(
        self, title: str, message: str, severity: str,
        agent: str, fields: dict
    ) -> bool:
        icon    = SEVERITY_ICONS.get(severity, "📌")
        color   = SEVERITY_COLORS.get(severity, 0x8B5CF6)
        ts      = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        embed_fields = [
            {"name": "Agent",    "value": f"`{agent}`",    "inline": True},
            {"name": "Severity", "value": f"`{severity.upper()}`", "inline": True},
            {"name": "Time",     "value": ts,               "inline": True},
        ]
        for k, v in fields.items():
            embed_fields.append({"name": k, "value": str(v)[:1020], "inline": False})

        payload = {
            "username":   "Open Claw Stack",
            "avatar_url": "https://img.icons8.com/color/96/artificial-intelligence.png",
            "embeds": [{
                "title":       f"{icon} {title}",
                "description": message[:2000],
                "color":       color,
                "fields":      embed_fields,
                "footer": {
                    "text": "Open Claw Stack — Sovereign AI System",
                },
            }],
        }
        return self._post(self.discord_url, payload, "Discord")

    # ──────────────────────────────────────────────
    # Slack
    # ──────────────────────────────────────────────

    def _send_slack(self, title: str, message: str, severity: str, agent: str) -> bool:
        icon = SEVERITY_ICONS.get(severity, "📌")
        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{icon} {title}", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message[:2000]},
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"*Agent:* `{agent}` | *Severity:* `{severity.upper()}` | {time.strftime('%H:%M UTC')}"},
                    ],
                },
                {"type": "divider"},
            ]
        }
        return self._post(self.slack_url, payload, "Slack")

    # ──────────────────────────────────────────────
    # HTTP POST (shared)
    # ──────────────────────────────────────────────

    def _post(self, url: str, payload: dict, platform: str) -> bool:
        if not url:
            return False
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            if resp.status_code in (200, 204):
                logger.info(f"WebhookAlert: {platform} alert sent")
                return True
            logger.warning(f"WebhookAlert: {platform} returned {resp.status_code}: {resp.text[:100]}")
            return False
        except Exception as exc:
            logger.warning(f"WebhookAlert: {platform} post failed: {exc}")
            return False

    @property
    def configured(self) -> bool:
        return bool(self.discord_url or self.slack_url)

    @property
    def sent_count(self) -> int:
        return self._sent_count
