# scraper_skeleton

A production-grade Python web scraping skeleton that wires all core scraping concerns into a single reusable framework. Built over 15 days as a structured portfolio project demonstrating professional Python engineering — async HTTP, data pipelines, storage backends, anti-bot evasion, scheduling, and CLI tooling.

---

## What this is

Most scraping projects start from scratch every time — reimplementing the same fetcher, the same retry logic, the same CSV writer. This skeleton solves that. Every concern is a standalone layer. You plug in your spider, write your CSS selectors, and everything else — rate limiting, retries, proxy rotation, data cleaning, validation, checkpointing — is already handled.

**Built for Upwork/Fiverr freelance jobs.** When a client posts a scraping job, you fork this repo, write a spider for their site, and deliver in hours instead of days.

---

## Architecture

```
URL list
  ↓ url_utils          — normalize, validate, deduplicate
  ↓ Fetcher            — async HTTP with rate limiting, retries, proxy rotation
  ↓ Parser             — BS4 (CSS selectors) or lxml (XPath)
  ↓ Middleware stack   — logging, retry on HTTP errors, proxy injection
  ↓ Pipeline           — clean → transform → validate (Pydantic)
  ↓ Pandas layer       — quality analysis, DataFrame export
  ↓ Storage            — CSV / SQLite / PostgreSQL
  ↓ CheckpointManager  — resumable scrapes, delta scraping
  ↓ Scheduler          — cron / interval / one-off scheduling
```

---

## Project structure

```
scraper_skeleton/
├── config/
│   └── config.py              # all settings via .env
├── utils/
│   ├── logger.py              # loguru structured logging
│   ├── helpers.py             # utility functions
│   ├── retry.py               # tenacity retry decorator
│   ├── rate_limiter.py        # per-domain async token bucket
│   └── url_utils.py           # URL validation, chunking, pagination
├── fetcher/
│   ├── base_fetcher.py        # ABC + FetchResult dataclass
│   ├── http_fetcher.py        # sync requests wrapper
│   ├── async_fetcher.py       # aiohttp async fetcher with semaphore
│   ├── batch_fetcher.py       # chunked concurrent batch fetching
│   ├── browser_fetcher.py     # Playwright for JS-heavy sites
│   └── session_manager.py     # login + cookie persistence
├── parser/
│   ├── base_parser.py         # ABC + ParseResult dataclass
│   ├── bs4_parser.py          # BeautifulSoup CSS selector helpers
│   └── lxml_parser.py         # lxml XPath helpers
├── middleware/
│   ├── base_middleware.py     # MiddlewareChain + ABC
│   ├── retry_middleware.py    # retry on 429/5xx
│   ├── proxy_middleware.py    # proxy injection and rotation
│   └── logging_middleware.py  # request/response timing
├── pipeline/
│   ├── cleaner.py             # normalize raw scraped values
│   ├── transformer.py         # reshape data for storage schema
│   └── validator.py           # Pydantic schema enforcement
├── pandas_layer/
│   ├── dataframe_builder.py   # dicts → typed DataFrame
│   ├── analyzer.py            # quality scoring, deduplication
│   └── exporter.py            # CSV / Excel / JSON export
├── storage/
│   ├── base_storage.py        # ABC + SaveResult dataclass
│   ├── csv_storage.py         # flat file, append/overwrite modes
│   ├── sqlite_storage.py      # async SQLite with checkpointing
│   ├── postgres_storage.py    # async PostgreSQL with connection pooling
│   └── checkpoint_manager.py  # resumable scrapes + delta scraping
├── anti_bot/
│   ├── proxy_manager.py       # pool health tracking, ban/cooldown
│   ├── headers_manager.py     # full browser header generation
│   └── fingerprint_manager.py # TLS spoofing, Playwright stealth
├── scheduler/
│   └── job_scheduler.py       # APScheduler wrapper: cron/interval/once
├── spiders/
│   ├── base_spider.py         # ABC with shared fetch/parse/save/stats
│   ├── example_spider.py      # reference implementation — books.toscrape.com
│   └── batch_spider.py        # production spider: chunked, checkpointed
├── tests/
│   └── test_day{1-15}.py      # isolation + integration tests per layer
├── examples/
│   └── day{1-15}_example.py   # runnable demo per layer
├── main.py                    # CLI entry point
├── requirements.txt           # all dependencies with comments
└── .env.example               # environment variable template
```

