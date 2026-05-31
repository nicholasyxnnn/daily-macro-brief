# Cost Analysis

## Daily Token Budget

| Component | Model | Input tokens | Output tokens | Est. cost/day |
|-----------|-------|-------------|---------------|---------------|
| System prompt (cached) | Sonnet | ~900 cached | — | ~$0.001 |
| Market + calendar data | Sonnet | ~400 uncached | — | ~$0.001 |
| Regime context + content excerpts | Sonnet | ~800 uncached | — | ~$0.002 |
| Synthesis output | Sonnet | — | ~1,500 | ~$0.023 |
| Haiku prefilter (×3) | Haiku | ~150 total | ~30 total | ~$0.001 |
| **Total** | | | | **~$0.028/day** |

## Monthly Projection

| Scenario | Days/month | Cost/month |
|----------|-----------|------------|
| Weekdays only (20 days) | 20 | **~$0.56** |
| Daily (31 days) | 31 | **~$0.87** |

## Cost Levers

**Prompt caching** is the biggest lever. The system prompt (CLAUDE.md + positions + XML schema)
is ~900 tokens. Caching cuts input cost on that block by ~90% via Anthropic's ephemeral cache
(5-min TTL, refreshed each run). Daily runs easily stay within TTL when GitHub Actions cold-start
is fast.

**Single synthesis call** covers modules 2, 4, 5, and 6 together. Calling per-module would
4× the output token cost with no quality gain.

**Haiku prefilter** runs only on the top 6 scored items and approves/rejects each in ~50 tokens,
gating Sonnet's attention to analytically substantive content at negligible cost.

**max_tokens: 2000** hard ceiling on Sonnet output prevents runaway verbose responses and
keeps output cost bounded regardless of prompt drift.

## API Usage

| Service | Usage | Cost |
|---------|-------|------|
| FRED API | Rate data | Free (no limit) |
| yfinance | Market prices | Free (Yahoo Finance) |
| ForexFactory | Calendar scrape | Free (with rate limiting) |
| Feedparser / RSS | Layer 1: 12 central bank feeds + 8 Substacks | Free |
| Exa.ai | Layer 2: 3 semantic queries/day (~60 req/month) | Free tier (1,000 req/month) |
| Telegram Bot API | Delivery | Free |

Layer 3 (citation tracking) makes HTTP requests to article pages — no API cost, ~15 requests
per run, absorbed into existing network overhead.

## V2 Cost Considerations

- **Embedding-based novelty scoring**: ~$0.002/day for 50 items × 1536 dims (text-embedding-3-small)
- **Whisper podcast transcription**: ~$0.006/min; 1 episode/week ≈ $0.18/week
- **Multi-PM support**: costs scale linearly with PM count; shared scraping infrastructure
  means only synthesis + delivery multiply, not data collection
