# scraper_skeleton — Testing Branch Documentation

## What this branch is

The `testing` branch documents real-world scraping patterns against live sites. Every test maps to a class of client jobs you will encounter on Upwork and Fiverr. Each entry explains the problem, the exact approach, what to change in the skeleton, and what the result should look like.

This is your field manual. Before taking any scraping job, check this document first — the pattern you need is likely already here and tested.

---

## How to read this document

Each test entry follows the same structure:

- **Target** — the URL we tested against
- **Pattern** — the class of scraping problem this represents
- **Client job equivalent** — what kind of real Upwork job uses this pattern
- **What makes it hard** — why naive scrapers fail here
- **Skeleton approach** — exactly which modules to use and why
- **Step by step** — copy-paste instructions for wiring a new job
- **Key code** — the exact lines that matter
- **Output proof** — what success looks like in the terminal
- **What to watch for** — things that can go wrong and how to fix them

---

## Test index

| Test | Site | Pattern | Status |
|------|------|---------|--------|
| 1A | quotes.toscrape.com/js | JS rendering | ✅ Pass |
| 2A | quotes.toscrape.com/scroll | Infinite scroll | ✅ Pass |
| 2B | quotes.toscrape.com/login | Login + session | ✅ Pass |
| 3A | hn.algolia.com/api/v1/search | AJAX/XHR JSON API | ✅ Pass |
| 3B | quotes.toscrape.com/filter.aspx | Form interaction | ⚠️ Blocked — ASP.NET |
| 4A | amazon.com/s?k=python+books | Real e-commerce anti-bot | ✅ Pass |

---

## Common errors and fixes (apply to every new spider)

These mistakes happened repeatedly during testing. Never repeat them:

1. **No `storage_type` kwarg** — `BaseSpider.__init__` does not accept `storage_type`. Always pass an instantiated storage object: `MySpider(storage=CsvStorage())`
2. **Pipeline not initialized** — `_cleaner`, `_transformer`, `_validator` are NOT auto-initialized by BaseSpider. Always add to `__init__`:
```python
self._cleaner = DataCleaner()
self._transformer = DataTransformer(add_metadata=True)
self._validator = DataValidator(schema=MySchema, strict=False)
```
3. **No `self.logger`** — use `log` from `from utils.logger import log`, not `self.logger`

---

# Test 1A — JavaScript Rendering

## Target
`https://quotes.toscrape.com/js/`

## Pattern
**Client-side JavaScript rendering** — the page HTML is empty on first load. A JavaScript script runs in the browser, fetches data, and injects it into the DOM. Standard HTTP requests (aiohttp, requests) return an empty body.

## Client job equivalent
Any modern site built with React, Vue, Angular, or Next.js. Common examples:
- Job boards (Indeed, LinkedIn Jobs)
- Real estate listings
- Product catalogues built on Shopify
- News aggregators
- Dashboard-style sites with dynamic content

## What makes it hard
```python
# This returns empty HTML — no quotes
result = await fetcher.async_fetch("https://quotes.toscrape.com/js/")
soup = parser.make_soup(result.html)
quotes = soup.select("div.quote")   # → empty list []
```
The HTML returned by aiohttp is empty because the JavaScript that populates it hasn't run. You need a real browser to execute the JavaScript first.

## Skeleton approach
Replace `AsyncFetcher` with `BrowserFetcher`. Everything else — parser, pipeline, storage — stays identical. This is the key proof that the layered architecture works: swap one component, everything else is untouched.

**Why BrowserFetcher works:**
- Launches real Chromium via Playwright
- Navigates to the URL
- Waits for `networkidle` — all JS requests have finished
- Captures `page.content()` — the fully rendered HTML with all data injected

**Windows requirement:**
Playwright spawns subprocesses which conflict with `WindowsSelectorEventLoopPolicy`. The fix is to run Playwright in a `ThreadPoolExecutor` with its own `ProactorEventLoop`.

## Step by step

