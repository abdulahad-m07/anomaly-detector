"""Generate a retail-style sample Excel file (long format, currency).

Deliberately different from the other samples so you can watch auto mode
adapt: dd/mm/yyyy dates, dollar-formatted values like "$1,234.56", and
metric names the agent has never seen.

    Date                | Metric           | Value
    01/08/2026 10:00    | Store A Sales    | $1,234.56
    ...
"""

import os
import random
from datetime import datetime, timedelta

from openpyxl import Workbook

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE, "data", "retail_metrics.xlsx")


def generate(seed=99):
    """Build the retail workbook and save it to data/retail_metrics.xlsx."""
    random.seed(seed)
    today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=20)

    metrics = {
        "Store A Sales": {"base": 1200, "noise": 150, "anomaly": 150},
        "Store B Sales": {"base": 900, "noise": 110, "anomaly": 2100},
        "Website Orders": {"base": 300, "noise": 40, "anomaly": 600},
        "Refunds": {"base": 25, "noise": 6, "anomaly": 400},
    }

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Retail Daily"
    worksheet.append(["Date", "Metric", "Value"])

    for day_offset in range(21):
        day = start + timedelta(days=day_offset)
        is_last = day_offset == 20
        for name, meta in metrics.items():
            if is_last:
                value = meta["anomaly"]
            else:
                value = meta["base"] + random.uniform(
                    -meta["noise"], meta["noise"]
                )
            worksheet.append(
                [day.strftime("%d/%m/%Y %H:%M"), name, f"${value:,.2f}"]
            )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    workbook.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    generate()
