"""Reading the survey files, minimum wages and tables. No downloads."""
import io
import zipfile

import pandas as pd
import pytest

import data


def row(prov_id, date, amount, flag=1, variation=None):
    return dict(prov_prov_id=prov_id, effective_date=f"{date} 00:00:00", minimum_wage_amount=amount, minimum_wage_ind=flag,
                mwv_minimum_wage_variation_id=variation)


PROVINCES = [dict(prov_id=1, province_code="ON"), dict(prov_id=2, province_code="BC"), dict(prov_id=3, province_code="AB")]


def rates(*wages):
    return data.general_rates(dict(wages=list(wages), provinces=PROVINCES))


def test_general_rates_keep_flagged_rows_and_skip_special_rates():
    r = rates(row(1, "2018/01/01", 14.0), row(1, "2018/01/01", 13.15, flag=0, variation=7))
    assert r.mw.tolist() == [14.0]


def test_general_rates_fix_the_bc_date_typo_and_drop_the_stray_alberta_row():
    r = rates(row(2, "2026/06/01", 17.85), row(3, "2005/02/28", 1.99), row(3, "2005/09/01", 7.0))
    assert r[r.prov == "BC"].start.iloc[0] == pd.Timestamp("2025-06-01")
    assert r[r.prov == "AB"].mw.tolist() == [7.0]


def test_monthly_rates_use_the_rate_in_force_on_the_15th():
    steps = pd.DataFrame({"prov": ["ON", "ON"], "start": pd.to_datetime(["2017-10-01", "2018-01-16"]), "mw": [11.6, 14.0]})
    m = data.monthly_rates(steps, first="2018-01-01", last="2018-02-01").set_index("date").mw
    assert m[pd.Timestamp("2018-01-01")] == 11.6
    assert m[pd.Timestamp("2018-02-01")] == 14.0


def test_read_year_keeps_employees_and_converts_pay(tmp_path):
    rows = "SURVYEAR,SURVMNTH,PROV,SEX,HRLYEARN,FINALWT,UNION\n2006,1,35,1,2550,100,3\n2006,1,35,2,,100,\n"
    path = tmp_path / "2006.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("pub0106.csv", rows)
    d = data.read_year(path)
    assert len(d) == 1
    assert d.wage.iloc[0] == pytest.approx(25.5)
    assert "GENDER" in d


def test_code_reads_the_bracket_at_the_end_of_a_label():
    assert data.code("Utilities [BS22]") == "BS22"
    assert data.code("Business sector industries") is None


def test_every_survey_code_belongs_to_one_sector_and_non_market_sectors_are_out():
    codes = [c for s in data.SECTORS.values() for c in s[2]]
    assert len(codes) == len(set(codes))
    assert set(codes) == set(range(1, 22)) - {16, 17, 21}    # education, health, public administration


def test_each_sector_lists_matching_table_codes():
    for s in data.SECTORS.values():
        assert len(s[0]) == len(s[1])


def test_bea_rows_read_a_sheet_and_strip_footnotes(tmp_path):
    sheet = pd.DataFrame([["Title", None, None, None], ["Line", None, 1998, 1999], [1, "    Farms\\2\\", 10, 20], [2, "Farms", 30, 40],
                          [3, "  Mining", 5, 6]])
    path = tmp_path / "bea.xlsx"
    sheet.to_excel(path, sheet_name="T", header=False, index=False)
    r = data.bea_rows(path, "T")
    assert r.loc["Farms", 1999] == 20    # the first row of a repeated name is the sector total
    assert r.loc["Mining", 1998] == 5


def test_table_reads_columns_by_short_name(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "RAW", tmp_path)
    buffer = io.StringIO("REF_DATE,GEO,Thing,VALUE,Other\n2000,Canada,a,1.5,x\n")
    with zipfile.ZipFile(tmp_path / "123.zip", "w") as z:
        z.writestr("123.csv", buffer.getvalue())
    d = data.table("123", {"Thing": "thing"})
    assert list(d.iloc[0][["year", "geo", "thing", "value"]]) == [2000, "Canada", "a", 1.5]
