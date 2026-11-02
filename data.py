"""Get the Statistics Canada tables, the public Labour Force Survey files, minimum wages and US sector data, and read them.

The survey, minimum wage and CPI readers come from https://github.com/atamalfuzi/canada_minimum_wage (data.py). The changes:
more survey columns, employees only, files through 2024 only, and the CPI back to 1997.
"""
import http.client
import json
import re
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
RAW, CACHE = ROOT / "data" / "raw", ROOT / "data" / "cache"
OUTPUT, FIGURES = ROOT / "output", ROOT / "figures"
PUMF = "https://www150.statcan.gc.ca/n1/pub/71m0001x/"
WAGES = "https://minwage-salairemin.service.canada.ca/en/data/minimum_wage.json"
TABLE = "https://www150.statcan.gc.ca/n1/tbl/csv/{}-eng.zip"
PRODUCTIVITY, LABOUR, LFS_WAGES, UNIONS, PRICES = "36100480", "36100489", "14100064", "14100132", "18100004"
BEA_OUTPUT = "https://apps.bea.gov/industry/Release/XLS/GDPxInd/ValueAdded.xlsx"
BEA_JOBS = "https://apps.bea.gov/national/Release/XLS/Survey/Section6All_xls.xlsx"
FIRST_YEAR, LAST_YEAR, FIRST_MICRO = 1997, 2024, 2006    # productivity runs 1997-2024; public survey files start in 2006
PROVS = {10: "NL", 11: "PE", 12: "NS", 13: "NB", 24: "QC", 35: "ON", 46: "MB", 47: "SK", 48: "AB", 59: "BC"}
NAMES = {"NL": "Newfoundland and Labrador", "PE": "Prince Edward Island", "NS": "Nova Scotia", "NB": "New Brunswick",
         "QC": "Quebec", "ON": "Ontario", "MB": "Manitoba", "SK": "Saskatchewan", "AB": "Alberta", "BC": "British Columbia"}
KEEP = ["SURVYEAR", "SURVMNTH", "PROV", "AGE_12", "GENDER", "SEX", "EDUC", "MARSTAT", "IMMIG", "SCHOOLN", "NAICS_21",
        "FTPTMAIN", "UNION", "PERMTEMP", "HRLYEARN", "FINALWT"]

# The 13 business sectors all three sources can report. Education, health and public administration are left out because
# much of their output is measured from what they spend on staff, which makes their productivity partly a measure of pay.
# Each sector: productivity table codes, labour table codes, survey codes, the wage table's label, then US output and job lines.
SECTORS = {
    "Agriculture": (["BS11A", "BS115A"], ["11A", "115A"], [1], "Agriculture [111-112, 1100, 1151-1152]",
                    ["Farms"], ["Farms"]),
    "Mining, oil, forestry, fishing": (["BS113", "BS114", "BS1153", "BS21"], ["113", "114", "1153", "21"], [2, 3, 4],
                                       "Forestry, fishing, mining, quarrying, oil and gas [21, 113-114, 1153, 2100]",
                                       ["Mining", "Forestry, fishing, and related activities"],
                                       ["Mining", "Forestry, fishing, and related activities"]),
    "Utilities": (["BS22"], ["22"], [5], "Utilities [22]", ["Utilities"], ["Utilities"]),
    "Construction": (["BS23"], ["23"], [6], "Construction [23]", ["Construction"], ["Construction"]),
    "Manufacturing": (["BS3A"], ["31-33"], [7, 8], "Manufacturing [31-33]", ["Manufacturing"], ["Manufacturing"]),
    "Wholesale and retail": (["BS41", "BS4A"], ["41", "44-45"], [9, 10], "Wholesale and retail trade [41, 44-45]",
                             ["Wholesale trade", "Retail trade"], ["Wholesale trade", "Retail trade"]),
    "Transport and warehousing": (["BS4B"], ["48-49"], [11], "Transportation and warehousing [48-49]",
                                  ["Transportation and warehousing"], ["Transportation and warehousing"]),
    # US housing is left out of output because Canada's business sector excludes owner-occupied dwellings.
    "Finance and real estate": (["BS52", "BS53"], ["52", "53"], [12, 13], "Finance, insurance, real estate, rental and leasing [52-53]",
                                ["Finance and insurance", "Other real estate",
                                 "Rental and leasing services and lessors of intangible assets"],
                                ["Finance and insurance", "Real estate and rental and leasing"]),
    "Professional services": (["BS54"], ["54"], [14], "Professional, scientific and technical services [54]",
                              ["Professional, scientific, and technical services"],
                              ["Professional, scientific, and technical services"]),
    "Business support": (["BS56"], ["56"], [15], "Business, building and other support services [55-56]",
                         ["Administrative and waste management services"], ["Administrative and waste management services"]),
    "Information and recreation": (["BS51", "BS71"], ["51", "71"], [18], "Information, culture and recreation [51, 71]",
                                   ["Information", "Arts, entertainment, and recreation"],
                                   ["Information", "Arts, entertainment, and recreation"]),
    "Accommodation and food": (["BS72"], ["72"], [19], "Accommodation and food services [72]",
                               ["Accommodation and food services"], ["Accommodation and food services"]),
    "Other services": (["BS81"], ["81"], [20], "Other services (except public administration) [81]",
                       ["Other services, except government"], ["Other services, except government"]),
}
SURVEY_SECTOR = {code: name for name, s in SECTORS.items() for code in s[2]}


