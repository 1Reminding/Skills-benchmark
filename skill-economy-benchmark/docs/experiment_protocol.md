# 实验任务协议（Skill Pool 构建完成后）

**版本**：v1.0
**适用项目**：Agent Skill Benchmark 2.0 / Dense Skill Pool 实验
**状态**：Working Draft
**更新时间**：2026-04

---

## 1. 文档目的

本文档只回答一个问题：

> **在 Skill Pool 已经构建完成之后，实验到底应该怎么跑？**

本文档不讨论：

* Skill Pool 如何构建
* retrieval / prompt engineering 的实现细节
* 指标公式如何计算

本文档只聚焦于：

* 需要跑哪些实验条件
* 每个 task 应该测试哪些 skill configurations
* 哪些实验是必选，哪些实验是扩展项
* 不同阶段的实验规模如何控制
* 如何组织实验顺序，便于后续自动化或 vibe coding

---

## 2. 基本实验单位

在本项目中，真正的实验单位不是单纯的 task，也不是单纯的 skill，而是：

[
(task,\ model,\ configuration,\ repeat)
]

其中：

* **task**：一个 benchmark 任务
* **model**：一个评测模型（如 Gemini / Claude / GPT 系列）
* **configuration**：某种 skill 配置方式
* **repeat**：同一配置在同一 task 上的独立重复运行次数

因此，实验设计的核心不是“每个 task 有多少个 skill”，而是：

> **每个 task 最终要定义多少个可运行的 configuration。**

---

## 3. 配置层次定义

Skill Pool 构建完成后，对每个 task (t) 会得到一个候选池：

[
P_t = {s_1, s_2, \dots, s_{|P_t|}}
]

真正进入实验的不是整个构建流程，而是从 (P_t) 中选出的若干配置。

### 3.1 配置类型

#### A. No Skill

不给 agent 任何 skill。
作用：

* 作为最基本的 baseline
* 用于判断 skill 整体是否真的有帮助
* 作为后续“增益”解释的参考点

#### B. Original Curated

只给原 benchmark 自带的 curated skills。
作用：

* 保留与 SkillsBench 原始设定的可比性
* 作为“原始 benchmark 设定”对照组

#### C. Single Skill

从 task-level skill pool 中挑出若干单独的 skill，分别单独运行。
作用：

* 比较相似 skill 之间的效果差异
* 识别更高性价比、更高迁移性的 skill
* 为后续组合分析提供单体基线

#### D. Skill Combo

从 task-level skill pool 中挑出少量组合配置运行。
作用：

* 用于观察协同 / 冗余 / 冲突
* 为后续 SCS 类分析提供实验基础
* 检查组合是否优于最优单 skill

#### E. Full Pool

将整个 task-level skill pool 一次性提供给 agent。
作用：

* 观察 agent 在稠密候选空间中自主选择 skill 的能力
* 判断 dense pool 整体是否优于 original curated
* 更接近原始 SkillsBench 的 with-skills 设定

---

## 4. 每个 Task 的推荐实验配置

### 4.1 最小可行配置（MVP）

适用于第一轮 pilot：

1. `No Skill`
2. `Original Curated`
3. `Single Skill A`
4. `Single Skill B`
5. `Single Skill C`
6. `Skill Combo 1`
7. `Full Pool`

共 **7 个配置**。

推荐场景：

* 30 个任务的小规模 pilot
* 单模型实验
* 预算有限时的第一轮可行验证

### 4.2 平衡配置（推荐）

适用于主实验：

1. `No Skill`
2. `Original Curated`
3. `Single Skill A`
4. `Single Skill B`
5. `Single Skill C`
6. `Single Skill D`
7. `Skill Combo 1`
8. `Full Pool`

共 **8 个配置**。

推荐场景：

* 30–42 个任务
* 单模型或少量多模型
* 兼顾单 skill 差异分析与初步协同分析

### 4.3 强化配置（扩展）

适用于预算更充足、需要更完整协同分析时：

1. `No Skill`
2. `Original Curated`
3. `Single Skill A`
4. `Single Skill B`
5. `Single Skill C`
6. `Single Skill D`
7. `Skill Combo 1`
8. `Skill Combo 2`
9. `Full Pool`

共 **9 个配置**。

推荐场景：

* 42–56 个任务
* 重点分析协同、冗余和冲突模式

---

## 5. Single Skill 怎么选

### 5.1 原则

Single skill 配置的目标不是“穷举所有候选”，而是：

> **从 task-level pool 中选出足够有代表性的几个单 skill，形成可比较的候选集。**

### 5.2 推荐选择方式

对于每个 task，优先选择以下几类 skill：

