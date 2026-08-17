"""Tests for the email service (dry-run mode, no SMTP needed)."""

import os
import tempfile
import unittest
from datetime import datetime

from modules.email_service import EmailService

CONFIG = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "alerts@company.com",
    "sender_password": "REPLACE_ME",
    "recipients": ["team@company.com"],
}

ANOMALY = {
    "metric": "Sales Revenue",
    "current_value": 15000,
    "expected_value": 45000,
    "deviation_percent": -66.67,
    "z_score": -2.5,
    "severity": "HIGH",
    "unit": "USD",
}

CONTEXT = {
    "alert_priority": "HIGH",
    "anomaly_reason": "Payment gateway issue",
    "business_impact": "CRITICAL",
    "actionable_insight": "Investigate",
}


class TestEmailService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.service = EmailService(CONFIG, dry_run_dir=self.tmp)

    def test_is_dry_run_without_credentials(self):
        self.assertTrue(self.service._is_dry_run)

    def test_compose_contains_key_sections(self):
        ts = datetime(2026, 8, 16, 10, 30)
        subject, body = self.service.compose(
            ANOMALY, CONTEXT, [(ts, 45000)], ts
        )
        self.assertIn("[ALERT]", subject)
        self.assertIn("ANOMALY SUMMARY", body)
        self.assertIn("BUSINESS CONTEXT", body)
        self.assertIn("ACTION REQUIRED", body)
        self.assertIn("Sales Revenue", body)

    def test_dry_run_writes_file(self):
        from datetime import timedelta

        ts = datetime(2026, 8, 16, 10, 30)
        history = [(ts - timedelta(days=n), 45000) for n in range(1, 8)]
        ok = self.service.send_alert(ANOMALY, CONTEXT, history, ts)
        self.assertTrue(ok)

    def test_ascii_chart(self):
        chart = EmailService._ascii_chart([1, 5, 3, 10])
        self.assertIn("#", chart)

    def test_env_overrides_switch_to_real_mode(self):
        old = {
            "ANOMALY_SENDER_EMAIL": os.environ.get("ANOMALY_SENDER_EMAIL"),
            "ANOMALY_SENDER_PASSWORD": os.environ.get("ANOMALY_SENDER_PASSWORD"),
            "ANOMALY_RECIPIENTS": os.environ.get("ANOMALY_RECIPIENTS"),
        }
        os.environ["ANOMALY_SENDER_EMAIL"] = "alerts@gmail.com"
        os.environ["ANOMALY_SENDER_PASSWORD"] = "supersecret"
        os.environ["ANOMALY_RECIPIENTS"] = "a@x.com, b@x.com"
        try:
            service = EmailService(CONFIG)
            self.assertFalse(service._is_dry_run)
            self.assertEqual(service.config["recipients"], ["a@x.com", "b@x.com"])
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
