"""Monitoring loop.

The heartbeat of the agent. Every check interval it:

1. reads the latest rows from the Excel file
2. keeps only rows that are newer than the last check
3. groups them by metric and runs anomaly detection on the newest value
4. adds business context
5. decides whether an email is allowed (severity, suppression,
   cooldown, business hours)
6. sends the email and logs everything
"""

import time
from datetime import datetime, timedelta

from modules.anomaly_detector import AnomalyDetector
from modules.auto_detect import guess_metric_profile
from modules.context_analyzer import ContextAnalyzer
from modules.data_reader import DataReader, DataReaderError
from modules.email_service import EmailService


class MonitoringLoop:
    """Runs one or many monitoring passes over the Excel file."""

    SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "URGENT": 4}

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.reader = DataReader(config["excel_config"], logger)
        # Metrics configured in config.json; auto mode discovers more and
        # adds them here at runtime.
        self.metrics_base = {
            m["name"]: m for m in config.get("metrics", [])
        }
        self.detector = AnomalyDetector(
            config["anomaly_detection"],
            self.metrics_base,
            logger,
        )
        self.analyzer = ContextAnalyzer(
            config.get("business_rules", []),
            config.get("business_context", {}),
            logger,
        )
        self.emailer = EmailService(config["email_config"], logger)
        self.last_checked = None
        self.last_alert = {}  # metric name -> datetime of last alert

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _ensure_metric(self, metric_name):
        """Add a metric with sensible defaults if it was discovered at
        runtime (auto mode). Returns its config dict."""
        metric_cfg = self.metrics_base.get(metric_name)
        if metric_cfg is None:
            profile = guess_metric_profile(metric_name)
            metric_cfg = {
                "name": metric_name,
                "unit": profile["unit"],
                "priority": profile["priority"],
                "severity_threshold": 2.0,
                "alert_cooldown_minutes": 30,
            }
            self.metrics_base[metric_name] = metric_cfg
            self.logger.info(
                f"Auto-registered metric '{metric_name}' "
                f"(unit={metric_cfg['unit']}, priority={metric_cfg['priority']})"
            )
        return metric_cfg

    def _metric_priority(self, metric_name):
        """Priority tier configured for a metric (defaults to MEDIUM)."""
        return self._ensure_metric(metric_name).get("priority", "MEDIUM")

    def _cooldown_ok(self, metric_name, now):
        """True if enough time has passed since the last alert for metric."""
        metric_cfg = self._ensure_metric(metric_name)
        cooldown = timedelta(
            minutes=int(metric_cfg.get("alert_cooldown_minutes", 30))
        )
        last = self.last_alert.get(metric_name)
        return last is None or (now - last) >= cooldown

    def _within_alert_window(self, now, severity):
        """Enforce the business-hours rule for non-critical alerts."""
        monitor_cfg = self.config.get("monitoring", {})
        if monitor_cfg.get("alert_outside_business_hours", True):
            return True
        hours = monitor_cfg.get("business_hours", "")
        if not hours or "-" not in hours:
            return True
        start_text, end_text = hours.split("-", 1)
        try:
            start = datetime.strptime(start_text.strip(), "%H:%M").time()
            end = datetime.strptime(end_text.strip(), "%H:%M").time()
        except ValueError:
            return True
        if start <= now.time() <= end:
            return True
        # Outside business hours: only allow critical alerts.
        return self.SEVERITY_ORDER.get(severity, 1) >= self.SEVERITY_ORDER["HIGH"]

    def _should_alert(self, anomaly, context, now):
        """Apply the full alert decision logic from the spec (section 2.4)."""
        metric_name = anomaly["metric"]
        if not anomaly.get("anomaly_detected", False):
            return False, "no anomaly detected"
        if context.get("suppress_alert"):
            return False, "suppressed by business context"
        z_score = anomaly.get("z_score")
        if z_score is not None:
            threshold = float(
                self._ensure_metric(metric_name).get(
                    "severity_threshold", 2.0
                )
            )
            if abs(z_score) < threshold:
                return False, "below metric severity threshold"
        if not self._cooldown_ok(metric_name, now):
            return False, "within cooldown period"
        if not self._within_alert_window(now, context.get("alert_priority")):
            return False, "outside business hours and not critical"
        return True, "allowed"

    # ------------------------------------------------------------------
    # single pass
    # ------------------------------------------------------------------
    def run_once(self):
        """Execute one full monitoring pass. Returns list of actions."""
        actions = []
        now = datetime.now()
        try:
            records = self.reader.read_records()
        except DataReaderError as exc:
            self.logger.error(f"Read failed: {exc}")
            return actions

        if not records:
            self.logger.info("No data in file; nothing to check")
            return actions

        # Only evaluate rows that are newer than the last successful check.
        new_records = [
            r for r in records
            if self.last_checked is None or r["timestamp"] > self.last_checked
        ]
        self.last_checked = records[-1]["timestamp"]
        if not new_records:
            self.logger.info("No new data since last check")
            return actions

        # Group new rows by metric, newest first.
        by_metric = {}
        for record in new_records:
            by_metric.setdefault(record["metric_name"], []).append(record)
        for metric_name, rows in by_metric.items():
            rows.sort(key=lambda r: r["timestamp"])
            latest = rows[-1]
            self._ensure_metric(metric_name)
            history = [
                (r["timestamp"], r["metric_value"])
                for r in records
                if r["metric_name"] == metric_name
                and r["timestamp"] <= latest["timestamp"]
            ]
            # History excludes the row being evaluated.
            history_values = [v for _, v in history]
            past_history = [
                (ts, v)
                for ts, v in history
                if ts < latest["timestamp"]
            ]

            anomaly = self.detector.detect(
                metric_name,
                latest["metric_value"],
                past_history,
            )
            if anomaly is None or not anomaly.get("anomaly_detected", False):
                self.logger.info(
                    f"{metric_name}: no anomaly "
                    f"({latest['metric_value']})"
                )
                actions.append(
                    {
                        "metric": metric_name,
                        "action": "OK",
                        "value": latest["metric_value"],
                    }
                )
                continue

            anomaly["priority"] = self._metric_priority(metric_name)
            context = self.analyzer.analyze(anomaly, latest["timestamp"])
            allowed, reason = self._should_alert(anomaly, context, now)
            self.logger.info(
                f"{metric_name}: anomaly detected "
                f"(z={anomaly.get('z_score')}, "
                f"sev={anomaly.get('severity')}) "
                f"-> alert decision: {reason}"
            )
            if not allowed:
                actions.append(
                    {
                        "metric": metric_name,
                        "action": "SUPPRESSED",
                        "reason": reason,
                        "anomaly": anomaly,
                        "context": context,
                    }
                )
                continue

            sent = self.emailer.send_alert(
                anomaly, context, past_history, latest["timestamp"]
            )
            if sent:
                self.last_alert[metric_name] = now
                self.logger.info(
                    f"ALERT_SENT | {metric_name} | Severity: "
                    f"{context.get('alert_priority')} | "
                    f"Recipients: {len(self.config['email_config'].get('recipients', []))}"
                )
            actions.append(
                {
                    "metric": metric_name,
                    "action": "ALERT_SENT" if sent else "SEND_FAILED",
                    "anomaly": anomaly,
                    "context": context,
                }
            )
        return actions

    # ------------------------------------------------------------------
    # continuous loop
    # ------------------------------------------------------------------
    def run_forever(self):
        """Run until Ctrl+C, sleeping between passes."""
        interval = int(
            self.config.get("monitoring", {}).get(
                "check_interval_seconds", 300
            )
        )
        self.logger.info(
            f"Monitoring started (interval={interval}s). Press Ctrl+C to stop."
        )
        try:
            while True:
                self.run_once()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.logger.info("Monitoring stopped by user.")
