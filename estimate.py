"""Answer the three questions: accounting identities, panel pass-through, worker regressions and identification checks."""
import numpy as np
import pandas as pd
from scipy import sparse

from data import CACHE, FIRST_MICRO, LAST_YEAR, OUTPUT, union_table
from panels import JOB, PERSON, business_total, column_names, design, sector_panel, worker_years

WEBB = np.outer([-1, 1], np.sqrt([0.5, 1.0, 1.5])).ravel()
LAST_NOMINAL = 2021                  # nominal value added by industry stops here; real value added runs to 2024
# Three-year averages, so one odd year can't set a sector's growth, ending before the pandemic.
SECTOR_START, SECTOR_END = (1997, 1999), (2017, 2019)
PAY = {"lfs": "Survey hourly wage", "sna_wage": "National accounts wage rate", "paid_comp_hr": "Employee compensation per hour",
       "comp_hr": "Total compensation per hour"}


def wild_sums(a, b, level=0.95, reps=4999, seed=0):
    """Estimate sum(a) / sum(b) with a wild cluster bootstrap (Webb weights) over clusters, inverted for a range.
    a and b hold each cluster's sum of z*y and z*x, with z = x for least squares. Adapted from canada_minimum_wage's
    estimate.py, which works on rows; these sums make it fast and let it cover instruments. With an instrument this is
    an Anderson-Rubin test, so a weak first stage shows up as an open-ended range rather than a false narrow one."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    v = np.random.default_rng(seed).choice(WEBB, (reps, len(a)))
    beta = a.sum() / b.sum()
    se = np.sqrt(((a - beta * b) ** 2).sum()) / abs(b.sum())

    def p_value(b0):
        s = a - b0 * b
        star = v @ s / np.sqrt(((v * s) ** 2).sum(axis=1))
        return (np.abs(star) >= abs(s.sum() / np.sqrt((s ** 2).sum()))).mean()

    if se == 0:
        return beta, beta, beta, 1.0
    grid = np.linspace(beta - 12 * se, beta + 12 * se, 481)
    keep = np.flatnonzero([p_value(g) > 1 - level for g in grid])
    low = grid[keep[0]] if len(keep) and keep[0] > 0 else -np.inf
    high = grid[keep[-1]] if len(keep) and keep[-1] < len(grid) - 1 else np.inf
    return beta, low, high, p_value(0.0)


def cluster_se(a, b):
    """Ordinary clustered standard error of sum(a) / sum(b), with the small-sample factor."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    beta, g = a.sum() / b.sum(), len(a)
    return np.sqrt(((a - beta * b) ** 2).sum() * g / (g - 1)) / abs(b.sum())


def dummies(t, effects):
    """One column per level of each effect; an effect is a column name or a tuple of them."""
    out = [np.ones((len(t), 1))]
    for e in effects:
        key = t[list(e)].astype(str).agg("|".join, axis=1) if isinstance(e, tuple) else t[e]
        out.append(pd.get_dummies(key, dtype=float).to_numpy())
    return np.hstack(out)


def fit(t, y, x, effects=(), controls=(), z=None, weight="weight", cluster="sector"):
    """Coefficient on x after removing the effects and controls, with a wild bootstrap range over `cluster` and, for
    comparison, robust and sector-year standard errors. Controls are partialled out once; the bootstrap doesn't redo it."""
    need = [y, x, *controls] + ([z] if z else []) + ([weight] if weight else [])
    t = t.dropna(subset=need)
    w = np.sqrt(t[weight].to_numpy(float)) if weight else np.ones(len(t))
    X = dummies(t, effects)
    if controls:
        X = np.hstack([X, t[list(controls)].to_numpy(float)])
    U, s, _ = np.linalg.svd(X * w[:, None], full_matrices=False)
    U = U[:, s > 1e-9 * s.max()]

    def clean(col):
        v = t[col].to_numpy(float) * w
        return v - U @ (U.T @ v)

    yt, xt = clean(y), clean(x)
    zt = clean(z) if z else xt
    sums = pd.DataFrame({"a": zt * yt, "b": zt * xt, "sector": t.sector.values, "year": t.year.values, "prov": t.prov.values})
    by = sums.groupby(cluster)[["a", "b"]].sum()
    beta, low, high, p = wild_sums(by.a, by.b)
    e = yt - beta * xt
    pairs = sums.groupby(["sector", "year"])[["a", "b"]].sum()
    n, k = len(t), U.shape[1] + 1
    out = dict(coefficient=beta, low=low, high=high, p=p, se_clustered=cluster_se(by.a, by.b),
               se_sector_year=cluster_se(pairs.a, pairs.b),
               se_robust=np.sqrt((zt ** 2 * e ** 2).sum() * n / (n - k)) / abs((zt * xt).sum()),
               clusters=len(by), n=n)
    if z:    # first stage F on the instrument, clustered the same way
        first = pd.DataFrame({"a": zt * xt, "b": zt * zt, cluster: t[cluster].values}).groupby(cluster)[["a", "b"]].sum()
        out["first_stage"] = first.a.sum() / first.b.sum()
        out["first_stage_F"] = (out["first_stage"] / cluster_se(first.a, first.b)) ** 2
    return out


