# Daily Macro Brief Agent — Architecture Brief
> Drop this file into the root of your `daily-macro-brief` repo as `ARCHITECTURE.md`.
> Tell Claude Code: "Read ARCHITECTURE.md — this is the full planning document for this project. Use it as context and let's start building file by file."

---

## Project Overview

Build an automated Daily Macro Brief agent that runs every morning before market open, scrapes real market data and non-mainstream content, synthesizes insights via Claude API, and delivers a structured brief to a designated Telegram channel. The PM is macro-trained, reads Bloomberg/FT already, and wants synthesis and point of view — not news regurgitation.

**Deliverables:**
- GitHub repo (public) with full code + README + costs.md
- 1-page PDF memo covering design tradeoffs, assumptions, V2 features, and time spent

---

## Case Study Requirements — Module Checklist

| Module | Description | Constraint |
|--------|-------------|------------|
| 1 | Overnight market dashboard — US/EU close vs prior day: equities, rates, FX, gold, oil, BTC | Table format only, no chart |
| 2 | The 3 things that matter today | Each ≤ 80 words with explicit "so what" |
| 3 | Today's calendar — Asia/EU/US sessions with consensus estimates | |
| 4 | One chart worth seeing — dynamically selected, not fixed | Caption ≤ 30 words |
| 5 | Theme radar — 3 deep-content summaries tied to positions/themes | Non-mainstream sources only. Title + source + link + 60-100 word summary + "what this means for our book" |
| 6 | Contrarian corner | 50-100 words on a narrative market isn't pricing |

**Critical constraint:** LLM is for synthesis and writing only. All numbers must come from real APIs or scraping. Never use Claude to generate market data.

---

## Architecture

```
GitHub Actions (cron: 6:00am ET daily)
        ↓
main.py — orchestrator with isolated module execution
        ↓
┌─────────────────────────────────────┐
│         DATA COLLECTION             │
│  market_data.py   → yfinance + FRED │
│  calendar_scraper.py → ForexFactory │
│  content_scraper.py → curated RSS  │
└────────────────┬────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│        RELEVANCE SCORING            │
│  scorer.py                          │
│  Pure Python — zero token cost      │
│  Recency + position tag match +     │
│  novelty vs mainstream headlines    │
└────────────────┬────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│    HAIKU PRE-FILTER (quality gate)  │
│  ~50 tokens per call                │
│  Binary: is this analytically       │
│  substantive? Yes/No + reason       │
│  Runs on top 3 scored items only    │
└────────────────┬────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│    CLAUDE SONNET SYNTHESIS          │
│  Single API call for all modules    │
│  Prompt caching on system prompt    │
│  XML output schema for clean parse  │
│  max_tokens: 1200 hard ceiling      │
└────────────────┬────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│    CHART GENERATION                 │
│  chart.py — dynamic selection       │
│  Rules-based (not LLM-selected)     │
│  LLM writes caption only (30 words) │
└────────────────┬────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│    TELEGRAM DELIVERY                │
│  delivery.py                        │
│  Sectioned messages (1 per module)  │
│  Send → confirm → next section      │
│  Bloomberg terminal aesthetic       │
│  Monospace tables, bold headers     │
│  No emoji, no filler                │
└─────────────────────────────────────┘
```

---

## File Structure

