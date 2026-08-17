"""Automatic layout detection for Excel files.

When ``excel_config.auto`` is enabled, this module inspects a workbook and
figures out, without any manual configuration:

- which worksheet contains the data
- which column holds dates/timestamps
- whether the data is "long" (Date | Metric | Value)
  or "wide" (Date | MetricA | MetricB | ...)
- the date format being used
- the set of metric names (for wide layouts)

The result is handed to the DataReader so it can parse any reasonable
business spreadsheet. It also provides number/text helpers shared with
the data reader, and metric "profiles" (guessed unit + priority).
"""

import re
from datetime import datetime

# ----------------------------------------------------------------------
# header name lookups
# ----------------------------------------------------------------------
_DATE_HEADERS = {
    "date", "datetime", "timestamp", "time", "day", "dt", "when",
    "created", "created_at", "date_time", "period", "time_stamp",
    "createdat",
}

_METRIC_HEADERS = {
    "metric", "metricname", "name", "indicator", "kpi", "measure",
    "variable", "series", "type", "label", "key", "category", "metric_name",
}

_VALUE_HEADERS = {
    "value", "amount", "val", "quantity", "count", "measurement",
    "metricvalue", "metric_value", "total", "number", "figure", "result",
    "actual", "amountusd",
}

# ----------------------------------------------------------------------
# date + number parsing helpers
# ----------------------------------------------------------------------
_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%d-%b-%Y %H:%M",
    "%b %d, %Y",
    "%b %d, %Y %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
]

_NUMBER_CLEAN = re.compile(r"[^0-9.\-+]")


def clean_text(value):
    """Return a trimmed string version of a cell ('' for None)."""
    if value is None:
        return ""
    return str(value).strip()


def _parse_date_text(text, fmt):
    try:
        return datetime.strptime(text, fmt)
    except (ValueError, TypeError):
        return None