**Step 1 — Create your spider, inject BrowserFetcher:**
```python
from fetcher.browser_fetcher import BrowserFetcher
from spiders.base_spider import BaseSpider

class MyJsSpider(BaseSpider):
    def __init__(self, **kwargs):
        super().__init__(fetcher=BrowserFetcher(), **kwargs)
        self._cleaner = DataCleaner()
        self._transformer = DataTransformer(add_metadata=True)
        self._validator = DataValidator(schema=MySchema, strict=False)
```

**Step 2 — The ProactorEventLoop thread wrapper (already in browser_fetcher.py):**
```python
def _run_sync():
    new_loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(new_loop)
    try:
        return new_loop.run_until_complete(self._playwright_fetch(url))
    finally:
        new_loop.close()

loop = asyncio.get_event_loop()
with ThreadPoolExecutor(max_workers=1) as pool:
    result = await loop.run_in_executor(pool, _run_sync)
```

**Step 3 — In _playwright_fetch, wait for the right signal:**
```python
async with async_playwright() as pw:
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_selector("div.quote", timeout=10000)
    html = await page.content()
    await browser.close()
```

**Step 4 — CSS selectors are identical to static sites:**
```python
texts   = parser.get_all_text(soup, "span.text")
authors = parser.get_all_text(soup, "small.author")
```

**Step 5 — Pipeline and storage completely unchanged:**
```python
cleaned     = cleaner.clean_items(raw_items)
transformed = transformer.transform_items(cleaned)
batch       = validator.validate_batch(transformed)
await storage.save(batch.valid_items)
```

## Key code
The only file that changes from a static spider is the fetcher injection in `__init__`. One line.

## Output proof
```
BrowserFetcher OK: https://quotes.toscrape.com/js (8940 chars)
QuotesJsSpider: parsed 10 quotes
DataValidator: 10/10 items valid (100.0% pass rate)
SqliteStorage: saved 10 rows to 'quotes'
Spider 'QuotesJsSpider' finished — fetched=3 failed=0 items=30 saved=30
```

## What to watch for

**`NotImplementedError` on Windows:**
```
asyncio.create_subprocess_exec → NotImplementedError
```
Cause: Playwright subprocess under WindowsSelectorEventLoopPolicy.
Fix: Use the ProactorEventLoop thread wrapper (already in browser_fetcher.py).

**Empty HTML returned:**
Cause: `wait_until="domcontentloaded"` fires too early.
Fix: Use `wait_until="networkidle"` or add `page.wait_for_selector()`.

**Timeout on slow connections:**
Cause: Default 30s not enough.
Fix: Increase `timeout=60000` on goto and `timeout=30000` on wait_for_selector.

**`ERR_ABORTED` on page.goto:**
Cause: Windows transient navigation abort.
Fix: Wrap goto in a retry loop (3 attempts, 3s sleep between).

---

# Test 2A — Infinite Scroll

## Target
`https://quotes.toscrape.com/scroll`

## Pattern
**Infinite scroll / lazy loading** — the page loads a fixed batch of content on first render. As the user scrolls to the bottom, an AJAX request fires and new content is injected into the DOM. There is no "page 2" URL — it's all one URL, content growing dynamically.

## Client job equivalent
- Twitter/X timelines
- LinkedIn job listings and profiles
- Instagram feeds
- Indeed search results
- Facebook marketplace
- Product listings with lazy loading
- News feeds

## What makes it hard
```python
# Only gets the first batch — misses everything loaded by scrolling
await page.goto(url, wait_until="networkidle")
html = await page.content()
quotes = soup.select("div.quote")   # → only 10, not 50
```

## Skeleton approach
Run Playwright directly in the spider (not through BrowserFetcher) for fine-grained control, then use a **DOM element count detection loop**:
1. Count current DOM elements
2. Scroll to bottom via JavaScript
3. Wait for networkidle
4. Count again
5. Exit when count stops growing

