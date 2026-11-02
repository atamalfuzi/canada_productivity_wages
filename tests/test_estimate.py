"""The panel arithmetic and the estimators, on made-up data. No downloads."""
import numpy as np
import pandas as pd
import pytest

import estimate
import panels
from data import SECTORS, SURVEY_SECTOR
from panels import PROV_LIST, SECTOR_LIST


def made_up_panel(seed=0, beta=0.3, years=range(1997, 2025)):
    """A sector, province, year panel where pay responds to productivity by beta."""
    rng = np.random.default_rng(seed)
    rows = []
    sector_trend = {s: rng.normal(0.01, 0.01) for s in SECTOR_LIST}
    for s in SECTOR_LIST:
        for p in PROV_LIST:
            lp = rng.normal(3, 0.3)
            for y in years:
                lp += sector_trend[s] + rng.normal(0, 0.03)
                lfs = beta * lp + 0.01 * (y - 1997) + rng.normal(0, 0.01)
                rows.append(dict(sector=s, prov=p, year=y, lp=lp, lfs=lfs, sna_wage=lfs, paid_comp_hr=lfs + 0.1, comp_hr=lfs + 0.2, price=0.0, share=-0.5,
                                 cpi=0.02 * (y - 1997), hours=1000 + rng.uniform(0, 500), lp_us=lp))
    return pd.DataFrame(rows)


def test_tornqvist_matches_one_part_and_equal_growth():
    real = pd.DataFrame({"a": [100.0, 110.0, 121.0]}, index=[2000, 2001, 2002])
    nominal = pd.DataFrame({"a": [100.0, 120.0, 150.0]}, index=real.index)
    assert panels.tornqvist(nominal, real).tolist() == pytest.approx([100, 110, 121])
    two_r = pd.DataFrame({"a": [100.0, 110.0], "b": [50.0, 55.0]}, index=[2000, 2001])
    two_n = pd.DataFrame({"a": [100.0, 100.0], "b": [50.0, 80.0]}, index=two_r.index)
    assert panels.tornqvist(two_n, two_r).tolist() == pytest.approx([150, 165])


def test_tornqvist_keeps_growing_after_nominal_values_stop():
    real = pd.DataFrame({"a": [100.0, 110.0, 121.0], "b": [100.0, 100.0, 100.0]}, index=[2020, 2021, 2022])
    nominal = pd.DataFrame({"a": [100.0, 100.0, np.nan], "b": [100.0, 100.0, np.nan]}, index=real.index)
    chain = panels.tornqvist(nominal, real)
    assert chain[2022] / chain[2021] == pytest.approx(np.exp(0.5 * np.log(1.1)))


def test_tornqvist_ignores_a_part_that_is_zero():
    real = pd.DataFrame({"a": [100.0, 110.0], "b": [0.0, 0.0]}, index=[2000, 2001])
    nominal = pd.DataFrame({"a": [100.0, 110.0], "b": [0.0, 0.0]}, index=real.index)
    assert panels.tornqvist(nominal, real).iloc[-1] == pytest.approx(110)


def test_add_logs_makes_the_accounting_identity_exact():
    rng = np.random.default_rng(1)
    rows = pd.DataFrame(rng.uniform(1, 100, (2, 9)), columns=["real", "hours", "nominal", "comp", "paid_comp", "paid_hours", "wage_bill", "lfs_wage", "cpi"])
    p = panels.add_logs(rows)
    r = estimate.accounting_row(p.iloc[0], p.iloc[1])
    terms = ["productivity", "labour share", "output prices vs CPI", "benefits", "self-employed", "survey vs accounts"]
    assert sum(r[t] for t in terms) == pytest.approx(r["real survey wage"])
    assert r["compensation in output prices"] == pytest.approx(r["productivity"] + r["labour share"])
    assert r["labour share and prices"] == pytest.approx(r["labour share"] + r["output prices vs CPI"])


def test_cluster_se_on_a_known_case():
    a = np.array([1.0, 3.0])
    b = np.array([1.0, 1.0])
    assert estimate.cluster_se(a, b) == pytest.approx(np.sqrt(2 * 2) / 2)