```
daily-macro-brief/
├── .github/
│   └── workflows/
│       └── daily_brief.yml          # GitHub Actions schedule (6am ET)
├── src/
│   ├── market_data.py               # Module 1 — yfinance + FRED
│   ├── calendar_scraper.py          # Module 3 — ForexFactory scrape
│   ├── content_scraper.py           # Module 5 data layer — RSS + Nitter
│   ├── scorer.py                    # Relevance ranking (pure Python)
│   ├── synthesizer.py               # Claude API calls
│   ├── chart.py                     # Module 4 — dynamic chart selection
│   └── delivery.py                  # Telegram sectioned delivery
│   ├── fallbacks/
│   │   ├── market_fallback.py       # Cached/stale data fallback
│   │   ├── calendar_fallback.py
│   │   └── content_fallback.py      # Yesterday's unused high-scored items
│   ├── validators/
│   │   ├── scrape_validator.py      # Schema change detection
│   │   └── output_validator.py      # Claude XML output validation
│   └── monitoring/
│       └── admin_alerts.py          # Silent failure alerts to admin channel
├── prompts/
│   └── schemas.py                   # XML output schemas per module
├── config/
│   ├── positions.yml                # PM's current book — human-editable daily
│   └── sources.yml                  # Curated source registry
├── CLAUDE.md                        # Persistent LLM context (see below)
├── main.py                          # Orchestrator
├── config.py                        # Settings loader
├── requirements.txt
├── README.md
├── ARCHITECTURE.md                  # This file
└── costs.md
```

---

## CLAUDE.md — Persistent System Context

This file is prepended to every synthesis API call and cached. It eliminates prompt drift and enforces style without paying full token cost each time.

```markdown
# CLAUDE.md — Daily Macro Brief Agent

## PM Profile
Macro-trained institutional PM. No patience for long reads. Already reads Bloomberg, FT, WSJ.
Do NOT summarize mainstream coverage. Synthesize, select, have a point of view.
Core ask: "What changed overnight + so what for our book."

## Voice & Style
- Direct. No throat-clearing. First sentence must be the insight.
- Numbers always. Vague qualitative claims are rejected.
- "So what" must reference a specific position or theme from positions.yml.
- Never use: "notably", "it's worth mentioning", "in conclusion", "it is important to note"
- Bloomberg terminal tone: sparse, structured, high information density.

## House Positions
Injected dynamically from positions.yml at runtime. Never hard-code.

## Output Format
Strict XML schema. Never deviate. Never add unrequested sections.
Schema definitions in prompts/schemas.py.

## Token Budget Per Module (hard limits)
- Module 1: data formatting only, no synthesis, ~200 tokens output
- Module 2: 3 × 80 words max
- Module 3: structured table, no prose, ~150 tokens output
- Module 4: caption 30 words exactly
- Module 5: 3 × 100 words max per summary + 1 line book implication
- Module 6: 75 words max
```

---

## Data Sources

### Module 1 — Market Dashboard
| Asset Class | Tickers | Source |
|-------------|---------|--------|
| US Equities | SPY, QQQ, DJI | yfinance |
| EU Equities | DAX, FTSE, CAC | yfinance |
| Asia Equities | Nikkei, HSI, CSI300 | yfinance |
| US Rates | 2Y, 10Y, 30Y Treasury | FRED API |
| EU Rates | Bund 10Y, Gilt 10Y | yfinance |
| FX | DXY, EUR/USD, USD/JPY, GBP/USD, USD/CNH | yfinance |
| Commodities | Gold, WTI, Brent | yfinance |
| Crypto | BTC-USD | yfinance |

### Module 3 — Economic Calendar
- **Primary:** ForexFactory scrape (free, comprehensive)
- **Fallback:** TradingEconomics API (free tier)
- Filter to: high-impact events only + events relevant to current positions

### Module 4 — Chart Selection Logic (rules-based, not LLM)
```
Priority order:
1. If a position-tagged asset moved >1.5 std dev overnight → chart that asset with 90-day context
2. If yield curve moved significantly → 2s10s spread, 6-month lookback
3. If VIX spike → VIX vs SPX 30-day
4. If EM stress signals → EM FX basket vs DXY
5. Default fallback → yield curve (only if nothing else qualifies)
```
LLM writes the ≤30 word caption after chart is selected by the rules.

### Module 5 — Content Source Registry (sources.yml)

