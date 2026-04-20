import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.execution_trace import ExecutionTrace, SkillCall


def _parse_iso_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now()


def _extract_trajectory_steps(trial_dir: Path) -> list[dict[str, Any]]:
    candidates = [
        trial_dir / "agent" / "trajectory.json",
        trial_dir / "trajectory.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict) and "trajectory" in data:
            traj = data["trajectory"]
            if isinstance(traj, dict):
                steps = traj.get("steps", [])
                if isinstance(steps, list):
                    return [s for s in steps if isinstance(s, dict)]
        if isinstance(data, dict):
            steps = data.get("steps", [])
            if isinstance(steps, list):
                return [s for s in steps if isinstance(s, dict)]
    return []


def _extract_skill_calls(steps: list[dict[str, Any]]) -> tuple[list[SkillCall], int]:
    calls: list[SkillCall] = []
    step_counter = 0

    for step in steps:
        if step.get("source") == "agent":
            step_counter += 1

        tool_calls = step.get("tool_calls") or []
        observation = step.get("observation") or {}
        results = observation.get("results") if isinstance(observation, dict) else None
        output_text = None
        if isinstance(results, list):
            chunks: list[str] = []
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("content"), str):
                    chunks.append(item["content"])
            if chunks:
                output_text = "\n".join(chunks)

        metrics = step.get("metrics") or {}
        prompt_tokens = int(metrics.get("prompt_tokens") or 0)
        completion_tokens = int(metrics.get("completion_tokens") or 0)
        step_tokens = max(0, prompt_tokens + completion_tokens)

        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function_name = call.get("function_name") or "unknown_tool"
            arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            calls.append(
                SkillCall(
                    skill_name=str(function_name),
                    input_params=arguments,
                    output=output_text,
                    token_used=step_tokens,
                    time_cost_ms=0.0,
                    success=True,
                )
            )

    if step_counter == 0 and calls:
        step_counter = len(calls)
    return calls, step_counter


def parse_harbor_job_to_traces(job_dir: str | Path) -> list[ExecutionTrace]:
    job_dir = Path(job_dir)
    traces: list[ExecutionTrace] = []

    if not job_dir.is_dir():
        return traces

    for trial_dir in sorted(job_dir.iterdir()):
        if not trial_dir.is_dir():
            continue

        result_path = trial_dir / "result.json"
        if not result_path.is_file():
            continue

        with open(result_path) as f:
            result = json.load(f)

        # Skip job-level result summaries.
        if not isinstance(result, dict) or "task_name" not in result:
            continue

        task_id = str(result.get("task_name"))
        started_at = _parse_iso_datetime(result.get("started_at"))
        finished_at = _parse_iso_datetime(result.get("finished_at"))

        agent_result = result.get("agent_result") or {}
        n_input_tokens = int(agent_result.get("n_input_tokens") or 0)
        n_output_tokens = int(agent_result.get("n_output_tokens") or 0)
        n_cache_tokens = int(agent_result.get("n_cache_tokens") or 0)
        total_tokens = max(0, n_input_tokens + n_output_tokens + n_cache_tokens)

        verifier_result = result.get("verifier_result") or {}
        rewards = verifier_result.get("rewards") if isinstance(verifier_result, dict) else {}
        reward = rewards.get("reward") if isinstance(rewards, dict) else None
        task_success = bool(reward is not None and float(reward) >= 1.0)

        exception_info = result.get("exception_info") or {}
        failure_reason = None
        if isinstance(exception_info, dict):
            failure_reason = exception_info.get("exception_message")
        if not task_success and not failure_reason:
            failure_reason = "Verifier reward below 1.0"

        steps = _extract_trajectory_steps(trial_dir)
        skill_calls, steps_taken = _extract_skill_calls(steps)
        if steps_taken == 0:
            metadata = agent_result.get("metadata") if isinstance(agent_result, dict) else {}
            episodes = metadata.get("n_episodes") if isinstance(metadata, dict) else None
            steps_taken = int(episodes or 0)
        if steps_taken == 0:
            steps_taken = len(skill_calls)

        agent_info = result.get("agent_info") or {}
        agent_name = str(agent_info.get("name") or "harbor_agent")

        traces.append(
            ExecutionTrace(
                task_id=task_id,
                agent_name=agent_name,
                start_time=started_at,
                end_time=finished_at,
                total_tokens=total_tokens,
                steps_taken=steps_taken,
                skill_calls=skill_calls,
                task_success=task_success,
                failure_reason=failure_reason,
            )
        )

    return traces
