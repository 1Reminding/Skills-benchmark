阶段 A：内部基线池

这是你现在已经在做的。

目的：

跑通整条 pipeline
先用 benchmark 内部已有 skill 做 baseline
知道 retrieval / scoring / pool selection 怎么工作

输出：

一个 internal candidate pool

也就是你现在看到的 task_pools/*.json。

阶段 B：外部扩充池

这才是你真正想要的 contribution。

目的：

去 benchmark 外部找“同类但细节不同”的 skill
再用 prompt engineering 改写成统一格式
构建更 dense 的 skill pool

输出：

一个 expanded / enriched skill pool

这一步才会真正增加“可比较 skill 数量”。

所以你现在的代码到底算什么

一句话：

现在的代码是在做“内部候选池构建”，不是在做“外部新 skill 发现”。

它的价值不是最终贡献本身，而是：

统一现有 skill
定义 task schema
验证 retrieval 逻辑
为后面的外部 skill 扩展打底

如果这一步不先做，后面你从外部找来一堆 skill，也没地方接、没法比较、没法过滤。

你说得对：真正想扩 skill，确实应该去外部找

这个方向是对的。
而且我也认同：

如果目标是“解决 task 对应 skill 太少”，仅靠 benchmark 内部互相调 skill 是不够的。

所以后面一定要引入外部来源。

但外部 retrieval 不应该直接“临时联网乱搜”

更合理的做法是：

先建立一个“外部 skill source corpus”

来源可以是：

1. 官方文档 / cookbook / how-to

比如：

pandas / openpyxl / pdfplumber / geopandas 官方文档
pytest / uv / GitHub Actions 相关文档
各类 tutorial / best practice guide
2. 高质量开源仓库中的 docs / examples

不是整个 repo 全吃，而是重点抓：

README
docs/
examples/
usage guides
3. benchmark 同类任务的经验型操作模板

比如：

PDF 表格抽取流程
spreadsheet sanity check
CI log triage
dependency debugging checklist
geospatial distance workflow
外部 retrieval 的正确目标，不是“找答案”，而是“找程序性方法”

也就是说，你们想找的是这类内容：

怎么从 PDF 抽表
怎么做表格验证
怎么 debug CI
怎么验证输出
怎么处理 geospatial 数据
怎么进行 workflow decomposition

而不是：

这个 task 的具体答案
这个 task 的标准解
直接针对 benchmark task 的泄露解法
所以后面真正该新增的不是改现在的 06/07，而是再加两层
新增层 1：外部语料收集 / 标准化

建议新脚本：

scripts/05_build_external_skill_corpus.py

它做的事情：

从你们选定的外部来源收集 skill-like 文本
统一切成 skill 候选单元
标准化成和 skill_registry.json 类似的 schema

输出：

data/external_skill_corpus.json

每条长这样：

{
  "skill_id": "external_pdf_table_extraction_v1",
  "source_type": "external_corpus",
  "source_url": "...",
  "family": ["document_extraction"],
  "artifacts": ["pdf"],
  "operations": ["extract", "transform"],
  "tools": ["pdf", "python"],
  "summary": "Use pdfplumber to extract multi-page tables and normalize them into structured rows.",
  "raw_snippet": "...",
  "license_note": "..."
}
新增层 2：external retrieval

建议新脚本：

scripts/07b_expand_skill_pool_with_external.py

它做的事情：

输入：

task schema
skill_registry.json（内部 skill）
external_skill_corpus.json（外部语料）

输出：

每个 task 的 internal + external raw candidates

也就是说，这一步才开始真正把“外面找来的 skill”并入候选池。

新增层 3：prompt engineering 生成 / 改写

建议新脚本：

scripts/09_generate_candidate_skills.py

它做的事情：

输入：

task schema
internal top-k skills
external top-k snippets

然后让模型做：

abstraction
rewrite
compression
decomposition
composition

输出：

skill_pool/generated/<task>.json

这些才是你们真正“新造出来”的 skill 候选。

所以你现在看到“几乎完整的一版都出来了”，其实只是基础版完整了

你现在完成的是：

原始 benchmark skill
→ 统一 registry
→ 内部 retrieval
→ internal task pool

但你们真正想做的完整版本应该是：

原始 benchmark skill
→ 统一 registry

外部文档/仓库/指南
→ external skill corpus

task schema
+ internal registry
+ external corpus
→ retrieval

retrieved candidates
→ prompt engineering 改写/生成
→ final enriched skill pool
你现在最该怎么理解“当前代码的角色”

它不是白做的。
它的角色是：

1. 给你一个内部 baseline

你后面可以比较：

只用 internal pool
internal + external retrieval
internal + external + generation

这样论文里才有层次。

2. 给外部 skill 一个统一接入口

如果现在没有 registry/schema/pool 这套结构，后面外部找来的 skill 没地方挂。

3. 帮你发现 task schema / scoring / pool selection 的问题

这些问题一定要先在内部版本上调通，不然外部语料一加只会更乱。