**Tier 1 — Central Banks (highest signal, most underread)**
```yaml
central_banks:
  - name: Federal Reserve Speeches
    rss: https://www.federalreserve.gov/feeds/speeches.xml
    credibility: tier_1
    always_include: true
  - name: ECB Publications
    rss: https://www.ecb.europa.eu/rss/fsr.html
    credibility: tier_1
  - name: BIS Working Papers
    url: https://www.bis.org/doclist/wppubls.rss
    credibility: tier_1
  - name: BOJ Speeches
    rss: https://www.boj.or.jp/en/rss/release.xml
    credibility: tier_1
```

**Tier 2 — Buy-Side / Institutional Research**
```yaml
buyside:
  - name: PIMCO Blog
    rss: https://www.pimco.com/rss/feeds/blog.xml
    credibility: tier_2
    position_tags: [rates, duration, EM]
  - name: Hoisington Quarterly
    url: https://hoisington.com/economic_overview.html
    credibility: tier_2
    scrape_frequency: quarterly
    position_tags: [duration, deflation]
  - name: GMO Letters
    url: https://www.gmo.com/americas/research-library/
    credibility: tier_2
    scrape_frequency: monthly
```

**Tier 3 — Independent Macro (Substack RSS — all public)**
```yaml
independent:
  - name: Lyn Alden
    rss: https://www.lynalden.com/feed/
    credibility: tier_2
    position_tags: [gold, dollar, fiscal, EM]
  - name: Doomberg
    rss: https://doomberg.substack.com/feed
    credibility: tier_2
    position_tags: [energy, commodities]
  - name: Macro Alf (Alfonso Peccatiello)
    rss: https://themacrocompass.substack.com/feed
    credibility: tier_2
    position_tags: [rates, macro]
  - name: Adam Tooze Chartbook
    rss: https://adamtooze.substack.com/feed
    credibility: tier_2
    position_tags: [geopolitics, fiscal, EM]
  - name: Concoda
    rss: https://concoda.substack.com/feed
    credibility: tier_2
    position_tags: [dollar, liquidity]
```

**Tier 4 — X/Twitter (via Nitter, no API cost)**
```yaml
twitter:
  - handle: LukeGromen
    nitter_url: https://nitter.net/LukeGromen/rss
    position_tags: [dollar, gold, fiscal]
  - handle: JeffSnider_AIP
    nitter_url: https://nitter.net/JeffSnider_AIP/rss
    position_tags: [dollar, eurodollar, rates]
```

---

## Dynamic Position Config (positions.yml)

Human-editable file. PM or assistant updates when book changes. Read fresh every morning.

```yaml
# positions.yml — update whenever book changes
# Last updated: 2026-05-31

positions:
  - asset: USD/JPY
    direction: long
    conviction: high
    theme: BOJ policy divergence vs Fed
    tags: [JPY, BOJ, rates, FX]

  - asset: Gold
    direction: long
    conviction: medium
    theme: Real rate sensitivity, de-dollarization
    tags: [gold, real_rates, dollar, inflation]

  - asset: EM Debt (Brazil, India, Indonesia)
    direction: long
    conviction: medium
    theme: EM carry + reform stories
    tags: [EM, rates, carry, BRL, INR, IDR]

  - asset: US 10Y
    direction: short
    conviction: high
    theme: Fiscal supply concern, term premium repricing
    tags: [rates, duration, UST, fiscal]

watching:
  - theme: European defense / energy rotation
    tags: [Europe, defense, energy, geopolitics]
    position: none
```

---

## Relevance Scoring Logic (scorer.py)

Pure Python — zero token cost. Runs before any LLM call.

```python
def score_content(item, positions):
    score = 0

    # Recency (published within last 24hrs = max score)
    hours_old = (now - item.published).total_seconds() / 3600
    score += max(0, 10 - hours_old * 0.4)

    # Position tag match
    matched_tags = set(item.tags) & get_all_position_tags(positions)
    score += len(matched_tags) * 3

    # Conviction weight (high conviction positions score higher)
    for position in positions:
        if any(tag in item.tags for tag in position.tags):
            conviction_bonus = {'high': 3, 'medium': 2, 'low': 1}
            score += conviction_bonus.get(position.conviction, 0)

    # Substance filter (thin posts penalized)
    if item.word_count < 300:
        score -= 5

    # Source tier bonus
    tier_bonus = {'tier_1': 4, 'tier_2': 2}
    score += tier_bonus.get(item.source_tier, 0)

    return score
```

