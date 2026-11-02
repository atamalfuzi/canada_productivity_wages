"""Build the sector panel (sector, province, year, 1997-2024) and the worker-level design matrices (2006-2024)."""
import numpy as np
import pandas as pd
from scipy import sparse

from data import (CACHE, FIRST_YEAR, LAST_YEAR, NAMES, PROVS, SECTORS, SURVEY_SECTOR, cpi, labour_table, minimum_wage,
                  productivity_table, survey, us_productivity, wage_table)

GEO = {"Canada": "CA", **{name: abbr for abbr, name in NAMES.items()}}
SECTOR_LIST = list(SECTORS)
PROV_LIST = list(PROVS.values())


def tornqvist(nominal, real):
    """Chain real value added across parts of a sector. Chained dollars can't be added up, so each part's growth is
    weighted by its average share of nominal value added. Parts that are zero or missing in either year get no weight."""
    growth = np.log(real.where(real > 0)).diff()
    share = nominal.div(nominal.sum(axis=1, min_count=1), axis=0).ffill()    # the newest year has real output but no nominal yet
    weight = ((share + share.shift()) / 2).where(growth.notna(), 0)
    chain = (growth.fillna(0) * weight).sum(axis=1) / weight.sum(axis=1).replace(0, np.nan)
    return real.iloc[0].sum() * np.exp(chain.fillna(0).cumsum())


def combine(wide):
    """Add up one sector and place's parts: wide has measures in columns, for (code, year) rows."""
    out = wide.groupby("year")[[c for c in wide if c not in ("code", "year", "real", "nominal")]].sum(min_count=1)
    n = wide.pivot(index="year", columns="code", values="nominal")
    r = wide.pivot(index="year", columns="code", values="real")
    out["nominal"] = n.sum(axis=1, min_count=1)
    out["real"] = tornqvist(n, r)
    return out


def annual_prices():
    c = cpi()
    return np.log(c.groupby(c.date.dt.year).cpi.mean()).rename("cpi").rename_axis("year").reset_index()


def annual_minimum():
    """Log general minimum wage in each province, the average of its months, in 2024 dollars."""
    m = minimum_wage().merge(cpi(), on="date")
    m["lmw"] = np.log(m.mw * 100 / m.cpi)
    return m.groupby(["prov", m.date.dt.year.rename("year")]).lmw.mean().reset_index()


def add_logs(p):
    """Everything is in logs, so the accounting identities in estimate.py are sums."""
    p["lp"] = np.log(p.real / p.hours)
    p["price"] = np.log(p.nominal / p.real)
    p["share"] = np.log(p.comp / p.nominal)
    p["comp_hr"] = np.log(p.comp / p.hours)
    p["paid_comp_hr"] = np.log(p.paid_comp / p.paid_hours)
    p["sna_wage"] = np.log(p.wage_bill / p.paid_hours)
    p["lfs"] = np.log(p.lfs_wage)
    return p