def get(url, timeout=300, tries=3):
    """One dropped connection shouldn't end a 640 MB download."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as r:
                return r.read()
        except (OSError, http.client.HTTPException):
            if attempt == tries:
                raise
            time.sleep(30)


def fetch(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(url))
    return path


def download():
    """The survey files for 2006 to 2024 and the other sources, about 700 MB the first time."""
    page = get(PUMF + "71m0001x2021001-eng.htm", timeout=60).decode("utf-8", "ignore")
    for link in sorted(set(re.findall(r'href="(2021001/hist/(\d{4})-CSV\.zip)"', page))):
        if FIRST_MICRO <= int(link[1]) <= LAST_YEAR:
            fetch(PUMF + link[0], RAW / f"{link[1]}.zip")
    fetch(WAGES, RAW / "minimum_wage.json")
    for table in (PRODUCTIVITY, LABOUR, LFS_WAGES, UNIONS, PRICES):
        fetch(TABLE.format(table), RAW / f"{table}.zip")
    fetch(BEA_OUTPUT, RAW / "bea_value_added.xlsx")
    fetch(BEA_JOBS, RAW / "bea_nipa6.xlsx")


def read_year(path):
    frames = []
    with zipfile.ZipFile(path) as z:
        for name in sorted(n for n in z.namelist() if re.search(r"pub\d{4}\.csv$", n, re.I)):
            with z.open(name) as f:
                frames.append(pd.read_csv(f, usecols=lambda c: c.upper() in KEEP))
    d = pd.concat(frames, ignore_index=True)
    d.columns = d.columns.str.upper()
    d = d.rename(columns={"SEX": "GENDER"})    # the older files' name for it
    d = d[d.HRLYEARN.notna()]                  # only employees report pay
    for c in d.columns.difference(["FINALWT", "HRLYEARN"]):
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("float32")
    d["wage"] = (d.pop("HRLYEARN") / 100).astype("float32")
    d["FINALWT"] = d.FINALWT.astype("float32")
    return d


def survey():
    """One pickle per year, so the slow CSV read happens once."""
    out = []
    for year in range(FIRST_MICRO, LAST_YEAR + 1):
        cached = CACHE / f"{year}.pkl"
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            read_year(RAW / f"{year}.zip").to_pickle(cached)
        out.append(cached)
    return out


def rate_rows(data):
    """Every row of the database's JSON, with its province and start date."""
    w, p = pd.DataFrame(data["wages"]), pd.DataFrame(data["provinces"])
    w = w.merge(p[["prov_id", "province_code"]], left_on="prov_prov_id", right_on="prov_id")
    w["prov"] = w.province_code.replace({"NF": "NL"})
    w["start"] = pd.to_datetime(w.effective_date.str[:10], format="%Y/%m/%d")
    return w