---

## Token Efficiency Implementation

### 1. Prompt Caching
System prompt (CLAUDE.md + positions + schemas) is identical every day. Cache it.
```python
{
    "type": "text",
    "text": system_prompt_content,
    "cache_control": {"type": "ephemeral"}  # 60-70% input cost reduction
}
```

### 2. Tiered Model Usage
- **Scoring:** Pure Python (free)
- **Pre-filter:** claude-haiku-4-5 — binary substance check, ~50 tokens/call
- **Synthesis:** claude-sonnet-4-6 — single call for all modules

### 3. Single Synthesis Call
All modules generated in one API call. Never one call per module.
Output structured as XML tags: `<module_2>...</module_2>` etc.
max_tokens: 1200 (hard ceiling for entire brief)

### 4. Data Pre-Processing
Python formats all data before LLM sees it. Never pass raw JSON to Claude.
Content: pass title + first 400 words only. Full text is never needed.

### 5. Output Length Contracts
Enforced in CLAUDE.md + API max_tokens. Prevents padding.

### Projected Daily Cost
| Component | Est. Cost |
|-----------|-----------|
| Cached system prompt | ~$0.002 |
| Market + calendar data input | ~$0.002 |
| Theme content excerpts input | ~$0.004 |
| Haiku pre-filter (3 calls) | ~$0.001 |
| Sonnet synthesis output | ~$0.018 |
| **Total** | **~$0.027/day (~$0.81/month)** |

---

## Reliability Architecture

### Core Principle
Never fail silently. Always deliver something. PM never gets silence.

### Fallback Chain Per Module
```
Module 1 (Market Data):
  Primary → yfinance
  Fallback → Alpha Vantage API
  Last resort → Previous day's data with [STALE — {date}] flag

Module 3 (Calendar):
  Primary → ForexFactory scrape
  Fallback → TradingEconomics API
  Last resort → Static notice: [CALENDAR UNAVAILABLE]

Module 5 (Theme Radar):
  Primary → Full source registry scrape
  Fallback → Yesterday's unused high-scored items (cached)
  Last resort → Central bank RSS only (most stable tier)
```

### Module Independence
Each module runs in isolated try/except. One failure cannot cascade.
```python
for module in modules:
    try:
        results[module.name] = module.run()
    except Exception as e:
        results[module.name] = module.fallback()
        admin_alert(module.name, e)  # silent alert to separate admin channel
```

### Scraping Resilience
- Rotating user agents (browser signature pool)
- Rate limiting with randomized jitter between requests
- Schema change detection: assert on output shape before passing to scorer
- If scrape returns empty/malformed → immediate fallback, no garbage passed to LLM

### Claude Output Validation
```python
required_modules = ['module_2', 'module_5', 'module_6']
for module in required_modules:
    if module not in parsed or len(parsed[module]) < 50:
        parsed[module] = get_fallback(module)
```

### Idempotency
State file tracks last successful send date. Prevents duplicate briefs on retry runs.
```
last_run: 2026-05-31
status: success
```

### GitHub Actions Config
```yaml
timeout-minutes: 15
retry: 2
```

---

## Delivery Format — Telegram

**Style:** Bloomberg terminal aesthetic. Monospace tables. Bold section headers. No emoji. No filler. High information density.

**Structure:** Sectioned messages — one per module, sent sequentially with delivery confirmation between each. Feels like a briefing unfolding, not a wall of text. If one section fails mid-send, PM receives: `[Brief incomplete — modules X-Y delayed. Admin notified.]`