def changes(p, h, cols=("lp", "lfs", "sna_wage", "paid_comp_hr", "comp_hr", "price", "cpi", "lp_us", "lmw", "adjusted")):
    """Change over h years within each sector and province, weighted by the cell's average hours."""
    q = p[p.prov != "CA"].sort_values(["sector", "prov", "year"]).copy()
    g = q.groupby(["sector", "prov"])
    for c in cols:
        if c in q:
            q["d_" + c] = g[c].diff(h)
    q["weight"] = (q.hours + g.hours.shift(h)) / 2
    q["d_real"] = q.d_lfs - q.d_cpi
    return q[q.d_lp.notna() & np.isfinite(q.d_lp)]


# Question 1: identities and pass-through

def accounting_row(a, b):
    """Log change in real survey pay from row a to row b, split into terms that add up exactly."""
    d = b - a
    terms = {"productivity": d.lp, "labour share": d.share, "output prices vs CPI": d.price - d.cpi,
             "benefits": d.sna_wage - d.paid_comp_hr, "self-employed": d.paid_comp_hr - d.comp_hr, "survey vs accounts": d.lfs - d.sna_wage}
    # Labour share and output prices can't be told apart without nominal value added, but their sum can be measured.
    return {"real survey wage": d.lfs - d.cpi, "real total compensation": d.comp_hr - d.cpi,
            "compensation in output prices": d.comp_hr - d.price, "labour share and prices": d.comp_hr - d.cpi - d.lp, **terms}


def accounting(p):
    t = business_total(p).set_index("year")
    periods = [(1997, 2024), (1997, 2019), (1997, 2007), (2007, 2019), (2019, 2024), (2019, LAST_NOMINAL)]
    return pd.DataFrame([{"start": a, "end": b, **accounting_row(t.loc[a], t.loc[b])} for a, b in periods])


def sector_accounting(p):
    """The same split for each sector, from three-year averages of the logs, plus size and union coverage."""
    c = p[p.prov == "CA"].set_index("sector")
    cols = ["lp", "price", "share", "comp_hr", "paid_comp_hr", "sna_wage", "lfs", "cpi"]
    a = c[c.year.between(*SECTOR_START)].groupby(level=0)[cols].mean()
    b = c[c.year.between(*SECTOR_END)].groupby(level=0)[cols].mean()
    out = pd.DataFrame([accounting_row(a.loc[s], b.loc[s]) for s in a.index], index=a.index)
    late = c[c.year.between(2022, 2024)].groupby(level=0)[["lp", "lfs", "cpi"]].mean()
    out["productivity_to_2024"], out["real_survey_wage_to_2024"] = late.lp - a.lp, late.lfs - late.cpi - a.lfs + a.cpi
    out["hours_share"] = c[c.year.between(*SECTOR_END)].groupby(level=0).hours.mean()
    out["hours_share"] /= out.hours_share.sum()
    out["labour_share_level"] = np.exp(b.share)
    u = union_table()
    out["union_coverage"] = u[u.year.between(*SECTOR_END)].groupby("sector").coverage.mean()
    return out


def pandemic_jump(p):
    """How much of the 2020 productivity jump happened within sectors, using 2019 hours as weights, and how much from hours moving."""
    c = p[p.prov == "CA"]
    lp, hours = c.pivot(index="year", columns="sector", values="lp"), c.pivot(index="year", columns="sector", values="hours")
    t = business_total(p).set_index("year").lp
    total = t[2020] - t[2019]
    within = (hours.loc[2019] / hours.loc[2019].sum() * (lp.loc[2020] - lp.loc[2019])).sum()
    return pd.DataFrame([dict(part="Total", change=total), dict(part="Within sectors", change=within), dict(part="Hours moving between sectors", change=total - within)])


