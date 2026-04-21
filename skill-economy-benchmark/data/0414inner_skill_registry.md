最好的开始方式是做一个能跑通的、可解释的 MVP retrieval：

task schema 抽取 → 规则召回 → embedding 补召回 → 输出 top-k 候选 skill

这一步做出来，你们后面再接 prompt engineering 生成 skill pool 就顺了。

你现在最该做的版本

我建议你第一版 retrieval 只做这 4 件事：

1. 先把每个 task 变成 schema

不要直接拿 instruction.md 去做相似度检索。
先把 task 解析成一个结构化对象，比如：

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

你第一版甚至可以先手工写 5~10 个 task 的 schema，不一定一开始就自动抽。

2. 再把每个 skill 也做成 schema

对每个 skill 也做类似的 registry，例如：

{
  "skill_id": "xlsx_sanity_check",
  "source": "generic",
  "family": ["spreadsheet_analytics"],
  "artifacts": ["xlsx"],
  "operations": ["validate", "clean"],
  "tools": ["spreadsheet", "python"],
  "domain_specificity": "low",
  "granularity": "atomic",
  "summary": "Check spreadsheet schema, missing values, column types, and basic consistency."
}

这里最关键的是：

artifacts
operations
tools
family
granularity
summary
3. 先做规则召回，不要先做学习式 retrieval

第一版直接写一个 scoring function：

score(t,s)=3⋅1[family match]+2⋅∣artifact overlap∣+2⋅∣operation overlap∣+1⋅∣tool overlap∣+1⋅1[domain compatible]
score(t,s)=3⋅1[family match]+2⋅∣artifact overlap∣+2⋅∣operation overlap∣+1⋅∣tool overlap∣+1⋅1[domain compatible]

你不需要完全照这个公式，但建议权重大概这样分：

family 匹配最重要
artifact / operation 次重要
tools / domain 稍弱

然后对每个 task，把所有 skills 打分，取 top-k。

4. embedding 只做“补召回”或“重排序”

不要一开始把 retrieval 变成“纯 embedding 相似度”。
更稳的是：

规则召回 top-20
对这 top-20 再做 embedding rerank
最后取 top-8 / top-10

这样不会被表面文本相似度带偏。

你现在就能落地的实现顺序
Phase A：先做最小闭环

选 5 个 task，选 20~30 个 skills，先不求全。

建议你先挑这些任务试：

sales-pivot-analysis
weighted-gdp-calc
fix-build-agentops
latex-formula-extraction
earthquake-plate-calculation

因为它们 family 差异比较大，容易看出 retrieval 是否靠谱。

Phase B：先建两个文件
文件 1：data/task_schemas.json

先手工写 5~10 个 task schema。

文件 2：data/skill_registry.json

把你们已有的 skill 全部做成结构化 registry。

这一版完全可以先半手工，不要一开始追求自动抽取全量 84 个任务。

Phase C：写一个最简 retriever

建议你先写：

src/pool_builder/retriever.py

最小接口：

def retrieve_candidates(task_schema, skill_registry, top_k=10):
    ...
    return ranked_skills

输出格式建议这样：

[
  {
    "skill_id": "xlsx_sanity_check",
    "score_rule": 8,
    "score_embed": 0.71,
    "final_score": 8.71,
    "retrieval_path": ["family_match", "artifact_match", "operation_match"]
  }
]
我建议你第一版只做 3 类候选

不要一开始把 pool 来源搞太复杂。
先召回这三类就够了：

1. original curated

task 原本自带的 skill

2. capability-matched

按 family / artifact / operation 匹配来的候选

3. generic procedural

人工准备一小批通用 skill，比如：

error diagnosis
result verification
spreadsheet sanity check
file format validation
step decomposition

这三类已经够你做第一轮 retrieval 了。

你现在别做的事
1. 不要先做 PPO

现在完全没必要。
因为你连“好 retrieval 长什么样”都还没定义清楚，PPO 只会让你更难 debug。

2. 不要先追求自动抽 84 个 task schema

先做 5~10 个能跑通再扩。

3. 不要先生成大量新 skill

你现在第一步是先把 候选召回 做稳。
生成应该接在 retrieval 后面，而不是前面。

4. 不要先做所有组合分析

retrieval 阶段只负责给出好的候选 skill，不负责组合爆炸问题。

