# AI Risk Radar

**Live page:** https://ai-data-market-radar.streamlit.app/?lang=en · [Українська версія](README_UA.md)

An open, automatically updated radar of **public signals** about how close frontier AI is to
**loss of human control**. It does not grade models or companies. It asks one question:
*what do public data say is actually happening?*

**Scope.** The radar tracks only the loss-of-control scenario: an AI system acting beyond the
authority it was given. Deliberate misuse of AI by people (weapons, surveillance, fraud) is real
but is a different question and is **not** counted here.

**Terms.** Where possible the radar uses terms with a legal basis, mainly the EU AI Act
(Regulation (EU) 2024/1689): Art. 3(1) (levels of autonomy, adaptiveness after deployment,
influence on physical or virtual environments), Art. 14 (human oversight) and Art. 15
(accuracy, robustness, cybersecurity).

---

## What the page shows

### 1. Main chart: "how many times more than in December 2023"

One logarithmic axis, three lines. Each line is divided by its own December 2023 value, so
different units can share one chart without being mixed.

| Line | What it measures | Source |
|---|---|---|
| **Autonomy of the leading model** | METR 50% time horizon $T_{50}$: the length of a software task (in hours of expert human work) that the best model completes in half of attempts. Running maximum over release dates. | METR, via Epoch AI (CC BY 4.0) |
| **AI specialists** | Share of job postings that mention AI; one line for all countries of the tracker (geometric mean of each country's growth, equal weight). China is not in the tracker: separately, outside the line, the card shows the number of open postings on the career pages of leading Chinese labs (DeepSeek, Moonshot, Zhipu, MiniMax) — a count of the companies' own postings, not a market share. | Indeed Hiring Lab AI Tracker (CC BY 4.0) |
| **Money** | Quarterly capital expenditure of Amazon, Alphabet, Meta and Microsoft. | SEC EDGAR filings |

**After the last METR measurement** (METR stopped updating in 2026) the autonomy line continues
as a **dashed estimate** from the Epoch Capabilities Index (ECI) of the leading model:

$$\log_{10}(1 + T_{50,\text{min}}) = a + b \cdot \text{ECI}$$

fitted on months from January 2024 where both exist (R² ≈ 0.99). The band is ±2 standard errors
of the fit. This is an estimate, not a measurement.

**Money by source.** The area under the money line is split by where the companies' cash came from
in that quarter: own operating cash flow, net new debt (issued minus repaid), and sale of shares.
Companies do not disclose which source paid for which building, so the shares of the quarter's
inflows are applied to capital expenditure. This is an approximation.

### 2. Research direction: "gas" and "brakes"

Two bars per quarter, as a share of all AI papers on arXiv (cs.AI, cs.LG, cs.CL, cs.RO, cs.MA).
The chart shows the latest quarter; earlier quarters are selected in a menu:

* **Growth of AI autonomy** ("gas"): autonomous task execution, adaptiveness after deployment
  (self-improvement), influence on the physical environment (robot + AI model), reasoning,
  autonomous scientific research.
* **Human oversight and robustness of AI** ("brakes"): human oversight, understanding of
  capabilities and limitations, robustness and cybersecurity, detection of undesired behaviour,
  prevention of risks to safety and fundamental rights, and resistance to shutdown and human
  intervention.

**Method.** Papers are counted with the arXiv search API (`opensearch:totalResults`); **no model
reads the papers**. Each direction is a list of phrases searched in title and abstract. Known
pitfalls are handled: arXiv stems words (`agentic` = `agent`, `robotic` = `robot`), so ambiguous
phrases are removed or paired (a robotics paper counts only if it also mentions an AI model).
Phrase lists grow from the data: once a month, topics from new papers not covered by any phrase
are offered as candidates, and a person accepts or rejects them. Any change of the phrase list recomputes the
whole history from January 2023 under a new method version.

A separate alert fires if the "resistance to shutdown" direction jumps (≥ 10 papers and ≥ 3× its
recent level).

### 3. Action circle of the leading models

How often leading models act **beyond the bounds of their task** in **real use**.

* **Leader of a lab** = its strongest model by ECI, not the newest. Models published under two
  names (e.g. Claude Mythos X = Claude Fable X) are joined by an alias table.
* **Only real use.** Data come from the developers' system cards: samples of the model's
  real, day-to-day work. Deployment simulations, re-generation of recorded traffic, red-teaming,
  honeypots and tests run without safeguards are **excluded**.
* **Only actions.** A false report about work done is a statement, not an action, and is not
  counted. An action not provided for by the task (working around a block, using permissions not
  granted, acting on resources the user did not name) is counted.
* **Units are never averaged across.** Labs count per step (turn), per task (trajectory) or per
  run. A share per step and a share per task are different numbers, so each unit is shown
  separately.
* **Verification.** Extraction is done by a model, then checked by code: every quote and number
  must be found in the source, and a second, different model must agree. Records with signs of a
  test (e.g. "without safeguards", "simulated", "evaluation") are never confirmed automatically
  and go to a person.

* **Periods.** The circle shows the latest month; earlier months are selected in a menu. A past
  month uses the same verified records and rules, but only models released by the end of that
  month (a recalculation, not a snapshot of what the page showed at that time).

"Skynet" on this scale = every action is beyond bounds.

### 4. Autonomy horizon scale (SAI_T)

$$SAI_T = \frac{\log_{10}(1 + T_{\text{min}})}{\log_{10}(124\,800)} \times 100\%$$

The reference point is **1 human-year of work = 2 080 h = 124 800 min**. The scale is
logarithmic: each doubling of the horizon adds about 6 points, so 70 % on this scale is still only
a few percent of a human-year in hours. METR measures reliably only up to about 16 hours; values
above that are marked as estimates.

### 5. Market layer

* **Funding ladder** (v0, thresholds not yet validated): where the race is financed from, from
  safe to fragile: own cash → reserves → net new debt → supplier credit (signals from Nvidia's
  receivables and inventories) → money from the public (IPO or net share issuance). Computed per
  company, only the highest rung is published.
* **AI bubble fragility index** (v0): credit spreads, high-yield spread, 10-year Treasury yield,
  Fed funds rate and developer postings vs all postings. Each is a percentile of its own
  history up to that day (no look-ahead). ICE and Moody's spreads are shown only as scores, as
  their licences do not allow redistribution of raw series.

---

## Where we might be wrong

* **Autonomy estimate.** Since METR stopped updating, the current autonomy value is an
  extrapolation through ECI. The fit is strong on past data but may break for future models.
* **Keyword counting.** Phrases miss papers that use other words and catch some that use the same
  words differently. arXiv is mostly English; Chinese-language research is largely invisible.
* **Few circle data.** Only a handful of system cards publish real-use rates, in different units,
  often as upper bounds ("less than 0.01 %"). There is not yet enough data for a trend.
* **Self-reported data.** Real-use rates come from the developers themselves and from their own
  model-based monitors.
* **Proxies.** Capital expenditure of four companies includes non-AI spending; AI job postings
  cover a few countries only.
* **Thresholds of the market layer** are a first version and have not been validated.

Feedback and criticism are very welcome: please open an issue.

---

## How it works

```
collectors/   data collectors (one shared framework in core/)
metrics/      derived series written to fct_metric_values
sql/          database migrations (Supabase / Postgres), applied in order
app.py        Streamlit page; ui_overview.py - the two summary charts
tests/        tests (python -m pytest -q)
docs/         technical notes and archive
```

* Database: Supabase (Postgres). All derived numbers are stored with a `method_version`;
  changing a method recomputes the series instead of mixing versions.
* Schedule: GitHub Actions, daily (`.github/workflows/pipeline_cron.yml`).
* A language model (Gemini, free tier) is used only to extract data from system cards, job
  postings and a small daily sample of new papers. All series on the page are computed by code.

| Data | Source | Licence / terms |
|---|---|---|
| METR time horizons, Epoch Capabilities Index | Epoch AI | CC BY 4.0 |
| AI job postings share | Indeed Hiring Lab | CC BY 4.0 |
| Open postings at Chinese labs | career pages of DeepSeek, Moonshot, Zhipu (MokaHR), MiniMax (Feishu) | public pages; counter and posting texts. Skills are extracted by keywords, without a language model; the region in the filter is China, separate from APAC |
| Job postings and counts | Adzuna API | API terms. Skills, track, level and work format are extracted by keywords, without a language model — the same way as postings of the Chinese labs |
| Capital expenditure, filings | SEC EDGAR | public data |
| Rates and spreads | FRED (St. Louis Fed) | per series; ICE/Moody's shown as scores only |
| Paper counts | arXiv API | arXiv API terms |
| Action rates | Developers' system cards (Anthropic, OpenAI) | quoted with page references |

Technical notes: [docs/MIGRATIONS.md](docs/MIGRATIONS.md) (framework and database migrations),
[docs/market_signals.md](docs/market_signals.md) (SEC collectors).
