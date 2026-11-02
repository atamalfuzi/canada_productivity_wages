"""Draw the static charts from the tables in output/."""
import textwrap

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data import FIGURES, OUTPUT
from panels import business_total, sector_panel

INK, MUTED, GREY, GRID = "#0b0b0b", "#52514e", "#a8a7a2", "#e6e5e1"
BLUE, ORANGE = "#2a78d6", "#eb6834"
MINUS = "−"
plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
                     "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": MUTED,
                     "axes.grid": True, "grid.color": GRID, "axes.axisbelow": True, "legend.frameon": False,
                     "axes.titlelocation": "left", "axes.titlecolor": INK, "axes.titlesize": 12})
SOURCE = "Source: Statistics Canada tables 36-10-0480, 36-10-0489, 14-10-0064, 18-10-0004."
MICRO = "Source: Statistics Canada Labour Force Survey public microdata and table 36-10-0480; Government of Canada minimum wage database."


def save(fig, name, title, subtitle, caption):
    fig.text(0.015, 0.985, title, fontsize=15, fontweight="bold", color=INK, va="top")
    fig.text(0.015, 0.925, subtitle, color=MUTED, va="top")
    fig.text(0.015, 0.012, "\n".join(textwrap.wrap(caption, 138)), color=MUTED, fontsize=9, va="bottom")
    fig.savefig(FIGURES / name, dpi=200, facecolor="white")
    plt.close(fig)


def aggregate():
    t = business_total(sector_panel()).set_index("year")
    lines = {"Productivity": (t.lp, INK), "Real total compensation per hour": (t.comp_hr - t.cpi, BLUE),
             "Real survey wage": (t.lfs - t.cpi, ORANGE)}
    fig, ax = plt.subplots(figsize=(10, 5.6))
    fig.subplots_adjust(left=0.075, right=0.80, top=0.84, bottom=0.14)
    ends = []
    for name, (s, colour) in lines.items():
        v = (s - s.loc[1997]) * 100
        ax.plot(v.index, v, color=colour, lw=2, label=name)
        ends.append([name, v.iloc[-1]])
    ends.sort(key=lambda e: e[1])
    for i, (name, value) in enumerate(ends):
        ax.annotate(f"{name.replace(' per hour', '')}\n{value:+.1f}", (2024, value), xytext=(8, (i - 1) * 22), textcoords="offset points",
                    color=INK, va="center", fontsize=9.5)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_ylabel("Log points since 1997")
    ax.set_xlim(1997, 2024)
    ax.legend(loc="upper left")
    save(fig, "aggregate.png", "Over 27 years, compensation and productivity grew by about the same amount",
         "The 13 business sectors together, deflated by the CPI. The paths differ a lot along the way.",
         "Total compensation includes benefits and an estimate for the self-employed. The survey wage is employees' usual hourly pay. " + SOURCE)


def sector_points(ax, s, y):
    w = s.hours_share
    ax.scatter(s.productivity * 100, s[y] * 100, s=w * 2400, color=BLUE, alpha=0.75, edgecolor="white", linewidth=1.5, zorder=3)
    x = s.productivity
    b = (w * (x - (w * x).sum()) * s[y]).sum() / (w * (x - (w * x).sum()) ** 2).sum()
    a = (w * s[y]).sum() - b * (w * x).sum()
    xs = np.array([x.min(), x.max()])
    ax.plot(xs * 100, (a + b * xs) * 100, color=INK, lw=2, zorder=2)
    return b


