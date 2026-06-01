# Daily Macro Brief Agent — Architecture

## Project Overview

Automated daily macro brief for an institutional PM. Runs every morning before market open, sources non-mainstream analytical content, synthesizes insights via Claude API, and delivers a structured brief to Telegram. The PM reads Bloomberg/FT already — the brief exists to surface what they'd otherwise miss and to form a point of view, not to summarize the news.

---

## Module Checklist

| Module | Content | Constraint |
|--------|---------|------------|
| 1 | Overnight market dashboard — equities, rates, FX, commodities, BTC | Table only, no LLM |
| 2 | 3 things that matter today | Each ≤80 words with explicit "so what for the book" |
| 3 | Economic calendar — Asia/EU/US sessions with consensus estimates | Table only, no LLM |
| 4 | One chart — LLM picks from 14 options guided by content signals; rules-based fallback | Caption ≤30 words |
| 5 | Theme radar — 3 non-mainstream summaries tied to positions | Source + link + summary + book implication |
| 6 | Contrarian corner | 50-100 words: Claude's own derived point of view, not a source summary |

**Critical constraint:** LLM synthesizes and writes. All numbers come from real APIs. Claude never generates prices or rates.

---

## Architecture

```
cron-job.org → workflow_dispatch (6am HKT / 22:00 UTC, daily)
        ↓
main.py — orchestrator, isolated try/except per module
        ↓
┌────────────────────────────────────────────┐
│           MODULE 1: MARKET DATA            │
│  market_data.py — yfinance + FRED          │
│  Extracts top movers for Layer 2 queries   │
└───────────────────┬────────────────────────┘
                    ↓
┌────────────────────────────────────────────┐
│        MODULE 5 DATA: THREE-LAYER          │
│                                            │
│  LAYER 1 — Curated Registry (always runs)  │
│  Central bank RSS feeds → regime context   │
│  8 trusted Substacks → Theme Radar pool    │
│                                            │
│  LAYER 2 — Exa Semantic Discovery          │
│  3 regime-aware queries built from movers  │
│  Q1: why top mover moved (non-consensus)   │
│  Q2: what consensus misses on positions    │
│  Q3: tail risks given current regime       │
│  Results enter Theme Radar pool if scored  │
│                                            │
│  LAYER 3 — Citation Graph                  │
│  Fetches outbound links from Layer 1 items │
│  Counts cross-citations across sources     │
│  2+ citations → Contrarian Corner input    │
└───────────────────┬────────────────────────┘
                    ↓
┌────────────────────────────────────────────┐
│         RELEVANCE SCORING                  │
│  scorer.py — pure Python, zero token cost  │
│  tier_2 (Substacks/Exa) +4 > tier_1 +2    │
│  Non-mainstream signal scores above        │
│  authoritative-but-mainstream central banks│
└───────────────────┬────────────────────────┘
                    ↓
┌────────────────────────────────────────────┐
│    HAIKU PRE-FILTER (quality gate)         │
│  ~50 tokens per call                       │
│  Binary: analytically substantive? Yes/No  │
│  Runs on top 6 scored items                │
└───────────────────┬────────────────────────┘
                    ↓
┌────────────────────────────────────────────┐
│    CLAUDE SONNET SYNTHESIS                 │
│  Single API call for modules 2, 4, 5, 6   │
│  Inputs (distinct roles):                  │
│    house_view    → macro narrative/themes  │
│    regime_items  → policy backdrop context │
│    content_items → Theme Radar candidates  │
│    citation_item → Contrarian Corner input │
│    chart_menu    → 14 options + descriptions│
│  Mandate: synthesize / select / explain    │
│  Sources are inputs to thinking, not       │
│  content to be rephrased                   │
│  Prompt cached · max_tokens: 2000          │
│  XML parse: sanitize-and-retry on bad &    │
└───────────────────┬────────────────────────┘
                    ↓
┌────────────────────────────────────────────┐
│    CHART + DELIVERY                        │
│  chart.py — 14 options, editorial-first    │
│    selection: ContentSignal > moves >      │
│    rotating default (4-day cycle)          │
│    1yr avg line + date watermark           │
│  delivery.py — sectioned Telegram messages │
└────────────────────────────────────────────┘
```

---

## File Structure

```
daily-macro-brief/
├── .github/workflows/daily_brief.yml   # workflow_dispatch — triggered by cron-job.org at 6am HKT
├── src/
│   ├── market_data.py                  # Module 1 — yfinance + FRED
│   ├── calendar_scraper.py             # Module 3 — ForexFactory → TradingEconomics fallback
│   ├── content_scraper.py              # Module 5 — three-layer content sourcing
│   ├── scorer.py                       # Relevance ranking (pure Python, zero token cost)
│   ├── synthesizer.py                  # Claude API — Haiku prefilter + Sonnet synthesis
│   ├── chart.py                        # Module 4 — dynamic chart selection
│   ├── delivery.py                     # Telegram formatter + sender
│   ├── utils.py                        # Shared helpers
│   ├── fallbacks/                      # Stale cache + placeholder fallbacks
│   ├── validators/                     # Scrape shape + Claude output checks
│   └── monitoring/                     # Silent failure alerts to admin channel
├── prompts/schemas.py                  # XML output contracts
├── config/
│   ├── positions.yml                   # PM's current book — edit when book changes
│   └── sources.yml                     # Layer 1 curated registry (RSS only)
├── config.py                           # Settings + env var loader
├── main.py                             # Orchestrator
├── CLAUDE.md                           # Persistent LLM system context (prompt-cached)
├── requirements.txt
└── costs.md                            # Detailed cost breakdown
```