def aggregate_regression(p):
    """Business sector totals, no sector detail: annual and five-year changes, with Newey-West ranges."""
    t = business_total(p).sort_values("year")
    rows = []
    for name, y in {"real survey wage": t.lfs - t.cpi, "real total compensation": t.comp_hr - t.cpi,
                    "compensation in output prices": t.comp_hr - t.price}.items():
        for h in (1, 5):
            d = pd.DataFrame({"y": y.diff(h), "x": t.lp.diff(h)}).dropna()
            x = d.x - d.x.mean()
            b = (x * d.y).sum() / (x ** 2).sum()
            u = (d.y - d.y.mean() - b * x) * x
            lags = max(h, 2)
            var = (u ** 2).sum() + 2 * sum((1 - k / (lags + 1)) * (u.values[k:] * u.values[:-k]).sum() for k in range(1, lags + 1))
            se = np.sqrt(var) / (x ** 2).sum()
            rows.append(dict(pay=name, years=h, coefficient=b, low=b - 1.96 * se, high=b + 1.96 * se, n=len(d)))
    return pd.DataFrame(rows)


FE = {"no effects": (), "year": ("year",), "province-year": (("prov", "year"),),
      "sector + province-year": ("sector", ("prov", "year")),
      "sector-year + province-year": (("sector", "year"), ("prov", "year"))}
MAIN_FE = FE["sector + province-year"]


def passthrough(p):
    """Pay on productivity: each pay measure, deflated by the CPI and by the sector's own output price, over three horizons."""
    rows = []
    for h in (1, 5, 10):
        q = changes(p, h)
        for pay, label in PAY.items():
            q["real_cpi"] = q["d_" + pay] - q.d_cpi
            q["real_own"] = q["d_" + pay] - q.d_price
            for deflator, col in (("CPI", "real_cpi"), ("own output price", "real_own")):
                rows.append(dict(pay=label, deflator=deflator, years=h, **fit(q, col, "d_lp", MAIN_FE)))
    return pd.DataFrame(rows)


def by_effects(p):
    """How the answer moves with what is held fixed, for five-year changes in survey pay."""
    q = changes(p, 5)
    return pd.DataFrame([dict(effects=name, **fit(q, "d_real", "d_lp", fe)) for name, fe in FE.items()])


def where_it_goes(p):
    """Within a sector and province, a change in productivity must show up as real pay, a labour share change or a relative
    price change, so these slopes add up to 1. Identities can't say which way anything runs. Ends in 2021, with nominal output."""
    rows = []
    for h in (1, 5):
        q = changes(p, h)
        q = q.assign(d_share=q.groupby(["sector", "prov"]).share.diff(h))
        q = q.assign(real_comp=q.d_comp_hr - q.d_cpi, minus_share=-q.d_share, minus_price=-(q.d_price - q.d_cpi)).dropna(subset=["d_share", "d_price"])
        for part, y in (("Real total compensation per hour", "real_comp"), ("Labour share (sign flipped)", "minus_share"),
                        ("Output prices vs CPI (sign flipped)", "minus_price")):
            rows.append(dict(years=h, part=part, **fit(q, y, "d_lp", MAIN_FE)))
    return pd.DataFrame(rows)


