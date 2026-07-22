# PK/PD Analysis: Immunotherapy Dosing Recommendation

An agent-orchestrated PK/PD workflow that converts the supplied synthetic
immunotherapy dataset into a partner-ready dosing recommendation.

## Quick start

Requires Python 3.9+ and an OpenRouter API key.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set OPENROUTER_API_KEY in .env
python run_pkpd_analysis.py
```

The single entry point performs data validation, PK model comparison,
covariate and exposure-response analysis, scientific review, report writing,
and release-decision generation.

## Verify

```bash
python -m pytest tests/ -v
```

The workflow writes these final deliverables under `results/final/`:

- `analysis_summary.json`
- `reviewer_decision.json`
- `release_decision.json`
- `partner_report.md`
- `report.html`
- `planner_output.json`
- `spend_report.json`

## API

```bash
uvicorn api.main:app --port 8000
```

Endpoints:

- `GET /model-summary`
- `POST /recommend`

Example request:

```bash
curl -X POST http://127.0.0.1:8000/recommend \
  -H 'Content-Type: application/json' \
  -d '{"weight_kg":75,"creatinine_clearance_ml_min":90,"genotype":"WT/WT"}'
```

## Docker

```bash
docker build -t pkpd-analysis .
docker run --rm --env-file .env pkpd-analysis python run_pkpd_analysis.py
docker run --rm -p 8000:8000 pkpd-analysis
```

The image includes pinned Quarto so the complete workflow can render HTML.
The `.env` file is excluded from the Docker build context; pass it only at run
time when executing OpenRouter calls.

## Architecture

- `pipeline/` — deterministic PK/PD analysis and diagnostics
- `agents/` — OpenRouter planning, scientific review, and report synthesis
- `api/` — FastAPI recommendation service
- `results/` and `logs/` — generated evidence, decisions, reports, and audit logs

## Key decisions

- PK candidates are fit on log-concentration residuals; model selection is
  cohort-wide.
- Weight, creatinine clearance, and genotype are evaluated as pre-specified
  covariates.
- Efficacy and safety exposure-response models inform dosing decisions.
- A material covariate effect without exposure-matching simulation produces
  `insufficient_evidence`, never an invented numeric dose.
- Agent outputs are schema-validated, retried at most once, and checked by
  deterministic reviewer and report validators.

## LLM configuration and spend

The workflow uses OpenRouter's OpenAI-compatible API and requires
`OPENROUTER_API_KEY`. Usage metadata is recorded in `logs/llm_calls.jsonl`;
do not commit `.env` credentials. Each workflow run writes a conservative
list-price estimate to `results/final/spend_report.json`; it is based on token
usage, not an invoice, and documents the price source and $20 challenge cap.

## Coding-agent usage

See [prompt-development evidence](docs/prompt_development.md) for the
baseline/final prompt comparison, four material coding-agent prompts, their
implementation outcomes, and the evidence used to evaluate final prompts.
