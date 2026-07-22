# PK/PD Analysis: Immunotherapy Dosing Recommendation

An agent-orchestrated PK/PD analysis workflow that turns synthetic
immunotherapy trial data into a partner-ready dosing recommendation. Combines
quantitative pharmacometric analysis, a two-stage covariate/exposure-response
workflow, and a three-agent LLM pipeline (planner, scientific reviewer,
report writer) with deterministic safety nets around the LLM-generated
outputs.

## Setup

Requires Python 3.9+.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY (see "LLM configuration" below)
```

## Execution

Single entry point, runs the full analytical pipeline and saves
`results/final/analysis_summary.json`:

```bash
python3 run_pkpd_analysis.py
```

Run the full agent pipeline (reviewer + report writer) on top of the
analysis:

```bash
python3 agents/orchestrator.py
```

Run the API (requires `results/final/analysis_summary.json` to exist):

```bash
uvicorn api.main:app --port 8000
```

Run the full test suite:

```bash
python3 -m pytest tests/ -v
```

## LLM configuration

This project calls an LLM through OpenRouter's OpenAI-compatible API
(`https://openrouter.ai/api/v1`), using `OPENROUTER_API_KEY`,
`OPENROUTER_BASE_URL`, and `OPENROUTER_MODEL` from `.env`. Default model is
`anthropic/claude-3.5-haiku`, chosen for low cost given this workflow makes
several structured calls per run.

**Local dry-run fallback:** `agents/llm_client.py` includes a clearly-marked
fallback (`_client_and_model()`) that calls OpenAI directly if
`OPENROUTER_API_KEY` is unset but `OPENAI_API_KEY` is — used only for local
development/testing when an OpenRouter key wasn't yet configured. It prints
an explicit warning to stderr whenever triggered and shares the identical
client, retry, and logging code path as the OpenRouter integration; only the
base URL, key, and default model name differ. It is commented for removal
before a production/graded run using the real OpenRouter key.

## Architecture

pipeline/ Deterministic analytical modules (no LLM calls)
data_loading.py Load + lightly type the three input CSVs and metadata
validation.py Data-quality gate: duplicates, joins, schedules,
endpoint consistency, site consistency (hard-fails on
real errors, warns on soft issues)
endpoints.py Derive analysis-ready endpoints (grade>=2 AE, week-12
biomarker reduction, biomarker AUC/slope)
eda.py Lightweight descriptive plots (concentration-time,
covariate distributions, biomarker trajectories)
pk.py Fit 1- vs 2-compartment PK models per patient (log-
residual weighted least squares), select ONE
cohort-wide structural model by a >=65% majority-
evidence rule (not per-patient), report population
parameters as median/IQR
covariates.py Screen weight, creatinine clearance, and genotype
(allele-count encoded) against CL/V; flags an effect
"clinically material" only if its CI excludes zero
AND it implies >=20% change across the covariate's IQR
exposure_response.py Fit efficacy (clinical_response) and safety
(grade>=2 AE) logistic models against per-patient
AUC = dose/CL, univariate and weight-adjusted
diagnostics.py Aggregate convergence, parameter validity, and a
patient-level aggregate predictive check (median of
per-patient predicted concentrations vs. median
observed, at nominal timepoints)
dosing.py RULE-BASED (no simulation) dosing recommendations;
"insufficient_evidence" and "no_subgroup_adjustment"
are first-class, deliberately reachable outcomes, not
fallbacks

