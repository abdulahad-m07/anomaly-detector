"""Unit tests for the anomaly detector."""

import unittest

from modules.anomaly_detector import AnomalyDetector

DETECTION_CONFIG = {
    "method": "z_score",
    "z_score_threshold": 2.0,
    "moving_avg_window": 3,
    "moving_avg_deviation_pct": 30.0,
    "min_data_points": 5,
}

METRICS_CONFIG = {
    "Test Metric": {"name": "Test Metric", "unit": "count", "priority": "HIGH"},
}


def make_history(values):
    """Turn a list of floats into (timestamp, value) pairs."""
    from datetime import datetime, timedelta

    start = datetime(2026, 8, 1, 10, 0)
    return [
        (start + timedelta(days=i), value) for i, value in enumerate(values)
    ]


def noisy_history():
    """20 history points with a mean of ~100 and stddev of ~11."""
    return make_history([
        80, 95, 110, 85, 120, 90, 105, 98, 88, 115,
        92, 108, 100, 96, 102, 94, 118, 82, 112, 98,
    ])


class TestAnomalyDetector(unittest.TestCase):
    def setUp(self):
        self.detector = AnomalyDetector(DETECTION_CONFIG, METRICS_CONFIG)

    def test_detects_spike(self):
        result = self.detector.detect("Test Metric", 300, noisy_history())
        self.assertIsNotNone(result)
        self.assertTrue(result["anomaly_detected"])
        self.assertGreater(abs(result["z_score"]), 3.0)

    def test_no_anomaly_for_normal_value(self):
        result = self.detector.detect("Test Metric", 105, noisy_history())
        self.assertIsNotNone(result)
        self.assertFalse(result["anomaly_detected"])

    def test_severity_increases_with_distance(self):
        mild = self.detector.detect("Test Metric", 130, noisy_history())  # z ~ 2.7
        extreme = self.detector.detect("Test Metric", 200, noisy_history())  # z ~ 9
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        self.assertGreater(
            order[extreme["severity"]], order[mild["severity"]]
        )

    def test_constant_history_spike_is_anomaly(self):
        result = self.detector.detect("Test Metric", 300, make_history([100] * 20))
        self.assertIsNotNone(result)
        self.assertTrue(result["anomaly_detected"])
        self.assertEqual(result["severity"], "HIGH")

    def test_insufficient_data_falls_back(self):
        history = make_history([100] * 2)  # below min_data_points
        result = self.detector.detect("Test Metric", 300, history)
        self.assertIsNotNone(result)
        self.assertFalse(result["anomaly_detected"])
        self.assertTrue(result.get("insufficient_data"))

    def test_threshold_method(self):
        config = {**DETECTION_CONFIG, "method": "threshold",
                  "threshold_bounds": {"Test Metric": {"lower": 0, "upper": 150}}}
        detector = AnomalyDetector(config, METRICS_CONFIG)
        result = detector.detect("Test Metric", 300, make_history([100] * 20))
        self.assertIsNotNone(result)
        self.assertTrue(result["anomaly_detected"])
        self.assertEqual(result["detection_method"], "threshold")


if __name__ == "__main__":
    unittest.main()