def sector_panel(rebuild=False):
    """One row per sector, place and year. Place is a province or CA for Canada. Territories are out: the survey and its
    wage table don't cover them."""
    path = CACHE / "sector_panel.pkl"
    if path.exists() and not rebuild:
        return pd.read_pickle(path)
    prod = productivity_table().pivot_table(index=["geo", "code", "year"], columns="measure", values="value").reset_index()
    labour = labour_table().pivot_table(index=["geo", "code", "year"], columns="measure", values="value").reset_index()
    rows = []
    for name, s in SECTORS.items():
        for geo, abbr in GEO.items():
            a = combine(prod[(prod.geo == geo) & prod.code.isin(s[0])].drop(columns="geo"))
            b = labour[(labour.geo == geo) & labour.code.isin(s[1])].groupby("year")[["paid_hours", "paid_comp", "wage_bill"]].sum(min_count=1)
            rows.append(a.join(b).assign(sector=name, geo=geo, prov=abbr).reset_index())
    p = pd.concat(rows, ignore_index=True).merge(wage_table(), on=["sector", "geo", "year"], how="left")
    p = add_logs(p.merge(annual_prices(), on="year"))
    us = us_productivity()
    p = p.merge(us.assign(lp_us=np.log(us.lp_us)), on=["sector", "year"], how="left").merge(annual_minimum(), on=["prov", "year"], how="left")
    p = p[p.year.between(FIRST_YEAR, LAST_YEAR)].sort_values(["sector", "prov", "year"]).reset_index(drop=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.to_pickle(path)
    return p


def business_total(p):
    """The 13 sectors added up for Canada, one row per year."""
    c = p[p.prov == "CA"]
    n = c.pivot(index="year", columns="sector", values="nominal")
    r = c.pivot(index="year", columns="sector", values="real")
    t = c.groupby("year")[["hours", "comp", "paid_hours", "paid_comp", "wage_bill", "employees"]].sum()
    t["nominal"], t["real"] = n.sum(axis=1, min_count=1), tornqvist(n, r)
    t["lfs_wage"] = c.assign(v=c.lfs_wage * c.employees).groupby("year").v.sum() / t.employees
    return add_logs(t.join(c.groupby("year").cpi.first())).reset_index()


# Worker-level regressors. Each group lists a survey variable's levels; the first level of each is the base.
PERSON = {"age": ("AGE_12", list(range(1, 11))), "gender": ("GENDER", [1, 2]), "education": ("EDUC", list(range(7))),
          "marital": ("marital", [1, 2, 3]), "immigrant": ("IMMIG", [3, 1, 2]), "student": ("student", [0, 1])}
JOB = {"full-time": ("fulltime", [0, 1]), "permanent": ("permanent", [0, 1])}
GROUPS = {**PERSON, **JOB, "union": ("union", [0, 1]), "sector": ("sector_id", list(range(len(SECTOR_LIST)))),
          "province": ("prov_id", list(range(len(PROV_LIST)))),
          "sector x province": ("cell_id", list(range(len(SECTOR_LIST) * len(PROV_LIST)))),
          "year": ("year", list(range(2006, LAST_YEAR + 1)))}
NUMERIC = ["lp", "lmw"]


def prepare(d, mw, prices, lp):
    """Employees aged 15 to 64 in the 13 sectors, with the regressors the design needs."""
    d = d[(d.AGE_12 <= 10) & d.NAICS_21.isin(SURVEY_SECTOR) & (d.wage > 0)].copy()
    d["year"] = d.SURVYEAR.astype(int)
    d["date"] = pd.to_datetime(dict(year=d.year, month=d.SURVMNTH.astype(int), day=1))
    d["prov"] = d.PROV.astype(int).map(PROVS)
    d["sector"] = d.NAICS_21.astype(int).map(SURVEY_SECTOR)
    d = d.merge(mw, on=["prov", "date"]).merge(prices, on="date").merge(lp, on=["sector", "prov", "year"])
    d["y"] = np.log(d.wage.astype(float) * 100 / d.cpi)
    d["lmw"] = np.log(d.mw * 100 / d.cpi)
    d["w"] = d.FINALWT.astype("float64")
    d["marital"] = np.select([d.MARSTAT.isin([1, 2]), d.MARSTAT.isin([3, 4, 5])], [1, 2], 3)
    d["student"] = d.SCHOOLN.isin([2, 3]).astype(int)
    d["fulltime"] = (d.FTPTMAIN == 1).astype(int)
    d["permanent"] = (d.PERMTEMP == 1).astype(int)
    d["union"] = d.UNION.isin([1, 2]).astype(int)
    d["sector_id"] = d.sector.map({s: i for i, s in enumerate(SECTOR_LIST)}).astype(int)
    d["prov_id"] = d.prov.map({s: i for i, s in enumerate(PROV_LIST)}).astype(int)
    d["cell_id"] = d.sector_id * len(PROV_LIST) + d.prov_id
    return d


def column_names():
    """Name and group of every column of design()."""
    names = [("constant", "constant")]
    for group, (_, levels) in GROUPS.items():
        names += [(f"{group}={v}", group) for v in levels[1:]]
    names += [(n, n) for n in NUMERIC]
    return pd.DataFrame(names, columns=["name", "group"])


def design(d):
    """All regressors for one set of workers as a sparse matrix, in the order of column_names()."""
    n = len(d)
    rows, cols, vals = [np.arange(n)], [np.zeros(n, dtype=int)], [np.ones(n)]
    start = 1
    for _, (var, levels) in GROUPS.items():
        where = pd.Series(range(-1, len(levels) - 1), index=levels).reindex(d[var].to_numpy()).to_numpy()    # base level is -1
        keep = where >= 0
        rows.append(np.arange(n)[keep])
        cols.append((start + where[keep]).astype(int))
        vals.append(np.ones(keep.sum()))
        start += len(levels) - 1
    for i, name in enumerate(NUMERIC):
        rows.append(np.arange(n))
        cols.append(np.full(n, start + i))
        vals.append(d[name].to_numpy(float))
    start += len(NUMERIC)
    return sparse.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, start))


def worker_years(panel=None):
    """One prepared year of workers at a time, since the whole file won't fit in memory here."""
    p = sector_panel() if panel is None else panel
    mw, prices = minimum_wage(), cpi()
    lp = p[p.prov != "CA"][["sector", "prov", "year", "lp"]]
    for path in survey():
        yield prepare(pd.read_pickle(path), mw, prices, lp)


if __name__ == "__main__":
    p = sector_panel(rebuild=True)
    q = p[p.prov != "CA"]
    print(q[["lp", "lfs", "comp_hr", "sna_wage", "paid_comp_hr"]].notna().mean().round(3).to_dict(), len(q))
    print(q[q.lp.isna() | q.lfs.isna()].groupby(["sector", "prov"]).size().sort_values().tail(12))
    print(len(survey()), "survey years ready")
