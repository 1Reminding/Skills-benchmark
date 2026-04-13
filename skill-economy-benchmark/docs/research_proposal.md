# Research Proposal: Agent Skill Benchmark 2.0

**Author:** Yinda Chen
**Date:** 2026-04-12

---

## 1. Core Problem

Traditional SkillBench focuses only on "Pass/Fail" outcomes, ignoring two critical dimensions:

1. **Skill Economy**: When completing a task, is the Agent's use of Skills "cost-effective"? (e.g., token consumption, step count, time)
2. **Skill Effectiveness**: Is the Skill combination "efficient"? (e.g., Skill reuse rate, cross-task transferability, failure modes)

## 2. Innovation Points

### 2.1 Economy Metrics

| Metric | Abbreviation | Definition |
|--------|--------------|------------|
| Token Efficiency | TE | `(task_success) / (total_token_consumption)` |
| Step Redundancy Rate | SRR | `max(0, (actual_steps - optimal_steps) / optimal_steps)` |
| Skill Utilization Cost | SUC | `Σ(cost_per_call for each skill invocation)` |

### 2.2 Effectiveness Metrics

| Metric | Abbreviation | Definition |
|--------|--------------|------------|
| Skill Combination Synergy | SCS | Success rate improvement when using multiple skills in combination |
| Cross-Task Transferability | CTT | Reuse success rate of the same skill across different tasks |
| Failure Mode Specificity | FMS | Classification of failure as "Missing Skill" vs "Bad Combination" |

## 3. Data Flow Pipeline

```
Task Dataset
    ↓
Skill Taxonomy & Annotation
    ↓
Agent Execution Environment
    ↓
Execution Logs & Traces
    ↓
┌─────────────────────┐
│  Economy Calculator  │
│  Effectiveness       │
│  Analyzer            │
└─────────────────────┘
    ↓
Unified Evaluation Report
    ↓
Visualization Dashboard
```

## 4. Relationship to Existing Work

This work extends [SkillsBench](https://github.com/benchflow-ai/skillsbench) (Li et al., 2025), which introduced the first benchmark for evaluating how well AI agents use Skills. SkillsBench measures pass rate and normalized gain across 84 tasks in 11 domains. Our contribution adds a **cost-awareness** layer (economy metrics) and a **diagnostic** layer (effectiveness metrics) that go beyond binary pass/fail evaluation.

### Key Differences from SkillsBench v1:

| Aspect | SkillsBench v1 | Our Extension (v2) |
|--------|----------------|---------------------|
| Primary metric | Pass Rate | Pass Rate + Economy + Effectiveness |
| Cost awareness | None | Token Efficiency, Step Redundancy, Skill Cost |
| Failure diagnosis | Binary pass/fail | Missing Skill vs Bad Combination |
| Cross-task analysis | Per-task only | Cross-Task Transferability |
| Skill interaction | Independent | Combination Synergy |

## 5. Expected Outcomes

1. A reusable evaluation framework that can be applied to any agent system
2. Empirical evidence on the cost-effectiveness tradeoffs of skill augmentation
3. Diagnostic tools for identifying why skills fail (missing vs. miscombined)
4. Visualization dashboard for comparing agents across economy and effectiveness dimensions
