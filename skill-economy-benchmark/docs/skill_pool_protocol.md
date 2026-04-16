# Skill Pool 构建协议

**版本**：v1.0
**适用项目**：Agent Skill Benchmark 2.0 / SkillsBench 扩展研究
**状态**：Working Draft
**更新时间**：2026-04

---

## 1. 文档目的

本文档用于统一 Skill Pool 的构建方法，明确以下问题：

1. 为什么需要从原始 benchmark 的稀疏 task-skill 映射，扩展到可分析的 dense skill pool。
2. 如何根据 task 进行 retrieval，而不是仅靠表面文本相似度检索。
3. 如何结合 API 与 prompt engineering 生成、改写、压缩和过滤候选 skill。
4. 如何从候选池中选出真正用于评测的单 skill、组合 skill 和 full-pool 配置。
5. 如何控制成本、避免数据泄露，并保证后续 economy / effectiveness 指标具有可解释性。

本文档既作为项目内部协议，也作为后续论文 Method / Appendix 的基础版本。

---

## 2. 问题背景与动机

SkillsBench v1 证明了 curated skills 可以提升任务通过率，但其原始 task-skill 映射往往较为稀疏：

* 一些 task 只有 1 个 skill；
* 一些 skill 只出现在极少数 task 中；
* 很多 task 缺少足够的可替代 skill，难以比较“哪个 skill 更好”；
* Skill Combination Synergy（SCS）、Cross-Task Transferability（CTT）、Failure Mode Specificity（FMS）等高阶分析，在候选空间过小的情况下容易欠识别（under-identified）。

因此，本项目不把重点放在“训练一个 skill generator”，而是优先构建一个：

> **围绕 task family / capability schema 的、多来源、多粒度、可比较的 candidate skill pool。**

这样做的目标不是直接追求更高通过率，而是让 benchmark 可以回答以下更细致的问题：

* 什么样的 skill 更高效？
* 什么样的 skill 更容易跨任务迁移？
* 哪些组合具有正向协同，哪些组合存在冗余或冲突？
* 失败到底是缺少 skill，还是已有 skill 组合方式不合理？

---

## 3. 核心定义

### 3.1 Task

Task 指 benchmark 中的一个评测任务，通常包含：

* `instruction.md`：任务描述
* `task.toml`：元数据（领域、难度、超时时间等）
* `environment/`：容器环境、可用工具与 skills
* `tests/`：确定性 verifier
* `solution/`：参考解法（仅供离线分析，不直接暴露给生成过程）

### 3.2 Skill

Skill 是一种结构化的程序性知识封装，通常包含：

* `SKILL.md`：how-to guidance
* `scripts/`：可执行辅助脚本（可选）
* `references/`：参考文档（可选）

Skill 的目标不是提供任务答案，而是提供可复用、可迁移的操作方法。

### 3.3 Skill Pool

对每个 task (t)，我们构建一个 candidate skill pool：

[
P_t = {s_1, s_2, \dots, s_{|P_t|}}
]

其中，`P_t` 是围绕 task (t) 的候选 skill 集合。它不是最终评测配置，而是**候选空间**。

### 3.4 Evaluation Configuration

真正跑实验时，不是直接“跑整个 pool”，而是从 (P_t) 中定义若干配置：

[
\mathcal{A}_t \subseteq 2^{P_t}
]

典型配置包括：

* `No Skill`：不给任何 skill
* `Original Curated`：原 benchmark 自带的 curated skills
* `Single Skill`：从 pool 中挑出的单个 skill
* `Skill Combo`：从 pool 中挑出的少量组合
* `Full Pool`：把整个 (P_t) 提供给 agent

---

## 4. 总体流程概览

Skill Pool 构建分为两层：

### 第一层：构建层（Pool Construction）

1. Task 解析与标准化
2. Capability Schema 抽取
3. 多来源 candidate retrieval
4. API + prompt engineering 生成与改写 skill 候选
5. 结构检查、去重、反泄露过滤
6. 构建 family-level pool 与 task-level pool

### 第二层：评测层（Pool-Based Evaluation）

1. 从 pool 中选择单 skill / 组合 / full-pool 配置
2. 在多个模型和多次 repeat 下运行 benchmark
3. 计算 Pass Rate、TE、SRR、SUC、SCS、CTT、FMS
4. 分析 good skill 的结构特征与使用规律

---

## 5. Step 0：Task Family 归类

