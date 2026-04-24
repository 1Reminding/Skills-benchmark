---
skill_id: "excel-workflow-data-verification"
display_name: "Excel Workflow Data Verification"
task_id: "weighted-gdp-calc"
family: ["spreadsheet_analytics"]
artifacts: ["xlsx"]
tools: ["python", "spreadsheet"]
operations: ["extract", "verify"]
granularity: "compositional"
confidence: 0.8
source_urls: ["https://github.com/RayCarterLab/ExcelAlchemy/blob/main/examples/README.md", "https://github.com/RayCarterLab/ExcelAlchemy/blob/main/examples/fastapi_reference/README.md"]
---
# Excel Workflow Data Verification

## Summary
Verify data existence and integrity during spreadsheet import/update workflows, ensuring that row-level operations are correctly tracked and reported in a structured format.

## Why kept
Recovered from prefilter because final reviewer kept too few candidates.

## When to use
Use this skill when the task requires artifacts xlsx, tools python, spreadsheet, and operations extract, verify.

## Evidence
- RayCarterLab/ExcelAlchemy:examples/README.md :: Recommended Reading Order
  - https://github.com/RayCarterLab/ExcelAlchemy/blob/main/examples/README.md
- RayCarterLab/ExcelAlchemy:examples/fastapi_reference/README.md :: `POST /employee-imports`
  - https://github.com/RayCarterLab/ExcelAlchemy/blob/main/examples/fastapi_reference/README.md

