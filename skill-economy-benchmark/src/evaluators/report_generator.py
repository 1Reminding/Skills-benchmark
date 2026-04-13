import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any


def generate_report(
    task_results: List[Dict[str, Any]],
    output_path: str | Path,
) -> Dict[str, Any]:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_tasks = len(task_results)
    n_success = sum(1 for r in task_results if r["task_success"])

    metric_keys = list(task_results[0]["metrics"].keys()) if task_results else []
    aggregated: Dict[str, float] = {}
    for key in metric_keys:
        values = [r["metrics"][key] for r in task_results]
        aggregated[f"mean_{key}"] = sum(values) / len(values) if values else 0.0

    failure_modes: Dict[str, int] = {}
    for r in task_results:
        mode = r.get("failure_mode", "unknown")
        failure_modes[mode] = failure_modes.get(mode, 0) + 1

    report = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_tasks": n_tasks,
            "successful_tasks": n_success,
            "success_rate": n_success / n_tasks if n_tasks else 0.0,
            "failure_mode_distribution": failure_modes,
        },
        "aggregated_metrics": aggregated,
        "task_results": task_results,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    return report