agents/ LLM-calling agents and shared infrastructure
schemas.py Pydantic contracts for all inter-agent JSON payloads
llm_client.py Shared OpenRouter/OpenAI client: call_structured()
(schema-validated JSON, embeds the JSON schema in the
prompt, bounded retries) and call_text() (plain
markdown, same retry/logging pattern)
planner.py Pre-analysis planning agent (schema-validated plan,
not wired into pipeline execution — see "Key
decisions")
reviewer.py Reviews the AnalysisSummary for evidence soundness
BEFORE a report exists; includes a deterministic
post-review validator (validate_review_findings) that
auto-removes LLM findings factually contradicted by
the AnalysisSummary, and downgrades (not deletes)
interpretive confidence-calibration disagreements
report_writer.py Generates the partner-facing Markdown report;
includes a deterministic post-generation validator
(validate_report) checking diagnostic-flag inclusion
and confidence-language calibration, with ONE bounded
regeneration attempt if violations are found
orchestrator.py Thin sequencing: run_reviewer() (evidence gate) ->
run_report_writer() (report-level validation/
regeneration happens internally)
prompts/ FINAL prompts (iterated from the supplied baseline;
see "Prompt development" below)

prompts/ SUPPLIED baseline prompts, run unchanged for the
results/baseline/ capture (never modified)

results/
baseline/ Baseline planner/reviewer/report-writer outputs using
the unmodified supplied prompts, plus baseline EDA
final/ Final analysis_summary.json, reviewer_decision.json,
partner_report.md, and report.html (rendered from
report.qmd via Quarto)

api/ FastAPI service: POST /recommend, GET /model-summary.
Loads results/final/analysis_summary.json ONCE at
startup (via a lifespan hook) and serves rule-based
lookups against it — no pipeline rerun per request,
no live simulation.

logs/ Machine-readable run logs: llm_calls.jsonl (every LLM
call, tokens, success/failure), reviewer_overrides.jsonl
(deterministic finding removals), report_validation.jsonl
(report validator outcomes), revision_cycles.jsonl
(reviewer -> report sequencing)


## Key decisions

**Two-stage approximation, not full NLME.** PK/PD parameters are fit
per-patient (8 concentration timepoints each, IV bolus, single 100 mg dose),
then summarized at the population level by median/IQR. A full nonlinear
mixed-effects model was judged disproportionate to this challenge's scope and
runtime budget; this simplification is stated explicitly in
`AnalysisSummary.limitations` and in the partner report itself, rather than
hidden.

**Cohort-wide PK structural model, not per-patient.** Even though ~33% of
patients showed individual statistical support for a 2-compartment structure,
the whole cohort uses ONE structural model (1-compartment, selected because
2-compartment support fell short of a pre-specified 65% majority threshold).
Mixing structural models across patients would make covariate and
exposure-response comparisons incoherent. This tradeoff has a real,
documented consequence: the population-average predictive check does not
pass at every timepoint (see `diagnostics.critical_flags`) — this is
disclosed, not concealed, throughout the pipeline and report (see
"Known limitations" for how this finding is characterized).

**Fitting objective: log-concentration residuals, not raw weighted least
squares.** PK measurement error is typically proportional to concentration.
An earlier weighted-least-squares approach (weights = 1/predicted^2) was
replaced with log-residual fitting after reviewing that it produced an
inconsistency between the fitting objective and the AICc-based model
comparison; log-residual fitting is self-consistent for both.

**Materiality gate, not significance alone.** A covariate effect is only
treated as "clinically material" (and only then eligible for a dosing
recommendation beyond "no adjustment") if its 95% CI excludes zero AND it
implies at least a 20% change in the PK parameter across the covariate's
interquartile range. Statistically significant but small effects
(creatinine clearance, genotype) are explicitly tested, found non-material,
and reported as such — not silently omitted. This directly addresses a
failure mode observed in the SUPPLIED baseline planner prompt, which
instructs selecting dosing rules from "statistically significant" covariates
alone (see "Prompt development").

**Dosing engine never fabricates a specific alternative dose from a
covariate effect alone.** Where a covariate effect is material (weight, on
both CL and V), the dosing engine returns `insufficient_evidence` rather
than inventing a new mg value — translating a covariate effect into a
specific alternative dose requires exposure-matching simulation, which this
two-stage analysis does not perform. `null` recommended_dose_mg is the
deliberately correct output here.

**Deterministic checks layered on top of LLM judgment, not instead of it.**
Reviewer and report-writer prompts were iterated multiple times against
real analysis output. Some LLM miscalibrations (e.g. conflating "the
diagnostic flag is mentioned but I claim it's not addressed" — a factual,
checkable error) proved resistant to further prompt wording changes. Rather
than continuing to iterate prompts indefinitely, small deterministic
post-generation validators (`validate_review_findings`,
`validate_report`) were added to catch objectively-checkable failure modes
(fact contradiction, banned confidence-inflating language, missing
diagnostic-flag mentions), while leaving genuinely interpretive judgments to
the LLM. This is documented in detail under "Prompt development."

**Planner is evaluated, not pipeline-driving.** The `pipeline/` modules were
built directly from PK/PD domain practice, not generated from the planner
agent's output. `run_planner()` exists, is schema-validated, and its
baseline output was compared against what the pipeline actually tested
(confirming reasonable alignment — the planner independently named renal
function and genotype as expected covariates, both of which the pipeline
does test). This is a deliberate, disclosed scope decision given the time
budget, not an oversight: a fully planner-driven pipeline (where the
planner's JSON output determines which analysis code paths execute) was out
of scope for this timeframe.

## Prompt development

The three prompts in `prompts/` (supplied, unmodified) were run once against
this project's real pipeline output and saved to `results/baseline/` before
any editing, per the challenge's requirements.

**Baseline reviewer**: approved the real `AnalysisSummary` with zero findings
across two independent baseline runs, on both occasions without engaging
with the known predictive-check failure and, on one run, mischaracterizing
`no_subgroup_adjustment` conclusions as "backed by statistically significant
covariate effects" — collapsing the distinction between "found significant"
and "found material enough to act on" that the underlying analysis
deliberately preserves.

**Baseline report writer**: omitted the safety exposure-response finding
entirely, used "robust efficacy evidence" for a recommendation whose own
`confidence` field was "moderate," and introduced "younger or heavier
subgroups" — age was never a tested covariate. This is a clear factual
hallucination, not a tone issue.

**Final reviewer** (`agents/prompts/scientific_reviewer.md`) was rewritten
across four iterations, each addressing a specific documented failure from
the previous round:
1. Corrected the mismatched output schema (baseline `<output_format>` didn't
   match this project's actual `ReviewerDecision` fields) and reframed the
   role (reviewing `AnalysisSummary`, not rendered report text).
2. Added explicit rules that "insufficient_evidence" is a valid conclusion
   and that non-significant results are not the same as absent evidence —
   this iteration OVERCORRECTED, producing findings that treated an honestly-
   reported non-significant safety result as a defect requiring "more
   evidence."
3. Added explicit rules that moderate confidence is compatible with a
   maintain-dose recommendation under specific, stated conditions, and that
   revision should not be requested merely because more evidence would be
   desirable — this iteration eliminated the overcorrection but surfaced an
   evidence-conflation bug (a finding borrowed "exploratory" language from
   the covariate section and applied it to an unrelated recommendation).
4. Added an explicit evidence-isolation rule (evaluate each recommendation
   only against its own supporting fields). This resolved the conflation
   bug but still, on the next live run, produced one finding that repeated
   the already-addressed moderate-confidence tension and one finding that
   was internally self-contradictory (acknowledged a flag was mentioned,
   then claimed it wasn't accounted for).

Given that four rounds of increasingly precise prompt wording did not
reliably eliminate factually-checkable errors, a **deterministic
post-review validation layer** (`validate_review_findings` in
`agents/reviewer.py`) was added instead of a fifth prompt iteration. It
auto-removes findings that are factually contradicted by the
`AnalysisSummary` (e.g. claiming a mentioned flag is unaddressed, claiming
efficacy/safety evidence is absent when both exist) and downgrades (rather
than deletes) genuinely interpretive confidence-calibration disagreements.
On the subsequent live run, the LLM reviewer approved cleanly on its own,
with the deterministic layer available as a backstop rather than needed as
a correction.

**Final report writer** (`agents/prompts/report_writer.md`) was similarly
rewritten to require: exact preservation of `insufficient_evidence` /
`no_subgroup_adjustment` terminology (not softened paraphrases), explicit
statement of the confidence level with no stronger language than it
supports, mandatory inclusion of both efficacy and safety findings, and
"higher exposure" (not "higher dose" or "increasing dose," since only one
dose was studied) when describing the exposure-response relationship. Live
testing still showed a residual gap — "robust" appearing in the confidence
section despite an explicit prompt rule against it, and the specific
diagnostic flag being generically summarized rather than stated — so a
**deterministic post-generation validator** (`validate_report`) was added,
with ONE bounded regeneration attempt if violations are found (satisfies the
challenge's "handle malformed model output... without an unbounded retry
loop" requirement). On the next live run, the first attempt failed both
checks, the bounded regeneration correctly triggered, and the regenerated
report passed cleanly.

**Key finding**: prompt-only calibration reliably fixes some classes of
LLM error (missing sections, wrong terminology, absent context) but is
demonstrably unreliable for others — particularly claims that are
objectively checkable against the input JSON (does this exact text appear;
does a banned word appear given a specific field value). Those checks were
moved into deterministic code rather than pursued through further prompt
iteration, which is a design conclusion this project treats as a genuine
result, not a shortcut.

## Coding-agent usage

Built primarily with Codex (via the Codex CLI/desktop tool), with Claude used
throughout for prompt drafting, critical review of Codex's output, and
architectural decisions before each Codex invocation.

Representative prompts that materially changed the implementation or
scientific analysis:

1. **PK fitting objective correction**: identifying that weighted least
   squares (fitting) and unweighted RSS (AICc calculation) were
   inconsistent, and requesting a full switch to log-concentration-residual
   fitting used consistently for parameter estimation, multistart selection,
   and AICc. Changed the model-selection split from 44.2% to 32.9%
   2-compartment support (same ultimate conclusion, more defensible method)
   and eliminated a physiologically implausible outlier volume estimate
   (31.2 L -> 8.6 L).
2. **Cohort-wide vs. per-patient structural model selection**: explicitly
   directing that per-patient model preference be used only as evidence for
   ONE cohort-wide structural choice, never allowing different patients to
   be modeled with different structures — this shaped the population
   parameter summary, the covariate analysis, and the predictive-check
   design that followed.
3. **Covariate materiality threshold**: requesting that "clinically
   material" require both statistical significance AND a >=20% predicted
   change across the covariate's interquartile range (not the full observed
   range, which is vulnerable to outliers), directly shaping which covariate
   effects the dosing engine is permitted to act on.
4. **Dosing engine never fabricates a dose from a covariate alone**: an
   explicit, repeatedly-enforced constraint that a material covariate effect
   produces `insufficient_evidence` (recommended_dose_mg=null), never a
   specific invented alternative dose — validated by unit tests asserting no
   test scenario causes dose fabrication.
5. **Deterministic reviewer/report validators**: after four rounds of prompt
   iteration failed to reliably eliminate factually-checkable reviewer and
   report errors, requesting small, narrowly-scoped deterministic Python
   validators (not a second LLM call) to catch fact-contradiction and
   confidence-language violations, with bounded (one-shot) regeneration —
   shaped the final reviewer/report-writer architecture more than any single
   further prompt edit would have.

## Known limitations

- Two-stage approximation, not full NLME population PK.
- Single studied dose level; no dose-proportionality assessment possible.
- Population-average predictive check does not pass at every nominal
  timepoint. This is potentially consistent with residual structural
  heterogeneity, including two-compartment behavior in some patients (~33%
  showed individual-level support for a 2-compartment structure), but this
  attribution is circumstantial — the diagnostic itself does not isolate
  which patients or mechanism drive the mismatch.
- Covariate effects are exploratory two-stage associations, not definitive
  population PK covariate effects.
- `agents/planner.py`'s output is evaluated against, but does not drive,
  the pipeline's actual analysis code.
- LLM reviewer/report-writer calibration is imperfect even after four
  rounds of iteration; deterministic validators catch specific,
  objectively-checkable failure modes but are not a general substitute for
  LLM judgment on genuinely interpretive questions.

## API spend

See `logs/llm_calls.jsonl` for a full per-call record (timestamp, agent,
attempt number, model, token counts, success/failure). Development calls in
this repository's history used the documented local fallback (see
`_client_and_model()` in `agents/llm_client.py`) because an OpenRouter key
was unavailable in this environment. The fallback shares the identical
client, retry, and logging code path as the OpenRouter integration — only
the base URL, key, and default model name differ. The OpenRouter integration
itself is fully implemented but was not live-tested in this environment;
spend tracking via the same log file applies identically once
`OPENROUTER_API_KEY` is set.
