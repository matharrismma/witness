# Bond and PILOT memo (round 2) — de-identified spec

Staff memo for the board of [AUTHORITY] on a taxable revenue bond and PILOT for
[COMPANY]'s [PROJECT] in [COUNTY]. Keep bracket placeholders as-is.

## Facts (the only inputs you may use)

- Project cost to be funded from bond proceeds: $12,000,000. Costs of issuance are 2.0% of
  PAR and are paid from proceeds, so par must satisfy par × (1 − 0.02) ≥ 12,000,000.
  Par is then rounded UP to the next $5,000.
- Rate 4.50% fixed annual, monthly rate = 0.045/12. Term 20 years = 240 months.
  Months 1–24 are INTEREST-ONLY (payment = par × monthly rate). Months 25–240 (216 payments)
  are level principal-and-interest payments that fully amortize par.
- [COMPANY] projected net operating income available for debt service: $1,500,000/yr.
- Taxable property under the PILOT: real property $18,000,000 (value constant) AND
  equipment $9,000,000. Equipment fair market value declines 10% of ORIGINAL cost each
  year: year-1 value = 9,000,000 × 0.90, year-2 = 9,000,000 × 0.80, ..., with a floor of 20%
  of original cost (so year 8 onward = 1,800,000).
- Assessment ratio 40%. Millage: 27.9 mills in years 1–5, 28.5 mills in years 6 and after.
- Abatement schedule, 10 years, applies to the combined (real + equipment) tax:
  year 1 = 100% abated; the abated share then declines 10 percentage points each
  subsequent year (year 2 = 90%, year 3 = 80%, ..., year 10 = 10%). Year 11 onward full tax.
- Discount rate 5.0% annual; end-of-year cash flows; year 1 discounted one period.
- Jobs: 150 at $52,000.

## Required claims (plain numbers; ratios as decimals)

| id | definition |
|---|---|
| par | bond par after the 2% issuance cost gross-up and $5,000 round-up |
| monthly_io | monthly payment during months 1–24 |
| monthly_pi | level monthly P&I payment during months 25–240 |
| total_interest | total interest over all 240 months = (24 × monthly_io + 216 × monthly_pi) − par |
| dscr_amort | NOI / (12 × monthly_pi) |
| equip_val_y3 | equipment fair market value in year 3 |
| full_tax_y1 | full (unabated) combined tax in year 1 (real + equipment, 27.9 mills) |
| full_tax_y8 | full combined tax in year 8 (equipment at floor, 28.5 mills) |
| pilot_y6 | PILOT payment in year 6 |
| total_abated_10 | sum of abated amounts, years 1–10 |
| npv_abated | present value of abated amounts, years 1–10, at 5.0% |
| abated_per_job | total_abated_10 / 150 |

## Rules
- Do NOT run code or use any tool. Reason and compute by hand, showing arithmetic.
- Return ONLY a JSON object: {"draft": "<~200-word memo, placeholders intact>",
  "claims": [{"id","value","inputs","formula"} × 12]}. "formula" uses only digits, decimal
  points and + - * / ^ ( ) and evaluates to value.
