"""Scribe packets — map each required claim to the core verify step(s) that recompute it.

This is the OPERATOR side. It computes the datum from the spec inputs (the same arithmetic the
writers were asked to do by hand) and hands the core a step whose `claimed_value` is the WRITER's
number — so the core's verifier reports CONFIRMED only when the writer's number matches the datum.
A second `arith` step checks the writer's own stated formula evaluates to their own number
(internal consistency), independent of whether the number is right.

Nothing here imports the core: these are plain {id, domain, spec} dicts handed to nh_org.core_client.
Round 2 (bond + PILOT, interest-only period, depreciating equipment, millage step).
"""
import math
import re

CLAIMS = ["par", "monthly_io", "monthly_pi", "total_interest", "dscr_amort", "equip_val_y3",
          "full_tax_y1", "full_tax_y8", "pilot_y6", "total_abated_10", "npv_abated", "abated_per_job"]

PAR = math.ceil(12_000_000 / 0.98 / 5000) * 5000
R = "(0.045/12)"
N = 216
PI = f"{PAR}*{R}*(1+{R})^{N}/((1+{R})^{N}-1)"
ev = [max(9_000_000 * (1 - 0.1 * y), 1_800_000) for y in range(1, 11)]
mill = [27.9] * 5 + [28.5] * 5
full = [(18_000_000 + ev[i]) * 0.40 * mill[i] / 1000 for i in range(10)]
ab = [1.0 - 0.1 * i for i in range(10)]
abated = [full[i] * ab[i] for i in range(10)]


def packets_for(cid, value, formula):
    num = lambda sid, expr, tol=1e-3: {"id": sid, "domain": "mathematics", "spec": {"mode": "numeric",
          "params": {"numeric_expr": expr, "claimed_value": float(value), "rel_tol": tol}}}
    E = {"par": f"{PAR}", "monthly_io": f"{PAR}*{R}", "monthly_pi": PI,
         "total_interest": f"24*{PAR}*{R}+216*{PI}-{PAR}",
         "equip_val_y3": f"{ev[2]}", "full_tax_y1": f"(18000000+{ev[0]})*0.40*27.9/1000",
         "full_tax_y8": f"(18000000+{ev[7]})*0.40*28.5/1000", "pilot_y6": f"{full[5]}*(1-{ab[5]})",
         "total_abated_10": f"{sum(abated)}",
         "npv_abated": "+".join(f"{x}/1.05^{i+1}" for i, x in enumerate(abated)),
         "abated_per_job": f"{sum(abated)}/150"}
    steps = []
    if cid == "dscr_amort":
        pi = PAR * (0.045 / 12) * (1 + 0.045 / 12) ** N / ((1 + 0.045 / 12) ** N - 1)
        steps.append({"id": "re", "domain": "real_estate", "spec": {"RE_VERIFY": {
            "net_operating_income": 1_500_000, "annual_debt_service": round(12 * pi, 2),
            "claimed_dscr": float(value)}}})
    elif cid in E:
        steps.append(num("re", E[cid]))
    if formula and re.fullmatch(r"[0-9eE+\-*/^(). ]+", formula.strip()):
        steps.append(num("ar", formula.strip(), 1e-3))
    return steps