---

## Content Sourcing — Three-Layer Design

### Layer 1: Curated Registry (`sources.yml`)

Always runs. Two distinct roles:

**Central banks (12 RSS feeds) → regime context**
Fed Speeches, NY Fed Liberty Street Economics, ECB Publications, ECB Working Papers,
BIS Working Papers, BOJ Speeches, RBI Speeches, IMF Blog, NBER Working Papers,
World Bank Research, Bank of Canada, Reserve Bank of Australia

These are authoritative but mainstream for a macro PM — they feed the policy backdrop
that informs all module outputs, not the Theme Radar candidates.

**Trusted Substacks (8) → Theme Radar pool**
Lyn Alden, Joseph Wang (FedGuy), Luke Gromen (FFTT), CrossBorder Capital (Michael Howell),
Andreas Steno Larsen, Adam Tooze Chartbook, Robin Brooks, Macro Alf (Alfonso Peccatiello)

Independent, non-consensus analytical voices. Compete for Module 5 slots via scoring.

### Layer 2: Exa Semantic Discovery

Runs after market_data. Builds 3 targeted queries from overnight context:

```python
Q1 = "Why {top_mover} moved {X}% — independent analytical view challenging consensus"
Q2 = "What consensus is missing on {high_conviction_positions} — institutional blind spots"
Q3 = "Underpriced tail risks given {regime_characterization} — what isn't being positioned for"
```

Regime is auto-detected from VIX level, yield curve shape, dollar direction, equity performance.
Results enter the scorer alongside Substack items. Deduplicated by URL across all 3 queries.

### Layer 3: Citation Graph

Fetches outbound links from up to 12 Layer 1 articles. Counts how many independent sources
cite the same URL. URLs cited by 2+ sources surface as `citation_item` — passed directly
to the synthesizer as a Contrarian Corner candidate, validated by multiple smart readers
but not yet mainstream.

---

## Synthesis Mandate

Claude is an analyst, not an aggregator. Three inputs, three distinct purposes:

- **`regime_items`** (central bank items): background — what policymakers are signaling
- **`content_items`** (Substack + Exa): foreground — non-consensus analytical signal
- **`citation_item`** (cross-cited piece): potential — what multiple smart readers noticed independently

For every module: synthesize connections, select what matters for this specific book,
explain a point of view. Module 6 must state a contrarian view — derived from the data
if nothing explicit is available. Never hedge, never attribute to "some analysts."

---

## Scoring Logic

```python
score = recency_bonus          # max +10, decays 0.4/hr over 48h
      + tag_match * 3          # per matched position tag
      + conviction_bonus       # +3 high, +2 medium, +1 low
      - 5 (if word_count < 300)
      + tier_bonus             # tier_2 (Substacks/Exa) +4 | tier_1 (central banks) +2
```

Tier bonus is intentionally inverted vs credibility: central banks are authoritative but
mainstream; Substacks and Exa results carry the non-mainstream signal the brief exists to surface.

---

## Reliability

- Each module runs in isolated `try/except` — one failure cannot cascade
- Fallback chain: live data → cached stale data → static placeholder
- Claude output validated before delivery; missing modules get placeholder text
- State file prevents duplicate briefs on retry runs (idempotency)
- Admin alerts sent silently to a separate Telegram channel on any module failure

---

## Token Efficiency

| Technique | Saving |
|-----------|--------|
| Prompt caching (CLAUDE.md + positions + schema) | ~90% on ~900 cached input tokens |
| Single synthesis call for modules 2, 4, 5, 6 | Avoids 4× per-module overhead |
| Haiku prefilter at ~50 tokens/call | Protects Sonnet from low-quality inputs |
| max_tokens: 2000 hard ceiling | Bounds output cost regardless of prompt drift |

Estimated: **~$0.028/day · ~$0.56/month** (weekdays only)

---

## Required API Keys

| Key | Where | Cost |
|-----|-------|------|
| `ANTHROPIC_API_KEY` | console.anthropic.com | ~$0.028/day |
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram | Free |
| `TELEGRAM_CHAT_ID` | @userinfobot on Telegram | Free |
| `TELEGRAM_ADMIN_CHAT_ID` | Same as above | Free |
| `FRED_API_KEY` | fred.stlouisfed.org/docs/api | Free |
| `EXA_API_KEY` | exa.ai | Free tier (1,000 req/month) |

---

## V2 Ideas

- Position drift detection — flag positions not updated in >14 days
- Weekly PnL attribution — link market moves to stated positions
- Source quality feedback loop — Telegram reactions adjust scorer weights
- Podcast transcription via Whisper — surface key segments from Macro Voices, Odd Lots
- Real portfolio sync via IBKR / Bloomberg PORT API
