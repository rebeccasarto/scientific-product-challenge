# Partner Decision Memo: 100 mg Immunotherapy Study

## Decision for today

Continue the current 100 mg dose for the overall study population. The data
support efficacy at observed exposure levels, and we did not identify a
statistically significant exposure-related safety signal. This is a
moderate-confidence, interim decision—not a basis for a broader dosing-label
change.

We should not introduce a weight-based dose adjustment at this stage. Weight
appears to affect clearance and volume, but the analysis does not yet include
exposure-matching simulations that would support a specific alternative dose.

## What supports that decision

- Higher AUC was associated with higher odds of clinical response (OR 2.02 per
  standard-deviation increase; 95% CI 1.44–2.82).
- The safety exposure-response estimate was not statistically significant (OR
  1.16; 95% CI 0.86–1.57).
- Renal function had a statistically detectable but small association with
  clearance (9.3% across its interquartile range). The estimated genotype
  effect on clearance was also small (9.9%) but was not statistically
  significant; genotype was statistically associated with volume. None of
  these findings met the pre-specified 20% threshold for clinical materiality,
  so no adjustment is recommended for either subgroup.

## What prevents release as a final decision package

One diagnostic result needs to be resolved before this work is presented as a
decision-ready release: patient-level aggregate median predictions were not
within 20% of observed medians at every scheduled timepoint. That failure does
not erase the observed efficacy signal, but it limits confidence in any
quantitative dosing claim.

The other release blocker is the weight finding. A roughly 30% estimated
change in clearance across the interquartile weight range is large enough to
investigate, but not enough to justify choosing a new dose without simulation.

## Proposed next step

Run a full population PK analysis and use it for exposure-matching simulations
in the upper-weight subgroup. We should return with a numeric dose option only
if the updated model passes its predictive checks and the simulated exposure
range can be tied to the observed efficacy and safety evidence. Otherwise, the
appropriate outcome is to retain 100 mg without weight stratification.

In parallel, confirm the overall 100 mg decision prospectively with exposure,
response, and adverse-event monitoring. The acceptance criterion is not simply
model convergence: predicted concentration summaries must adequately reproduce
the observed time-course, and any proposed subgroup dose must preserve the
exposure range supported by the current data.

## Quinn feedback loop

This run surfaced two product requirements that should become standard release
gates for future partner work:

1. A materially sized covariate effect cannot turn into a numeric dosing
   recommendation unless an exposure-matching simulation is present.
2. A failed predictive check must appear in the executive decision and block a
   `ready_to_send` release, even when the scientific reviewer finds the rest of
   the package internally consistent.

For the next iteration, I would add an explicit prompt and validator check for
simulation evidence, require the report to state diagnostic failures in its
opening recommendation, and capture the result as a reusable evaluation case.
That makes the delivery playbook safer while preserving a clear, useful answer
for the partner today.

## Delivery status

The current release status is **requires revision**. The linked analysis
summary, scientific review, release decision, and partner report provide the
supporting audit trail for this memo.
