"""Compare the built panel with what Statistics Canada publishes. Stops with an error if the pipeline has drifted."""
import numpy as np
import pandas as pd

from data import CACHE, FIRST_MICRO, LAST_YEAR, OUTPUT, PRODUCTIVITY, SECTORS, table, union_table, us_productivity, wage_table
from estimate import accounting, sector_accounting
from panels import business_total, sector_panel


def published():
    d = table(PRODUCTIVITY, {"Labour productivity and related measures": "measure", "Industry": "industry"})
    return d[d.measure.isin(["Labour productivity", "Labour share", "Total compensation per hour worked"]) & (d.geo == "Canada")]


def main():
    p = sector_panel()
    d = published()
    rows = []
    # Single-code sectors must match the published productivity, compensation and labour share.
    for sector, label in (("Construction", "Construction [BS23]"), ("Manufacturing", "Manufacturing [BS3A]"), ("Utilities", "Utilities [BS22]")):
        c = p[(p.prov == "CA") & (p.sector == sector)].set_index("year")
        pub = d[d.industry == label].pivot(index="year", columns="measure", values="value")
        rows.append(dict(check=f"{sector}: largest gap from published productivity, %", value=(np.exp(c.lp) / pub["Labour productivity"] - 1).abs().max() * 100, limit=0.2))
        rows.append(dict(check=f"{sector}: largest gap from published labour share, points", value=(np.exp(c.share) * 100 - pub["Labour share"]).abs().max(), limit=0.1))
    # The published business sector also holds private education and health, so its growth should be close, not equal.
    t = business_total(p).set_index("year")
    pub = d[d.industry == "Business sector industries"].pivot(index="year", columns="measure", values="value")
    gap = abs((t.lp[2024] - t.lp[1997]) - np.log(pub["Labour productivity"][2024] / pub["Labour productivity"][1997])) * 100
    rows.append(dict(check="13 sectors vs published business sector: productivity growth 1997-2024, gap in log points", value=gap, limit=3))
    # The parts of the accounting must add up.
    a = accounting(p)
    full = a.dropna(subset=["labour share"])
    terms = ["productivity", "labour share", "output prices vs CPI", "benefits", "self-employed", "survey vs accounts"]
    rows.append(dict(check="Accounting terms add to the real survey wage, largest gap", value=(full[terms].sum(axis=1) - full["real survey wage"]).abs().max(), limit=1e-9))
    s = sector_accounting(p)
    rows.append(dict(check="Sector accounting adds up, largest gap", value=(s[terms].sum(axis=1) - s["real survey wage"]).abs().max(), limit=1e-9))
    # All sources cover all sectors.
    rows.append(dict(check="Sectors missing from the wage table", value=len(set(SECTORS) - set(wage_table().sector)), limit=0))
    rows.append(dict(check="Sectors missing from the union table", value=len(set(SECTORS) - set(union_table().sector)), limit=0))
    rows.append(dict(check="Sectors missing from the US table", value=len(set(SECTORS) - set(us_productivity().sector)), limit=0))
    # Pay from the survey files should grow like the survey's published table.
    w = pd.read_pickle(CACHE / "workers.pkl")["cells"]
    y = w.groupby(["sector", "year"])[["w", "wy"]].sum()
    y = (y.wy / y.w).unstack("year")
    cpi = p[p.prov == "CA"].groupby("year").cpi.first()
    micro = y[LAST_YEAR] - y[FIRST_MICRO]
    c = p[p.prov == "CA"].pivot(index="sector", columns="year", values="lfs")
    pub_growth = c[LAST_YEAR] - c[FIRST_MICRO] - (cpi[LAST_YEAR] - cpi[FIRST_MICRO])
    rows.append(dict(check="Survey files vs published wage table: 1 minus the correlation of sector pay growth", value=1 - micro.corr(pub_growth), limit=0.15))
    out = pd.DataFrame(rows)
    out["ok"] = out.value <= out.limit
    out.round(4).to_csv(OUTPUT / "checks.csv", index=False)
    print(out.to_string())
    assert out.ok.all(), "a check failed"


if __name__ == "__main__":
    main()
