# Agent Skill Benchmark 2.0 -- 经济性与有效性评估框架

**作者：** Qinghua Xing | **日期：** 2026-04-12

> 基于 [benchflow-ai/skillsbench](https://github.com/benchflow-ai/skillsbench)（Apache 2.0）构建

---

## 核心文档

- **[SkillsBench 原理、数据集、指标与我们的改进（含 NeurIPS TODO）](docs/skillbench_overview_and_our_contribution.md)** -- 最完整的项目说明文档，介绍 SkillsBench v1 的原理、数据集构成、已知局限性，以及我们 6 个创新指标的设计动机、数学定义和 NeurIPS 投稿计划
- [指标数学定义与伪代码](docs/metrics_definition.md) -- 6 个指标的公式和实现逻辑
- [研究提案](docs/research_proposal.md) -- 研究概述
- [Skill Pool 构建协议](docs/skill_pool_protocol.md) -- 说明 retrieval + prompt engineering 的候选 skill 构建、过滤、去重与反泄露流程
- [实验任务协议](docs/experiment_protocol.md) -- 说明 skill pool 构建完成后需要运行的实验配置、对照组、重复次数与主实验模板

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
3. **现有 benchmark 的 task-skill 映射往往过于稀疏。**  
   在很多任务中，可用 skill 数量很少，甚至只有 1 个。这会直接导致：
   - Skill 之间缺乏可比性
   - 组合协同（SCS）难以稳定计算
   - 跨任务迁移性（CTT）样本不足
   - “缺 skill”与“组合不当”的分析缺乏依据

因此，我们的目标不只是提出新的评测指标，而是进一步回答：

> **如何把一个稀疏的 skill benchmark 扩展成一个可分析的 skill pool，并在此基础上研究“什么样的 skill 才是好的 skill”？**

### 核心思路

本项目包含两个互补层次：

#### 层次 1：扩展评测维度
在 SkillsBench v1 的 Pass Rate 之外，我们引入两个新维度：

- **Economy**：完成任务花了多大代价？
- **Effectiveness**：为什么成功 / 为什么失败？Skill 组合是否合理？

#### 层次 2：扩展 skill 候选空间
我们进一步观察到：如果每个 task 只有极少数 skill，可计算的分析维度会非常有限。  
因此，本项目不把重点放在训练一个 skill generator，而是采用一种更轻量、可控、可复现的方法：

> **retrieval + prompt engineering 的 skill pool construction pipeline**

即：针对每类 task，从已有 skill、相似任务、通用 procedural pattern 中进行检索，再通过受控生成与过滤，构建一个更稠密、更可比较的 skill pool。

### 方法概览

```text
                 SkillsBench v1
        Pass/Fail on sparse task-skill mappings
                           │
                           ▼
        Diagnose sparsity and under-identified metrics
                           │
                           ▼
   Retrieval-augmented skill pool construction (ours)
   ├── retrieve similar skills / task patterns
   ├── prompt-based candidate skill generation
   ├── filtering / dedup / anti-leakage checks
   └── build dense per-task candidate pools
                           │
                           ▼
     Evaluate with outcome + economy + effectiveness
   ├── Pass Rate
   ├── Token Efficiency / Step Redundancy / Skill Cost
   ├── Skill Combination Synergy
   ├── Cross-Task Transferability
   └── Failure Mode Specificity
                           │
                           ▼
     Analyze what makes a "good skill"
   ├── high cost-effectiveness
   ├── strong cross-task transferability
   ├── positive composition synergy
   └── interpretable failure patterns
```   
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

### 创新点 C：Benchmark Diagnosis —— 发现稀疏 skill 生态的问题

我们指出：现有 SkillsBench 风格的 task-skill 映射在很多任务上过于稀疏，导致高阶分析指标难以成立。  
这不仅影响 Skill 组合协同（SCS）和跨任务迁移性（CTT）的稳定计算，也限制了“好 skill 长什么样”的经验分析。

我们因此将 **skill sparsity** 本身视为 benchmark 的一个结构性问题。

### 创新点 D: Retrieval-Augmented Skill Pool Construction

为了解决 task 下可比 skill 不足的问题，我们提出一种轻量但有效的 skill pool 构建方案，而不是训练一个昂贵的 skill generator：

1. **Retrieval**：从已有 skill 库、相似任务、跨领域 procedural pattern 中检索候选材料
2. **Prompt-based Generation**：通过受控 prompt 生成多个 skill 候选，而不是为单个任务拟合一个“专属答案”
3. **Filtering & Safety Checks**：
   - 结构合法性检查
   - 与已有 skill 去重
   - task-specific leakage 检测
   - 成本与长度标注
4. **Dense Skill Pooling**：为每个 task / task family 建立更丰富的 skill 候选池，使得后续比较和分析成为可能

### 创新点 E：从“Skill 是否有用”走向“好 Skill 有什么特征”

本项目最终关注的不只是分数，而是现象分析：

- 哪些 skill 具有更高的 cost-effectiveness？
- 哪些 skill 更容易跨任务迁移？
- 哪些组合真正产生了 1+1>2 的效果？
- 哪些失败来自缺 skill，哪些来自错误组合？
- 高质量 skill 在长度、抽象层次、结构组织和调用方式上具有什么共性？

因此，本项目的目标是把 Skill 评测从：

> “Skill 有没有用？”

推进到：

> “什么样的 Skill 值得保留、复用与组合？”
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

## Skill Pool 构建方案

### 为什么需要 Skill Pool

原始 benchmark 中，很多 task 只绑定了极少数 curated skills。  
这会带来一个直接后果：虽然 Pass Rate 仍然可以计算，但更细粒度的 economy / effectiveness 分析会受到很大限制。

例如：

- 如果一个 task 只有 1 个 skill，就很难讨论 skill 之间的优劣
- 如果几乎没有可替代 skill，SCS 难以反映真正的组合协同
- 如果某个 skill 只出现在 1 个任务里，CTT 就缺乏统计意义
- FMS 中“Missing Skill”与“Bad Combination”的区分，也会因为候选空间不足而变得不可靠

因此，我们引入一个新的中间层：

> **为每个 task / task family 构建一个更稠密的 candidate skill pool。**

### Skill Pool Construction Pipeline

#### Step 1: Retrieval
针对每个 task，我们检索三类材料：

- **已有 skills**：原始 benchmark 中的 curated skills
- **相似任务 skills**：同领域或程序结构相似任务中的 skill
- **通用 procedural patterns**：可迁移的 how-to 模板、工具使用流程与分步策略

#### Step 2: Prompt-Based Candidate Generation
基于检索到的材料，使用 prompt engineering 生成多个候选 skill。  
这里的目标不是为单个 task 写“专属答案”，而是生成 **可复用、可迁移、具有程序性指导价值** 的 skill 描述。

生成约束包括：

- 必须是 procedural guidance，而非 task answer
- 尽量避免 task-specific 文件名、路径、魔法常数
- 使用统一的 skill 结构与格式
- 控制长度，避免冗长和重复

#### Step 3: Filtering and Normalization
对候选 skill 做进一步过滤：

- 结构合法性检查（是否符合 skill 格式）
- 与已有 skill 去重
- 反泄露检测（是否包含 task-specific solution pattern）
- 长度、抽象层次、领域标签、成本标签归一化

#### Step 4: Pooling
将通过过滤的 skill 合并为 task-level 或 family-level 的 candidate pool，供后续实验使用。

### 设计原则

我们的 skill pool 构建方法遵循三条原则：

1. **Low-cost**：避免训练专门的 skill generator，优先使用 retrieval + prompting
2. **Controllable**：生成过程透明、可调试、易做 ablation
3. **Benchmark-oriented**：目标不是训练最强模型，而是让 benchmark 拥有足够的 skill 多样性，以支持更可靠的比较和分析

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
├── skill_pool/                       # 新增：扩展后的 skill pool
│   ├── raw_retrieved/                # 检索得到的原始候选材料
│   ├── generated/                    # prompt 生成的候选 skill
│   ├── filtered/                     # 过滤后的 skill pool
│   └── metadata.json                 # skill 来源、标签、成本、长度等元数据
├── prompts/                          # 新增：skill 构建与过滤用 prompt
│   ├── retrieve_and_generate.md
│   ├── dedup_filter.md
│   └── leakage_check.md
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
│   ├── 04_visualize_results.py      # 生成可视化图表
│   ├── 05_run_real_evaluation.py    # 真实 Harbor 任务运行 + 轨迹评估
│   ├── 06_compare_with_without_skills.py # with-skills vs no-skills 对照
│   ├── 07_build_skill_pool_retrieval_v2.py  # retrieval-only skill pool 构建（稳定版）
│   └── 08_prepare_external_skills_catalog.py # 外部 skill 清单标准化（含 URL/license）
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
│   └── skill_pool_protocol.md        # 新增：skill pool 构建协议
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

### 运行真实 Harbor 实验（with-skills vs no-skills）

```bash
# 需要 Docker（SkillsBench 的 environment.type=docker）
docker --version

# 运行真实对照实验（可通过 --task-ids 先小规模测试）
python scripts/06_compare_with_without_skills.py \
  --skillsbench-root /local-data/xingqinghua/skillsbench \
  --task-ids weighted-gdp-calc,sales-pivot-analysis,earthquake-plate-calculation \
  --agent oracle \
  --attempts 1
```

注意事项：
- 如果终端出现 `No such file or directory: 'docker'` 或 `Docker is not installed`，说明任务环境未真正启动，结果为基础设施失败，不是指标本身为 0。
- `scripts/05_run_real_evaluation.py` 现在会在运行前检查 Docker；如果所有 trace 都是 infra error，会直接报错退出，避免生成误导性的“全 0”评估报告。
- 仅在已有有效 Harbor 产物时才使用 `--skip-run` 做离线解析。

### 先做 Skill Pool Retrieval（不依赖 Docker / 不依赖 API）

```bash
# 小规模先跑 2-3 个 task（推荐先做这步）
python scripts/07_build_skill_pool_retrieval_v2.py \
  --task-ids sales-pivot-analysis,weighted-gdp-calc,earthquake-plate-calculation \
  --max-pool-size 10 \
  --max-generic 1 \
  --max-cross 1 \
  --max-external 0
```

输出目录：
- `skill_pool/raw_retrieved/<task_id>.json`：三路召回结果（orig/cross/external）
- `skill_pool/task_pools/<task_id>.json`：合并后的 task-level candidate pool
- `skill_pool/metadata.json`：本次运行清单

### 外部检索与收集（GitHub API）

```bash
# Step 08: 先基于 task schema 生成 query plans
python scripts/08_generate_external_queries.py \
  --task-ids sales-pivot-analysis,weighted-gdp-calc,fix-build-agentops,earthquake-plate-calculation \
  --max-queries-per-task 10

# Step 09: 实时外部抓取 + query-driven 打分（推荐）
# 可选：export GITHUB_TOKEN=...
python scripts/09_collect_external_skills.query_driven.py \
  --live-fetch \
  --task-ids sales-pivot-analysis,weighted-gdp-calc,fix-build-agentops,earthquake-plate-calculation \
  --max-skills 40 \
  --output-file data/external_skill_corpus.json

# 可选：加入你手工维护的仓库地址清单（JSON）
python scripts/09_collect_external_skills.query_driven.py \
  --live-fetch \
  --extra-repos-file data/external_repo_sources.json \
  --task-ids sales-pivot-analysis,weighted-gdp-calc \
  --max-skills 40 \
  --output-file data/external_skill_corpus.json

# 小规模开启 external 候选
python scripts/07_build_skill_pool_retrieval_v2.py \
  --task-ids sales-pivot-analysis,weighted-gdp-calc \
  --external-skills data/external_skill_corpus.json \
  --max-generic 1 \
  --max-cross 1 \
  --max-external 2
```

`data/external_skill_corpus.json` 每条候选建议包含：
- `metadata.source_url`：原始来源链接
- `metadata.license_note`：许可证说明（或待确认）
- `family / artifacts / operations / tools / granularity / domain_specificity`：用于可解释检索

说明：
- `--live-fetch` 会优先从 GitHub 实时拉取 skills（默认仓库：`anthropics/skills`、`openai/skills`），若拉取失败会回退到本地 `--source-file`。
- `--extra-repos-file` 支持手工扩展仓库来源（例如 SkillBench 相关仓库），格式支持：
  - `{"repos":[{"repo_url":"https://github.com/<owner>/<repo>","paths":["skills","docs/skills"],"ref":"main","enabled":true}]}`
  - 或显式 `owner/repo` 字段：`{"owner":"<owner>","repo":"<repo>","paths":["skills"]}`
- 可用 `--save-live-snapshot` 将本次实时拉取内容写回本地快照，便于复现。

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