def sensitivity(p, adjusted=None):
    """The main estimate, five-year changes with sector and province-year effects, on other samples."""
    q = changes(p, 5)
    big = q.prov.isin(["ON", "QC", "BC", "AB"])
    cases = {"All": q, "Without mining, oil, forestry, fishing": q[q.sector != "Mining, oil, forestry, fishing"],
             "Without agriculture": q[q.sector != "Agriculture"], "Without Finance and real estate": q[q.sector != "Finance and real estate"],
             "Ending by 2019": q[q.year <= 2019], "Four largest provinces": q[big]}
    rows = [dict(sample=name, **fit(t, "d_real", "d_lp", MAIN_FE)) for name, t in cases.items()]
    rows.append(dict(sample="Each cell counted equally", **fit(q.assign(weight=1.0), "d_real", "d_lp", MAIN_FE)))
    trim = q[q.d_lp.between(*q.d_lp.quantile([0.01, 0.99]))]
    rows.append(dict(sample="Largest 2% of productivity changes dropped", **fit(trim, "d_real", "d_lp", MAIN_FE)))
    national = p[p.prov == "CA"].sort_values(["sector", "year"]).copy()
    g = national.groupby("sector")
    national = national.assign(d_real=g.lfs.diff(5) - g.cpi.diff(5), d_lp=g.lp.diff(5), weight=(national.hours + g.hours.shift(5)) / 2)
    rows.append(dict(sample="Canada-wide sector panel", **fit(national, "d_real", "d_lp", ("sector", "year"))))
    if adjusted is not None:
        r = changes(p.merge(adjusted[["sector", "prov", "year", "adjusted"]], on=["sector", "prov", "year"], how="left"), 5)
        r = r.assign(d_raw=r.d_real)
        same = r.dropna(subset=["d_adjusted"])
        rows.append(dict(sample=f"Survey files {FIRST_MICRO}-{LAST_YEAR}, raw pay", **fit(same, "d_raw", "d_lp", MAIN_FE)))
        rows.append(dict(sample=f"Survey files {FIRST_MICRO}-{LAST_YEAR}, pay holding worker mix fixed", **fit(same, "d_adjusted", "d_lp", MAIN_FE)))
    return pd.DataFrame(rows)


# Identification checks

def instruments(q):
    """Productivity change in the same sector and years in the other provinces, and in the US."""
    total = q.assign(v=q.d_lp * q.weight).groupby(["sector", "year"])[["v", "weight"]].transform("sum")
    q = q.copy()
    q["z_other"] = (total.v - q.d_lp * q.weight) / (total.weight - q.weight)
    q["z_us"] = q.d_lp_us
    return q


def timing(p):
    """Annual changes: does pay move with past, current or future productivity, and does past pay predict productivity?"""
    q = changes(p, 1).sort_values(["sector", "prov", "year"])
    g = q.groupby(["sector", "prov"])
    q["lp_lag"], q["lp_lead"], q["real_lag"] = g.d_lp.shift(1), g.d_lp.shift(-1), g.d_real.shift(1)
    both = q.dropna(subset=["lp_lag", "lp_lead"])
    rows = [dict(outcome="pay", regressor=label, **fit(both, "d_real", x, MAIN_FE, controls=[c for c in ("lp_lag", "d_lp", "lp_lead") if c != x]))
            for label, x in (("productivity, last year", "lp_lag"), ("productivity, this year", "d_lp"), ("productivity, next year", "lp_lead"))]
    rows.append(dict(outcome="productivity", regressor="pay, last year", **fit(q, "d_lp", "real_lag", MAIN_FE, controls=["lp_lag"])))
    return pd.DataFrame(rows)


def instrumented(p):
    """Productivity in the same sector elsewhere can't be moved by a wage shock in this sector and province, and US
    productivity can't be moved by a Canadian wage shock. Common shocks can still reach both, so these aren't proof."""
    rows = []
    for h in (1, 5):
        q = instruments(changes(p, h))
        effects = ("sector", ("prov", "year"))
        sample = q.dropna(subset=["z_us"])
        rows.append(dict(method="Least squares", instrument="", years=h, **fit(sample, "d_real", "d_lp", effects)))
        for name, z in (("Same sector, other provinces", "z_other"), ("Same sector, US", "z_us")):
            rows.append(dict(method="Reduced form", instrument=name, years=h, **fit(sample, "d_real", z, effects)))
            rows.append(dict(method="Instrumented", instrument=name, years=h, **fit(sample, "d_real", "d_lp", effects, z=z)))
    return pd.DataFrame(rows)


# Question 2: workers

SPECS = {
    "A. Sector, province and year only": ["sector", "province", "year"],
    "B. A plus worker characteristics": ["sector", "province", "year", *PERSON],
    "C. B plus job type, union and minimum wage": ["sector", "province", "year", *PERSON, *JOB, "union", "lmw"],
    "D. C with sector-by-province effects": ["sector x province", "year", *PERSON, *JOB, "union", "lmw"],
    "E. D without year effects": ["sector x province", *PERSON, *JOB, "union", "lmw"],
}
MAIN_SPEC = "D. C with sector-by-province effects"
FOCUS = {"lp": "sector", "lmw": "province", "union": "sector"}


