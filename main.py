"""Entry point for the AI-Powered Excel Anomaly Detection Agent.

Usage:
    python main.py                    # interactive: choose which data, then watch
    python main.py --once             # single pass on the configured file
    python main.py --config path.json # continuous run with a specific config
"""

import argparse
import json
import logging
import os
import sys

from modules.monitor_loop import MonitoringLoop


def load_config(config_path):
    """Read and validate the JSON configuration file."""
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    required = [
        "excel_config",
        "anomaly_detection",
        "email_config",
        "monitoring",
    ]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Config missing required sections: {missing}")
    return config


def setup_logging(config):
    """Configure logging to file and console."""
    log_file = config["monitoring"].get("log_file", "logs/anomaly_detection.log")
    log_dir = os.path.dirname(os.path.abspath(log_file))
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("anomaly_agent")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


# ----------------------------------------------------------------------
# interactive helpers
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def find_excel_files():
    """List Excel files available in the data/ folder."""
    os.makedirs(DATA_DIR, exist_ok=True)
    files = [
        os.path.join(DATA_DIR, f)
        for f in os.listdir(DATA_DIR)
        if f.lower().endswith((".xlsx", ".xlsm"))
    ]
    return sorted(files)


def generate_samples():
    """Create the sample data files so the menu has choices."""
    from scripts import (
        generate_retail_sample,
        generate_sample_data,
        generate_wide_sample,
    )
    generate_sample_data.generate()
    generate_wide_sample.generate()
    generate_retail_sample.generate()


def ask_which_file():
    """Show a menu of data files and return the chosen path (or None)."""
    files = find_excel_files()
    print("\n=== Which data should I watch? ===")
    if not files:
        answer = input(
            "No Excel files found in the data/ folder. "
            "Generate sample data? [y/n]: "
        ).strip().lower()
        if answer in ("y", "yes"):
            generate_samples()
            files = find_excel_files()
            if not files:
                print("Sample generation failed.")
                return None
        else:
            print("Nothing to do. Bye!")
            return None
    for i, path in enumerate(files, 1):
        print(f"  {i}. {os.path.basename(path)}")
    print(
        "  Or type a full path to any Excel file on your computer "
        "('q' to quit)."
    )
    choice = input("Your choice: ").strip()
    if choice.lower() in ("q", "quit", "exit"):
        return None
    if choice.isdigit():
        index = int(choice) - 1
        if 0 <= index < len(files):
            return files[index]
        print("Invalid number.")
        return None
    if choice:
        return choice
    return None


def ask_mode():
    """Ask whether to run once or keep watching."""
    answer = input("Run once (1) or keep watching (2)? [1/2]: ").strip()
    return answer == "2"


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Excel anomaly detection agent with email alerts"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the configuration JSON file",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single monitoring pass and exit",
    )
    args = parser.parse_args()

    default_config = os.path.join(BASE_DIR, "config.json")

    if args.config is None and not args.once:
        # Interactive mode: let the user choose which data to watch.
        config = load_config(default_config)
        chosen = ask_which_file()
        if not chosen:
            return
        config["excel_config"]["file_path"] = chosen
        keep_watching = ask_mode()
    else:
        config_path = args.config or default_config
        config = load_config(config_path)
        keep_watching = not args.once

    logger = setup_logging(config)
    logger.info(
        f"Watching file: {config['excel_config'].get('file_path')}"
    )

    loop = MonitoringLoop(config, logger)
    if keep_watching:
        loop.run_forever()
    else:
        loop.run_once()


if __name__ == "__main__":
    main()