def test_wild_range_holds_the_truth_and_excludes_zero_for_a_clear_effect():
    rng = np.random.default_rng(0)
    b = rng.uniform(1, 2, 20)
    a = 0.5 * b + rng.normal(0, 0.05, 20)
    beta, low, high, p = estimate.wild_sums(a, b)
    assert low < 0.5 < high
    assert p < 0.05
    assert low > 0 and beta == pytest.approx(a.sum() / b.sum())


def test_wild_range_is_open_ended_for_a_useless_instrument():
    rng = np.random.default_rng(3)
    a = rng.normal(0, 1, 20)
    b = rng.normal(0, 1, 20) + 0.001
    _, low, high, _ = estimate.wild_sums(a, b)
    assert np.isinf(low) or np.isinf(high)


def test_fit_recovers_a_slope_despite_the_effects():
    q = estimate.changes(made_up_panel(), 1)
    r = estimate.fit(q, "d_lfs", "d_lp", estimate.MAIN_FE)
    assert r["coefficient"] == pytest.approx(0.3, abs=0.02)
    assert r["low"] < 0.3 < r["high"]
    assert r["clusters"] == 13


def test_shared_shocks_make_robust_errors_too_small():
    """Workers in the same sector and year share the same regressor and the same shock. That is the proposal's design problem."""
    rng = np.random.default_rng(0)
    frames = []
    for j, s in enumerate(SECTOR_LIST):
        for y in range(2000, 2020):
            frames.append(pd.DataFrame({"sector": s, "year": y, "prov": rng.choice(PROV_LIST, 40), "x": rng.normal(),
                                        "y": rng.normal() + rng.normal(0, 0.2, 40)}))
    t = pd.concat(frames, ignore_index=True)
    r = estimate.fit(t, "y", "x", weight=None)
    assert r["se_sector_year"] > 2 * r["se_robust"]


def test_instrument_undoes_a_reverse_feedback():
    """Pay shocks feed into measured productivity. Least squares is pulled up; the instrument isn't."""
    rng = np.random.default_rng(0)
    rows = []
    for s in SECTOR_LIST:
        for p in PROV_LIST:
            for y in range(2000, 2020):
                rows.append(dict(sector=s, prov=p, year=y, shock=rng.normal(), z=rng.normal(), noise=rng.normal()))
    t = pd.DataFrame(rows)
    t["x"] = t.z + 0.5 * t.shock + 0.3 * t.noise
    t["y"] = 0.1 * t.x + t.shock
    ols = estimate.fit(t, "y", "x", weight=None)["coefficient"]
    iv = estimate.fit(t, "y", "x", z="z", weight=None)
    assert ols > 0.4
    assert iv["coefficient"] == pytest.approx(0.1, abs=0.05)
    assert iv["first_stage_F"] > 10


def test_instruments_leave_out_the_own_province():
    q = pd.DataFrame({"sector": "a", "year": 2000, "prov": ["x", "y", "z"], "d_lp": [1.0, 2.0, 4.0], "weight": [1.0, 1.0, 2.0], "d_lp_us": 0.5})
    z = estimate.instruments(q).set_index("prov").z_other
    assert z["x"] == pytest.approx((2 + 8) / 3)
    assert z["z"] == pytest.approx(1.5)


def test_dispersion_shares_add_to_one():
    rng = np.random.default_rng(0)
    s = pd.DataFrame({"hours_share": rng.dirichlet(np.ones(13)), "real total compensation": rng.normal(0, 1, 13),
                      "labour share": rng.normal(0, 1, 13), "output prices vs CPI": rng.normal(0, 1, 13)}, index=SECTOR_LIST)
    s["productivity"] = s["real total compensation"] - s["labour share"] - s["output prices vs CPI"]
    assert estimate.dispersion(s).share_of_variance.sum() == pytest.approx(1)


def raw_workers(n, year, rng):
    """Records shaped like the cached survey files, with some the study must drop."""
    return pd.DataFrame({"SURVYEAR": year, "SURVMNTH": rng.integers(1, 13, n), "PROV": rng.choice([10, 11, 12, 13, 24, 35, 46, 47, 48, 59], n),
                         "AGE_12": rng.integers(1, 12, n), "GENDER": rng.integers(1, 3, n), "EDUC": rng.integers(0, 7, n), "MARSTAT": rng.integers(1, 7, n),
                         "IMMIG": rng.integers(1, 4, n), "SCHOOLN": rng.integers(1, 4, n), "NAICS_21": rng.integers(1, 22, n), "FTPTMAIN": rng.integers(1, 3, n),
                         "UNION": rng.integers(1, 4, n), "PERMTEMP": rng.integers(1, 5, n), "wage": rng.uniform(15, 40, n), "FINALWT": rng.uniform(50, 200, n)})