def normal_equations():
    """X'WX, X'Wy and yearly means, built one survey year at a time and cached."""
    path = CACHE / "normal.pkl"
    if path.exists():
        return pd.read_pickle(path)
    k = len(column_names())
    xx, xy, yy, n = np.zeros((k, k)), np.zeros(k), 0.0, 0
    means = {}
    for d in worker_years():
        X = design(d)
        w, y = d.w.to_numpy(), d.y.to_numpy()
        xx += (X.T @ sparse.diags(w) @ X).toarray()
        xy += X.T @ (w * y)
        yy += (w * y * y).sum()
        n += len(d)
        means[int(d.year.iloc[0])] = dict(x=X.T @ w / w.sum(), y=(w * y).sum() / w.sum(), w=w.sum(), n=len(d))
    out = dict(xx=xx, xy=xy, yy=yy, n=n, means=means)
    pd.to_pickle(out, path)
    return out


def solve(ne, columns):
    return np.linalg.solve(ne["xx"][np.ix_(columns, columns)], ne["xy"][columns])


def spec_columns(names, groups):
    return np.flatnonzero(names.group.isin(["constant", "lp", *groups]))


def worker_regressions():
    """Log real pay on sector-province productivity, for each specification, with standard errors at several levels.
    Scores are collected by sector-province-year so that any coarser clustering can be built from them."""
    path = CACHE / "workers.pkl"
    if path.exists():
        return pd.read_pickle(path)
    names, ne = column_names(), normal_equations()
    jobs = []
    for spec, groups in SPECS.items():
        cols = spec_columns(names, groups)
        beta = solve(ne, cols)
        for focus in FOCUS:
            where = names.index[names.group == focus][-1] if focus == "union" else names.index[names.name == focus][0]
            if where not in cols:
                continue
            others = cols[cols != where]
            jobs.append(dict(spec=spec, focus=focus, where=where, others=others, beta=beta[list(cols).index(where)],
                             gx=solve_rhs(ne, others, where), gy=solve(ne, others)))
    main = spec_columns(names, SPECS[MAIN_SPEC])
    beta_main = pd.Series(solve(ne, main), index=names.name.iloc[main])
    person = names.index[names.group.isin(PERSON)]
    cells, sums = [], {(j["spec"], j["focus"]): [] for j in jobs}
    robust = {(j["spec"], j["focus"]): [0.0, 0.0] for j in jobs}
    for d in worker_years():
        X = design(d).tocsc()
        w, y = d.w.to_numpy(), d.y.to_numpy()
        ids = d[["sector", "prov", "year"]]
        for j in jobs:
            Z = X[:, j["others"]]
            xt = X[:, j["where"]].toarray().ravel() - Z @ j["gx"]
            yt = y - Z @ j["gy"]
            e = yt - j["beta"] * xt
            key = (j["spec"], j["focus"])
            sums[key].append(ids.assign(a=w * xt * yt, b=w * xt * xt).groupby(["sector", "prov", "year"]).sum())
            robust[key][0] += (w ** 2 * xt ** 2 * e ** 2).sum()
            robust[key][1] += (w * xt * xt).sum()
        z = X[:, person] @ beta_main.reindex(names.name.iloc[person]).to_numpy()
        cells.append(ids.assign(w=w, wy=w * y, wz=w * z, union=w * d.union.to_numpy(), degree=w * (d.EDUC >= 5).to_numpy(), n=1.0)
                     .groupby(["sector", "prov", "year"]).sum())
    table = []
    for j in jobs:
        key = (j["spec"], j["focus"])
        s = pd.concat(sums[key]).reset_index()
        n = ne["n"]
        row = dict(spec=j["spec"], variable=j["focus"], coefficient=j["beta"], n=n, se_robust=np.sqrt(robust[key][0]) / robust[key][1])
        row["se_sector_province_year"] = cluster_se(s.a, s.b)
        for label, by in (("sector_year", ["sector", "year"]), ("province_year", ["prov", "year"]), ("sector", ["sector"]), ("province", ["prov"])):
            g = s.groupby(by)[["a", "b"]].sum()
            row["se_" + label] = cluster_se(g.a, g.b)
        g = s.groupby("prov" if FOCUS[j["focus"]] == "province" else "sector")[["a", "b"]].sum()
        _, row["low"], row["high"], row["p"] = wild_sums(g.a, g.b)
        table.append(row)
    cell = pd.concat(cells).reset_index()
    cell["raw"], cell["adjusted"] = cell.wy / cell.w, (cell.wy - cell.wz) / cell.w
    out = dict(table=pd.DataFrame(table), cells=cell, beta=beta_main)
    pd.to_pickle(out, path)
    return out


