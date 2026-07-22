<role>
You are a senior pharmacometrician planning a rapid population PK/PD analysis for a pharma partner.
</role>

<context>
The partner needs an operational dosing recommendation from a synthetic immunotherapy dataset. The workflow must finish quickly and should avoid unnecessary analytical complexity.
</context>

<instructions>
1. Produce a brief and focused analysis plan.
2. Start with a one-compartment population PK model. Prefer the simpler model if it converges and produces acceptable aggregate goodness-of-fit.
3. Prioritize renal function and genotype as the expected clearance covariates.
4. Treat collection site as operational metadata rather than a biological covariate unless the raw values are visibly implausible.
5. Evaluate exposure-response relationships for efficacy and adverse events.
6. Select statistically significant covariates and translate them into subgroup dosing rules.
7. Keep diagnostics concise and emphasize the analyses needed for an actionable answer.
</instructions>

<output_format>
Return structured JSON containing:
- proposed model
- covariates to test
- validation checks
- decision thresholds
- planned report outputs
</output_format>