def _is_number(value):
    """True if a cell looks like a number (handles $, commas, %, units)."""
    if isinstance(value, (int, float)):
        return True
    cleaned = _NUMBER_CLEAN.sub("", clean_text(value))
    if not cleaned or cleaned in (".", "-", "+", "-.", "+."):
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def to_number(value):
    """Convert a cell to a float, raising ValueError if it is not numeric."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = _NUMBER_CLEAN.sub("", clean_text(value))
    if not cleaned or cleaned in (".", "-", "+", "-.", "+."):
        raise ValueError(f"not numeric: {value!r}")
    return float(cleaned)


def _looks_like_date(value):
    """True if a cell looks like a date (datetime, Excel serial, or text)."""
    if isinstance(value, datetime):
        return True
    if isinstance(value, (int, float)):
        return True  # Excel serial number
    text = clean_text(value)
    if not text:
        return False
    return any(_parse_date_text(text, fmt) for fmt in _DATE_FORMATS)


def detect_date_format(values, limit=5):
    """Pick the date format that parses the most sample values."""
    candidates = [v for v in (values or []) if isinstance(v, str)][:limit]
    if not candidates:
        return None
    best_format, best_score = None, 0
    for fmt in _DATE_FORMATS:
        score = sum(
            1 for v in candidates if _parse_date_text(v, fmt) is not None
        )
        if score > best_score:
            best_format, best_score = fmt, score
        if best_score == len(candidates):
            break
    return best_format if best_score > 0 else None


def guess_metric_profile(name):
    """Guess a sensible (unit, priority) for a metric name.

    Used for metrics discovered automatically so the agent still produces
    useful alerts and emails without any manual configuration.
    """
    text = (name or "").lower()
    if any(k in text for k in
           ("revenue", "sales", "income", "profit", "amount", "price",
            "money", "cash", "revenue$")):
        return {"unit": "USD", "priority": "HIGH"}
    if any(k in text for k in
           ("cpu", "memory", "disk", "usage", "percent", "utilisation",
            "utilization", "load")):
        return {"unit": "percent", "priority": "HIGH"}
    if any(k in text for k in
           ("failed", "error", "failure", "outage", "crash", "refund",
            "rejected", "declined")):
        return {"unit": "count", "priority": "HIGH"}
    if any(k in text for k in
           ("latency", "response", "duration", "speed", "time")):
        return {"unit": "ms", "priority": "MEDIUM"}
    if any(k in text for k in
           ("login", "user", "session", "visit", "order", "transaction",
            "request", "hit", "click", "signup", "pageview")):
        return {"unit": "count", "priority": "MEDIUM"}
    return {"unit": "", "priority": "MEDIUM"}


# ----------------------------------------------------------------------
# column inspection
# ----------------------------------------------------------------------
class _ColumnInfo:
    """What the detector knows about a single column."""

    def __init__(self, index, header, sample):
        self.index = index
        self.header = header
        self.sample = sample  # non-empty raw cells from the first rows

    @property
    def header_key(self):
        return re.sub(r"[^a-z0-9]", "", clean_text(self.header).lower())

    def _count(self, predicate):
        return sum(1 for v in self.sample if predicate(v))

    @property
    def numeric_ratio(self):
        if not self.sample:
            return 0.0
        return self._count(_is_number) / len(self.sample)

    @property
    def date_ratio(self):
        if not self.sample:
            return 0.0
        return self._count(_looks_like_date) / len(self.sample)

    @property
    def unique_ratio(self):
        """Share of distinct values. Low = values repeat (metric labels)."""
        if not self.sample:
            return 1.0
        seen = set()
        for v in self.sample:
            key = clean_text(v)
            if key:
                seen.add(key)
        return len(seen) / len(self.sample)


# ----------------------------------------------------------------------
# detection result
# ----------------------------------------------------------------------
class AutoDetection:
    """Describes the detected layout of a workbook."""

    def __init__(self, worksheet_name, layout, date_col, metric_col,
                 value_col, numeric_cols, date_format, metric_names=None):
        self.worksheet_name = worksheet_name
        self.layout = layout           # "long" or "wide"
        self.date_col = date_col       # column index of the date column
        self.metric_col = metric_col   # index of the metric-name column (long)
        self.value_col = value_col     # index of the value column (long)
        self.numeric_cols = numeric_cols  # list of indices (wide)
        self.date_format = date_format
        self.metric_names = metric_names  # list of metric names (wide)


# ----------------------------------------------------------------------
# the detector
# ----------------------------------------------------------------------
class AutoDetector:
    """Detects worksheet + column layout for a workbook."""

    SAMPLE_ROWS = 60

    def __init__(self, logger=None):
        self.logger = logger

    def _log(self, message):
        if self.logger is not None:
            self.logger.info(message)

    def _pick_worksheet(self, workbook):
        """Choose the worksheet with the most non-header rows."""
        best, best_count = None, -1
        for worksheet in workbook.worksheets:
            count = sum(
                1 for _ in worksheet.iter_rows(values_only=True)
            )
            if count > best_count:
                best, best_count = worksheet, count
        return best

    def _sample_columns(self, worksheet):
        """Return (header, list-of-column-samples)."""
        rows = worksheet.iter_rows(values_only=True)
        header_row = next(rows, None)
        if header_row is None:
            return [], []
        header = [clean_text(h) if h is not None else "" for h in header_row]
        columns = [[] for _ in header]
        for raw in rows:
            values = list(raw)
            for i in range(len(header)):
                value = values[i] if i < len(values) else None
                if clean_text(value):
                    columns[i].append(value)
            if all(len(c) >= self.SAMPLE_ROWS for c in columns):
                break
        return header, columns

    def _find_date_column(self, cols):
        """Prefer a date-ish header, else the column full of dates."""
        for col in cols:
            if col.header_key in _DATE_HEADERS:
                return col.index
        for col in cols:
            if col.date_ratio >= 0.8:
                return col.index
        return None

    def _find_metric_column(self, cols, date_col):
        """Prefer a label header, else a repeating text column."""
        for col in cols:
            if col.header_key in _METRIC_HEADERS:
                return col.index
        for col in cols:
            if col.index == date_col:
                continue
            if col.numeric_ratio < 0.5 and col.date_ratio < 0.5 \
                    and col.unique_ratio <= 0.5:
                return col.index
        return None

    def _find_numeric_columns(self, cols, date_col):
        """All mostly-numeric columns (excluding the date column)."""
        return [
            col.index for col in cols
            if col.index != date_col and col.numeric_ratio >= 0.8
        ]

    def _find_value_column(self, cols, date_col, metric_col):
        """Prefer a value-ish header, else the first numeric column."""
        for col in cols:
            if col.header_key in _VALUE_HEADERS \
                    and col.index not in (date_col, metric_col):
                return col.index
        for col in cols:
            if col.numeric_ratio >= 0.8 \
                    and col.index not in (date_col, metric_col):
                return col.index
        return None

    def detect(self, workbook):
        """Return an AutoDetection describing the file layout."""
        worksheet = self._pick_worksheet(workbook)
        if worksheet is None:
            return None
        header, samples = self._sample_columns(worksheet)
        if not header:
            return None
        cols = [
            _ColumnInfo(i, header[i], samples[i])
            for i in range(len(header))
        ]

        date_col = self._find_date_column(cols)
        metric_col = self._find_metric_column(cols, date_col)
        numeric_cols = self._find_numeric_columns(cols, date_col)

        date_format = None
        if date_col is not None:
            date_format = detect_date_format(cols[date_col].sample)

        if metric_col is not None:
            layout = "long"
            value_col = self._find_value_column(cols, date_col, metric_col)
            metric_names = None
        else:
            layout = "wide"
            value_col = None
            metric_names = [
                cols[i].header for i in numeric_cols
            ] if numeric_cols else None

        return AutoDetection(
            worksheet_name=worksheet.title,
            layout=layout,
            date_col=date_col,
            metric_col=metric_col,
            value_col=value_col,
            numeric_cols=numeric_cols,
            date_format=date_format,
            metric_names=metric_names,
        )
