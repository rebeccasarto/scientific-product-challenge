# Scientific Product and Agentic Analysis Challenge

**Time limit:** 2–4 hours from first commit to submission

## Goal

Build an agent-orchestrated PK/PD analysis workflow that turns synthetic immunotherapy data into a partner-ready dosing recommendation.

Use coding agents and LLMs as part of the implementation. The final system should combine quantitative analysis, scientific review, prompt design, and clinical translation.

Use whichever coding agent you work best with, including Cursor, Claude Code, or Codex.

## What you will build

Your workflow should:

- inspect the supplied synthetic PK/PD dataset
- select and fit appropriate PK and exposure-response models
- evaluate covariates and population variability
- produce diagnostics and dosing recommendations
- use LLM agents for planning, scientific review, and report synthesis
- revise analysis or reporting when review identifies a problem
- generate the final report, release decision, and run logs from code

Starter agent prompts are provided. Use, modify, or replace them as you judge appropriate.

## Required repository contents

- `README.md`: setup, execution, architecture, key decisions, and coding-agent usage
- `run_pkpd_analysis.py`: single entry point for the complete workflow
- `pipeline/`: analysis and orchestration code
- `agents/`: agent code, schemas, and final prompts
- `logs/`: model calls, agent decisions, revisions, failures, and iteration history
- `data/`: generated datasets
- `results/`: model outputs, diagnostics, generated report, and release decision
- `api/`: lightweight service for dosing recommendations
- `report.qmd`: report source
- rendered report in HTML or PDF
- `Dockerfile`
- `.env.example`

## Analysis requirements

The workflow should be data-adaptive rather than a fixed sequence.

Implement:

- exploratory data and quality assessment
- comparison of plausible PK models
- population variability and at least two covariates
- exposure-response analysis for efficacy and safety
- model diagnostics and uncertainty assessment
- subgroup-specific dosing recommendations where supported

Expected outputs include:

- final model equations and parameter estimates
- model-selection evidence
- goodness-of-fit diagnostics
- covariate effects
- exposure-response results
- dosing simulations or an equivalent quantitative justification
- confidence, limitations, and validation needs

## Agentic workflow requirements

Use separate agent responsibilities for at least:

- analysis planning
- scientific review
- partner-report synthesis

Agents should exchange structured, validated outputs. A reviewer decision must be able to trigger a bounded revision or rerun. Handle malformed model output or failed calls without an unbounded retry loop.

The workflow must generate:

- `results/baseline/`: report and reviewer decision from the supplied prompts
- `results/final/analysis_summary.json`
- `results/final/release_decision.json`
- the final rendered partner report under `results/final/`
- machine-readable run and decision logs

The generated release decision should state whether the package is ready to send, requires revision, or should be held.

## Prompt development

Initial prompts are provided in `prompts/`.

Treat them as production inputs:

- run the supplied prompts unchanged once before editing them
- preserve the baseline report and reviewer decision under `results/baseline/`
- inspect their effect on analysis and reporting
- move the final versions into `agents/prompts/`
- document the reasoning and evidence behind the final prompt choices
- preserve the final report and reviewer decision under `results/final/`

Evaluate the final prompts against scientific correctness, decision usefulness, and partner readability.

## Report requirements

The final report should include:

1. Executive recommendation
2. Analysis journey
3. PK/PD findings
4. Population and subgroup findings
5. Dosing recommendation
6. Diagnostics and uncertainty
7. Clinical implementation
8. Validation needs and limitations

The report should be usable by a pharma clinical-development team without reading the code or logs.

## API requirement

Build a lightweight API with:

- `POST /recommend`: accepts patient covariates and returns a dosing recommendation with uncertainty
- `GET /model-summary`: returns model parameters, fit evidence, and key population findings

Use validated request and response models with clear error handling.

## Data

The supplied `data/` directory contains:

- patient demographics and covariates
- concentration-time profiles
- longitudinal biomarkers
- clinical response and adverse-event outcomes

Analyze the supplied files as the baseline. You may generate additional data for sensitivity work, but preserve the supplied files and document material changes and assumptions.

## Execution

- One command must reproduce the complete workflow: `python run_pkpd_analysis.py`
- The analysis should complete in under 15 minutes after dependencies are installed.
- Commit generated model artifacts, diagnostics, logs, and the rendered report.
- Use the provided OpenRouter API key for LLM calls made by the workflow.
- Use an OpenAI or Anthropic Claude model available through OpenRouter.
- OpenRouter provides an OpenAI-compatible API at `https://openrouter.ai/api/v1`.
- Document all model/API spend.
- Keep paid model/API spend at or below **$20**.
- Do not commit credentials.

## Coding-agent usage

Document 3–5 prompts that materially affected your implementation or scientific analysis. Explain what changed as a result.

## Submission

- Create a private repository named `iollo-scientific-product-challenge-<your-name>`.
- Invite `daniollo`.
- Commit as you work; we review commit history.
- Send the repository URL when complete.