在 retrieval 之前，先不要把 task 视为完全独立的个体，而应尽量归纳其所属的 **task family**。

### 5.1 归类目标

Task family 的作用是：

* 扩大候选来源，而不是局限于完全相似的 task 文本；
* 让跨任务 procedural pattern 可以被共享；
* 为后续 CTT / SCS 分析提供更稳定的统计基础。

### 5.2 建议 family 粒度

示例：

* spreadsheet manipulation / spreadsheet analytics
* pdf extraction / document-to-structure
* debugging / CI repair / dependency fixing
* geospatial analysis
* scientific data processing
* web/content transformation
* planning / scheduling / workflow execution

### 5.3 归类方式

可采用以下混合策略：

1. 规则归类：根据 task 元数据、文件类型、主要工具、输出格式手工定义 family。
2. LLM 辅助归类：让模型根据 task schema 提议 family 标签，再人工审核。
3. 逐步修订：先得到粗 family，再在 pilot 实验后调整。

---

## 6. Step 1：Task 解析与 Capability Schema 抽取

### 6.1 为什么不能只靠文本相似度 retrieval

Task 与 skill 的相似性通常不体现在表面措辞，而体现在：

* 操作结构是否相似
* 使用的工具是否相似
* 输入 / 输出对象是否相似
* verifier 对结果的约束是否相似

因此，retrieval 的核心不应是：

> `task text -> embedding -> 找最像的 skill`

而应是：

> `task -> capability schema -> 多路召回 candidate skills`

### 6.2 建议抽取的 capability schema

对每个 task，抽取以下字段：

#### A. Artifact / 输入对象

* pdf
* xlsx
* csv
* codebase
* logs
* webpage
* image / video
* json / structured records

#### B. Core Operations / 核心操作

* extract
* transform
* aggregate
* validate
* debug
* search
* patch
* compare
* optimize
* summarize
* verify

#### C. Tooling / 工具环境

* shell
* python
* browser
* spreadsheet
* latex
* geospatial
* testing / CI
* database

#### D. Output Requirements / 输出要求

* exact numeric answer
* JSON
* patch / code diff
* completed spreadsheet
* structured report
* file update

#### E. Domain / 领域标签

* software engineering
* finance
* science
* office
* healthcare
* cybersecurity
* manufacturing

#### F. Constraints / 任务约束

* deterministic verifier
* exact format required
* no external internet
* timeout-sensitive
* multi-step workflow
* file-system mutation required

### 6.3 Schema 抽取实现建议

#### 方案 A：规则 + 轻量模型混合

* 规则系统先抽取文件类型、输出要求、可见工具
* 使用轻量模型补充高层标签（operations / domain / constraints）

#### 方案 B：直接 LLM 抽取结构化 JSON

让模型读取：

* `instruction.md`
* `task.toml`
* `tests/test_outputs.py` 的摘要
* 可见技能和工具信息

输出标准化 JSON，例如：

```json
{
  "task_id": "sales-pivot-analysis",
  "family": "spreadsheet_analytics",
  "artifacts": ["xlsx", "pdf"],
  "operations": ["extract", "aggregate", "validate"],
  "tools": ["spreadsheet", "python"],
  "output_type": "completed_spreadsheet",
  "domain": "office",
  "constraints": ["deterministic_verifier", "exact_format_required"]
}
```

### 6.4 注意事项

* 不要把完整 oracle 直接输入生成模型。
* tests 可用于理解 verifier 约束，但应只传“输出格式和关键检查维度的摘要”，避免答案泄露。
* schema 抽取过程应尽量稳定，可缓存中间结果。

---

## 7. Step 2：多来源 Candidate Retrieval

### 7.1 Retrieval 的设计原则

我们不把 retrieval 理解为“找文本最像的 skill”，而是理解为：

> **根据 capability schema，从多个来源召回可能有用、可比较、可扩展的候选 skill。**

### 7.2 候选来源

对 task (t)，定义：

[
P_t^{raw} = P_t^{orig} \cup P_t^{cap} \cup P_t^{cross} \cup P_t^{generic}
]

#### A. (P_t^{orig})：原始 curated skills

* 原 benchmark 中 task 自带的 skills
* 作用：保留与原论文的可比性

#### B. (P_t^{cap})：基于 capability schema 匹配的 skills

* 通过 artifact / operations / tools / output constraints 进行匹配
* 不要求 task 描述在表面文本上相似