def general_rows(data):
    """The rows that set a general rate, with the database's known errors corrected."""
    w = rate_rows(data)
    # The database's general-rate flag misses these rows, which have no special category attached.
    missed = {("ON", "2023-10-01"), ("MB", "2023-10-01"), ("SK", "2023-10-01"), ("PE", "2024-04-01"), ("NB", "2009-04-15")}
    added = w.mwv_minimum_wage_variation_id.isna() & pd.Series(
        [(a, str(b.date())) in missed for a, b in zip(w.prov, w.start)], index=w.index)
    w = w[(w.minimum_wage_ind == 1) | added].copy()
    # One BC row is dated 2026-06-01 and expires 2025-06-01: its start year is a typo for 2025.
    w.loc[(w.prov == "BC") & (w.minimum_wage_amount == 17.85), "start"] = pd.Timestamp("2025-06-01")
    # One Alberta row is a stray $1.99 dated 2005.
    return w[w.prov.isin(PROVS.values()) & (w.minimum_wage_amount >= 2.5)]


def general_rates(data):
    """The general hourly rate for each province and start date, from the database's JSON."""
    w = general_rows(data)[["prov", "start", "minimum_wage_amount"]].rename(columns={"minimum_wage_amount": "mw"})
    return w.drop_duplicates(["prov", "start"]).sort_values(["prov", "start"])


def monthly_rates(steps, first="1997-01-01", last=f"{LAST_YEAR}-12-01"):
    """The rate in force on the 15th of each month, since the survey's reference week holds the 15th."""
    months = pd.date_range(first, last, freq="MS")
    rows = []
    for prov, g in steps.groupby("prov"):
        s = g.set_index("start").mw
        rows.append(pd.DataFrame({"prov": prov, "date": months, "mw": s.reindex(months + pd.Timedelta(days=14), method="ffill").values}))
    return pd.concat(rows, ignore_index=True)


def minimum_wage():
    return monthly_rates(general_rates(json.loads((RAW / "minimum_wage.json").read_text(encoding="utf-8-sig"))["data"]))


def cpi():
    """All-items CPI for Canada, 2024 average = 100."""
    with zipfile.ZipFile(RAW / f"{PRICES}.zip") as z, z.open(f"{PRICES}.csv") as f:
        c = pd.read_csv(f, usecols=["REF_DATE", "GEO", "Products and product groups", "VALUE"])
    c = c[(c.GEO == "Canada") & (c["Products and product groups"] == "All-items")]
    c = pd.DataFrame({"date": pd.to_datetime(c.REF_DATE), "cpi": c.VALUE.astype(float)}).sort_values("date")
    c = c[c.date >= f"{FIRST_YEAR}-01-01"]
    c["cpi"] /= c[c.date.dt.year == LAST_YEAR].cpi.mean() / 100
    return c


def table(number, columns):
    """One Statistics Canada table with short column names."""
    with zipfile.ZipFile(RAW / f"{number}.zip") as z, z.open(f"{number}.csv") as f:
        return pd.read_csv(f, usecols=list(columns) + ["REF_DATE", "GEO", "VALUE"]).rename(
            columns={**columns, "REF_DATE": "year", "GEO": "geo", "VALUE": "value"})


def code(label):
    """'Utilities [BS22]' gives BS22; a label with no code gives nothing."""
    found = re.search(r"\[([^\]]+)\]$", label)
    return found.group(1) if found else None