def sectors():
    s = pd.read_csv(OUTPUT / "sectors.csv", index_col="sector")
    fig, axes = plt.subplots(1, 2, figsize=(11, 6), sharex=True)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.79, bottom=0.17, wspace=0.17)
    b = sector_points(axes[0], s, "real total compensation")
    c = sector_points(axes[1], s, "output prices vs CPI")
    axes[0].set_title(f"Real compensation per hour (slope {b:.2f})")
    axes[1].set_title(f"Output price against the CPI (slope {c:.2f})".replace("-", MINUS))
    axes[0].plot([0, 90], [0, 90], color=GREY, lw=1, ls=(0, (4, 3)), zorder=1)
    axes[0].annotate("one for one", (62, 62), xytext=(6, -14), textcoords="offset points", color=MUTED, fontsize=9)
    left = {"Agriculture": (-8, 8, "right"), "Wholesale and retail": (-6, -28, "left"), "Mining, oil, forestry, fishing": (8, 2, "left"),
            "Finance and real estate": (6, 12, "left"), "Business support": (-4, 12, "center"), "Manufacturing": (-8, -26, "center"),
            "Construction": (-14, -3, "right")}
    right = {"Agriculture": (-2, -36, "right"), "Wholesale and retail": (16, 8, "left"), "Mining, oil, forestry, fishing": (8, 2, "left"),
             "Finance and real estate": (8, 8, "left"), "Business support": (8, 8, "left"), "Manufacturing": (-16, -28, "center"),
             "Construction": (-14, -3, "right")}
    for ax, y, short in zip(axes, ("real total compensation", "output prices vs CPI"), (left, right)):
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_xlabel("Productivity growth, log points")
        ax.set_xlim(-20, 95)
        for name, (dx, dy, ha) in short.items():
            ax.annotate(name, (s.productivity[name] * 100, s[y][name] * 100), xytext=(dx, dy), textcoords="offset points",
                        fontsize=8.5, color=INK, ha=ha)
    axes[0].set_ylabel("Log points")
    d = pd.read_csv(OUTPUT / "dispersion.csv").set_index("part").share_of_variance
    save(fig, "sectors.png", "Sectors with faster productivity saw lower relative prices far more than higher pay",
         "Growth from 1997-99 to 2017-19 in each of 13 sectors. Circle area shows hours worked.",
         f"Of the differences between sectors in productivity growth, {d.iloc[2]:.0%} show up in output prices, {d.iloc[0]:.0%} in real compensation and "
         f"{d.iloc[1]:.0%} in the labour share. Slopes are hours-weighted. " + SOURCE)


def clustering():
    w = pd.read_csv(OUTPUT / "worker_regressions.csv")
    m = w[w.spec.str.startswith("D.") & (w.variable == "lp")].iloc[0]
    rows = [("Robust errors, as the proposal planned", m.se_robust), ("Clustered by sector, province and year", m.se_sector_province_year),
            ("Clustered by sector and year", m.se_sector_year), ("Clustered by sector", m.se_sector)]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    fig.subplots_adjust(left=0.33, right=0.97, top=0.78, bottom=0.26)
    for i, (name, se) in enumerate(rows):
        ax.plot([m.coefficient - 1.96 * se, m.coefficient + 1.96 * se], [i, i], color=BLUE, lw=2.5, solid_capstyle="round")
    ax.plot([m.low, m.high], [4, 4], color=ORANGE, lw=2.5, solid_capstyle="round")
    ax.scatter([m.coefficient] * 5, range(5), color=INK, s=44, zorder=3, edgecolor="white", linewidth=1.2)
    ax.set_yticks(range(5), [r[0] for r in rows] + ["Wild cluster bootstrap by sector"])
    ax.invert_yaxis()
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Change in pay for a 1% rise in sector productivity, %")
    save(fig, "clustering.png", f"Robust errors make the estimate look about {m.se_sector / m.se_robust:.0f} times as precise",
         f"The same coefficient from {m.n / 1e6:.1f} million worker records, with 95% ranges under each assumption.",
         "Productivity is measured by sector, province and year, so workers in the same cell share every shock to it. " + MICRO)


