# Proposed website text

For the website session. Nothing here has been published to the site. Figures are in `figures/` in this repository. Suggested page name: `canada-productivity-wages.html`.

## Portfolio entry

**Productivity and pay by sector in Canada**

Open-data study, 2026 (from an SFU labour economics proposal)

Whether pay in Canada follows productivity, across 13 business sectors and 10 provinces from 1997 to 2024, using Statistics Canada tables and 8.1 million public survey records. Over the whole period, compensation and productivity grew by about the same amount, but a sector's own productivity gains show up mostly in lower relative prices, with little in its workers' pay. Education and minimum wages account for more of the rise in pay since 2006 than sector productivity does.

Repository: https://github.com/atamalfuzi/canada_productivity_wages

## Project page

### Productivity and pay by sector in Canada

This began as a proposal for my labour economics course at Simon Fraser University. It had no results, because it depended on restricted survey access. This version answers its three questions from open data: Statistics Canada's productivity and labour tables for 1997 to 2024, and Labour Force Survey public files for 2006 to 2024. It also changes parts of the design, including the standard errors, the deflators and the treatment of minimum wages. These results describe how pay and productivity move together. They are not causal estimates.

**Figure: `figures/aggregate.png`**

#### How much of wage gains come from productivity?

Across the 13 sectors, productivity rose 30.9 log points from 1997 to 2024, and real compensation per hour rose 31.4. The match depends on the end date: through 2019, compensation had risen 24.2 against 29.0 for productivity, and the gap closed only after 2019.

Within a sector and province, compared with others in the same province and year, the picture is different. A 1% rise in productivity comes with −0.01% in the survey wage over five years (95% range −0.06 to 0.04), and 0.15% in national accounts compensation per hour (0.08 to 0.31), which shares its hours with productivity. Measured in the sector's own output prices, as Feldstein (2008) recommends, the figures are 0.41% and 0.56%.

#### Is productivity the main driver?

Real pay rose 22.1 log points from 2006 to 2024. A regression on 8.1 million worker records attributes 5% of that to sector productivity, 25% to education and 18% to minimum wages. Another 44% is common to all sectors and may include economy-wide productivity growth, so the range for productivity is 5% to about half. The design can't narrow it.

**Figure: `figures/wage_change.png`**

Productivity here is measured by sector, province and year, so every worker in a cell shares it. Robust errors, which the proposal planned to use, would make the estimate look about 18 times as precise as clustering by sector does.

**Figure: `figures/clustering.png`**

#### Why do sectors differ?

Sector productivity growth differs far more than pay growth. Of the variance in productivity growth across sectors, 77% lines up with relative output prices, 12% with real compensation and 11% with the labour share. This fits Baumol's (1967) account: workers can move between sectors, so pay grows at similar rates, and slower sectors' prices rise instead.

**Figure: `figures/sectors.png`**

Holding worker characteristics fixed removes 52% of the variance in pay levels across sectors, but 17% of the variance in pay growth. Pass-through is highest in labour-intensive services, though measured productivity there may partly reflect pay.

**Figure: `figures/passthrough.png`**

#### What this can't show

Higher pay can raise measured productivity, common shocks can move both, and sector comparisons can't show how far economy-wide gains reach workers as a whole. Timing tests and instruments (the same sector in other provinces and in the US) find no sign of reverse causality, but their ranges are wide and they can't rule it out.

Python, with pandas and SciPy. Data: Statistics Canada tables 36-10-0480, 36-10-0489, 14-10-0064, 14-10-0132 and 18-10-0004, Labour Force Survey public microdata, the Government of Canada minimum wage database, and the US Bureau of Economic Analysis.

### Figures to use

| File | Where | Alt text |
|---|---|---|
| `figures/aggregate.png` | Top of page | Productivity, real compensation and real survey wages since 1997, ending at 30.9, 31.4 and 27.2 log points. |
| `figures/wage_change.png` | Second question | The 22.1 log point rise in pay from 2006 to 2024 split into education, other traits, minimum wage, mix, sector productivity, job type, union coverage and year effects. |
| `figures/clustering.png` | Second question | The same productivity estimate with much wider ranges as clustering moves from robust errors to the sector level. |
| `figures/sectors.png` | Third question | Sector productivity growth against real compensation (flat) and against relative output prices (falling). |
| `figures/passthrough.png` | Third question | Pass-through estimates and ranges for each of the 13 sectors. |

`figures/workers_mix.png` is also available if the page needs a chart on worker mix.