## Key code — The scroll loop
```python
scroll_count = 0
previous_count = 0

while scroll_count < self.max_scrolls:
    current_count = await page.eval_on_selector_all(
        "div.quote", "elements => elements.length"
    )
    if scroll_count > 0 and current_count == previous_count:
        break  # no new content — we're done
    previous_count = current_count
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    await asyncio.sleep(1)
    scroll_count += 1

html = await page.content()  # capture everything in one shot
```

## Output proof
```
InfiniteScrollSpider: scroll 0/20 — 10 quotes visible
InfiniteScrollSpider: scroll 1/20 — 20 quotes visible
...
InfiniteScrollSpider: no new quotes — reached end at 100 quotes
DataValidator: 100/100 items valid (100.0% pass rate)
Spider 'InfiniteScrollSpider' finished — fetched=0 failed=0 items=100 saved=100
```

## What to watch for

**Count never grows:**
Cause: networkidle fires before DOM is updated.
Fix: Increase `asyncio.sleep(1)` to `asyncio.sleep(2)` or `3`.

**ERR_ABORTED on page.goto:**
Fix: Wrap goto in retry loop with 3s sleep between attempts.

**Site requires scroll to a specific element, not the bottom:**
```python
items = await page.query_selector_all("div.item")
if items:
    await items[-1].scroll_into_view_if_needed()
```

---

# Test 2B — Login Wall

## Target
`https://quotes.toscrape.com/login`
Credentials: username: `user`, password: `password`

## Pattern
**Authentication wall** — content is only accessible after login. Session cookies must be maintained across all subsequent requests.

## Client job equivalent
- LinkedIn profiles and job listings
- Job board dashboards
- SaaS data exports
- Members-only directories
- E-commerce order histories

## Skeleton approach
**Option A — SessionManager** for standard HTML form login (no JS):
```python
from fetcher.session_manager import SessionManager

session = SessionManager(
    login_url="https://quotes.toscrape.com/login",
    credentials={"username": "user", "password": "password"},
    success_indicator="Logout",
)
await session.login()
# All subsequent fetches reuse session cookies automatically
result = await session.fetch("https://quotes.toscrape.com/")
```

**Option B — Playwright** for JS-heavy login forms:
```python
await page.fill("input[name='username']", "user")
await page.fill("input[name='password']", "password")
await page.click("input[type='submit']")
await page.wait_for_load_state("networkidle")
cookies = await context.cookies()
# Pass cookies to subsequent requests
```

## Key distinction
Use SessionManager when the login form is plain HTML. Use Playwright when the login page has JS-driven validation, OTP fields, or CAPTCHA.

---

# Test 3A — AJAX / XHR JSON API

## Target
`https://hn.algolia.com/api/v1/search?query=python&tags=story`

## Pattern
**Hidden JSON API** — the site's UI fires background XHR requests to a REST API. The data lives in the API response, not the HTML. Calling the API directly is faster and more reliable than parsing rendered HTML.

## Client job equivalent
- Any modern SPA (React, Vue, Angular)
- Booking sites
- Job boards
- News aggregators
- Dashboards with dynamic content

## How to find the API endpoint
1. Open Chrome DevTools → Network tab
2. Filter by Fetch/XHR
3. Interact with the page (search, paginate, scroll)
4. Look for requests returning JSON
5. Copy the Request URL — that's your endpoint

## What makes it different
No BS4 or lxml needed. The response is already structured JSON:
```python
result = await self.fetch(api_url)
data = json.loads(result.html)   # it's JSON, not HTML
hits = data.get("hits", [])
total_pages = data.get("nbPages", 1)
```

## Skeleton approach
Use `AsyncFetcher` directly against the API endpoint. Pagination is handled by incrementing a `page` query parameter.

## Key code
```python
import json

page = 0
while True:
    api_url = f"https://hn.algolia.com/api/v1/search?query=python&tags=story&page={page}&hitsPerPage=20"
    result = await self.fetch(api_url)
    data = json.loads(result.html)
    hits = data.get("hits", [])
    total_pages = data.get("nbPages", 1)

    if not hits:
        break

    raw = [{"title": h.get("title",""), "author": h.get("author",""), ...} for h in hits]
    # pipeline + save as normal

    page += 1
    if page >= total_pages or page >= 5:
        break
```