#### C. (P_t^{cross})：跨 task / 跨 domain 的操作相似候选

* 来自其他 family，但操作流程相似
* 例如：

  * 文档抽取与日志抽取都属于“非结构化 -> 结构化”
  * CI 修复与数据管线修复都可能涉及“定位报错 -> 修改配置 -> 验证”

#### D. (P_t^{generic})：通用 procedural skills

* 如：

  * error diagnosis
  * result verification
  * spreadsheet sanity checks
  * step decomposition
  * file format validation

### 7.3 Retrieval 的具体实现建议

#### 第一阶段：规则召回（高 recall）

基于以下字段做粗召回：

* artifact overlap
* operations overlap
* tooling overlap
* output-type compatibility
* domain compatibility
* family compatibility

可以为每类字段设置简单权重，例如：

* family match: +3
* artifact match: +2
* operation match: +2
* tool match: +1
* output match: +2
* domain match: +1

得到一个初步候选集。

#### 第二阶段：语义召回（补充 recall）

对 task schema 摘要和 skill 摘要做 embedding / semantic search，补充可能被规则漏掉的候选。

> 推荐使用 embedding 做“补充召回”，而不是把它当作唯一依据。

#### 第三阶段：多样性约束（保证可分析性）

最终召回时，不应只保留“最像”的 skills，而应故意保留不同粒度的技能：

* 原子 skill（atomic）
* 通用 procedural skill（generic）
* 组合型 workflow skill（compositional）

这样后续 single-skill / combo-skill 分析才有意义。

### 7.4 Retrieval 的输出格式

建议每个 raw candidate 都附带如下元数据：

```json
{
  "skill_id": "xlsx_sanity_check",
  "source": "generic",
  "retrieval_path": ["family_match", "artifact_match", "semantic_search"],
  "estimated_granularity": "atomic",
  "estimated_domain_specificity": "low",
  "score": 8.7
}
```

---

## 8. Step 3：API + Prompt Engineering 生成候选 Skill

### 8.1 为什么还需要生成

仅做 retrieval 仍然不够，因为：

* 原始 benchmark 中 skill 数量有限；
* 召回来的 skill 未必适合当前 task family；
* 同一个 procedural pattern 往往需要更抽象、更简洁或更细粒度的变体；
* 后续分析需要不同风格、不同抽象层级的可比较候选。

因此，我们在 retrieval 之后加入 prompt-based candidate generation。

### 8.2 生成目标

生成的 skill 不应该是“任务答案”或“题解”，而应该是：

* 可复用
* 可迁移
* 程序性（procedural）
* 结构统一
* 长度可控
* 尽量少 task-specific 泄露

### 8.3 推荐生成的 skill 类型

#### A. 原子 skill（Atomic Skill）

只覆盖一个主要操作能力，例如：

* 从 PDF 中提结构化表格
* 检查 xlsx 的列类型与缺失值
* 解析 CI 日志中的依赖报错

#### B. 通用 procedural skill（Generic Procedural Skill）

偏方法论，例如：

* 修改代码后优先做最小验证
* 面对多文件输出先构造统一中间表示
* 结果计算前先做输入格式 sanity check

#### C. 组合型 workflow skill（Compositional Workflow Skill）

将 2–3 个步骤串起来，例如：

* 先抽取表格 -> 再做字段归一 -> 最后做统计计算
* 先定位依赖冲突 -> 再锁版本 -> 再重跑测试

### 8.4 生成 Prompt 设计建议

#### Prompt 输入建议包含

* task schema 摘要
* 当前 family 描述
* 检索到的 top-k candidate skill 摘要
* 本次生成的目标类型（atomic / generic / compositional）
* 统一的格式要求
* 反泄露约束

#### Prompt 输出要求

* skill 名称
* skill 摘要
* `SKILL.md` 正文
* 能力标签 / 使用场景
* 禁止包含：

  * task-specific 答案
  * 精确数值解
  * oracle 特有路径
  * 明显 task-only 文件名模式

### 8.5 推荐的 prompt 操作类型

不是只有“从零生成”，而是应该包括：

1. **Abstraction**：把已有 skill 改写得更抽象、更可迁移
2. **Compression**：把冗长 skill 压缩成更精炼版本
3. **Decomposition**：把大 skill 拆成原子 skill
4. **Composition**：把相关原子 skill 组合成 workflow skill
5. **Normalization**：统一 skill 风格、格式和结构