def solve_rhs(ne, columns, target):
    return np.linalg.solve(ne["xx"][np.ix_(columns, columns)], ne["xx"][columns, target])


def wage_change(start, end):
    """Change in mean log real pay from one year to another, as the fitted model splits it up. With year effects, the
    common trend is left in 'year effects'. Without them, it has to load on productivity and the other trending variables."""
    names, ne = column_names(), normal_equations()
    a, b = ne["means"][start], ne["means"][end]
    label = {**{g: "Worker characteristics: " + g for g in PERSON}, **{g: "Job type: " + g for g in JOB},
             "union": "Union coverage", "lmw": "Minimum wage", "lp": "Sector productivity",
             "sector x province": "Sector and province mix", "year": "Year effects"}
    rows = []
    for spec in (MAIN_SPEC, "E. D without year effects"):
        cols = spec_columns(names, SPECS[spec])
        beta = solve(ne, cols)
        effect = pd.Series(beta * (b["x"] - a["x"])[cols], index=names.group.iloc[cols]).groupby(level=0).sum().drop("constant")
        total = b["y"] - a["y"]
        for group, value in effect.items():
            rows.append(dict(spec=spec, start=start, end=end, part=label[group], change=value, share=value / total))
        rows.append(dict(spec=spec, start=start, end=end, part="Total", change=total, share=1.0))
        rows.append(dict(spec=spec, start=start, end=end, part="Not explained", change=total - effect.sum(), share=(total - effect.sum()) / total))
        rows.append(dict(spec=spec, start=start, end=end, part="Memo: change in worker-weighted log productivity",
                         change=(b["x"] - a["x"])[names.index[names.name == "lp"][0]], share=np.nan))
    return pd.DataFrame(rows)


# Question 3: sectors

def dispersion(s):
    """Across sectors, productivity growth = real compensation growth - labour share change - relative output price change,
    so differences in productivity growth split exactly into those three. Shares of the hours-weighted variance."""
    w = s.hours_share / s.hours_share.sum()
    lp = s.productivity
    parts = {"Real total compensation per hour": s["real total compensation"], "Labour share (sign flipped)": -s["labour share"],
             "Output prices vs CPI (sign flipped)": -s["output prices vs CPI"]}

    def split(keep):
        ww, x = w[keep] / w[keep].sum(), lp[keep]
        mean_x = (ww * x).sum()
        return {k: (ww * (x - mean_x) * (v[keep] - (ww * v[keep]).sum())).sum() / (ww * (x - mean_x) ** 2).sum() for k, v in parts.items()}

    full = split(np.ones(len(s), dtype=bool))
    drops = pd.DataFrame([split((s.index != out)) for out in s.index], index=s.index)
    return pd.DataFrame([dict(part=k, share_of_variance=full[k], lowest_leaving_one_out=drops[k].min(), highest_leaving_one_out=drops[k].max()) for k in parts])


def weighted_sd(v, w):
    w = w / w.sum()
    return np.sqrt((w * (v - (w * v).sum()) ** 2).sum())


def spread(s):
    """How much sector growth rates differ, and the cross-sector slope of pay growth on productivity growth."""
    w = s.hours_share
    rows = [dict(measure=m, sd_across_sectors=weighted_sd(s[m], w)) for m in
            ["productivity", "real total compensation", "real survey wage", "output prices vs CPI", "labour share"]]
    x, y = s.productivity - (w * s.productivity).sum() / w.sum(), s["real survey wage"]
    return pd.DataFrame(rows), (w * x * y).sum() / (w * x * x).sum()


def sector_slopes(p):
    """Five-year pass-through within each sector, from differences across provinces and over time, ranges over provinces."""
    q = changes(p, 5)
    return pd.DataFrame([dict(sector=name, **fit(g, "d_real", "d_lp", ("prov", "year"), cluster="prov")) for name, g in q.groupby("sector")])


