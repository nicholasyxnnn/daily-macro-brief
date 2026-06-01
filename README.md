# daily-macro-brief

Automated daily macro brief agent for institutional PMs. Runs daily at 6am HKT (22:00 UTC) via cron-job.org → GitHub Actions workflow_dispatch. Delivers a structured, synthesis-first brief to Telegram — market dashboard, 3 things that matter, economic calendar, one chart, theme radar from non-mainstream sources, and a contrarian corner.

**Cost: ~$0.028/day (~$0.56/month on weekdays).**

---

## What it produces

| Module | Content | Constraint |
|--------|---------|------------|
| 1 | Overnight market dashboard — equities, rates, FX, commodities, BTC | Table only, no LLM |
| 2 | 3 things that matter today | Each ≤80 words with explicit "so what for the book" |
| 3 | Economic calendar — Asia/EU/US sessions with consensus estimates | Table only, no LLM |
| 4 | One chart — LLM picks from 14 options guided by content signals | Caption ≤30 words |
| 5 | Theme radar — 3 deep-content summaries from non-mainstream sources | Source + link + summary + book implication |
| 6 | Contrarian corner | 50-100 words on a narrative the market isn't pricing |

---

## Architecture

```
cron-job.org → workflow_dispatch (6am HKT / 22:00 UTC, daily)
  → main.py (orchestrator, isolated try/except per module)
      → market_data.py      yfinance + FRED
      → calendar_scraper.py ForexFactory → TradingEconomics fallback
      → content_scraper.py  Three-layer: RSS (Layer 1) + Exa discovery (Layer 2) + citation graph (Layer 3)
      → scorer.py           Pure Python relevance ranking (zero token cost)
      → synthesizer.py      Haiku prefilter + single Sonnet call (prompt cached)
      → chart.py            14 options, editorial selection + matplotlib
      → delivery.py         Sectioned Telegram messages
```

LLM is used for synthesis and writing only. All market data and numbers come from real APIs. Claude never generates prices or rates.

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/daily-macro-brief
cd daily-macro-brief
pip install -r requirements.txt
```

### 2. Get API keys

| Key | Where | Cost |
|-----|-------|------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | ~$0.028/day |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) on Telegram | Free |
| `TELEGRAM_CHAT_ID` | [@userinfobot](https://t.me/userinfobot) on Telegram | Free |
| `TELEGRAM_ADMIN_CHAT_ID` | Same as above (can be same as CHAT_ID) | Free |
| `FRED_API_KEY` | [fred.stlouisfed.org/docs/api](https://fred.stlouisfed.org/docs/api/api_key.html) | Free |
| `EXA_API_KEY` | [exa.ai](https://exa.ai) | Free tier (1000 req/month) — Layer 2 dynamic discovery |
| `NEWSAPI_KEY` | [newsapi.org](https://newsapi.org) | Free tier (100 req/day) — Module 2 market context |
| `FINNHUB_API_KEY` | [finnhub.io](https://finnhub.io) | Free tier (60 req/min) — Module 3 calendar primary |

### 3. Add secrets to GitHub

```
Settings → Secrets and variables → Actions → New repository secret
```

Add each key from the table above.

### 4. Update your positions

Edit `config/positions.yml` whenever your book changes. The agent reads it fresh every morning.

```yaml
meta:
  aum_mm: 100
  currency: USD

house_view:
  narrative: >
    Your macro thesis here — injected into every synthesis call.
  themes: [USD strength, Bear duration, Long gold / real assets]

positions:
  - id: fx_usdjpy
    name: Long USD/JPY
    bucket: fx
    direction: long
    notional_mm: 12
    conviction: high
    theme: USD strength
    instrument: USDJPY
    entry_price: 149.80
    tags: [fx, usd, jpy, currency, boj]
```

---

## Running manually

```bash
export ANTHROPIC_API_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export FRED_API_KEY=...

python main.py
```

Or trigger a run from the GitHub Actions tab using **workflow_dispatch**.

---

## File structure

```
daily-macro-brief/
├── .github/workflows/daily_brief.yml   # workflow_dispatch — triggered by cron-job.org at 6am HKT
├── src/
│   ├── market_data.py                  # Module 1 — yfinance + FRED
│   ├── calendar_scraper.py             # Module 3 — ForexFactory
│   ├── content_scraper.py              # Module 5 data — three-layer content sourcing
│   ├── scorer.py                       # Relevance ranking (pure Python)
│   ├── synthesizer.py                  # Claude API — Haiku + Sonnet
│   ├── chart.py                        # Module 4 — dynamic chart selection
│   ├── delivery.py                     # Telegram formatter + sender
│   ├── utils.py                        # Shared helpers
│   ├── fallbacks/                      # Stale cache + placeholder fallbacks
│   ├── validators/                     # Scrape shape + Claude output checks
│   └── monitoring/                     # Silent failure alerts to admin channel
├── prompts/schemas.py                  # XML output contracts
├── config/
│   ├── positions.yml                   # PM's current book — edit daily
│   └── sources.yml                     # Layer 1 curated registry (central banks + Substacks)
├── config.py                           # Settings + env var loader
├── main.py                             # Orchestrator
├── CLAUDE.md                           # Persistent LLM system context
├── requirements.txt
└── costs.md                            # Detailed cost breakdown
```

---

## Reliability

- Each module runs in an isolated `try/except` — one failure cannot cascade
- Fallback chain per module: live data → cached stale data → static placeholder
- Claude output validated before delivery; missing modules get placeholder text
- State file (`state/run_state.json`) prevents duplicate briefs on retry runs
- Admin alerts sent silently to a separate Telegram channel on any module failure

---

## V2 ideas

- Position drift detection — flag positions not updated in >14 days
- Weekly PnL attribution — link market moves to stated positions
- Source feedback loop — Telegram reactions (👍/👎) adjust scorer weights
- Real portfolio sync via IBKR / Bloomberg PORT API
- Embedding-based novelty scoring against 30-day rolling corpus
