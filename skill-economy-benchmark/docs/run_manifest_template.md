# Run Manifest Template

用于统一描述单个 task 的实验运行配置，便于脚本自动调度。

## 最小字段

```yaml
run_id: sales-pivot-analysis_gemini3flash_v1

task_id: sales-pivot-analysis
model: gemini-3-flash-preview
repeats: 3

enabled: true

configurations:
  - type: no_skill

  - type: original_curated

  - type: single
    skills: [skill_a]

  - type: single
    skills: [skill_b]

  - type: single
    skills: [skill_c]

  - type: combo
    skills: [skill_a, skill_c]

  - type: full_pool
```

## 字段说明

* `run_id`：本次运行唯一标识
* `task_id`：任务名
* `model`：使用的模型
* `repeats`：每个配置重复次数
* `enabled`：是否执行该 task
* `configurations`：本 task 要跑的配置列表

## configuration 类型

### 1. no_skill

不给任何 skill。

```yaml
- type: no_skill
```

### 2. original_curated

只使用原始 curated skills。

```yaml
- type: original_curated
```

### 3. single

只给一个 skill。

```yaml
- type: single
  skills: [skill_a]
```

### 4. combo

给少量组合 skill。

```yaml
- type: combo
  skills: [skill_a, skill_b]
```

### 5. full_pool

给整个 task-level skill pool。

```yaml
- type: full_pool
```

## 推荐约束

* `single` 配置建议 3–4 个
* `combo` 配置建议 1–2 个
* `full_pool` 建议保留
* 主实验默认保留：

  * `no_skill`
  * `original_curated`
  * 若干 `single`
  * 1 个 `combo`
  * `full_pool`

## 推荐主实验模板

```yaml
run_id: <task>_<model>_main

task_id: <task>
model: gemini-3-flash-preview
repeats: 3
enabled: true

configurations:
  - type: no_skill
  - type: original_curated
  - type: single
    skills: [skill_a]
  - type: single
    skills: [skill_b]
  - type: single
    skills: [skill_c]
  - type: single
    skills: [skill_d]
  - type: combo
    skills: [skill_a, skill_c]
  - type: full_pool
```

## 可选扩展字段

如果后面需要，可增加：

```yaml
metadata:
  family: spreadsheet_analytics
  priority: high
  notes: first-round pilot
```

以及：

```yaml
output_dir: results/runs/
timeout: 3600
```

没有这些字段也可以先跑。