你现在最实用的工作拆分
第一步：整理输入

今天就能开始做：

手工给 5 个 task 写 schema
手工给 20~30 个 skill 写 registry
第二步：实现规则打分

写一个最简单的检索器：

family match
artifact overlap
operation overlap
tool overlap

先不加 embedding 都可以。

第三步：人工看 top-k 是否合理

这一步特别重要。
你们不是先看数值，而是先看：

top-5 里有没有明显不相关的
有没有该召回但没召回的
generic skill 会不会压过 task-relevant skill
cross-task 候选是不是有点意思
第四步：再加 embedding rerank

等规则版 top-k 看起来“基本靠谱”，再加 embedding 做辅助。

我建议你第一周就做出这 3 个产物
产物 1：task_schemas.json

至少 5 个 task

产物 2：skill_registry.json

至少 20~30 个 skill

产物 3：retrieval_results.json

长这样：

{
  "sales-pivot-analysis": [
    "xlsx_basic_ops",
    "spreadsheet_sanity_check",
    "pdf_table_extraction",
    "result_verification",
    "table_aggregation_workflow"
  ]
}

只要这三个东西出来了，你们 retrieval 就算真正开始了。

一个很实际的建议：先别让 LLM 决定一切

最稳的做法是：

schema 抽取：可以部分用 LLM
retrieval 主体：先规则化
rerank：再加 embedding
candidate 扩展：后面再上 prompt engineering

这样你每一步都知道在干什么，不会黑箱。

如果你问“我现在第一行代码该写什么”

我会建议你按这个顺序：

文件一
src/pool_builder/schema_types.py

定义两个 dataclass / pydantic model：

TaskSchema
SkillSchema
文件二
src/pool_builder/retriever.py

先写：

score_rule(task, skill)
retrieve_candidates(task, skills, top_k=10)
文件三
scripts/build_initial_retrieval.py

作用：

读取 task_schemas.json
读取 skill_registry.json
跑 retrieval
输出 retrieval_results.json

你们现在的做法，精简但具体地总结一下
第 1 步：扫描原始 skill 目录

代码：

scripts/06_build_skill_registry_from_dataset.py

做的事情：

扫描 dataset/<task>/environment/skills/<skill>/SKILL.md
读取每个原始 skill
自动抽取结构化字段，比如：
skill_id
summary
family
artifacts
operations
tools
granularity
domain_specificity

生成的文件：

1. data/skill_registry.raw.json
一条记录 = 一个 task 下出现的一次 skill occurrence
用来保留最原始的扫描结果，便于 debug 和追溯
2. data/skill_registry.json
去重聚合后的统一 registry
retrieval 真正使用的输入文件
你们现在已经有 7 条聚合 skill，可以直接进入下一步。
3. data/skill_registry.review.json
不是主数据，而是人工检查提示
用来标记：
短 summary
metadata 稀疏
可疑 artifacts
多文本版本合并
你现在这份 review 已经开始正常工作。
第 2 步：统一 skill 表示

逻辑上你们现在已经完成了这个转换：

原始 SkillsBench task 内 skills
→ 扫描与标准化
→ 统一 skill registry

这一步的意义是：

不再每次 retrieval 都去 task 目录临时扫 skill
后续 retrieval 只读一个统一表
便于跨 task 检索、去重、调试
第 3 步：下一步进入 retrieval

代码：

scripts/07_build_skill_pool_retrieval_v2.py

它应该做的事情是：

从 dataset_index.json 和 task 文件中构建 TaskSchema
从 data/skill_registry.json 读 SkillSchema
按 capability overlap 做 retrieval
输出每个 task 的候选 skill pool

你后面应该得到这类文件：

1. skill_pool/raw_retrieved/<task>.json
原始候选
按来源分 bucket，比如：
orig
cross
generic
external
2. skill_pool/task_pools/<task>.json
平衡后的 task-level candidate pool
这是后面做 single / combo / full-pool 配置的基础
3. skill_pool/metadata.json
整体 manifest
记录本次 retrieval 的参数和输出位置
你现在的逻辑闭环

一句话版：

dataset/<task>/environment/skills/
→ 06_build_skill_registry_from_dataset.py
→ data/skill_registry.json
→ 07_build_skill_pool_retrieval_v2.py
→ skill_pool/task_pools/<task>.json
→ 后续再做 prompt generation / filtering / experiment configs