## Output proof
```
AsyncFetcher OK: https://hn.algolia.com/api/v1/search?query=python&tags=story&page=0 (HTTP 200)
DataValidator: 20/20 items valid (100.0% pass rate)
Page 0/50 — 20 stories
...
Page 4/50 — 20 stories
Spider 'HNSpider' finished — fetched=5 failed=0 items=100 saved=100
```

## What to watch for

**Rotating API keys in the URL:**
Some sites embed a short-lived API key in the XHR URL (e.g. Algolia's internal infrastructure URLs). These expire. Look for a cleaner public API endpoint instead — check the site's docs or look for a simpler URL pattern without a key parameter.

**Rate limiting:**
APIs rate limit aggressively. Add delays between pages and respect `Retry-After` headers.

**Pagination tokens instead of page numbers:**
Some APIs use cursor-based pagination. Look for a `nextCursor` or `nextPageToken` field in the response and pass it back in the next request.

---

# Test 3B — Form Interaction (ASP.NET — Blocked)

## Target
`https://quotes.toscrape.com/filter.aspx`

## Pattern
**Form interaction / search** — fill dropdowns, click submit, scrape results.

## Client job equivalent
- Job boards with location/role filters
- Real estate search with price/bed/bath filters
- Flight scrapers
- Any site with a multi-field search interface

## What happened
The target uses ASP.NET with ViewState and `__doPostBack()`. The `/filter.aspx` endpoint only accepts POST requests — direct GET navigation returns `405 Method Not Allowed`. Playwright could load the form page at `/search.aspx` but the postback mechanism caused timeouts finding the `select#author` element.

## Why it failed
ASP.NET's ViewState mechanism keeps server-side state. When you select an author, `__doPostBack()` fires and reloads the page with a new ViewState token. Playwright's `networkidle` and `domcontentloaded` both struggle to reliably detect when this postback cycle completes.

## Correct approach for future ASP.NET jobs
```python
# Step 1 — Navigate to the GET entry point, not the POST handler
await page.goto("https://site.com/search.aspx", wait_until="domcontentloaded")
await asyncio.sleep(3)  # let ViewState initialize

# Step 2 — Wait explicitly for the select element
await page.wait_for_selector("select#author", timeout=30000)

# Step 3 — Select option and wait for postback to complete
await page.select_option("select#author", "Albert Einstein")
await asyncio.sleep(3)  # postback takes time — networkidle is unreliable here

# Step 4 — Click submit and wait
await page.click("input[type='submit']")
await asyncio.sleep(3)
html = await page.content()
```

## Key lesson
Never navigate directly to the POST handler URL (`/filter.aspx`). Always start at the GET entry point and let the form submit naturally. Use `asyncio.sleep()` instead of `wait_for_load_state("networkidle")` for ASP.NET postbacks.

---

# Test 4A — Real E-commerce with Anti-Bot

## Target
`https://www.amazon.com/s?k=python+books`

## Pattern
**Production anti-bot protection** — Amazon uses a multi-layer bot detection system: TLS fingerprinting, JavaScript challenges, behavioral analysis, and IP reputation scoring.

## Client job equivalent
- Price monitoring and comparison
- Competitor product analysis
- Product data aggregation
- Stock/availability tracking
- Review scraping

## What makes it hard
Amazon's bot management runs in layers:

| Layer | What it checks | How to beat it |
|-------|---------------|----------------|
| TLS fingerprint | Cipher suites, extension order | TlsFetcher (curl-cffi) |
| JS interstitial challenge | `bm-verify` token, JS execution | Playwright headless=False |
| Headless browser detection | `navigator.webdriver`, canvas, WebGL | Remove webdriver flag |
| IP reputation | Request frequency, IP history | Residential proxies |
| Behavioral signals | Mouse movement, scroll, timing | Randomized delays |

## Skeleton approach — Two phase

**Phase 1 — TlsFetcher alone (fails on Amazon):**
```python
from anti_bot.fingerprint_manager import TlsFetcher
fetcher = TlsFetcher(browser="chrome120")
result = fetcher.fetch("https://www.amazon.com/s?k=python+books")
# Returns HTTP 200 but serves JS interstitial, not product HTML
```
TlsFetcher passes the TLS check but cannot execute JavaScript to solve the `bm-verify` challenge.

**Phase 2 — Playwright headless=False (works):**
```python
browser = await pw.chromium.launch(
    headless=False,  # visible browser — bypasses headless detection
    args=["--no-sandbox", "--start-maximized"]
)
context = await browser.new_context(
    viewport={"width": 1280, "height": 800},
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    locale="en-US",
    timezone_id="America/New_York",
)
page = await context.new_page()

# Remove the key headless signal
await page.add_init_script(
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)

await page.goto(url, wait_until="domcontentloaded", timeout=90000)
await asyncio.sleep(7)  # let JS challenge resolve and redirect fire

await page.wait_for_selector(
    "div[data-component-type='s-search-result']",
    timeout=20000
)
html = await page.content()
```

## CSS selectors for Amazon search results
```python
cards     = soup.select("div[data-component-type='s-search-result']")
title     = card.select_one("h2 span")
price     = card.select_one("span.a-price span.a-offscreen")
rating    = card.select_one("span.a-icon-alt")
reviews   = card.select_one("span.a-size-base.s-underline-text")
link      = card.select_one("a.a-link-normal.s-no-outline")
```

## Output proof
```
AmazonSpider: navigating to https://www.amazon.com/s?k=python+books&page=3
AmazonSpider: product cards visible
AmazonSpider: found 48 product cards on page 3
DataValidator: 48/48 items valid (100.0% pass rate)
CsvStorage: saved 48 rows to data/output.csv
Spider 'AmazonSpider' finished — fetched=0 failed=0 items=48 saved=48
```

## What to watch for

**JS interstitial / bm-verify page:**
```
meta http-equiv="refresh" content="5; URL='/s?k=...&bm-verify=AAQAAAAN...
```
Cause: TlsFetcher passes TLS but cannot execute JS challenge.
Fix: Switch to Playwright headless=False.

**Timeout on page.goto:**
Cause: Amazon's challenge page takes longer than 60s on slow connections.
Fix: Increase timeout to `90000` and add retry loop (3 attempts).

**Page loads but no product cards:**
Cause: Still on challenge page or CAPTCHA page.
Fix: Check for `"Robot Check"` or `"Enter the characters"` in HTML and skip/retry.

**Pages 1 and 2 timeout but page 3 succeeds:**
Cause: Amazon's servers vary response time per request. Each page is an independent browser session.
Fix: Add retry loop with 3 attempts per page and `timeout=90000`.

**IP gets banned after repeated runs:**
Cause: Same residential IP hitting Amazon repeatedly.
Fix: Add `asyncio.sleep(random.uniform(3, 8))` between pages and use rotating proxies for production jobs.

---

# General Rules for Any Scraping Job

## Rule 1 — Identify the rendering type first
Before writing any code, open the target URL in Chrome with JavaScript disabled (`Settings → Site Settings → JavaScript → Blocked`). If the page is empty or broken — it's a JS site, use BrowserFetcher. If it looks normal — it's static, use AsyncFetcher.

## Rule 2 — Check for hidden APIs first
Open Chrome DevTools → Network tab → reload the page → filter by `Fetch/XHR`. If you see API calls returning JSON, call the API directly with AsyncFetcher. API scraping is faster, cheaper, and more reliable than browser scraping.

## Rule 3 — Always do a quick selector audit
```python
from parser.bs4_parser import BS4Parser
from fetcher.http_fetcher import HttpFetcher

with HttpFetcher() as f:
    result = f.fetch("https://target-site.com")

parser = BS4Parser()
soup = parser.make_soup(result.html)
print(parser.get_all_text(soup, "h2.product-title")[:5])
# Empty list = wrong selector. Real data = good to go.
```

## Rule 4 — Rate limiting is not optional
```bash
RATE_LIMIT=0.5   # 1 req/2s — safe default
RATE_LIMIT=0.2   # 1 req/5s — sensitive sites
RATE_LIMIT=2.0   # 2 req/s  — only when explicitly allowed
```

## Rule 5 — Run FingerprintAnalyzer before protected jobs
```python
from anti_bot.fingerprint_manager import FingerprintAnalyzer
from anti_bot.headers_manager import HeadersManager

headers = HeadersManager(browser="chrome").get_headers(url="https://target.com")
report = FingerprintAnalyzer().check_headers(headers)
# score=0 (LOW) → safe. score=5+ → add proxies and TLS fetcher.
```

## Rule 6 — Always checkpoint large jobs
```python
cp = CheckpointManager(db_path="data/job.db")
await cp.init()
pending = await cp.get_pending(all_urls)
for url in pending:
    result = await fetcher.async_fetch(url)
    await cp.mark_done(url, content_hash=hash_content(result.html))
```

## Rule 7 — Always validate before saving
```python
cleaned     = cleaner.clean_items(raw)
transformed = transformer.transform_items(cleaned)
batch       = validator.validate_batch(transformed)
await storage.save(batch.valid_items)
```

## Rule 8 — Query results with query_db.py before delivery
```bash
python tools/query_db.py --db data/output.db --table items --count
python tools/query_db.py --db data/output.db --table items --limit 10
python tools/query_db.py --db data/output.db --table items --export csv
```

---

# Quick Reference — Which fetcher for which job

| Situation | Fetcher | Why |
|-----------|---------|-----|
| Site renders with JS disabled | `AsyncFetcher` | Static HTML |
| Site blank with JS disabled | `BrowserFetcher` | JS rendering required |
| Site has infinite scroll | `BrowserFetcher` + scroll loop | Need JS execution + scroll |
| Site requires login (HTML form) | `SessionManager` | Cookie persistence |
| Site requires login (JS form) | `Playwright` | Full browser needed |
| Cloudflare / TLS challenge only | `TlsFetcher` | TLS fingerprint spoofing |
| Cloudflare + JS challenge | `Playwright headless=False` | Full browser + no webdriver flag |
| Site returns JSON from API | `AsyncFetcher` | Direct API call |
| Large batch, 100+ URLs | `BatchFetcher` | Chunked concurrent |
| ASP.NET form with postback | `Playwright` + `asyncio.sleep()` | ViewState requires browser |

---

# Quick Reference — Which storage for which job

| Situation | Storage | Why |
|-----------|---------|-----|
| One-off delivery to client | `CsvStorage` | Client opens in Excel |
| Resumable job, local | `SqliteStorage` | Fast, no setup |
| Recurring retainer, large scale | `PostgresStorage` | Upsert, concurrent writes |
| Need to query before export | `SqliteStorage` + `query_db.py` | SQL queries |

---

# Files in the testing branch

```
spiders/
  quotes_js_spider.py          ← Test 1A: JS rendering
  infinite_scroll_spider.py    ← Test 2A: Infinite scroll
  hn_spider.py                 ← Test 3A: AJAX/XHR JSON API
  form_interaction_spider.py   ← Test 3B: Form interaction (ASP.NET blocked)
  amazon_spider.py             ← Test 4A: Real e-commerce anti-bot

run_quotes.py                  ← Test runner: quotes.toscrape.com static
run_hn.py                      ← Test runner: HN Algolia API
run_form.py                    ← Test runner: form interaction
run_amazon.py                  ← Test runner: Amazon

tools/
  query_db.py                  ← CLI tool for querying any SQLite DB

TESTING.md                     ← This file
new_chat_prompt.md             ← Paste this at the start of any new chat
```
