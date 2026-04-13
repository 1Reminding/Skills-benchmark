# SkillsBench 原理、数据集、指标与我们的改进

**作者：** Qinghua Xing (xingqinghua@mail.nankai.edu.cn)
**日期：** 2026-04-12
**目标会议：** NeurIPS 2026 Datasets and Benchmarks Track

---

## 目录

- [一、SkillsBench v1 的原理](#一skillsbench-v1-的原理)
  - [1.1 核心概念：什么是 Agent Skill](#11-核心概念什么是-agent-skill)
  - [1.2 评测框架设计](#12-评测框架设计)
  - [1.3 数据集构成](#13-数据集构成)
  - [1.4 原版评测指标](#14-原版评测指标)
  - [1.5 关键实验结论](#15-关键实验结论)
  - [1.6 已知局限性](#16-已知局限性)
- [二、我们的改进与创新](#二我们的改进与创新)
  - [2.1 定位：从 "做没做对" 到 "做得好不好"](#21-定位从-做没做对-到-做得好不好)
  - [2.2 创新指标体系](#22-创新指标体系)
  - [2.3 对 SkillsBench v1 局限性的直接回应](#23-对-skillsbench-v1-局限性的直接回应)
  - [2.4 与 Related Work 的差异化定位](#24-与-related-work-的差异化定位)
- [三、Target NeurIPS 的论文思路](#三target-neurips-的论文思路)
  - [3.1 论文标题候选](#31-论文标题候选)
  - [3.2 故事线（Story Line）](#32-故事线story-line)
  - [3.3 核心实验设计](#33-核心实验设计)
  - [3.4 预期 Contribution 清单](#34-预期-contribution-清单)
- [四、NeurIPS 投稿 TODO](#四neurips-投稿-todo)

---

## 一、SkillsBench v1 的原理

### 1.1 核心概念：什么是 Agent Skill

SkillsBench (Li et al., 2025, arXiv:2602.12670) 首次将 **Agent Skill** 定义为一种模块化的程序性知识封装。一个 Skill 是一个结构化的文件夹，包含：

```
skill-name/
├── SKILL.md      # 程序性指导（"怎么做"，而非"是什么"）
├── scripts/      # 可执行脚本（可选）
└── references/   # 参考文档（可选）
```

Skill 的核心定义满足四个标准：
1. **程序性内容**：包含 how-to 指导，而非事实检索
2. **任务类适用性**：适用于一类问题，而非单个实例
3. **结构化组件**：包含 SKILL.md 文件 + 可选资源
4. **可移植性**：基于文件系统，可在不同的 Agent harness 间共享

这一定义明确排除了：系统提示词、Few-shot 示例、RAG 检索结果、工具文档。Skill 独特地结合了**模块化封装 + 程序性指导 + 可执行资源 + 跨模型可移植性**。

### 1.2 评测框架设计

SkillsBench 基于 Harbor 框架构建，采用容器化评测：

```
评测条件（3种）：
  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
  │  No Skills   │   │ Curated      │   │ Self-Gen     │
  │  无 Skill    │   │ Skills       │   │ Skills       │
  │  (基线)      │   │ 人类策划     │   │ 模型自生成    │
  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
         │                  │                  │
         └──────────┬───────┴──────────┬───────┘
                    ↓                  ↓
              Docker 容器           Docker 容器
              (隔离执行)           (隔离执行)
                    ↓                  ↓
              确定性验证器          确定性验证器
              (pytest断言)         (pytest断言)
                    ↓                  ↓
              Pass / Fail          Pass / Fail
```

核心设计特点：
- **三条件对比**：同一任务在 No Skills / Curated Skills / Self-Generated Skills 下分别评测
- **确定性验证**：所有任务都通过 pytest 断言验证，不使用 LLM-as-Judge
- **容器隔离**：每次执行在独立 Docker 容器中运行
- **多模型多 Harness**：测试了 7 种 Agent-Model 配置（Claude Code + 4 个 Claude 模型、Gemini CLI + 2 个 Gemini 模型、Codex CLI + GPT-5.2）

### 1.3 数据集构成

**规模：**
- 84 个任务，横跨 11 个领域
- 来自 105 位贡献者的 322 个候选任务，经严格筛选
- 总计产生了 7,308 条有效轨迹

**领域分布：**

| 领域 | 任务数 | 代表性任务 |
|------|--------|-----------|
| 软件工程 | ~15 | fix-build-agentops, fix-erlang-ssh-cve |
| 金融 | ~8 | weighted-gdp-calc, financial-modeling-qa |
| 自然科学 | ~10 | earthquake-plate-calculation, gravitational-wave-detection |
| 医疗健康 | ~5 | lab-unit-harmonization |
| 制造业 | ~6 | manufacturing-fjsp-optimization |
| 网络安全 | ~7 | suricata-custom-exfil, dapt-intrusion-detection |
| 能源 | ~5 | energy-ac-optimal-power-flow |
| 办公 | ~10 | sales-pivot-analysis, exceltable-in-ppt |
| 媒体 | ~6 | video-silence-remover, speaker-diarization-subtitles |
| 数学 | ~5 | lean4-proof |
| 机器人 | ~4 | virtualhome-agent-planning |

**难度分层（基于人类完成时间）：**

| 难度 | 比例 | 人类时间 |
|------|------|---------|
| Core | 19.8% | < 60 分钟 |
| Extended | 50.0% | 1-4 小时 |
| Extreme | 30.2% | > 4 小时 |

**质量控制流程：**
1. 结构验证：文件完整性、TOML 语法
2. Oracle 执行：参考方案必须 100% 通过测试
3. 指令质量：人类撰写检测（GPTZero + 人工审核）
4. 泄露审计：AI Agent 自动检测 Skill 是否包含直接答案
5. 人工审核：数据有效性、任务真实性、Oracle 质量、Skill 质量、反作弊

### 1.4 原版评测指标

SkillsBench v1 使用两个指标：

**1. Pass Rate（通过率）**
```
Pass Rate = (1/N) × Σ_{i=1}^{N} (1/K) × Σ_{k=1}^{K} I(task_i, trial_k)
```
其中 N=84（任务数），K=5（每个任务重复 5 次），I 是指示函数。

**2. Normalized Gain（归一化增益）**

借鉴物理教育研究中 Hake (1998) 的公式：
```
g = (pass_skill - pass_vanilla) / (1 - pass_vanilla)
```
衡量 Skill 在"剩余可改进空间"中的改进比例。

**局限：** 这两个指标都只衡量"对不对"，完全不涉及"代价多大"和"为什么错"。

### 1.5 关键实验结论

SkillsBench v1 的 7 个核心发现：

| # | 发现 | 数据支撑 |
|---|------|---------|
| F1 | 策划 Skill 带来显著但不均匀的提升 | +16.2pp 平均，范围 +13.6pp 到 +23.3pp |
| F2 | Gemini CLI + Flash 达到最高性能 | 48.7% with Skills |
| F3 | 自生成 Skill 基本无效 | -1.3pp 平均 |
| F4 | Skill 收益因领域差异巨大 | 医疗 +51.9pp vs 软工 +4.5pp |
| F5 | 2-3 个 Skill 最优 | +18.6pp，4+ 仅 +5.9pp |
| F6 | 简洁 Skill 优于全面 Skill | Detailed +18.8pp，Comprehensive -2.9pp |
| F7 | 小模型 + Skill 可匹敌大模型裸跑 | Haiku+Skill(27.7%) > Opus-noSkill(22.0%) |

### 1.6 已知局限性

SkillsBench v1 论文明确承认的不足（引自其 Section 5.1）：

1. **覆盖范围**：仅评测终端类容器化任务，不涉及 GUI 交互、多 Agent 协作、超长流程
2. **因果归因不足**：Skill 注入增加了上下文长度，观测到的增益可能部分来自"更多上下文"而非"程序性结构"
3. **缺乏成本分析**：论文在 Figure 4 中展示了 Pareto 图但没有系统化的成本指标
4. **缺乏失败诊断**：只有 pass/fail，不区分"缺 Skill"和"Skill 组合不当"
5. **缺乏 Skill 组合分析**：论文提到"future work should study Skills composition"但未实现
6. **Benchmark vs Ecosystem gap**：只测试了高质量 Skill（质量分 10.1/12），未反映生态系统真实质量（6.2/12）

---

## 二、我们的改进与创新

### 2.1 定位：从 "做没做对" 到 "做得好不好"

我们的核心观察：

> 在实际 Agent 部署中，同样成功完成任务的两个 Agent，如果一个消耗了 150 tokens / 2 步完成，另一个消耗了 5000 tokens / 20 步完成，它们的"成功"含义是完全不同的。Pass Rate 无法区分这种差异。

类比：如果 Pass Rate 是大学入学考试的"是否及格"，我们引入的经济性指标就是"考了多少分"，有效性指标就是"每道题的分析报告"。

### 2.2 创新指标体系

#### 经济性指标（Economy Metrics）—— "代价有多大"

| 指标 | 数学定义 | 衡量什么 | 为什么是创新 |
|------|---------|---------|------------|
| **Token Efficiency (TE)** | `I(success) / total_tokens` | 每 token 的产出效率 | SkillsBench 只统计了 token 数量（Figure 4），但未定义系统化的效率指标 |
| **Step Redundancy Rate (SRR)** | `max(0, (steps - optimal) / optimal)` | 相对于最优方案多走的弯路 | SkillsBench 完全没有步骤级分析 |
| **Skill Utilization Cost (SUC)** | `Σ cost(skill_i)` | 所有 Skill 调用的加权总成本 | 首次为每个 Skill 定义调用成本，支持成本敏感的 Pareto 分析 |

#### 有效性指标（Effectiveness Metrics）—— "为什么对/错"

| 指标 | 数学定义 | 衡量什么 | 为什么是创新 |
|------|---------|---------|------------|
| **Skill Combination Synergy (SCS)** | `P(success \| combo) - mean(P(success \| single_i))` | Skill 组合的协同效应 | 直接回应 SkillsBench 的 Future Work: "study Skills composition" |
| **Cross-Task Transferability (CTT)** | `\|{t: success with skill s}\| / \|{t: used skill s}\|` | 单个 Skill 的跨任务通用性 | SkillsBench 只做单任务分析，我们引入跨任务视角 |
| **Failure Mode Specificity (FMS)** | 分类为 Missing / Bad Combo / Success | 失败原因的精确诊断 | SkillsBench 只有 pass/fail，我们提供可操作的改进建议 |

### 2.3 对 SkillsBench v1 局限性的直接回应

| SkillsBench v1 的局限 | 我们的回应 | 论文引用 |
|----------------------|-----------|---------|
| "缺乏成本分析" | 引入 TE + SRR + SUC 三个经济性指标 | §5.1, Figure 4 |
| "缺乏失败诊断" | 引入 FMS，区分 Missing Skill vs Bad Combination | §5.1 |
| "缺乏 Skill 组合分析" | 引入 SCS 组合协同指标 | §5.1 "future work should study Skills composition" |
| "因果归因不足" | SRR 通过与 optimal_steps 比较，部分解耦 "更多上下文" vs "更好程序" | §5.1 |
| "Only terminal tasks" | 我们的指标框架是 modality-agnostic 的，可扩展到 GUI/多模态 | §5.1 |

### 2.4 与 Related Work 的差异化定位

| 方向 | 代表工作 | 评估什么 | 我们的差异 |
|------|---------|---------|-----------|
| Agent 能力评测 | AgentBench, SWE-bench, Terminal-Bench | Agent 裸能力 | 我们评测 **Skill 增强的效率和诊断** |
| 工具使用评测 | ToolLLM, Toolformer | 工具选择的正确性 | 我们不仅评价"用对了没"还评价"用得划不划算" |
| 成本优化 | FrugalGPT, RouterBench | 模型路由的成本 | 我们聚焦 **Skill 层面** 的成本，而非模型选择 |
| 多维评估 | MMLU, BIG-bench | 能力的多维分解 | 我们分解的维度是 **经济性+有效性**，而非知识类别 |
| SkillsBench v1 | Li et al. 2025 | Skill 是否有用 | 我们评价 Skill **有多有用**、**代价多大**、**为什么失败** |

---

## 三、Target NeurIPS 的论文思路

### 3.1 论文标题候选

1. **"Beyond Pass/Fail: Economy and Effectiveness Metrics for Agent Skill Evaluation"**（推荐）
2. "SkillBench 2.0: How Much Does It Cost When Agent Skills Work?"
3. "Measuring the Price of Skill: An Economic Evaluation Framework for LLM Agent Augmentation"

### 3.2 故事线（Story Line）

```
Hook:
  "Agent Skills 被证明能提升 16.2pp 的通过率（SkillsBench, 2025），
   但两个同样成功的 Agent 可能消耗了 10x 不同的 tokens。
   现有基准完全无法区分这种差异。"

Gap:
  "现有评测只关注 binary outcome，忽略了：
   (1) 成本效率 —— 同样完成任务，代价可以相差数量级
   (2) 失败诊断 —— 失败是因为缺 Skill 还是 Skill 组合不当？
   (3) 组合效应 —— Skill 之间是协同还是冲突？"

Method:
  "我们提出 6 个新指标（3 Economy + 3 Effectiveness），
   在 SkillsBench 的 84 个任务上扩展评测框架。
   我们的框架是 modality-agnostic 的，可迁移到任意 Agent 系统。"

Key Results:
  "(1) 经济性：Agent 之间的 Token Efficiency 可相差 5-10x
   (2) 冗余性：平均 38% 的步骤是冗余的
   (3) 诊断：60% 的失败是 Bad Combination 而非 Missing Skill
   (4) 协同：2-3 个 Skill 组合产生正向协同，4+ 个开始冲突
   (5) 迁移：通用 Skill (xlsx, pdf) 的 CTT > 0.8, 领域 Skill < 0.5"

Impact:
  "这套框架让 Skill 的评估从 '有没有用' 进化到 '怎么用最好'，
   为 Skill 选择、编排和优化提供数据驱动的决策支持。"
```

### 3.3 核心实验设计

#### 实验 1：经济性分析（对应论文 Section 4.1）

**目标：** 证明 Pass Rate 不足以评价 Skill 效果

| 对比维度 | 方法 |
|---------|------|
| 同任务不同 Agent | 在每个任务上对比 7 种 Agent-Model 配置的 TE/SRR/SUC |
| 同 Agent 不同 Skill 条件 | 对比 No Skill / Curated / Self-Gen 三个条件下的经济性 |
| 成本-效果 Pareto 前沿 | 用 TE 和 SUC 构建成本-效果 Pareto 图（升级 SkillsBench Figure 4） |

预期发现：
- 通过率相同的 Agent，TE 可以相差 5-10x
- Self-Generated Skills 虽然通过率低，但步骤冗余率更高（Agent "摸索"式执行）
- 存在"Sweet Spot"：最优成本效益点不一定是最高通过率

#### 实验 2：有效性诊断（对应论文 Section 4.2）

**目标：** 证明 FMS 诊断对 Skill 改进有实际指导价值

| 对比维度 | 方法 |
|---------|------|
| 失败模式分布 | 对全部失败轨迹分类，统计 Missing vs Bad Combination 比例 |
| 领域差异 | 按 11 个领域统计失败模式，发现领域特异性 |
| 改进验证 | 对 Bad Combination 类失败，重新设计 Skill 编排后验证是否改善 |

预期发现：
- 软件工程领域：失败主要是 Bad Combination（Skill 可用但编排不当）
- 医疗/制造领域：失败主要是 Missing Skill（缺少关键领域知识）
- FMS 诊断可以直接指导 Skill 改进方向

#### 实验 3：Skill 组合与迁移分析（对应论文 Section 4.3）

**目标：** 证明 SCS 和 CTT 提供了 SkillsBench v1 完全缺失的视角

| 对比维度 | 方法 |
|---------|------|
| 组合协同曲线 | 绘制 SCS vs Skill 数量的曲线，验证 v1 的 "2-3 最优" 发现 |
| Skill 通用性热力图 | 绘制每个 Skill × 每个领域的 CTT 热力图 |
| 组合推荐 | 基于 SCS 数据，构建 "最优 Skill 组合推荐" |

预期发现：
- 通用 Skill（如 xlsx, pdf 处理）CTT > 0.8，领域 Skill < 0.5
- 最优组合不一定是"所有可用 Skill 都用上"，与 v1 Finding 5 一致
- SCS 可以预测组合效果，为自动 Skill 选择提供依据

### 3.4 预期 Contribution 清单

NeurIPS Datasets and Benchmarks Track 的审稿标准对照：

| NeurIPS 标准 | 我们如何满足 |
|-------------|-------------|
| **Novelty of the dataset/benchmark** | 首个将经济性和有效性维度引入 Skill 评测的框架 |
| **Usefulness** | 6 个指标均可直接用于 Agent 开发者优化 Skill 策略 |
| **Quality and rigor** | 基于 SkillsBench 的 84 个任务 + 7,308 轨迹，统计检验充分 |
| **Clarity of documentation** | 完整的代码库 + 数学定义 + 可复现的 dry-run pipeline |
| **Broader impact** | 推动 Skill 评测从 "有没有用" 到 "怎么用最好"，降低 Agent 部署成本 |

---

## 四、NeurIPS 投稿 TODO

### 截止日期 & 里程碑

NeurIPS 2026 Datasets and Benchmarks Track 预计：
- **摘要截止：** 2026 年 5 月中旬
- **全文截止：** 2026 年 5 月下旬
- 当前日期：2026-04-12，**剩余约 5-6 周**

### 详细 TODO

#### Phase 1: 基础设施完善（4/12 - 4/19，第 1 周）

- [ ] **P1-1** 轨迹解析器：实现 `src/agents/trajectory_parser.py`，解析 Harbor 框架的 `acp_trajectory.jsonl` 文件为 `ExecutionTrace` 对象
- [ ] **P1-2** 真实 Agent 接入：在至少 2 个 Agent-Model 配置上运行全部 84 个 SkillsBench 任务，收集真实轨迹
  - 优先选择：Claude Code + Opus 4.5、Gemini CLI + Gemini 3 Flash（SkillsBench v1 表现最好的两个）
- [ ] **P1-3** 数据集扩展：将 `dataset/` 从 6 个任务扩展到全部 84 个任务的元数据索引
- [ ] **P1-4** 指标验证：在真实轨迹上运行所有 6 个指标，验证计算正确性和合理性

#### Phase 2: 核心实验（4/19 - 5/03，第 2-3 周）

- [ ] **P2-1** 实验 1（经济性分析）：在 7 个 Agent-Model 配置 × 3 个 Skill 条件下计算 TE/SRR/SUC
  - 产出：Table: TE/SRR/SUC across configurations；Figure: Cost-Effectiveness Pareto 图
- [ ] **P2-2** 实验 2（失败诊断）：对全部失败轨迹运行 FMS 分类
  - 产出：Table: Failure mode distribution by domain；Figure: Missing vs Bad Combo 比例柱状图
- [ ] **P2-3** 实验 3（组合与迁移）：计算 SCS 和 CTT
  - 产出：Figure: SCS vs Skill 数量曲线；Figure: CTT 热力图（Skill × Domain）
- [ ] **P2-4** 统计检验：对所有核心发现做 bootstrap confidence interval 或 paired t-test
- [ ] **P2-5** 可视化升级：实现论文级别的 matplotlib/seaborn 图表（配色、字体、分辨率符合 NeurIPS 模板）

#### Phase 3: 论文撰写（5/03 - 5/17，第 4-5 周）

- [ ] **P3-1** 论文框架：使用 NeurIPS 2026 LaTeX 模板搭建 8 页论文框架
- [ ] **P3-2** Section 1 (Introduction)：3 段式结构 —— Hook（Skill 有用但评测不够）→ Gap（缺乏经济性和诊断性指标）→ Our Contribution（6 个新指标 + 实证分析）
- [ ] **P3-3** Section 2 (Background & Related Work)：
  - 2.1 Agent Skill 的定义与生态系统
  - 2.2 现有 Agent 评测基准（AgentBench, SWE-bench, Terminal-Bench, SkillsBench）
  - 2.3 成本感知的 AI 评估（FrugalGPT, RouterBench, 计量经济学视角）
- [ ] **P3-4** Section 3 (Method)：
  - 3.1 问题形式化：ExecutionTrace 作为评测的基本单元
  - 3.2 经济性指标：TE, SRR, SUC 的数学定义和性质分析
  - 3.3 有效性指标：SCS, CTT, FMS 的数学定义和性质分析
  - 3.4 评测框架：TraceEvaluator 的设计与实现
- [ ] **P3-5** Section 4 (Experiments)：三个实验 + 发现总结
- [ ] **P3-6** Section 5 (Discussion)：局限性 + 未来工作
- [ ] **P3-7** Section 6 (Conclusion)：1 段总结
- [ ] **P3-8** Appendix：完整指标推导、额外实验、数据集详情

#### Phase 4: 润色与提交（5/17 - 5/24，第 6 周）

- [ ] **P4-1** 内部审核：请 2-3 位合作者/同事阅读并反馈
- [ ] **P4-2** 语言润色：确保英文写作质量
- [ ] **P4-3** 代码清理：确保 GitHub 仓库可直接 `pip install` + 复现全部结果
- [ ] **P4-4** Camera-Ready 准备：补充 checklist、ethics statement、reproducibility statement
- [ ] **P4-5** 提交

### 风险与备选方案

| 风险 | 概率 | 备选方案 |
|------|------|---------|
| 真实轨迹收集时间不够 | 中 | 使用 SkillsBench 已有的 7,308 条轨迹数据（如果公开可用），或减少到 3 个 Agent 配置 |
| API 成本过高 | 低 | 优先使用 Gemini Flash（最便宜），或只做 Core 难度任务（17 个） |
| 指标区分度不够 | 低 | 引入更细粒度的 Skill 成本模型（如基于 token 的动态成本而非固定 cost_per_call） |
| NeurIPS D&B 不接受纯指标工作 | 中 | 增加 "Skill Selection as Optimization" 应用场景，展示指标的实用价值 |