def wage_change():
    d = pd.read_csv(OUTPUT / "wage_change.csv")
    d = d[d.spec.str.startswith("D.") & (d.start == 2006) & (d.end == 2024)].set_index("part").change * 100
    workers = d[d.index.str.startswith("Worker characteristics")]
    jobs = d[d.index.str.startswith("Job type")]
    edu = workers["Worker characteristics: education"]
    rows = [("Education", edu), ("Other worker traits", workers.sum() - edu), ("Minimum wage", d["Minimum wage"]),
            ("Sector and province mix", d["Sector and province mix"]), ("Sector productivity", d["Sector productivity"]),
            ("Full-time and permanent jobs", jobs.sum()), ("Union coverage", d["Union coverage"]), ("Year effects: common to all", d["Year effects"])]
    fig, ax = plt.subplots(figsize=(10, 5.4))
    fig.subplots_adjust(left=0.27, right=0.95, top=0.82, bottom=0.23)
    start = 0
    for i, (name, v) in enumerate(rows):
        colour = GREY if name.startswith("Year") else (ORANGE if name == "Sector productivity" else BLUE)
        ax.barh(i, v, left=start, color=colour, height=0.62)
        ax.annotate(f"{v:+.1f}".replace("-", MINUS), (max(start, start + v), i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=10, color=INK)
        start += v
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Log points of real pay")
    ax.axvline(0, color=MUTED, lw=0.8)
    save(fig, "wage_change.png", f"Real pay rose {start:.1f} log points from 2006 to 2024: what the model attributes it to",
         "Each bar is an estimated coefficient times the change in that variable. An accounting, not proof of cause.",
         f"Year effects hold whatever moved all sectors and provinces together, which can include economy-wide productivity growth. Worker-weighted "
         f"productivity rose {d['Memo: change in worker-weighted log productivity']:.1f} log points, so the sector estimate passes through little of it. " + MICRO)


def passthrough():
    s = pd.read_csv(OUTPUT / "sectors.csv").sort_values("coefficient")
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.subplots_adjust(left=0.27, right=0.96, top=0.84, bottom=0.21)
    for i, r in enumerate(s.itertuples()):
        ax.plot([r.low, r.high], [i, i], color=BLUE, lw=2.5, solid_capstyle="round")
    ax.scatter(s.coefficient, range(len(s)), color=INK, s=44, zorder=3, edgecolor="white", linewidth=1.2)
    ax.set_yticks(range(len(s)), s.sector)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Change in the survey wage for a 1% rise in the sector's productivity, %")
    save(fig, "passthrough.png", "Pay follows productivity most in labour-intensive services",
         "Five-year changes within each sector, compared across provinces, with 95% ranges.",
         "Ten provinces per sector, so ranges come from a wild cluster bootstrap by province. In the upper sectors pay is most of value added and "
         "prices often lean on costs, so measured productivity may partly reflect pay. " + SOURCE)


def workers_mix():
    s = pd.read_csv(OUTPUT / "sectors.csv")
    w = s.hours_share
    raw = (s.raw_level - (w * s.raw_level).sum() / w.sum()) * 100
    adj = (s.adjusted_level - (w * s.adjusted_level).sum() / w.sum()) * 100
    order = raw.sort_values().index
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.subplots_adjust(left=0.27, right=0.96, top=0.84, bottom=0.17)
    for i, k in enumerate(order):
        ax.plot([raw[k], adj[k]], [i, i], color=GRID, lw=3, zorder=1)
    ax.scatter(raw[order], range(len(order)), color=ORANGE, s=60, label="As observed", zorder=3, edgecolor="white", linewidth=1.2)
    ax.scatter(adj[order], range(len(order)), color=BLUE, s=60, label="Same workers in every sector", zorder=3, edgecolor="white", linewidth=1.2)
    ax.set_yticks(range(len(order)), s.sector[order])
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    ax.set_xlabel("Pay compared with the average sector, log points")
    c = pd.read_csv(OUTPUT / "composition_summary.csv").set_index("measure").value
    level = 1 - (c.level_sd_adjusted / c.level_sd_raw) ** 2
    growth = 1 - (c.growth_sd_adjusted / c.growth_sd_raw) ** 2
    save(fig, "workers_mix.png", "Who works in a sector explains about half of its pay level",
         "Average pay in 2006-2024, as observed and holding age, gender, education, marital, immigrant and student status fixed.",
         f"The worker mix accounts for {level:.0%} of the variance in pay levels across sectors, but only {growth:.0%} of the variance in pay growth. " + MICRO)


if __name__ == "__main__":
    FIGURES.mkdir(exist_ok=True)
    aggregate()
    sectors()
    clustering()
    wage_change()
    passthrough()
    workers_mix()
