# Metrics Definition

**Author:** Yinda Chen
**Date:** 2026-04-12

This document provides formal mathematical definitions and pseudocode for each metric in the Skill Economy Benchmark.

---

## 1. Economy Metrics

### 1.1 Token Efficiency (TE)

**Intuition:** Measures the "bang for your buck" in token usage. A successful task with fewer tokens is more efficient.

**Formula:**

```
TE(trace, task) = I(trace.task_success) / trace.total_tokens
```

where `I(·)` is the indicator function: `I(true) = 1`, `I(false) = 0`.

**Properties:**
- Range: [0, +∞) but practically [0, 1/min_tokens]
- Higher is better
- TE = 0 for all failed tasks regardless of token usage

**Pseudocode:**
```python
def compute_token_efficiency(trace, task):
    if trace.total_tokens == 0:
        return 0.0
    success = 1.0 if trace.task_success else 0.0
    return success / trace.total_tokens
```

---

### 1.2 Step Redundancy Rate (SRR)

**Intuition:** Measures how many extra steps the agent took compared to the human-defined optimum.

**Formula:**

```
SRR(trace, task) = max(0, (trace.steps_taken - task.optimal_steps) / task.optimal_steps)
```

**Properties:**
- Range: [0, +∞)
- Lower is better
- SRR = 0 means the agent used exactly the optimal number of steps (or fewer)
- SRR = 1.0 means the agent took twice the optimal steps

**Pseudocode:**
```python
def compute_step_redundancy(trace, task):
    if task.optimal_steps == 0:
        return 0.0
    redundancy = (trace.steps_taken - task.optimal_steps) / task.optimal_steps
    return max(0.0, redundancy)
```

---

### 1.3 Skill Utilization Cost (SUC)

**Intuition:** Total cost incurred from all skill invocations during task execution.

**Formula:**

```
SUC(trace, skill_registry) = Σ_{i=1}^{N} cost(skill_calls[i].skill_name)
```

where `cost(s)` looks up the `cost_per_call` from the skill taxonomy for skill `s`, and `N = len(trace.skill_calls)`.

**Properties:**
- Range: [0, +∞)
- Lower is better (for the same outcome)
- Enables cost comparison across different agent strategies

**Pseudocode:**
```python
def compute_skill_cost(trace, skill_registry):
    total = 0.0
    for call in trace.skill_calls:
        skill = skill_registry.get(call.skill_name)
        if skill:
            total += skill.cost_per_call
    return total
```

---

## 2. Effectiveness Metrics

### 2.1 Skill Combination Synergy (SCS)

**Intuition:** Measures whether using multiple skills together produces a synergistic effect (better than the sum of parts).

**Formula:**

Given a set of traces `T` and a specific skill combination `C = {s_1, s_2, ..., s_k}`:

```
SCS(C, T) = success_rate(traces using C) - mean(success_rate(traces using only s_i) for s_i in C)
```

**Properties:**
- Range: [-1, 1]
- SCS > 0 indicates positive synergy (combination is better than individual skills)
- SCS < 0 indicates negative synergy (skills interfere with each other)
- SCS = 0 indicates no interaction effect

**Pseudocode:**
```python
def compute_synergy(traces, skill_combination):
    combo_traces = [t for t in traces if uses_all_skills(t, skill_combination)]
    combo_success = mean(t.task_success for t in combo_traces)

    individual_rates = []
    for skill in skill_combination:
        single_traces = [t for t in traces if uses_only_skill(t, skill)]
        individual_rates.append(mean(t.task_success for t in single_traces))

    return combo_success - mean(individual_rates)
```

---

### 2.2 Cross-Task Transferability (CTT)

**Intuition:** Measures how well a skill generalizes across different tasks.

**Formula:**

For a skill `s` evaluated across tasks `{t_1, t_2, ..., t_m}`:

```
CTT(s) = |{t_i : exists trace using s on t_i with success}| / |{t_i : exists trace using s on t_i}|
```

**Properties:**
- Range: [0, 1]
- Higher is better
- CTT = 1 means the skill succeeds on every task where it's used
- CTT = 0 means the skill never leads to success

**Pseudocode:**
```python
def compute_transferability(skill_name, traces):
    tasks_attempted = set()
    tasks_succeeded = set()
    for trace in traces:
        if any(c.skill_name == skill_name for c in trace.skill_calls):
            tasks_attempted.add(trace.task_id)
            if trace.task_success:
                tasks_succeeded.add(trace.task_id)
    if not tasks_attempted:
        return 0.0
    return len(tasks_succeeded) / len(tasks_attempted)
```

---

### 2.3 Failure Mode Specificity (FMS)

**Intuition:** When a task fails, diagnoses whether the failure is due to a missing skill or a bad combination of skills.

**Classification Logic:**

```
FMS(trace, task) =
    "success"           if trace.task_success
    "missing_skill"     if required_skills(task) ⊄ used_skills(trace)
    "bad_combination"   if required_skills(task) ⊆ used_skills(trace) but task failed
    "other"             otherwise
```

**Encoding for aggregation:**
- "success" → 1.0
- "missing_skill" → 0.0
- "bad_combination" → 0.5
- "other" → 0.25

**Properties:**
- Provides actionable diagnosis for agent improvement
- "missing_skill" suggests the agent needs access to more skills
- "bad_combination" suggests the agent's skill orchestration logic needs improvement

**Pseudocode:**
```python
def compute_failure_mode(trace, task):
    if trace.task_success:
        return "success", 1.0

    used = {c.skill_name for c in trace.skill_calls}
    required = set(task.required_skills)

    if not required.issubset(used):
        return "missing_skill", 0.0
    else:
        return "bad_combination", 0.5
```