def productivity_table():
    """Hours, compensation and value added for each productivity table code."""
    d = table(PRODUCTIVITY, {"Labour productivity and related measures": "measure", "Industry": "industry"})
    keep = {"Hours worked for all jobs": "hours", "Total compensation for all jobs": "comp",
            "Nominal value added": "nominal", "Real value added": "real"}
    d = d[d.measure.isin(keep)]
    d["measure"] = d.measure.map(keep)
    d["code"] = d.industry.map({i: code(i) for i in d.industry.unique()})
    return d


def labour_table():
    """Paid-worker hours, wages and compensation for each labour table code."""
    d = table(LABOUR, {"Labour statistics": "measure", "North American Industry Classification System (NAICS)": "industry"})
    keep = {"Hours worked for paid workers jobs": "paid_hours", "Compensation of paid workers": "paid_comp",
            "Wages and Salaries": "wage_bill"}
    d = d[d.measure.isin(keep)]
    d["measure"] = d.measure.map(keep)
    d["code"] = d.industry.map({i: code(i) for i in d.industry.unique()})
    return d


def wage_table():
    """Average hourly pay and employees from the survey's published table, which starts in 1997."""
    d = table(LFS_WAGES, {"Wages": "measure", "Type of work": "work", "North American Industry Classification System (NAICS)": "industry",
                          "Gender": "gender", "Age group": "age"})
    d = d[(d.work == "Both full- and part-time employees") & (d.gender == "Total - Gender") & (d.age == "15 years and over")
          & d.measure.isin(["Average hourly wage rate", "Total employees, all wages"])]
    labels = {s[3]: name for name, s in SECTORS.items()}
    d = d.assign(sector=d.industry.map(labels), measure=d.measure.map({"Average hourly wage rate": "lfs_wage", "Total employees, all wages": "employees"}))
    return d.dropna(subset=["sector"]).pivot_table(index=["sector", "geo", "year"], columns="measure", values="value").reset_index()


def union_table():
    """Share of employees covered by a collective agreement, by sector across Canada."""
    d = table(UNIONS, {"Union status": "status", "North American Industry Classification System (NAICS)": "industry", "Gender": "gender"})
    d = d[(d.status == "Union coverage rate (by a collective agreement)") & (d.gender == "Total - Gender")]
    labels = {s[3].replace(", ", ","): name for name, s in SECTORS.items()}
    return d.assign(sector=d.industry.str.replace(", ", ",").map(labels)).dropna(subset=["sector"])[["sector", "year", "value"]].rename(
        columns={"value": "coverage"})


def bea_rows(path, sheet):
    """A BEA sheet as a table of years by line name, keeping the first row of each name."""
    d = pd.read_excel(path, sheet_name=sheet, header=None, engine="openpyxl")
    head = d.index[d[0].astype(str).str.strip() == "Line"][0]
    columns = {c: int(d.loc[head, c]) for c in d if pd.notna(d.loc[head, c]) and d.loc[head, c] != "Line"}
    rows = d.loc[head + 1:].dropna(subset=[1])
    names = rows[1].astype(str).str.replace(r"\\.*$", "", regex=True).str.strip()
    return rows[list(columns)].rename(columns=columns).astype(float).set_index(names).groupby(level=0, sort=False).first()


def us_productivity():
    """Real value added per full-time equivalent employee in each sector in the US, from BEA."""
    real = bea_rows(RAW / "bea_value_added.xlsx", "TVA106-A")
    jobs = bea_rows(RAW / "bea_nipa6.xlsx", "T60500D-A")
    years = sorted(set(real.columns) & set(jobs.columns))
    rows = []
    for name, s in SECTORS.items():
        output, workers = real.loc[s[4], years].sum(), jobs.loc[s[5], years].sum()
        rows.append(pd.DataFrame({"sector": name, "year": years, "lp_us": (output / workers).values}))
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    download()
    print(len(survey()), "survey files ready")
