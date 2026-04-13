# Agent Skill Benchmark 2.0 -- 经济性与有效性评估框架

**作者：** Qinghua Xing | **日期：** 2026-04-12

> 基于 [benchflow-ai/skillsbench](https://github.com/benchflow-ai/skillsbench)（Apache 2.0）构建

---

## 核心文档

- **[SkillsBench 原理、数据集、指标与我们的改进（含 NeurIPS TODO）](docs/skillbench_overview_and_our_contribution.md)** -- 最完整的项目说明文档，介绍 SkillsBench v1 的原理、数据集构成、已知局限性，以及我们 6 个创新指标的设计动机、数学定义和 NeurIPS 投稿计划
- [指标数学定义与伪代码](docs/metrics_definition.md) -- 6 个指标的公式和实现逻辑
- [研究提案](docs/research_proposal.md) -- 研究概述

## 目录

- [研究策略](#研究策略)
- [创新点](#创新点)
- [数据集说明](#数据集说明)
- [指标体系](#指标体系)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [实验结果](#实验结果)
- [后续计划](#后续计划)

---

## 研究策略

### 问题定位

现有的 Agent Skill 评测基准（如 SkillsBench）主要关注 **Pass/Fail 二元结果**，即"Agent 是否完成了任务"。然而，在实际部署中，我们同样关心：

1. **完成任务的代价有多大？** —— 一个消耗 500 tokens 就能完成的任务，和一个消耗 5000 tokens 才完成的任务，虽然结果相同，但经济性截然不同。
2. **Skill 的使用方式是否合理？** —— Agent 是否使用了多余的 Skill？Skill 之间的组合是否产生了协同效应？失败的原因是缺少 Skill 还是 Skill 组合不当？

### 核心方法

我们在 SkillsBench v1 的基础上引入两个新维度：

```
                    SkillsBench v1          SkillsBench 2.0 (本项目)
评估维度           Pass Rate               Pass Rate + Economy + Effectiveness
成本感知           无                       Token Efficiency, Step Redundancy, Skill Cost
失败诊断           二元 pass/fail           Missing Skill vs Bad Combination
跨任务分析         单任务独立               Cross-Task Transferability
Skill 交互分析     无                       Combination Synergy
```

### 技术路线

1. **Fork SkillsBench** 作为基础设施（84 个任务、11 个领域、确定性验证器）
2. **构建评估扩展层**（`src/`）实现 6 个创新指标
3. **选取代表性数据集**（`dataset/`）覆盖 5 个领域的 6 个真实任务
4. **Dry Run 验证**：使用 DummyAgent 生成模拟轨迹，端到端验证评估流水线
5. **未来接入真实 Agent**：替换 DummyAgent 为真实轨迹解析器即可

---

## 创新点

### 创新点 A：经济性指标（Economy Metrics）

传统基准只问"做没做对"，我们还问"花了多少代价"。

| 指标 | 缩写 | 公式 | 直觉 |
|------|------|------|------|
| Token 效率 | TE | `I(success) / total_tokens` | 成功时每消耗一个 token 的"产出" |
| 步骤冗余率 | SRR | `max(0, (实际步骤 - 最优步骤) / 最优步骤)` | Agent 多走了多少弯路 |
| Skill 调用成本 | SUC | `Σ cost_per_call` | 所有 Skill 调用的总成本 |

**为什么重要：**
- TE 可以直接量化不同 Agent 的"性价比"
- SRR 揭示 Agent 的执行效率，高 SRR 意味着存在无效重复操作
- SUC 支持跨策略的成本对比（如"多调用便宜 Skill" vs "少调用昂贵 Skill"）

### 创新点 B：有效性指标（Effectiveness Metrics）

传统基准只说"失败了"，我们还说"为什么失败"以及"Skill 组合是否合理"。

| 指标 | 缩写 | 公式 | 直觉 |
|------|------|------|------|
| Skill 组合协同 | SCS | `组合成功率 - 平均单 Skill 成功率` | 多 Skill 组合使用时的协同效应 |
| 跨任务迁移性 | CTT | `成功任务数 / 使用任务数` | 同一 Skill 在不同任务间的通用性 |
| 失败模式诊断 | FMS | 分类为 Missing Skill / Bad Combination | 精确定位失败原因 |

**为什么重要：**
- SCS > 0 说明 Skill 组合产生了"1+1>2"的效果
- CTT 帮助识别哪些 Skill 是"万金油"，哪些只适用于特定任务
- FMS 提供可操作的改进建议：缺 Skill 就补充，组合不当就优化编排逻辑

---

## 数据集说明

### 数据来源

数据集来自 [SkillsBench](https://github.com/benchflow-ai/skillsbench)（Apache 2.0），我们从 84 个任务中精选了 **6 个代表性任务**，覆盖 5 个领域：

| 任务 ID | 领域 | 难度 | 所需 Skills | 最优步骤 |
|---------|------|------|-------------|----------|
| `weighted-gdp-calc` | 金融分析 | 中等 | xlsx | 4 |
| `powerlifting-coef-calc` | 数据分析 | 简单 | xlsx, powerlifting, senior-data-scientist | 3 |
| `fix-build-agentops` | 软件工程 | 简单 | analyze-ci, testing-python, uv-package-manager | 5 |
| `sales-pivot-analysis` | 数据分析 | 中等 | xlsx, pdf | 5 |
| `earthquake-plate-calculation` | 地球物理 | 中等 | geospatial-analysis | 4 |
| `latex-formula-extraction` | 文档处理 | 中等 | pdf, marker | 4 |

### 任务结构

每个任务遵循 SkillsBench 的标准格式（Harbor 框架）：

```
dataset/<task-id>/
├── instruction.md          # 任务指令（给 Agent 的 prompt）
├── task.toml               # 元数据（领域、难度、超时时间等）
├── environment/
│   ├── Dockerfile          # 容器化执行环境
│   ├── skills/             # 可用 Skill 包
│   │   └── <skill-name>/
│   │       ├── SKILL.md    # Skill 使用说明
│   │       └── scripts/    # 辅助脚本
│   └── <data files>        # 任务数据（xlsx, pdf, json 等）
├── solution/
│   └── solve.sh            # 参考解决方案（Oracle）
└── tests/
    ├── test.sh             # 测试运行器
    └── test_outputs.py     # 确定性验证断言
```

### Skill 分类体系

我们为数据集中出现的所有 Skill 建立了统一的分类与成本模型（见 `dataset/dataset_index.json`），共 15 个 Skill，分为 5 个类别：

| 类别 | Skills | 平均成本 |
|------|--------|----------|
| 数据处理 (data) | xlsx, pdf, marker | 70 |
| 工程 (engineering) | analyze-ci, testing-python, uv-package-manager, code_write, code_read, debug | 85 |
| 分析 (analysis) | senior-data-scientist | 120 |
| 科学 (science) | geospatial-analysis | 100 |
| 领域知识 (domain) | powerlifting | 30 |

---

## 指标体系

详细数学定义见 [docs/metrics_definition.md](docs/metrics_definition.md)。

### 数据流

```
任务数据集 (dataset/)
    ↓
Skill 分类体系 (dataset_index.json)
    ↓
Agent 执行环境 (DummyAgent / 真实 Agent)
    ↓
执行轨迹 (ExecutionTrace)
    ↓
┌────────────────────────────┐
│  经济性计算器              │
│  ├── Token Efficiency      │
│  ├── Step Redundancy       │
│  └── Skill Cost            │
│  有效性分析器              │
│  ├── Skill Synergy         │
│  ├── Cross-Task Transfer   │
│  └── Failure Mode          │
└────────────────────────────┘
    ↓
统一评估报告 (results/evaluation_report.json)
    ↓
可视化图表 (results/*.png)
```

---

## 项目结构

```
skill-economy-benchmark/
├── dataset/                         # 真实 SkillsBench 数据集
│   ├── dataset_index.json           # 统一索引（任务+Skill 分类）
│   ├── weighted-gdp-calc/           # 金融分析任务
│   ├── powerlifting-coef-calc/      # 数据分析任务
│   ├── fix-build-agentops/          # 软件工程任务
│   ├── sales-pivot-analysis/        # 数据集成任务
│   ├── earthquake-plate-calculation/# 地球物理任务
│   └── latex-formula-extraction/    # 文档处理任务
├── src/                             # 核心代码
│   ├── core/                        # 数据模型 (Pydantic v2)
│   │   ├── task.py                  # Task 数据类
│   │   ├── skill.py                 # Skill 数据类 + Registry
│   │   └── execution_trace.py       # 执行轨迹数据类
│   ├── metrics/                     # 评估指标（核心创新）
│   │   ├── base_metric.py           # 指标基类
│   │   ├── economy/                 # 经济性指标
│   │   │   ├── token_efficiency.py  # TE
│   │   │   ├── step_redundancy.py   # SRR
│   │   │   └── skill_cost.py        # SUC
│   │   └── effectiveness/           # 有效性指标
│   │       ├── skill_synergy.py     # SCS
│   │       ├── transferability.py   # CTT
│   │       └── failure_analysis.py  # FMS
│   ├── evaluators/                  # 评估器
│   │   ├── trace_evaluator.py       # 轨迹评估器
│   │   └── report_generator.py      # 报告生成器
│   ├── agents/                      # Agent 实现
│   │   └── dummy_agent.py           # 模拟 Agent（Dry Run 用）
│   └── utils/                       # 工具类
│       ├── data_loader.py           # 数据加载器
│       └── visualization.py         # 可视化
├── scripts/                         # 运行脚本
│   ├── 01_setup_project.py          # 项目结构验证
│   ├── 02_generate_sample_data.py   # 生成示例数据
│   ├── 03_run_dry_evaluation.py     # 运行评估 (--sample / --dataset)
│   └── 04_visualize_results.py      # 生成可视化图表
├── tests/                           # 测试
│   ├── test_metrics.py              # 指标单元测试（16 个）
│   └── test_end_to_end.py           # 端到端测试（5 个）
├── results/                         # 输出结果
│   ├── evaluation_report.json       # 示例评估报告
│   ├── dataset_evaluation_report.json # 数据集评估报告
│   └── *.png                        # 可视化图表
├── docs/                            # 研究文档
│   ├── research_proposal.md         # 研究思路
│   └── metrics_definition.md        # 指标数学定义
├── data/                            # 示例数据
│   ├── raw/sample_tasks.json        # 3 个简单示例任务
│   └── skill_taxonomy/base_skills.json  # 5 个基础 Skill
├── pyproject.toml                   # 项目配置
├── requirements.txt                 # 依赖
├── README.md                        # English README
└── README_CN.md                     # 中文 README（本文件）
```

---

## 快速开始

### 环境安装

```bash
git clone https://github.com/ydchen0806/skill-economy-benchmark.git
cd skill-economy-benchmark
pip install -e ".[dev]"
```

### 运行示例数据评估

```bash
# 1. 生成示例数据
python scripts/02_generate_sample_data.py

# 2. 运行评估（3 个简单任务）
python scripts/03_run_dry_evaluation.py

# 3. 运行测试（21 个测试全部通过）
pytest tests/ -v

# 4. 生成可视化图表
python scripts/04_visualize_results.py
```

### 运行真实数据集评估

```bash
# 使用 SkillsBench 6 个代表性任务
python scripts/03_run_dry_evaluation.py --dataset

# 生成对应的可视化
python scripts/04_visualize_results.py --dataset
```

---

## 实验结果

### 示例数据结果（3 个任务）

| 任务 | 结果 | TE | SRR | SUC | FMS |
|------|------|-----|------|-----|-----|
| task_001 (排序) | PASS | 0.0067 | 0.00 | 200 | success |
| task_002 (调试) | PASS | 0.0025 | 0.67 | 440 | success |
| task_003 (规划+编写) | FAIL | 0.0000 | 0.50 | 300 | bad_combination |

### 真实数据集结果（6 个任务）

| 任务 | 结果 | TE | SRR | SUC | FMS |
|------|------|-----|------|-----|-----|
| weighted-gdp-calc | PASS | 0.0031 | 0.00 | 280 | success |
| powerlifting-coef-calc | PASS | 0.0040 | 0.00 | 230 | success |
| fix-build-agentops | PASS | 0.0021 | 0.20 | 500 | success |
| sales-pivot-analysis | PASS | 0.0026 | 0.00 | 340 | success |
| earthquake-plate-calc | FAIL | 0.0000 | 0.75 | 550 | bad_combination |
| latex-formula-extraction | PASS | 0.0033 | 0.00 | 250 | success |

**关键发现：**
- `earthquake-plate-calculation` 虽然使用了所需 Skill，但组合方式不当（FMS = bad_combination），SRR = 0.75 说明多了 75% 的冗余步骤
- `fix-build-agentops` 的 SUC 最高（500），因为涉及 6 个 Skill 调用
- `powerlifting-coef-calc` 的 TE 最高（0.004），说明其"性价比"最好

---

## 后续计划

完整的 NeurIPS 投稿 TODO（含 4 个 Phase、时间节点、风险评估）见 **[详细文档](docs/skillbench_overview_and_our_contribution.md#四neurips-投稿-todo)**。

核心里程碑：

| 阶段 | 时间 | 内容 |
|------|------|------|
| Phase 1: 基础设施 | 4/12-4/19 | 真实轨迹解析、Agent 接入、数据集扩展 |
| Phase 2: 核心实验 | 4/19-5/03 | 经济性分析、失败诊断、组合迁移实验 |
| Phase 3: 论文撰写 | 5/03-5/17 | NeurIPS LaTeX 模板、8 页论文 |
| Phase 4: 润色提交 | 5/17-5/24 | 内审、语言润色、代码清理、提交 |

---

## 引用

如果本项目对您的研究有帮助，请引用：

```bibtex
@misc{chen2026skilleconomy,
  title={Agent Skill Benchmark 2.0: Economy and Effectiveness Evaluation Framework},
  author={Yinda Chen},
  year={2026},
  url={https://github.com/ydchen0806/skill-economy-benchmark}
}
```

本项目基于 SkillsBench 构建：

```bibtex
@article{li2025skillsbench,
  title={SkillsBench: Benchmarking How Well Agent Skills Work Across Diverse Tasks},
  author={Li, Xiangyi and others},
  journal={arXiv preprint arXiv:2602.12670},
  year={2025}
}
```

## 许可证

[Apache 2.0](LICENSE)