def composition(cells):
    """Does the worker mix explain sector differences? Pay levels and growth, before and after holding worker
    characteristics fixed at their estimated returns. 'Adjusted' removes age, gender, education, marital, immigrant and
    student differences, valued at the main regression's coefficients."""
    c = cells.assign(wr=cells.w * cells.raw, wa=cells.w * cells.adjusted)
    y = c.groupby(["sector", "year"])[["w", "wr", "wa", "union", "degree"]].sum()
    y["raw"], y["adjusted"] = y.wr / y.w, y.wa / y.w
    g = lambda v, years: y.loc[(slice(None), slice(*years)), v].groupby("sector").mean()
    first, last = (2006, 2008), (2022, 2024)
    out = pd.DataFrame({"raw_growth": g("raw", last) - g("raw", first), "adjusted_growth": g("adjusted", last) - g("adjusted", first)})
    out["composition_growth"] = out.raw_growth - out.adjusted_growth
    level = y.groupby("sector")[["w", "wr", "wa", "union", "degree"]].sum()
    out["raw_level"], out["adjusted_level"] = level.wr / level.w, level.wa / level.w
    out["union_coverage_micro"], out["degree_share"] = level.union / level.w, level.degree / level.w
    out["weight"] = level.w
    stats = dict(level_sd_raw=weighted_sd(out.raw_level, out.weight), level_sd_adjusted=weighted_sd(out.adjusted_level, out.weight),
                 growth_sd_raw=weighted_sd(out.raw_growth, out.weight), growth_sd_adjusted=weighted_sd(out.adjusted_growth, out.weight),
                 mean_composition_growth=(out.composition_growth * out.weight).sum() / out.weight.sum())
    return out, stats


def correlates(table):
    """Rank correlations across the 13 sectors. Descriptive only: 13 points can't separate these from each other."""
    target = {"pass-through": "coefficient", "pay growth less productivity growth": "pay_gap"}
    traits = {"union coverage": "union_coverage", "labour share": "labour_share_level", "share with a degree": "degree_share",
              "productivity growth": "productivity", "raw pay level": "raw_level"}
    return pd.DataFrame([dict(sector_measure=a, trait=b, spearman=table[c].corr(table[d], method="spearman"))
                         for a, c in target.items() for b, d in traits.items()])


if __name__ == "__main__":
    OUTPUT.mkdir(exist_ok=True)
    p = sector_panel()
    accounting(p).round(5).to_csv(OUTPUT / "accounting.csv", index=False)
    s = sector_accounting(p)
    aggregate_regression(p).round(4).to_csv(OUTPUT / "aggregate_regression.csv", index=False)
    pandemic_jump(p).round(5).to_csv(OUTPUT / "pandemic_jump.csv", index=False)
    passthrough(p).round(5).to_csv(OUTPUT / "passthrough.csv", index=False)
    by_effects(p).round(5).to_csv(OUTPUT / "by_effects.csv", index=False)
    where_it_goes(p).round(5).to_csv(OUTPUT / "where_it_goes.csv", index=False)
    timing(p).round(5).to_csv(OUTPUT / "timing.csv", index=False)
    instrumented(p).round(5).to_csv(OUTPUT / "instrumented.csv", index=False)
    w = worker_regressions()
    w["table"].round(6).to_csv(OUTPUT / "worker_regressions.csv", index=False)
    pd.concat([wage_change(FIRST_MICRO, LAST_YEAR), wage_change(FIRST_MICRO, 2019)]).round(5).to_csv(OUTPUT / "wage_change.csv", index=False)
    sensitivity(p, w["cells"]).round(5).to_csv(OUTPUT / "sensitivity.csv", index=False)
    comp, stats = composition(w["cells"])
    pd.Series(stats).round(5).rename("value").rename_axis("measure").reset_index().to_csv(OUTPUT / "composition_summary.csv", index=False)
    slopes = sector_slopes(p).set_index("sector")
    table = s.join(comp.drop(columns="weight")).join(slopes[["coefficient", "low", "high"]])
    table["pay_gap"] = table["real survey wage"] - table.productivity
    table.round(5).rename_axis("sector").to_csv(OUTPUT / "sectors.csv")
    dispersion(s).round(4).to_csv(OUTPUT / "dispersion.csv", index=False)
    d, slope = spread(s)
    d.round(5).to_csv(OUTPUT / "spread.csv", index=False)
    pd.DataFrame([dict(measure="cross-sector slope of survey pay growth on productivity growth", value=round(slope, 4))]).to_csv(OUTPUT / "cross_sector_slope.csv", index=False)
    correlates(table).round(3).to_csv(OUTPUT / "correlates.csv", index=False)
    print("written to", OUTPUT)
