"""Anomaly detection engine.

Compares the latest value of a metric against its history using one of
three statistical methods:

1. z-score: how many standard deviations the value is from the mean
2. moving average: deviation from the rolling average of the last N points
3. threshold: hard upper/lower bounds defined per metric
"""

import statistics


class AnomalyDetector:
    """Detects outliers in a single metric's value history."""

    def __init__(self, detection_config, metrics_config, logger=None):
        self.detection_config = detection_config or {}
        self.metrics_config = metrics_config or {}
        self.logger = logger

    def _log(self, message, level="info"):
        if self.logger is not None:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")

    # ------------------------------------------------------------------
    # statistics helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _mean(values):
        return sum(values) / len(values)

    @staticmethod
    def _stddev(values):
        """Sample standard deviation (falls back to population when tiny)."""
        if len(values) < 2:
            return 0.0
        try:
            return statistics.stdev(values)
        except statistics.StatisticsError:
            return 0.0

    def _severity(self, magnitude, threshold):
        """Map how far past the threshold we are to LOW/MEDIUM/HIGH."""
        if magnitude >= threshold * 2:
            return "HIGH"
        if magnitude >= threshold * 1.5:
            return "MEDIUM"
        return "LOW"

    def _auto_method(self, history_values):
        """Pick a detection method from how much history is available."""
        min_points = int(self.detection_config.get("min_data_points", 10))
        if len(history_values) >= min_points:
            return "z_score"
        window = int(self.detection_config.get("moving_avg_window", 7))
        if len(history_values) >= window:
            return "moving_average"
        return "threshold"

    def _auto_bounds(self, history_values):
        """Sensible mean +/- 3*std fences when the user gave no thresholds."""
        if not history_values:
            return {"lower": -1e12, "upper": 1e12}
        mean = self._mean(history_values)
        stddev = self._stddev(history_values)
        if stddev == 0:
            if mean == 0:
                return {"lower": -1e12, "upper": 1e12}
            return {"lower": mean * 0.5, "upper": mean * 1.5}
        return {"lower": mean - 3 * stddev, "upper": mean + 3 * stddev}

    # ------------------------------------------------------------------
    # detection methods
    # ------------------------------------------------------------------
    def _z_score_detect(self, metric_cfg, current_value, history_values):
        """Method 1: flag when |z-score| exceeds the global threshold."""
        global_threshold = float(
            self.detection_config.get("z_score_threshold", 2.5)
        )
        mean = self._mean(history_values)
        stddev = self._stddev(history_values)
        if stddev == 0:
            # No variance at all: the only possible outlier is any value
            # that differs from the constant baseline.
            deviation_pct = (
                ((current_value - mean) / mean) * 100.0 if mean else 0.0
            )
            return {
                "current_value": current_value,
                "expected_value": round(mean, 2),
                "deviation_percent": round(deviation_pct, 2),
                "z_score": None,
                "anomaly_detected": current_value != mean,
                "severity": "HIGH" if current_value != mean else "LOW",
                "detection_method": "z_score",
            }
        z_score = (current_value - mean) / stddev
        anomaly = abs(z_score) >= global_threshold
        deviation_pct = (
            ((current_value - mean) / mean) * 100.0 if mean else 0.0
        )
        return {
            "current_value": current_value,
            "expected_value": round(mean, 2),
            "deviation_percent": round(deviation_pct, 2),
            "z_score": round(z_score, 4),
            "anomaly_detected": anomaly,
            "severity": self._severity(abs(z_score), global_threshold),
            "detection_method": "z_score",
        }

    def _moving_average_detect(self, metric_cfg, current_value, history_values):
        """Method 2: flag when deviation from the rolling average is too big."""
        window = int(
            self.detection_config.get("moving_avg_window", 7)
        )
        threshold_pct = float(
            self.detection_config.get("moving_avg_deviation_pct", 30.0)
        )
        if len(history_values) < window:
            window = len(history_values)
        if window == 0:
            return None
        rolling_avg = self._mean(history_values[-window:])
        deviation_pct = (
            ((current_value - rolling_avg) / rolling_avg) * 100.0
            if rolling_avg else 0.0
        )
        anomaly = abs(deviation_pct) >= threshold_pct
        return {
            "current_value": current_value,
            "expected_value": round(rolling_avg, 2),
            "deviation_percent": round(deviation_pct, 2),
            "z_score": None,
            "anomaly_detected": anomaly,
            "severity": self._severity(
                abs(deviation_pct), threshold_pct
            ),
            "detection_method": "moving_average",
        }

    def _threshold_detect(self, metric_cfg, current_value, history_values):
        """Method 3: flag when the value leaves configured bounds."""
        bounds = self.detection_config.get(
            "threshold_bounds", {}
        ).get(metric_cfg.get("name"), {})
        lower = bounds.get("lower")
        upper = bounds.get("upper")
        if lower is None and upper is None:
            # No explicit fences -> build sensible ones from the history
            # so auto mode still detects clearly-out-of-range values.
            bounds = self._auto_bounds(history_values)
            lower, upper = bounds["lower"], bounds["upper"]
        anomaly = (lower is not None and current_value < lower) or (
            upper is not None and current_value > upper
        )
        if not anomaly:
            return None
        expected = history_values[-1] if history_values else None
        deviation_pct = (
            ((current_value - expected) / expected) * 100.0
            if expected else 0.0
        )
        severity = "HIGH"
        if lower is not None and upper is not None:
            span = upper - lower
            if span > 0:
                severity = "HIGH" if abs(current_value - expected) > span else "MEDIUM"
        return {
            "current_value": current_value,
            "expected_value": round(expected, 2) if expected is not None else None,
            "deviation_percent": round(deviation_pct, 2),
            "z_score": None,
            "anomaly_detected": True,
            "severity": severity,
            "detection_method": "threshold",
        }

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    def detect(self, metric_name, current_value, history):
        """Run the configured method against a metric's history.

        Args:
            metric_name: name of the metric being checked
            current_value: latest value of the metric
            history: chronological list of previous (timestamp, value) pairs

        Returns:
            Detection dict (or None if detection was impossible).
        """
        metric_cfg = self.metrics_config.get(metric_name, {})
        method = self.detection_config.get("method", "z_score")
        min_points = int(self.detection_config.get("min_data_points", 10))
        history_values = [v for _, v in history]

        # Not enough history? Fall back to explicit threshold bounds if the
        # user defined any (auto-computed bounds need history to be useful).
        if len(history_values) < min_points:
            self._log(
                f"{metric_name}: only {len(history_values)} history points "
                f"(need {min_points}), falling back to thresholds",
                "warning",
            )
            bounds = self.detection_config.get(
                "threshold_bounds", {}
            ).get(metric_cfg.get("name"), {})
            if bounds.get("lower") is not None or bounds.get("upper") is not None:
                result = self._threshold_detect(
                    metric_cfg, current_value, history_values
                )
                if result is not None:
                    return result
            return {
                "metric": metric_name,
                "current_value": current_value,
                "expected_value": None,
                "deviation_percent": None,
                "z_score": None,
                "anomaly_detected": False,
                "severity": "LOW",
                "detection_method": "threshold",
                "insufficient_data": True,
            }

        if method == "auto":
            method = self._auto_method(history_values)
        if method == "threshold":
            result = self._threshold_detect(
                metric_cfg, current_value, history_values
            )
        elif method == "moving_average":
            result = self._moving_average_detect(
                metric_cfg, current_value, history_values
            )
        else:  # default z_score
            result = self._z_score_detect(
                metric_cfg, current_value, history_values
            )

        if result is None:
            # No anomaly and no bounds configured means "nothing to say".
            return None
        result["metric"] = metric_name
        result["unit"] = metric_cfg.get("unit", "")
        return result
