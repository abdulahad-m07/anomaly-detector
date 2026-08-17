"""Generate a sample business_metrics.xlsx for testing the agent.

Creates ~30 days of daily rows for four metrics, then injects a clear
anomaly into the newest row of each metric so you can watch the agent
detect and email alerts.
"""

import os
import random
from datetime import datetime, timedelta

from openpyxl import Workbook

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE, "data", "business_metrics.xlsx")


def generate(seed=42):
    """Build the workbook and save it to data/business_metrics.xlsx."""
    random.seed(seed)
    today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=29)

    metrics = {
        "Sales Revenue": {
            "unit": "USD",
            "base": 45000.0,
            "noise": 3500.0,
            "anomaly": 15000.0,  # big drop
        },
        "Customer Logins": {
            "unit": "count",
            "base": 5000.0,
            "noise": 500.0,
            "anomaly": 800.0,  # big drop
        },
        "Failed Transactions": {
            "unit": "count",
            "base": 20.0,
            "noise": 8.0,
            "anomaly": 700.0,  # big spike
        },
        "Server CPU": {
            "unit": "percent",
            "base": 45.0,
            "noise": 6.0,
            "anomaly": 92.0,  # spike near max
        },
    }

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Daily Metrics"
    worksheet.append(["Date", "Metric Name", "Value"])

    for day_offset in range(30):
        day = start + timedelta(days=day_offset)
        is_last = day_offset == 29
        for name, meta in metrics.items():
            if is_last:
                value = meta["anomaly"]
            else:
                value = meta["base"] + random.uniform(
                    -meta["noise"], meta["noise"]
                )
                # Weekends are naturally quieter for Sales Revenue.
                if name == "Sales Revenue" and day.weekday() >= 5:
                    value *= 0.6
            worksheet.append(
                [day.strftime("%Y-%m-%d %H:%M"), name, round(value, 2)]
            )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    workbook.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    generate()
