"""Email service module.

Composes a plain-text alert email from an anomaly + business context and
sends it over SMTP. Includes retry with exponential backoff. If no real
SMTP credentials are configured, falls back to a dry-run that writes the
email to disk so the whole pipeline can be tested safely.
"""

import os
import smtplib
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import format_datetime
from pathlib import Path


class EmailService:
    """Builds and sends anomaly alert emails."""

    # Environment variables override config.json so real credentials never
    # have to live in the project files.
    _ENV_OVERRIDES = {
        "ANOMALY_SENDER_EMAIL": "sender_email",
        "ANOMALY_SENDER_PASSWORD": "sender_password",
        "ANOMALY_SMTP_SERVER": "smtp_server",
        "ANOMALY_SMTP_PORT": "smtp_port",
    }

    def __init__(self, email_config, logger=None, dry_run_dir=None):
        self.config = dict(email_config or {})
        self._apply_env_overrides()
        self.logger = logger
        self.dry_run_dir = dry_run_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "logs",
            "emails_sent",
        )

    def _apply_env_overrides(self):
        """Pull sender credentials and recipients from environment variables."""
        for env_name, config_key in self._ENV_OVERRIDES.items():
            value = os.environ.get(env_name)
            if value:
                self.config[config_key] = value
        recipients = os.environ.get("ANOMALY_RECIPIENTS")
        if recipients:
            self.config["recipients"] = [
                address.strip()
                for address in recipients.split(",")
                if address.strip()
            ]

    def _log(self, message, level="info"):
        if self.logger is not None:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")

    @property
    def _is_dry_run(self):
        """True when SMTP is not configured, so we write emails to disk."""
        password = self.config.get("sender_password", "")
        return (
            not password
            or "REPLACE_ME" in password
            or not self.config.get("smtp_server")
        )

    # ------------------------------------------------------------------
    # composition
    # ------------------------------------------------------------------
    @staticmethod
    def _ascii_chart(values, width=28):
        """Render a simple ASCII bar chart of recent history values."""
        if not values:
            return "(no history available)"
        clean = [v for v in values if v is not None]
        if not clean:
            return "(no history available)"
        maximum = max(clean)
        minimum = min(clean)
        span = (maximum - minimum) or 1
        lines = []
        for value in clean:
            normalized = (value - minimum) / span
            bars = max(1, int(round(normalized * width)))
            lines.append(f"{value:>12.2f} |{'#' * bars}")
        return "\n".join(lines)

    def compose(self, anomaly, context, history, timestamp):
        """Build the email subject and body text."""
        metric = anomaly.get("metric", "Unknown")
        severity = context.get("alert_priority") or anomaly.get("severity")
        ts_text = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        subject = (
            f"[ALERT] {severity} - {metric} Anomaly Detected ({ts_text})"
        )

        current = anomaly.get("current_value")
        expected = anomaly.get("expected_value")
        deviation = anomaly.get("deviation_percent")
        unit = anomaly.get("unit", "")

        history_values = [v for _, v in (history or [])]
        if history_values:
            recent = history_values[-7:]
            avg_7 = sum(recent) / len(recent)
            peak = max(history_values)
            lowest = min(history_values)
        else:
            avg_7 = peak = lowest = None

        avg_7_text = f"{avg_7:.2f} {unit}" if avg_7 is not None else "N/A"
        peak_text = f"{peak:.2f} {unit}" if peak is not None else "N/A"
        lowest_text = f"{lowest:.2f} {unit}" if lowest is not None else "N/A"

        body = f"""ANOMALY SUMMARY
================
Metric: {metric}
Current Value: {current} {unit}
Expected Value: {expected if expected is not None else 'N/A'} {unit}
Deviation: {deviation if deviation is not None else 'N/A'}%
Severity: {severity}
Timestamp: {ts_text}

BUSINESS CONTEXT
================
Reason: {context.get('anomaly_reason')}
Impact: {context.get('business_impact')}
Recommendation: {context.get('actionable_insight')}

RECENT HISTORY
================
Last 7 days average: {avg_7_text}
Peak value: {peak_text}
Lowest value: {lowest_text}

DATA VISUALIZATION
================
{self._ascii_chart(history_values)}

ACTION REQUIRED
================
[] Investigate cause
[] Notify team lead
[] Update status page
[] Escalate if needed

Sent by: Anomaly Detection Agent
Time: {format_datetime(datetime.now(timezone.utc))}"""

        return subject, body

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------
    def _send_smtp(self, subject, body, recipients):
        """Send one email over SMTP with retry and exponential backoff."""
        attempts = int(self.config.get("retry_attempts", 3))
        backoff = int(self.config.get("retry_backoff_seconds", 5))
        for attempt in range(1, attempts + 1):
            try:
                server = smtplib.SMTP(
                    self.config["smtp_server"], int(self.config["smtp_port"])
                )
                if self.config.get("tls_enabled", True):
                    server.starttls()
                server.login(
                    self.config["sender_email"],
                    self.config["sender_password"],
                )
                message = MIMEText(body)
                message["Subject"] = subject
                message["From"] = self.config["sender_email"]
                message["To"] = ", ".join(recipients)
                if self.config.get("cc"):
                    message["Cc"] = ", ".join(self.config["cc"])
                if self.config.get("bcc"):
                    message["Bcc"] = ", ".join(self.config["bcc"])
                server.sendmail(
                    self.config["sender_email"],
                    recipients + self.config.get("cc", [])
                    + self.config.get("bcc", []),
                    message.as_string(),
                )
                server.quit()
                self._log(
                    f"Email sent to {len(recipients)} recipients: {subject}"
                )
                return True
            except Exception as exc:
                wait = backoff * (2 ** (attempt - 1))
                self._log(
                    f"SMTP attempt {attempt}/{attempts} failed "
                    f"({exc}); retrying in {wait}s",
                    "error",
                )
                if attempt < attempts:
                    time.sleep(wait)
        return False

    def _save_dry_run(self, subject, body, recipients):
        """Write the email to disk instead of sending it."""
        os.makedirs(self.dry_run_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(self.dry_run_dir, f"alert_{stamp}.txt")
        header = (
            f"TO: {', '.join(recipients)}\n"
            f"SUBJECT: {subject}\n"
            + "-" * 60
            + "\n"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(header + body)
        self._log(f"DRY-RUN: email written to {path}")
        return True

    def send_alert(self, anomaly, context, history, timestamp):
        """Compose and deliver an alert. Returns True on success."""
        subject, body = self.compose(anomaly, context, history, timestamp)
        recipients = self.config.get("recipients", [])
        if not recipients:
            self._log("No recipients configured; skipping email", "warning")
            return False
        if self._is_dry_run:
            return self._save_dry_run(subject, body, recipients)
        return self._send_smtp(subject, body, recipients)