### 8.6 生成模型建议

当前项目不建议训练专门的 skill generator，而是采用：

* **较便宜模型**：用于 schema extraction、草稿生成、批量 rewrite
* **质量较高模型**：用于 final rewrite、格式修正、泄露检查

实践建议：

* draft generation：优先用成本低、上下文长的模型
* final polishing：可用更强的模型做少量精修

---

## 9. Step 4：Filtering、Dedup 与 Anti-Leakage

这是整个协议里非常关键的一步。candidate 数量多并不等于 pool 质量高。

### 9.1 过滤目标

* 去掉明显重复或近重复 skill
* 去掉 task-specific 泄露严重的 skill
* 去掉过长、过散、不可执行的 skill
* 给保留下来的 skill 打上统一标签，方便后续分析

### 9.2 结构合法性检查

检查：

* 是否存在 `SKILL.md`
* 是否符合统一 section 规范
* 是否包含可理解的步骤说明
* 是否缺少必要前提或输出说明

### 9.3 去重（Dedup）

建议混合使用：

* 标题/名字归一化匹配
* 摘要相似度
* embedding 相似度
* LLM 判定“是否语义等价 / 近重复”

去重不是只看文本完全相同，而是看：

> 是否提供了本质上相同的程序性指导。

### 9.4 Anti-Leakage 检查

需重点禁止以下内容：

1. 直接给出任务答案
2. 暴露 oracle 中专属的解决路径
3. 包含 task-specific 文件名、路径、常数、专有中间变量
4. 仅适用于单个任务实例而无迁移价值的提示

建议对每个 candidate 记录以下 leakage 标签：

* `none`
* `low`
* `medium`
* `high`

高风险 candidate 直接丢弃。

### 9.5 长度与风格归一化

为后续分析方便，建议控制：

* 过长 skill：压缩
* 过短且抽象不足的 skill：补全
* 格式不一致的 skill：统一模板

### 9.6 元数据标注

每个保留 skill 建议补充：

* `source_type`：orig / retrieved / generated / rewritten
* `granularity`：atomic / generic / compositional
* `domain_specificity`：low / medium / high
* `estimated_cost`：low / medium / high
* `leakage_risk`
* `family`
* `supported_artifacts`
* `supported_operations`

---

## 10. Step 5：构建 Family-Level Pool 与 Task-Level Pool

### 10.1 Family-Level Pool

先按 task family 建一个较大的 pool：

[
P_f = P_f^{orig} \cup P_f^{cross} \cup P_f^{generic} \cup P_f^{synth}
]

建议大小：

* family-level pool：10–30 个候选 skills

作用：

* 作为上层候选仓库
* 支撑跨 task / family 的迁移性分析

### 10.2 Task-Level Pool

从 family pool 中，为具体 task 选择较小的 task-level 子池：

[
P_t \subseteq P_f
]

建议大小：

* task-level pool：8–16 个候选 skills

其中应尽量平衡：

* 原子 skill
* 通用 procedural skill
* 组合型 skill
* 原始 curated skill

---

## 11. Step 6：从 Skill Pool 到 Evaluation Configurations

### 11.1 为什么不能把 pool 中所有组合都跑一遍

如果 task-level pool 有 8 个 skill：

* 单 skill：8 个
* 两两组合：(\binom{8}{2}=28)
* 三个一组：(\binom{8}{3}=56)

组合数会快速爆炸，导致成本不可控。

### 11.2 推荐的配置选择策略

对每个 task，建议只评测少量代表性配置：

#### 必选

1. `No Skill`
2. `Original Curated`
3. 若干 `Single Skill`
4. `Full Pool`（可选但强烈建议保留）

#### 协同分析时增补

5. 1–2 个 `Skill Combo`

### 11.3 推荐配置规模

对于 pilot 阶段，建议平均每个 task：

* 3–4 个单 skill
* 1–2 个组合
* 1 个 full pool

于是总配置数约为：

[
C_t = 1(\text{No Skill}) + 1(\text{Curated}) + m_t + p_t + 1(\text{Full Pool})
]

轻量版本可取：

* (m_t = 3)
* (p_t = 1)

较完整版本可取：

* (m_t = 4)
* (p_t = 1) 或 (2)

---

## 12. 推荐的 Prompt 模板族

建议在 `prompts/` 目录中维护以下模板：

### 12.1 `extract_task_schema.md`

用途：

