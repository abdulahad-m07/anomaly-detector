"""Generate a wide-format sample Excel file (metrics as columns).

This file is deliberately different from the long-format sample: no
"Metric Name" column, different column headers, and a date format the
agent has to figure out on its own. Perfect for testing auto mode.

    Date       | Apples | Bananas | Website Crashes
    01/08/2026 |   100  |    50   |       3
    ...
"""

import os
import random
from datetime import datetime, timedelta

from openpyxl import Workbook

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE, "data", "wide_metrics.xlsx")


def generate(seed=7):
    """Build the wide workbook and save it to data/wide_metrics.xlsx."""
    random.seed(seed)
    today = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    start = today - timedelta(days=14)

    series = {
        "Apples": {"base": 100, "noise": 12, "anomaly": 250},     # spike
        "Bananas": {"base": 50, "noise": 6, "anomaly": 12},       # drop
        "Website Crashes": {"base": 3, "noise": 1, "anomaly": 40},  # spike
    }

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Fruit Store"
    worksheet.append(["Date", "Apples", "Bananas", "Website Crashes"])

    for day_offset in range(15):
        day = start + timedelta(days=day_offset)
        row = [day.strftime("%d/%m/%Y %H:%M")]
        for name, meta in series.items():
            if day_offset == 14:
                row.append(meta["anomaly"])
            else:
                row.append(round(
                    meta["base"] + random.uniform(-meta["noise"], meta["noise"]),
                    2,
                ))
        worksheet.append(row)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    workbook.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    generate()