---

## Quick start

**1. Clone and install**

```bash
git clone https://github.com/Bartier5/scraper_skeleton.git
cd scraper_skeleton
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
playwright install chromium
```

**2. Configure**

```bash
cp .env.example .env
# Edit .env with your settings
```

**3. Run the example spider**

```bash
# Scrape one page
python main.py --spider example --mode single --url https://books.toscrape.com/catalogue/page-1.html

# Scrape multiple pages concurrently
python main.py --spider example --mode batch --storage sqlite

# Run on a schedule (every hour)
python main.py --spider example --mode schedule --interval 3600

# Dry run — see config without fetching
python main.py --spider example --dry-run --url https://books.toscrape.com

# List all spiders
python main.py --list-spiders
```

**4. Run tests**

```bash
# All unit tests (no network, no DB required)
pytest tests/ -v -m "not integration"

# Full test suite including Day 15 smoke tests
pytest tests/test_day15.py -v

# Integration tests (requires PostgreSQL — see Day 11 setup)
pytest tests/test_day11.py -m integration -v
```

---

## Writing a spider for a new job

Copy `spiders/example_spider.py` and replace the CSS selectors:

```python
class MyClientSpider(BaseSpider):

    async def run(self, urls: list[str] = None, **kwargs) -> dict:
        urls = urls or ["https://client-site.com/products"]
        self.start_run(urls)

        async with self:
            for url in urls:
                result = await self.fetch(url)
                if result.success:
                    soup = self.parser.make_soup(result.html)

                    # ← Only thing you change per job: these selectors
                    names  = self.parser.get_all_text(soup, "h2.product-name")
                    prices = self.parser.get_all_text(soup, "span.price")
                    urls_  = self.parser.get_all_attr(soup, "a.product-link", "href")

                    raw = [{"name": n, "price": p, "url": u}
                           for n, p, u in zip(names, prices, urls_)]

                    cleaned     = self._cleaner.clean_items(raw)
                    transformed = self._transformer.transform_items(cleaned)
                    batch       = self._validator.validate_batch(transformed)
                    await self.save(batch.valid_items)

        self.finish_run()
        return self.get_stats()
```

Register it in `main.py`:

```python
SPIDER_REGISTRY["my_client"] = {
    "module": "spiders.my_client_spider",
    "class":  "MyClientSpider",
    "description": "Client job — product scraper",
}
```

---

## Storage backends

| Backend    | Use case                                | Setup    |
|------------|-----------------------------------------|----------|
| CSV        | Simple delivery, client opens in Excel  | None     |
| SQLite     | Resumable scrapes, local querying       | None     |
| PostgreSQL | Production retainer, multi-process, large scale | Required |

Switch via CLI:
```bash
python main.py --spider example --storage csv     # → data/output_TIMESTAMP.csv
python main.py --spider example --storage sqlite  # → data/scraper.db
python main.py --spider example --storage postgres # → POSTGRES_URL from .env
```

---

## Anti-bot stack

For sites with basic protection — rotate headers:
```python
from anti_bot.headers_manager import HeadersManager
manager = HeadersManager(browser="chrome")
headers = manager.get_headers(url="https://target.com", referer="https://google.com")
```

For sites with proxy detection — rotate IPs:
```python
from anti_bot.proxy_manager import ProxyManager
proxies = ProxyManager(strategy="round_robin", max_failures=3, cooldown=300)
proxies.load_from_file("proxies.txt")
proxy_url = proxies.get_proxy()
proxies.mark_success(proxy_url)   # or mark_failure(proxy_url)
```