1. **Original curated 中最关键的 1 个 skill**
2. **同能力但更抽象/更通用的 1 个 skill**
3. **跨任务迁移来的 1 个 cross-task skill**
4. **一个风格明显不同的 procedural / generic skill**

这样可以保证 single skill 实验具备：

* 原始对照
* 可迁移对照
* 风格差异对照
* 后续可分析性

### 5.3 不建议的做法

* 不要把 pool 中所有 single skills 全跑一遍
* 不要只选“看起来最强的”几个
* 不要把明显近重复的 skill 同时放入 single skill 实验

---

## 6. Combo 怎么选

### 6.1 为什么 Combo 不能全跑

如果一个 task-level pool 中有 8 个 skill：

* 单 skill：8 个
* 两两组合：28 个
* 三个一组：56 个

组合数会快速爆炸，成本完全不可控。

因此：

> **Combo 实验必须是有控制的、少量的、目的明确的。**

### 6.2 推荐的 Combo 选择原则

优先选择以下两类组合：

#### Combo 1：高互补预期组合

由两个功能互补、流程衔接清晰的 skill 组成。
例如：

* 抽取 + 校验
* 定位问题 + 修复问题
* 预处理 + 主分析

作用：

* 观察正向协同是否成立
* 判断组合是否优于最优单 skill

#### Combo 2：低互补 / 可能冗余组合（扩展项）

由两个功能重叠、风格接近、可能互相干扰的 skill 组成。
作用：

* 检查组合是否出现冲突或冗余
* 帮助分析“多 skill 不一定更好”的情况

### 6.3 Combo 的数量建议

* MVP 阶段：每个 task **1 个 combo**
* 主实验：每个 task **1–2 个 combo**
* 不建议超过 2 个，除非只在少量 family 上做专门协同实验

### 6.4 Family-Level Combo 分析

不是所有 task 都必须做 combo。

更合理的做法是：

* 对所有 task 保留少量 combo
* 对那些明显适合多步协作的 task family 再做更细的协同实验

适合重点做 combo 的 family 包括：

* spreadsheet analytics
* document extraction + transformation
* debugging / CI repair
* scientific workflow tasks

---

## 7. 为什么每个配置要重复运行

### 7.1 原因

即使在 temperature=0 的情况下，agent benchmark 仍然存在运行波动，包括：

* 工具调用路径差异
* 长上下文下的行为波动
* 超时与偶发失败
* 多步流程中的中间状态不稳定
* 对同一 skill configuration 的非完全确定性响应

因此：

> **单次运行不能稳定代表一个配置的真实性能。**

### 7.2 推荐重复次数

#### Pilot 阶段

* 每个配置 **3 次 repeat**
* 适合控制预算，同时保留基本稳定性

#### 主结果阶段

* 关键主表、关键 family、关键模型可补到 **5 次 repeat**
* 与原 SkillsBench 主设定更接近

### 7.3 建议策略

优先采用：

* 大规模扫实验：`repeat = 3`
* 最终主结果复核：`repeat = 5`

这样既能控制成本，也能保证关键表格更稳。

---

## 8. 必做实验清单

以下实验建议视为**主实验必须完成**。

### 实验 1：No Skill vs Original Curated vs Full Pool

**目的**：回答 dense skill pool 整体是否有价值。
**配置**：

* No Skill
* Original Curated
* Full Pool

**作用**：

* 建立最基本的三组对照
* 判断 dense pool 是否整体优于原 benchmark 设定
* 验证构建 skill pool 的工程工作是否值得

---

### 实验 2：Single Skill Ranking

**目的**：比较同一 task 下不同 single skill 的差异。
**配置**：

* 3–4 个代表性 single skills

**作用**：

* 识别高效 skill 与低效 skill
* 为“什么样的 skill 是好 skill”提供最直接证据
* 为 combo 分析提供单体参照

---

### 实验 3：Combo vs Best Single

**目的**：验证 skill 组合是否真的产生协同。
**配置**：

* 1–2 个 combo
* 对应的单 skill 基线

**作用**：

* 观察组合是否优于最优单 skill
* 识别正向协同、冗余和冲突
* 支持后续组合分析

---

### 实验 4：Full Pool vs Selected Configurations

**目的**：比较“agent 自由选择”与“人选配置”的差异。
**配置**：

* Full Pool
* 若干 single skills
* 若干 combos

**作用**：

* 观察 agent 是否能在 dense pool 中做出有效选择
* 判断 full pool 是带来帮助还是引入噪声

---

## 9. 选做实验清单

以下实验不是第一阶段必做，但如果时间和预算允许，建议后续加入。

### 实验 5：Cross-Model Robustness

**目的**：检查 skill 配置在不同模型族上是否稳定。
**做法**：

* 先用 1 个模型完成主实验
* 后续在少量代表模型上复跑关键 task / configuration

推荐模型族：

