---
skill_id: "pdf-table-to-structured-extraction"
display_name: "PDF Table to Structured Extraction"
task_id: "sales-pivot-analysis"
family: ["document_extraction"]
artifacts: ["pdf", "xlsx"]
tools: ["pdf", "python"]
operations: ["extract", "transform"]
granularity: "compositional"
confidence: 0.95
source_urls: ["https://github.com/Baskar-forever/TableExtractor-Advanced-PDF-Table-Extraction/blob/main/README.md", "https://github.com/xavctn/img2table/blob/main/README.md"]
---
# PDF Table to Structured Extraction

## Summary
Extracting tabular data from PDF documents using OCR and morphological transformations, then converting the results into structured formats like Pandas DataFrames or Excel workbooks.

## Why kept
Recovered from prefilter because final reviewer kept too few candidates.

## When to use
Use this skill when the task requires artifacts pdf, xlsx, tools pdf, python, and operations extract, transform.

## Evidence
- Baskar-forever/TableExtractor-Advanced-PDF-Table-Extraction:README.md :: Features
  - https://github.com/Baskar-forever/TableExtractor-Advanced-PDF-Table-Extraction/blob/main/README.md
- xavctn/img2table:README.md :: Features <a name="features"></a>
  - https://github.com/xavctn/img2table/blob/main/README.md

