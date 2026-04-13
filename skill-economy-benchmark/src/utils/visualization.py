from pathlib import Path
from typing import Dict, List, Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns


def plot_token_efficiency_bar(
    report: Dict[str, Any],
    output_path: str | Path,
) -> None:
    results = report["task_results"]
    task_ids = [r["task_id"] for r in results]
    te_values = [r["metrics"]["token_efficiency"] for r in results]

    fig, ax = plt.subplots(figsize=(8, 5))
    sns.barplot(x=task_ids, y=te_values, hue=task_ids, ax=ax, palette="viridis", legend=False)
    ax.set_xlabel("Task ID")
    ax.set_ylabel("Token Efficiency (TE)")
    ax.set_title("Token Efficiency per Task")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_redundancy_vs_success(
    report: Dict[str, Any],
    output_path: str | Path,
) -> None:
    results = report["task_results"]
    srr_values = [r["metrics"]["step_redundancy"] for r in results]
    success_values = [1.0 if r["task_success"] else 0.0 for r in results]
    task_ids = [r["task_id"] for r in results]

    fig, ax = plt.subplots(figsize=(8, 5))
    scatter = ax.scatter(srr_values, success_values, s=100, c=success_values,
                         cmap="RdYlGn", edgecolors="black", zorder=5)
    for i, tid in enumerate(task_ids):
        ax.annotate(tid, (srr_values[i], success_values[i]),
                    textcoords="offset points", xytext=(5, 5), fontsize=9)
    ax.set_xlabel("Step Redundancy Rate (SRR)")
    ax.set_ylabel("Success (1=Pass, 0=Fail)")
    ax.set_title("Step Redundancy vs Success Rate")
    ax.set_ylim(-0.1, 1.1)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