* 将 task 原始描述转成 capability schema

输出：

* JSON schema

### 12.2 `generate_atomic_skill.md`

用途：

* 根据 task schema + retrieval candidates 生成原子 skill

### 12.3 `generate_generic_skill.md`

用途：

* 生成通用 procedural skill

### 12.4 `generate_compositional_skill.md`

用途：

* 生成 workflow 组合 skill

### 12.5 `rewrite_and_compress_skill.md`

用途：

* 将长 skill 压缩为短 skill
* 将 task-specific 写法改为更通用的写法

### 12.6 `leakage_check.md`

用途：

* 判断 skill 是否泄露任务特定答案 / oracle path

### 12.7 `dedup_check.md`

用途：

* 判断两个 skills 是否本质重复

---

## 13. 推荐目录结构

```text
skill-economy-benchmark/
├── dataset/
├── skill_pool/
│   ├── raw_retrieved/
│   ├── generated/
│   ├── filtered/
│   ├── task_pools/
│   └── metadata.json
├── prompts/
│   ├── extract_task_schema.md
│   ├── generate_atomic_skill.md
│   ├── generate_generic_skill.md
│   ├── generate_compositional_skill.md
│   ├── rewrite_and_compress_skill.md
│   ├── leakage_check.md
│   └── dedup_check.md
├── src/
│   ├── pool_builder/
│   │   ├── task_parser.py
│   │   ├── schema_extractor.py
│   │   ├── retriever.py
│   │   ├── generator.py
│   │   ├── filter.py
│   │   └── pool_manager.py
│   └── ...
└── docs/
    └── skill_pool_protocol.md
```

---

## 14. 成本控制建议

### 14.1 不建议训练专门的 retrieval / generation 模型

原因：

* 训练成本高
* 周期长
* 反馈信号昂贵（需要下游 benchmark 才能知道好坏）
* 容易把 benchmark 论文变成 generation / RL 方法论文

### 14.2 推荐做法

* retrieval 阶段：规则 + embedding + 少量语义召回
* 生成阶段：API + prompt engineering
* 终检阶段：少量高质量模型做精修和过滤

### 14.3 成本大头在哪里

通常：

* **skill pool 构建成本 << 下游 benchmark 评测成本**

因此，构建阶段应优先保证：

* 候选足够多
* 泄露风险可控
* 元数据完备

不必过度追求训练式检索模型。

---

## 15. 风险与边界

### 15.1 主要风险

1. **过度 task-specific**：生成的 skill 只对单 task 有效
2. **答案泄露**：skill 暗含 oracle 路径或任务特定中间变量
3. **近重复过多**：pool 很大但本质上没有信息增益
4. **组合爆炸**：评测时组合数失控
5. **指标自证**：用同一套指标构建和验证，导致循环论证风险

### 15.2 缓解原则

* retrieval 与 generation 目标以“可迁移性”和“多样性”为先，不以单 task 最优为唯一目标
* filtering 中严格执行 anti-leakage
* 评测时只选少量代表性组合
* 将指标分为：

  * **construction-time selection metrics**
  * **analysis-time evaluation metrics**

---

## 16. 实施建议（最小可行版本）

如果要快速落地，建议按以下 MVP 顺序实现：

### Phase 1：Schema + Retrieval

* 完成 task schema 抽取
* 建立 family 标签
* 实现原始 curated / cross-task / generic 三路召回

### Phase 2：Prompt Generation

* 先只生成：

  * atomic skills
  * generic procedural skills
* 暂不追求复杂组合 skill

### Phase 3：Filter + Pool

* 做去重、泄露检查、元数据标注
* 构建 task-level pool

### Phase 4：Evaluation

每个 task 先只评测：

* No Skill
* Original Curated
* 3 个 single skills
* 1 个 combo
* 1 个 full pool

在 pilot 阶段控制实验规模，后续再扩展。

---

## 17. 本协议的最终目标

本协议服务的不是“训练一个最强 skill 生成器”，而是：

> **把原本稀疏的 task-skill benchmark 扩展成一个可比较、可分析、可解释的 dense skill ecology。**

在此基础上，我们才能进一步回答：

* 什么样的 skill 是高性价比的？
* 什么样的 skill 具有更强的跨任务迁移能力？
* 什么样的组合真正产生正向协同？
* 失败应该通过补 skill 解决，还是通过改编排解决？

这也是 Skill Pool 构建协议的根本目标。