def fake_inputs():
    months = pd.date_range("2006-01-01", "2024-12-01", freq="MS")
    provs = [p for p in PROV_LIST]
    mw = pd.DataFrame([dict(prov=p, date=m, mw=8 + 0.4 * (m.year - 2006) + 0.1 * i) for i, p in enumerate(provs) for m in months])
    prices = pd.DataFrame({"date": months, "cpi": 80 + (months.year - 2006) * 1.0})
    rng = np.random.default_rng(5)
    lp = pd.DataFrame([dict(sector=s, prov=p, year=y, lp=3 + rng.normal(0, 0.2)) for s in SECTOR_LIST for p in provs for y in range(2006, 2025)])
    return mw, prices, lp


def test_prepare_drops_people_outside_the_study_and_keeps_real_pay():
    mw, prices, lp = fake_inputs()
    d = panels.prepare(raw_workers(4000, 2010, np.random.default_rng(0)), mw, prices, lp)
    assert (d.AGE_12 <= 10).all()
    assert not d.NAICS_21.isin([16, 17, 21]).any()
    assert d.sector.isin(SECTORS).all()
    assert d.union.isin([0, 1]).all()
    row = d.iloc[0]
    assert row.y == pytest.approx(np.log(row.wage * 100 / row.cpi))
    assert set(SURVEY_SECTOR) >= set(d.NAICS_21.astype(int))


def test_design_matches_its_names_and_codes_a_worker_correctly():
    mw, prices, lp = fake_inputs()
    d = panels.prepare(raw_workers(4000, 2010, np.random.default_rng(0)), mw, prices, lp)
    X = panels.design(d).toarray()
    names = panels.column_names()
    assert X.shape == (len(d), len(names))
    row = pd.Series(X[0], index=names.name)
    w = d.iloc[0]
    assert row["constant"] == 1
    assert row["lp"] == pytest.approx(w.lp)
    assert row.get("gender=2") == (w.GENDER == 2)
    assert row.get("year=2010") == 1
    assert row.get("union=1") == w.union


def test_worker_regressions_recover_the_truth_and_the_change_adds_up(tmp_path, monkeypatch):
    """Build years of made-up workers whose pay depends on productivity by 0.25, then run the whole worker section."""
    mw, prices, lp = fake_inputs()
    effect = {(s, p): v for (s, p), v in zip([(s, p) for s in SECTOR_LIST for p in PROV_LIST], np.random.default_rng(1).normal(0, 0.05, 130))}

    def years():
        for y in range(2006, 2025):
            rng = np.random.default_rng(y)
            d = panels.prepare(raw_workers(6000, y, rng), mw, prices, lp)
            noise = rng.normal(0, 0.02, len(d))
            year = 0.01 * (y - 2006)
            d["y"] = 2.5 + 0.25 * d.lp + 0.05 * d.union + 0.1 * (d.EDUC >= 5) + year + np.array([effect[k] for k in zip(d.sector, d.prov)]) + noise
            yield d

    monkeypatch.setattr(estimate, "worker_years", years)
    monkeypatch.setattr(estimate, "CACHE", tmp_path)
    out = estimate.worker_regressions()
    t = out["table"].set_index(["spec", "variable"])
    main = t.loc[(estimate.MAIN_SPEC, "lp")]
    assert main.coefficient == pytest.approx(0.25, abs=0.01)
    assert main.se_robust > 0 and main.se_sector > 0
    assert t.loc[(estimate.MAIN_SPEC, "union")].coefficient == pytest.approx(0.05, abs=0.01)
    change = estimate.wage_change(2006, 2024)
    main_change = change[change.spec == estimate.MAIN_SPEC].set_index("part").change
    assert abs(main_change["Not explained"]) < 1e-8
    assert out["cells"].adjusted.notna().all()
    comp, stats = estimate.composition(out["cells"])
    assert len(comp) == 13
    assert stats["level_sd_adjusted"] >= 0
