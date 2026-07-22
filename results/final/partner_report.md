# Executive PK/PD Report

## Executive Recommendation

**Maintain 100 mg dose in the overall population**, with validation required before broad implementation. The current dose is supported by positive efficacy exposure-response (OR=2.02 per SD increase in AUC), but the pharmacokinetic model failed internal predictive checks. Weight-stratified dosing shows promise but requires exposure-matching simulation before dosing guidance can be issued.

---

## PK/PD Findings

**Pharmacokinetics:**  
A 1-compartment model fit 240 patients (100% convergence). Population median clearance: 0.38 L/h (IQR 0.30–0.45); volume: 4.6 L (IQR 3.8–5.7).

**Critical Diagnostic Limitation:**  
Patient-level aggregate median predictions were not within 20% of observed medians at every scheduled timepoint. This failure indicates the model's predictive performance does not fully capture observed data patterns and constrains confidence in derived dosing recommendations.

**Exposure-Response (Efficacy):**  
Higher AUC is associated with increased clinical response rate (OR=2.02 per SD increase, 95% CI [1.44, 2.82]). Safety signal is absent (grade ≥2 adverse events show no significant AUC relationship; OR=1.16, 95% CI [0.86, 1.57]).

---

## Population Insights

**Weight Effect (Clinically Material):**  
Clearance increases ~30% across the weight interquartile range (allometric exponent 0.79, 95% CI [0.67, 0.91], p<0.001). Volume shows similar effect (~31%, exponent 0.80, p<0.001).

**Renal Function & Genotype (Not Material):**  
Creatinine clearance shows modest CL effect (~9% across IQR, p=0.0001), below the ≥20% clinical-materiality threshold. Genotype effect on CL (~10% difference wild-type to homozygous mutant) is not statistically significant (p=0.081).

---

## Dosing Recommendation

| Subgroup | Action | Dose | Rationale |
|----------|--------|------|-----------|
| Overall population | Maintain | 100 mg | Positive efficacy; no safety signal. Moderate confidence pending prospective confirmation and full NLME modeling. |
| Upper weight quartile | Under investigation | TBD | 30% CL increase identified. Exposure-matching simulation required before alternative dose can be specified. |
| Renal impairment | No adjustment | 100 mg | Effect magnitude (9%) does not meet adjustment threshold. |
| Genetic variants | No adjustment | 100 mg | Effect not statistically significant. |

---

## Clinical Implementation

1. **Immediate:** Continue 100 mg in routine use with heightened monitoring.
2. **For heavy patients:** Apply cautious upward dose titration if efficacy target is not met; do not apply fixed adjustment until validated.
3. **Validation pathway:** Conduct prospective dose-confirmation study using full population PK modeling to resolve model predictive shortfall.

---

## Confidence and Limitations

The recommendation for the overall population carries **moderate confidence** because efficacy exposure-response is positive and safety is not compromised; however, the model's failure to predict observed median concentrations at all timepoints introduces structural uncertainty that cannot be ignored. Weight-based dosing is low-confidence pending simulation. This analysis used two-stage covariate association, not full NLME; single-dose level prevents assessment of dose proportionality; and all covariate effects remain exploratory rather than established population PK parameters. Release is conditional on acknowledgment of these limitations and commitment to confirmatory studies.