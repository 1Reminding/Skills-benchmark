这份代码里“最不对劲的地方”

真正的问题主要在 6 个点。

1. 它把 required_skills 用得太重了

现在这份代码在 family 推断、tools 推断、operations 推断、cross-task 打分里，都大量依赖 required_skills。例如：

_infer_family() 直接看 required_skills
_detect_tools() 看 required_skills
_detect_operations() 看 required_skills
_score_cross_task_candidate() 还会因为 source_skill in target_schema.required_skills 给高分

这和我们现在的目标有冲突。

因为你们现在要解决的是：

原 benchmark 的 task-skill mapping 太稀疏，不应该再把原始 required_skills 当成 retrieval 的主要锚点。

否则你会得到一个循环：

task 原来有什么 skill
retrieval 又因为原来有这个 skill 给高分
最后 pool 还是围着原 curated set 打转

这样很难真正扩展候选空间。

2. cross 其实只是“从别的 task 里抄 skill 名字”

现在 cross_candidates 的来源是：

遍历其他 task
取它们的 required_skills
按 domain/tag/required_skill_match 打分

这意味着你召回的是skill 名字，不是 skill 的真正 schema、摘要、能力标签，也不是 skill 文本本身。

这会导致一个问题：

你得到的是“别的任务也有 xlsx / pdf / geospatial-analysis”，
但你没有真正比较这些 skill 在程序结构上是不是适合当前 task。

换句话说，这更像label transfer，不是我们定义的 retrieval。

3. external 这一路又退回到了 token overlap

你自己之前就担心过：纯文本相似度未必有用。
而这里 _score_external_candidate() 基本还是在做：

task schema 拼成一坨 text
candidate 的 name + description token 化
看 overlap 数量
再加一点 family bias

这就回到了你一开始担心的问题：
表面词重合，并不等于能力结构相似。

所以这部分最多只能当“弱补召回”，不能当 retrieval 主体。

4. 它还没有 skill schema / skill registry

现在代码里有 TaskSchema，但没有一个同等重要的 SkillSchema。
这点很关键。

我们刚刚讨论的 retrieval 其实应该是：

task_schema↔skill_schema
task_schema↔skill_schema

而不是：

task_schema↔skill_name
task_schema↔skill_name

现在这份代码里，skill 侧缺了这些核心字段：

family
artifacts
operations
tools
granularity
domain_specificity
summary

结果就是：task 解析得还可以，但 skill 侧还是“扁平的名字列表”。

5. 它直接把 orig/cross/external 合并成 final pool

代码最后直接：

orig
cross
external

全部 merge 成 candidate_pool 写出去。

这一步太早了。
因为在我们现在的协议里，中间还应该有：

normalization
dedup
leakage check
granularity tagging
source balancing
task-level selection

也就是说：

现在这个 task_pool 更像“raw merged candidates”，
还不是你们真正要用来做 single/combo/full-pool 实验的 final pool。

6. family / operation 推断过于硬编码，容易误判

像这类规则：

只要 xlsx 在 required_skills 里，就直接认为是 spreadsheet_analytics
只要有 software-engineering domain 就加 debug/patch
output_type 固定写成 file_update_or_exact_answer

这在 MVP 阶段可以接受，但还太粗。
因为你们后面要拿这些 schema 做 retrieval，schema 一旦偏，召回就会跟着偏。

所以它“哪里不太对”

一句话说：

它已经有“task schema + 多来源候选”的外壳，但 retrieval 的核心仍然太依赖原始 required_skills 和浅层 token overlap。

这和我们后来讨论出来的更合理方案相比，差在这几个层级：

你们现在真正想要的是
task family / capability schema
skill schema / skill registry
规则召回主导
embedding 只做补召回或 rerank
retrieval 后还有 filtering / dedup / leakage
最后才形成真正的 task-level pool
而这份代码现在做到的是
task schema：有了
skill schema：没有
规则召回：有，但 heavily biased toward required_skills
embedding / semantic：没有，external 只是 token overlap
filtering：没有
final pool：合得太早
我建议你现在怎么处理它
可以直接保留的部分

这些不用推倒：

文件整体结构
TaskSchema dataclass
main() 的输出组织
raw_retrieved/ 和 task_pools/ 的目录思路
argparse 入口
应该优先重构的部分

按优先级，我建议你先改这 4 块：

第一优先：补一个 SkillSchema

这是最关键的。

把 skill 从“名字”升级成结构化对象，例如：

@dataclass
class SkillSchema:
    skill_id: str
    source: str
    family: list[str]
    artifacts: list[str]
    operations: list[str]
    tools: list[str]
    granularity: str
    domain_specificity: str
    summary: str

没有这层，retrieval 永远会很虚。

第二优先：让 cross 走 skill schema，不走 required_skills 名字

不要再从其他 task 的 required_skills 直接取 skill 名字。
应该从一个统一的 skill_registry.json 里取完整 skill schema，然后按 capability 匹配。

第三优先：把 external 从 token overlap 改成“弱语义补召回”

现在 external 还是太 lexical 了。
第一版你可以先不接 embedding API，但至少要：

基于 skill schema 的 structured match 做主召回
external 那一路只做补充
别让它主导结果
第四优先：不要直接写 final task_pool

先只输出：

raw_orig
raw_cross
raw_external

然后单独再走一步：

normalize
dedup
filter
finalize

这样架构才对。