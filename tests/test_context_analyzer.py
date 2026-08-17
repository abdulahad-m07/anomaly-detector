"""Unit tests for the business context analyzer."""

import unittest
from datetime import datetime

from modules.context_analyzer import ContextAnalyzer

RULES = [
    {
        "id": "weekend",
        "metric": "Sales Revenue",
        "condition": "day == 'Sunday'",
        "reason": "Weekend sales typically lower; expected behavior",
        "suppress_alert": True,
    },
    {
        "id": "urgent",
        "metric": "Failed Transactions",
        "condition": "current_value > 500",
        "reason": "Payment gateway issue detected",
        "suppress_alert": False,
        "escalate": True,
    },
]

ANOMALY = {
    "metric": "Sales Revenue",
    "current_value": 15000,
    "expected_value": 45000,
    "deviation_percent": -66.67,
    "z_score": -2.5,
    "severity": "HIGH",
    "unit": "USD",
}


class TestContextAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = ContextAnalyzer(RULES, {"peak_hours": [9, 10]})

    def test_suppresses_weekend(self):
        sunday = datetime(2026, 8, 16, 10, 0)
        result = self.analyzer.analyze(ANOMALY, sunday)
        self.assertTrue(result["suppress_alert"])
        self.assertEqual(result["anomaly_reason"],
                         "Weekend sales typically lower; expected behavior")

    def test_does_not_suppress_weekday(self):
        monday = datetime(2026, 8, 17, 10, 0)
        result = self.analyzer.analyze(ANOMALY, monday)
        self.assertFalse(result["suppress_alert"])

    def test_escalation_for_failed_transactions(self):
        anomaly = {**ANOMALY, "metric": "Failed Transactions",
                   "current_value": 700}
        result = self.analyzer.analyze(anomaly, datetime(2026, 8, 17, 10, 0))
        self.assertTrue(result["escalate"])
        self.assertEqual(result["alert_priority"], "URGENT")
        self.assertIn("CRITICAL", result["business_impact"])

    def test_rules_do_not_apply_to_other_metrics(self):
        anomaly = {**ANOMALY, "metric": "Server CPU"}
        result = self.analyzer.analyze(anomaly, datetime(2026, 8, 17, 10, 0))
        self.assertEqual(result["matched_rules"], [])


if __name__ == "__main__":
    unittest.main()