* Gemini 系列
* Claude 系列
* GPT 系列

---

### 实验 6：Task Family Focused Combo Study

**目的**：在适合多 skill 协作的 family 上做更细粒度协同实验。
**做法**：

* 只挑 1–2 个 family
* 增加 combo 数量
* 更系统地比较正协同与负协同

---

### 实验 7：Ablation on Full Pool Size

**目的**：观察池子大小是否影响 full-pool 效果。
**做法**：

* small pool
* medium pool
* full pool

**作用**：

* 判断稠密候选空间是帮助 agent 还是干扰 agent

---

## 10. 推荐实验顺序（便于落地）

为方便工程实现，建议实验按以下顺序推进。

### Phase A：最小闭环

对少量 task 先跑：

1. No Skill
2. Original Curated
3. 3 个 single skills
4. 1 个 combo
5. Full Pool

目标：

* 验证实验脚本可运行
* 验证日志记录格式正确
* 验证基础配置集是可行的

### Phase B：全量单模型主实验

在完整 task 集上跑：

* No Skill
* Original Curated
* 3–4 个 single skills
* 1 个 combo
* Full Pool

目标：

* 得到第一版主结果
* 建立 task-level 的可比性分析

### Phase C：扩展与补强

在关键任务或关键 family 上额外跑：

* 第 2 个 combo
* repeat=5 的复核
* 第 2 / 第 3 个模型的对照

目标：

* 强化论文主结论
* 补充稳健性验证

---

## 11. 任务规模建议

### 11.1 30 个任务（轻量版）

适合：

* 单模型 pilot
* 第一轮 skill pool 可行性验证
* 控制预算

推荐配置：

* 3 个 single skills
* 1 个 combo
* 1 个 full pool
* repeat=3

### 11.2 42 个任务（推荐版）

适合：

* 单模型主实验
* 兼顾多 task family 与分析深度
* 预算与论文说服力之间较平衡

推荐配置：

* 4 个 single skills
* 1 个 combo
* 1 个 full pool
* repeat=3

### 11.3 56 个任务（强化版）

适合：

* 更接近 benchmark-level claim
* 后期增强版主实验

推荐配置：

* 4 个 single skills
* 1–2 个 combos
* 1 个 full pool
* repeat=3 或关键设置补 5

---

## 12. 推荐的最小自动化接口

为了方便后续 vibe coding，建议每个 task 的实验输入统一为一个配置文件，例如：

```json
{
  "task_id": "sales-pivot-analysis",
  "model": "gemini-3-flash-preview",
  "repeats": 3,
  "configurations": [
    {"type": "no_skill"},
    {"type": "original_curated"},
    {"type": "single", "skills": ["skill_a"]},
    {"type": "single", "skills": ["skill_b"]},
    {"type": "single", "skills": ["skill_c"]},
    {"type": "combo", "skills": ["skill_a", "skill_c"]},
    {"type": "full_pool"}
  ]
}
```

这样后续运行器只需要读取统一配置并调度即可。

---

## 13. 不建议的实验做法

1. **不建议一上来跑所有 skill**
   会导致实验规模失控，且很多候选并不值得单独测试。

2. **不建议穷举所有组合**
   组合数增长过快，成本不可控。

3. **不建议省掉 No Skill**
   没有 No Skill，就无法判断 skill 整体是否真的有帮助。

4. **不建议只跑 Full Pool**
   这样无法分析 single skill 的差异，也无法解释组合协同。

5. **不建议所有 task 都做同等密度的 combo 实验**
   combo 更适合在少量高价值 family 上重点展开。

---

## 14. 推荐的主实验模板

如果只保留一套最推荐方案，建议如下：

### 主实验模板

* 任务数：**42 个**
* 模型数：**先 1 个主模型**
* repeats：**3**
* 每 task 配置：

  * No Skill
  * Original Curated
  * 4 个 single skills
  * 1 个 combo
  * Full Pool

即每个 task：

[
1 + 1 + 4 + 1 + 1 = 8 \text{ configurations}
]

这个模板兼顾：

* baseline 对照
* 原始 benchmark 可比性
* 单 skill 差异分析
* 初步协同分析
* dense pool 整体效果分析

是当前阶段最适合落地的主实验版本。

---

## 15. 本协议的最终目标

本协议服务于以下实验目标：

1. 验证 dense skill pool 是否比原始稀疏 skill 设置更有价值
2. 比较相似 skill 之间的差异
3. 分析组合是否带来真正的协同
4. 观察 agent 在 full pool 条件下的自主选择能力
5. 为后续“好 skill 的结构特征”分析提供干净、标准化、可复现的实验结果

因此，实验设计的重点不是“跑得越多越好”，而是：

> **用最有代表性的配置，得到最可解释、最可比较的结果。**
