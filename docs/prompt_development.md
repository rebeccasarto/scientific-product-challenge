# Prompt-development evidence

## Baseline and final prompts

The supplied prompts were run unchanged first. The resulting baseline planner,
report, and reviewer decision are retained under `results/baseline/`.

| Prompt | Problem observed in baseline | Final change | Evidence of improvement |
|---|---|---|---|
| Planner | The free-form plan proposed scope beyond a rapid, reproducible workflow. | Constrained the planner to the two PK candidates, three prespecified covariates, efficacy/safety endpoints, and conservative dosing policy. | `results/final/planner_output.json` validates that exact scope before analysis starts. |
| Scientific reviewer | The baseline review surfaced valid diagnostic and traceability concerns, but the earlier workflow could override a revise decision. | The reviewer now reviews evidence first and a revised report second; findings are not silently converted to approval. | The orchestrator test verifies exactly one revision and re-review. |
| Report writer | The baseline report could overstate conclusions or imply dose escalation from single-dose exposure data. | Required evidence-traceable claims, explicit safety context, calibrated confidence, explicit critical flags, and `insufficient_evidence` when simulation is absent. | Final report validation checks diagnostic-flag inclusion and confidence language. |

## Final-prompt evaluation

- **Scientific correctness:** prompts prohibit translating exposure variation
  into unsupported dose changes and require critical diagnostic limitations.
- **Decision usefulness:** prompts require an explicit overall recommendation
  while preserving `insufficient_evidence` for the upper-weight subgroup.
- **Partner readability:** the report prompt limits unnecessary methodology
  while requiring efficacy, safety, and uncertainty context needed to interpret
  the recommendation.

## Material coding-agent prompts

These are the implementation prompts that materially changed the submission.

1. “Implement one- and two-compartment individual PK fitting with a
   cohort-level, data-driven selection rule and preserve selection evidence in
   the analysis summary.”
   - Result: paired AICc evidence and the 65% cohort threshold are recorded in
     `analysis_summary.json`.

2. “Build conservative covariate and exposure-response rules: never invent a
   subgroup dose when exposure-matching simulation was not performed.”
   - Result: material weight effects produce `insufficient_evidence`, not an
     unsupported numeric dose.

3. “Use OpenRouter with schema-validated agent outputs, one bounded retry, and
   JSONL audit logging for every attempt.”
   - Result: `agents/llm_client.py` writes token, outcome, model, and error
     metadata to `logs/llm_calls.jsonl`.

4. “Make a reviewer revision request operational: regenerate the report once,
   re-review it, and prevent release when critical diagnostics remain.”
   - Result: the orchestrator now has a bounded review/revision/re-review path
     and the release decision contains unresolved diagnostic and simulation
     risks.

## Spend accounting

`results/final/spend_report.json` is generated from committed JSONL usage.
It uses the listed $1/M input and $5/M output prices for
`anthropic/claude-haiku-4.5` from OpenRouter’s
[pricing page](https://openrouter.ai/anthropic/claude-haiku-4.5/pricing).
The report is deliberately labelled an estimate because the logs do not carry
OpenRouter invoice identifiers, provider routing, or cache accounting.
