"""Tests for the data reader (needs a sample Excel file)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.data_reader import DataReader, DataReaderError


class TestDataReader(unittest.TestCase):
    def test_missing_file_raises(self):
        reader = DataReader({"file_path": "does_not_exist.xlsx"})
        with self.assertRaises(DataReaderError):
            reader.read_records()

    def test_legacy_xls_rejected(self):
        reader = DataReader({"file_path": "old.xls"})
        with self.assertRaises(DataReaderError):
            reader.read_records()

    def test_reads_generated_file(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "business_metrics.xlsx",
        )
        if not os.path.exists(path):
            self.skipTest("sample file not generated yet")
        reader = DataReader(
            {
                "file_path": path,
                "worksheet_name": None,
                "date_column": "Date",
                "metric_column": "Metric Name",
                "value_column": "Value",
            }
        )
        records = reader.read_records()
        self.assertGreater(len(records), 0)
        record = records[0]
        self.assertIn("timestamp", record)
        self.assertIn("metric_name", record)
        self.assertIn("metric_value", record)
        self.assertIsInstance(record["metric_value"], float)


if __name__ == "__main__":
    unittest.main()