**Example Module 1 format:**
```
*OVERNIGHT DASHBOARD — 2026-05-31*

`Asset        Last     Chg      Chg%`
`─────────────────────────────────────`
`SPY          589.2    +3.1     +0.5%`
`DAX          18,204   -45      -0.2%`
`USD/JPY      157.4    +0.8     +0.5%`
`Gold         2,341    +12      +0.5%`
`WTI          81.2     -0.4     -0.5%`
`BTC          68,400   +1,200   +1.8%`
`US 10Y       4.52%    +3bp`
`2s10s        -22bp    +1bp`
```

---

## House Position Assumptions (stated in Memo)

| Position | Direction | Conviction | Theme |
|----------|-----------|------------|-------|
| USD/JPY | Long | High | BOJ divergence vs Fed |
| Gold | Long | Medium | Real rates / de-dollarization |
| EM Debt (BRL, INR, IDR) | Long | Medium | EM carry + reform |
| US 10Y | Short | High | Fiscal supply / term premium |
| EU Defense/Energy | Watching | — | Geopolitical rotation |

These are sample assumptions for the submission. In production, positions.yml replaces all hard-coding.

---

## GitHub Actions Workflow

```yaml
# .github/workflows/daily_brief.yml
name: Daily Macro Brief

on:
  schedule:
    - cron: '0 11 * * 1-5'  # 6am ET (11am UTC), weekdays only
  workflow_dispatch:          # manual trigger for testing

jobs:
  run_brief:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run brief
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          NEWSAPI_KEY: ${{ secrets.NEWSAPI_KEY }}
        run: python main.py
```

---

## Required API Keys / Secrets

| Key | Where to get | Cost |
|-----|-------------|------|
| ANTHROPIC_API_KEY | console.anthropic.com | ~$0.027/day |
| TELEGRAM_BOT_TOKEN | @BotFather on Telegram | Free |
| TELEGRAM_CHAT_ID | Get from @userinfobot | Free |
| FRED_API_KEY | fred.stlouisfed.org/docs/api | Free |
| NEWSAPI_KEY | newsapi.org | Free tier |

---

## V2 Features (for Memo)

1. **Position drift detection** — flag positions not updated in >14 days with inline prompt in the brief: *"USD/JPY conviction last updated 14 days ago — confirm still active?"*
2. **Weekly performance attribution** — Friday brief includes a module linking overnight market moves to PnL impact across stated positions
3. **Source quality feedback loop** — PM can react to Telegram messages (👍/👎) to upvote/downvote sources, which adjusts their scorer weight over time

---

## Where This Goes With 1 Month Full-Time (for Memo)

- Real portfolio integration via broker API (IBKR, Bloomberg PORT) — positions auto-sync, no manual yml updates
- NLP-based novelty scoring — embeddings compare each scraped piece against a rolling 30-day corpus to quantify how different it is from what's already been seen
- Podcast transcription pipeline — auto-transcribe Macro Voices, Odd Lots, Forward Guidance via Whisper, surface key segments
- Multi-PM support — each PM has own positions.yml and delivery channel, one shared scraping infrastructure
- Web dashboard — lightweight read-only view of brief history, source performance, and cost tracking

---

## Build Order (recommended)

1. `config/positions.yml` + `config/sources.yml` — data contracts first
2. `src/market_data.py` — Module 1, test with real data
3. `src/calendar_scraper.py` — Module 3
4. `src/content_scraper.py` — Module 5 data layer
5. `src/scorer.py` — relevance ranking
6. `prompts/schemas.py` — XML output contracts
7. `CLAUDE.md` — system prompt
8. `src/synthesizer.py` — Claude API integration
9. `src/chart.py` — Module 4 dynamic selection
10. `src/delivery.py` — Telegram formatter + sender
11. `src/fallbacks/` + `src/validators/` — reliability layer
12. `main.py` — orchestrator wiring everything together
13. `.github/workflows/daily_brief.yml` — scheduling
14. `README.md` + `costs.md` — documentation

---

*Architecture designed for: reliability-first, token-efficient, non-mainstream content sourcing, dynamic position tracking, Bloomberg terminal aesthetic delivery.*
