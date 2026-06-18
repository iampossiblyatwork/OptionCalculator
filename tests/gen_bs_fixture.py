"""Generate the Python↔JS parity grid. Run: python tests/gen_bs_fixture.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import options as opt

GRID = []
for typ in ("call", "put"):
    for spot in (50, 90, 100, 110, 150):
        for strike in (80, 100, 120):
            for days in (0, 1, 30, 180, 365):
                for ivpct in (10, 30, 80):
                    for ratepct in (0, 4):
                        for divpct in (0, 3):
                            inp = dict(type=typ, spot=spot, strike=strike,
                                       days_to_expiration=days,
                                       volatility=ivpct / 100,
                                       risk_free_rate=ratepct / 100,
                                       dividend_yield=divpct / 100)
                            out = opt.black_scholes(**inp)
                            GRID.append({"input": inp, "expected": out})

path = os.path.join(os.path.dirname(__file__), "fixtures", "bs_parity.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(GRID, f, indent=2)
print(f"wrote {len(GRID)} cases to {path}")