For sites with TLS fingerprinting (Cloudflare) — use curl-cffi:
```python
from anti_bot.fingerprint_manager import TlsFetcher
with TlsFetcher(browser="chrome120") as fetcher:
    result = fetcher.fetch("https://cloudflare-protected.com")
```

Audit your headers before a job:
```python
from anti_bot.fingerprint_manager import FingerprintAnalyzer
report = FingerprintAnalyzer().check_headers(your_headers)
# → {"risk_score": 0, "risk_level": "LOW", "issues": []}
```

---

## Resumable scraping

```python
from storage.checkpoint_manager import CheckpointManager
from utils.helpers import hash_content

manager = CheckpointManager(db_path="data/job.db")
await manager.init()

for url in all_urls:
    if await manager.is_done(url):
        continue   # already scraped — skip

    result = await fetcher.async_fetch(url)
    content_hash = hash_content(result.html)

    if not await manager.has_changed(url, content_hash):
        continue   # content unchanged — skip (delta scraping)

    # ... parse, save ...
    await manager.mark_done(url, content_hash=content_hash)

# Or use get_pending() for batch efficiency (one query instead of N)
pending = await manager.get_pending(all_urls)
```

---

## Scheduling

```python
from scheduler.job_scheduler import JobScheduler

scheduler = JobScheduler(timezone="UTC")
await scheduler.start()

# Every hour
scheduler.run_interval(my_spider_job, job_id="hourly", hours=1)

# Every day at 9am
scheduler.run_cron(my_spider_job, job_id="daily", hour="9", minute="0")

# Run once now
scheduler.run_once(my_spider_job, job_id="now", delay_seconds=0)

await scheduler.wait()   # blocks until Ctrl+C
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
# Fetcher
REQUEST_TIMEOUT=30
CONCURRENCY=10
MAX_RETRIES=3
RATE_LIMIT=0.5         # requests/second per domain

# Storage
STORAGE_BACKEND=sqlite  # csv | sqlite | postgres
OUTPUT_DIR=data/
POSTGRES_URL=postgresql://user:password@localhost:5432/scraper_db

# Logging
LOG_LEVEL=INFO          # DEBUG | INFO | WARNING | ERROR
LOG_DIR=logs/

# Anti-bot
PROXY_LIST=             # path to proxy list file
```

---

## Tech stack

| Layer          | Library                  | Purpose                              |
|----------------|--------------------------|--------------------------------------|
| HTTP (sync)    | requests                 | Simple one-off fetches               |
| HTTP (async)   | aiohttp + aiodns         | Batch concurrent requests            |
| Browser        | Playwright               | JS-rendered pages                    |
| TLS spoof      | curl-cffi                | Bypass TLS fingerprinting            |
| Parsing        | BeautifulSoup4 + lxml    | CSS selectors + XPath                |
| Validation     | Pydantic v2              | Schema enforcement                   |
| DataFrames     | Pandas + openpyxl        | Analysis and Excel export            |
| Storage        | aiosqlite + asyncpg      | SQLite and PostgreSQL async          |
| Scheduling     | APScheduler              | Cron and interval jobs               |
| Logging        | loguru                   | Structured, colored, rotating logs   |
| Retry          | tenacity                 | Exponential backoff                  |
| Rate limiting  | aiolimiter               | Token bucket per domain              |
| Testing        | pytest                   | Isolation + integration tests        |

---

## Portfolio projects built on this skeleton

- **GhostProfiler** — Telegram behavioral analysis bot (VADER sentiment, K-Means clustering, LDA topic modeling, Isolation Forest, Groq API, PostgreSQL on Railway)
- **SHARP Bot** — Telegram sports betting analysis bot implementing the SHARP Model v3 across Football Original, HVLO, and NBA modes

---

## Author

**Anjikwi** — Computer Engineer  
GitHub: [Bartier5](https://github.com/Bartier5)  
Specializations: Python web scraping, automation, bot development  
Platforms: Upwork · Fiverr
