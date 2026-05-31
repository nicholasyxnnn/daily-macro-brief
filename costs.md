# Cost Analysis

## Daily Token Budget

| Component | Model | Input tokens | Output tokens | Est. cost/day |
|-----------|-------|-------------|---------------|---------------|
| System prompt (cached) | Sonnet | ~800 cached | — | ~$0.001 |
| Market + calendar data | Sonnet | ~400 uncached | — | ~$0.001 |
| Theme content excerpts | Sonnet | ~600 uncached | — | ~$0.002 |
| Synthesis output | Sonnet | — | ~1,200 | ~$0.018 |
| Haiku prefilter (×3) | Haiku | ~150 total | ~30 total | ~$0.001 |
| **Total** | | | | **~$0.023/day** |

## Monthly Projection

| Scenario | Days/month | Cost/month |
|----------|-----------|------------|
| Weekdays only (20 days) | 20 | **~$0.46** |
| Daily (31 days) | 31 | **~$0.71** |

## Cost Levers

**Prompt caching** is the biggest lever. The system prompt (CLAUDE.md + positions + XML schema)
is ~800 tokens. Caching cuts input cost on that block by ~90% via Anthropic's ephemeral cache
(5-min TTL, refreshed each run). Daily runs easily stay within TTL when GitHub Actions cold-start
is fast.

**Single synthesis call** covers modules 2, 4, 5, and 6 together. Calling per-module would
4× the output token cost with no quality gain.

**Haiku prefilter** runs only on the top 3 scored items (~50 tokens/call × 3 = 150 tokens total),
gating Sonnet's attention to analytically substantive content at negligible cost.

**max_tokens: 2000** hard ceiling on Sonnet output prevents runaway verbose responses and
keeps output cost bounded regardless of prompt drift.

## Free Tier API Usage

| Service | Usage | Cost |
|---------|-------|------|
| FRED API | Rate data | Free (no limit) |
| yfinance | Market prices | Free (Yahoo Finance) |
| ForexFactory | Calendar scrape | Free (with rate limiting) |
| Feedparser / RSS | Content sources (23 curated sources) | Free |
| NewsAPI | Keyword search by position tags | Free tier (100 req/day) |
| GDELT Doc 2.0 | Broad global sweep, no key required | Free |
| Telegram Bot API | Delivery | Free |

## V2 Cost Considerations

- **Embedding-based novelty scoring**: ~$0.002/day for 50 items × 1536 dims (text-embedding-3-small)
- **Whisper podcast transcription**: ~$0.006/min; 1 episode/week ≈ $0.18/week
- **Multi-PM support**: costs scale linearly with PM count; shared scraping infrastructure
  means only synthesis + delivery multiply, not data collection
