"""Business context analyzer.

Takes a detected anomaly and evaluates configurable IF-THEN business rules
against it. Rules can add an explanation (reason), an impact statement,
an actionable insight, an alert priority and can suppress the alert
entirely (e.g. expected weekend behaviour).
"""


class ContextAnalyzer:
    """Enriches anomalies with business explanations from rules."""

    def __init__(self, rules, business_context, logger=None):
        self.rules = rules or []
        self.business_context = business_context or {}
        self.logger = logger

    def _log(self, message, level="info"):
        if self.logger is not None:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")

    # ------------------------------------------------------------------
    # rule engine
    # ------------------------------------------------------------------
    @staticmethod
    def _evaluate(expression, variables):
        """Safely evaluate a rule condition using only whitelisted variables.

        Builtins are stripped so rules cannot touch the filesystem or shell.
        The only names available are the ones the analyzer injects.
        """
        try:
            return bool(
                eval(
                    expression,
                    {"__builtins__": {}},
                    variables,
                )
            )
        except Exception as exc:
            raise ValueError(
                f"Bad business rule condition '{expression}': {exc}"
            ) from exc

    def _build_variables(self, anomaly, timestamp):
        """Expose the anomaly details as names rules can reference."""
        day = timestamp.strftime("%A")
        hour = timestamp.hour
        peak_hours = self.business_context.get("peak_hours", [])
        return {
            "metric": anomaly.get("metric"),
            "unit": anomaly.get("unit", ""),
            "current_value": anomaly.get("current_value"),
            "expected_value": anomaly.get("expected_value"),
            "deviation_percent": anomaly.get("deviation_percent"),
            "z_score": anomaly.get("z_score"),
            "severity": anomaly.get("severity"),
            "day": day,
            "hour": hour,
            "is_weekend": day in ("Saturday", "Sunday"),
            "peak_hours": hour in peak_hours,
        }

    def _default_impact(self, anomaly):
        """Fallback impact text when no rule overrides it."""
        priority = anomaly.get("priority", "MEDIUM")
        severity = anomaly.get("severity", "MEDIUM")
        if priority == "HIGH" or severity == "HIGH":
            return (
                "Potential impact on business operations; "
                "investigate promptly"
            )
        return "May affect the metric's normal operating range"

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    def analyze(self, anomaly, timestamp):
        """Return a context dict explaining the anomaly.

        Args:
            anomaly: detection dict produced by AnomalyDetector
            timestamp: datetime of the anomaly

        Returns:
            {
                "metric": ...,
                "anomaly_reason": ...,
                "business_impact": ...,
                "actionable_insight": ...,
                "alert_priority": ...,
                "suppress_alert": bool,
                "escalate": bool,
                "matched_rules": [...],
            }
        """
        variables = self._build_variables(anomaly, timestamp)

        context = {
            "metric": anomaly.get("metric"),
            "anomaly_reason": (
                "Unusual deviation from the metric's normal pattern"
            ),
            "business_impact": self._default_impact(anomaly),
            "actionable_insight": (
                "Review the metric and check related systems for issues"
            ),
            "alert_priority": anomaly.get("severity", "MEDIUM"),
            "suppress_alert": False,
            "escalate": False,
            "matched_rules": [],
        }

        for rule in self.rules or []:
            if rule.get("metric") and rule.get("metric") != anomaly.get(
                "metric"
            ):
                continue
            condition = rule.get("condition")
            if not condition:
                continue
            try:
                matches = self._evaluate(condition, variables)
            except ValueError as exc:
                self._log(str(exc), "error")
                continue
            if not matches:
                continue
            context["matched_rules"].append(rule.get("id"))
            if rule.get("reason"):
                context["anomaly_reason"] = rule["reason"]
            if rule.get("business_impact"):
                context["business_impact"] = rule["business_impact"]
            if rule.get("actionable_insight"):
                context["actionable_insight"] = rule["actionable_insight"]
            if rule.get("suppress_alert"):
                context["suppress_alert"] = True
            if rule.get("escalate"):
                context["escalate"] = True
                context["alert_priority"] = "URGENT"
                context["business_impact"] = (
                    "CRITICAL - Revenue loss, customer complaints likely"
                )
                context["actionable_insight"] = (
                    "Contact the relevant team or vendor immediately"
                )

        return context
