# Executive Pharmacokinetics & Pharmacodynamics Report

## Executive Recommendation

**Maintain the current 100 mg dose for the overall population.** Efficacy exposure-response is statistically significant (OR = 2.02 per SD AUC increase; 95% CI [1.44, 2.82]), and safety does not increase materially with higher exposures. 

**Critical caveat:** The PK model failed internal validation (patient-level predictions deviated >20% from observed medians at key timepoints). Confidence in this recommendation is **moderate**, and prospective confirmation is required before broad implementation.

---

## PK/PD Findings

**Pharmacokinetics:**  
A 1-compartment model fit all 240 patients. Population median clearance = 0.38 L/h (IQR 0.30–0.45); volume of distribution = 4.63 L (IQR 3.81–5.72). The more complex 2-compartment structure was not supported in ≥65% of the cohort (32.9% showed AICc advantage >4 points).

**Exposure-Response:**  
Higher AUC is associated with greater odds of clinical response across all univariate and weight-adjusted models (OR range 1.84–2.02 per SD AUC). Safety (grade ≥2 adverse events) shows no significant exposure-dependent increase; 95% confidence intervals include zero for both univariate and weight-adjusted analyses.

---

## Population Insights

**Body Weight (Clinically Material Effect):**  
Clearance increases ~30% and volume increases ~31% across the interquartile weight range (61.9–86.4 kg), following allometric scaling. This effect is statistically significant (*p* < 1×10⁻²⁹ for CL) and exceeds the prespecified ≥20% clinical-materiality threshold.

**Renal Function & Genotype (Not Material):**  
Creatinine clearance effect on clearance (9.3% across IQR) and genotype effect on clearance (9.9% homozygous wild-type vs. homozygous mutant) both fall below the ≥20% materiality cutoff and do not warrant dose adjustments.

---

## Dosing Recommendation

| Subgroup | Recommendation | Rationale |
|----------|---|---|
| **Overall population** | **100 mg** (maintain) | Positive efficacy signal; safety CI includes zero |
| **Upper weight quartile** | **100 mg pending simulation** | 30% CL increase detected; exposure-matching simulation needed to justify adjusted dose |
| **Renal function range** | **100 mg** (no adjustment) | 9.3% CL effect <20% threshold |
| **Genotype groups** | **100 mg** (no adjustment) | 9.9% CL effect <20% threshold |

---

## Clinical Implementation

- Initiate 100 mg as standard dose across all patients.
- Consider prospective exposure monitoring in patients >90 kg to confirm adequate AUC exposure.
- Renal function and genotype do not require pretreatment dose adjustment.
- A full nonlinear mixed-effects population PK model is recommended for future studies to confirm covariate effects and improve predictive accuracy.

---

## Confidence and Limitations

**Model Fit Issue:**  
The PK model failed a basic predictive check—patient-level aggregate median predictions deviated >20% from observed medians at scheduled timepoints. This indicates residual bias and suggests the model may underestimate exposure variability or fail to capture key kinetic features. Dosing recommendations should be treated as preliminary.

**Additional Constraints:**  
Analysis used two-stage covariate assessment rather than full NLME modeling; this approach is exploratory and does not establish definitive population PK relationships. The single 100 mg dose level precludes dose-proportionality assessment. Weight-driven dose adjustment for the upper quartile requires exposure-matching simulation before clinical implementation.

**Validation Required:**  
Prospective dose-confirmation study and full NLME population PK modeling are essential before adoption in a broad population.