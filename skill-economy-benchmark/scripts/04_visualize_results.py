#!/usr/bin/env python3
"""Generate visualization charts from the evaluation report.

Supports both sample and dataset evaluation reports.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.visualization import plot_token_efficiency_bar, plot_redundancy_vs_success

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate evaluation visualizations")
    parser.add_argument("--dataset", action="store_true",
                        help="Use dataset evaluation report instead of sample")
    args = parser.parse_args()

    if args.dataset:
        report_path = RESULTS_DIR / "dataset_evaluation_report.json"
        prefix = "dataset_"
    else:
        report_path = RESULTS_DIR / "evaluation_report.json"
        prefix = ""

    if not report_path.exists():
        print(f"Report not found at {report_path}")
        print("Run scripts/03_run_dry_evaluation.py first.")
        sys.exit(1)

    with open(report_path) as f:
        report = json.load(f)

    print("Generating visualizations ...")

    bar_path = RESULTS_DIR / f"{prefix}token_efficiency_bar.png"
    plot_token_efficiency_bar(report, bar_path)
    print(f"  Bar chart saved to {bar_path}")

    scatter_path = RESULTS_DIR / f"{prefix}redundancy_vs_success.png"
    plot_redundancy_vs_success(report, scatter_path)
    print(f"  Scatter plot saved to {scatter_path}")

    print("Done!")


if __name__ == "__main__":
    main()
