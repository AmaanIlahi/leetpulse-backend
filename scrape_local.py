"""
Standalone local scraper — NOT part of the FastAPI app.

Usage:
    python scrape_local.py [--url http://localhost:8000] [--company google]

Requires:
    pip install playwright requests python-dotenv
    playwright install chromium
"""

import argparse
import json
import re
import sys
import time

try:
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    print("Run: pip install playwright && playwright install chromium")
    sys.exit(1)

import httpx
import requests
from dotenv import load_dotenv
import os

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

COMPANY_CONFIGS = {
    "meta": {
        "slug": "facebook-three-months",
        "url":  "https://leetcode.com/company/facebook/?favoriteSlug=facebook-three-months",
    },
    "google": {
        "slug": "google-thirty-days",
        "url":  "https://leetcode.com/company/google/?favoriteSlug=google-thirty-days",
    },
    "amazon": {
        "slug": "amazon-thirty-days",
        "url":  "https://leetcode.com/company/amazon/?favoriteSlug=amazon-thirty-days",
    },
    "microsoft": {
        "slug": "microsoft-three-months",
        "url":  "https://leetcode.com/company/microsoft/?favoriteSlug=microsoft-three-months",
    },
    "apple": {
        "slug": "apple-six-months",
        "url":  "https://leetcode.com/company/apple/?favoriteSlug=apple-six-months",
    },
    "netflix": {
        "slug": "netflix-all",
        "url":  "https://leetcode.com/company/netflix/?favoriteSlug=netflix-all",
    },
    "uber": {
        "slug": "uber-six-months",
        "url":  "https://leetcode.com/company/uber/?favoriteSlug=uber-six-months",
    },
    "bloomberg": {
        "slug": "bloomberg-three-months",
        "url":  "https://leetcode.com/company/bloomberg/?favoriteSlug=bloomberg-three-months",
    },
}

TAGS_API = "https://alfa-leetcode-api.onrender.com/select"

# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def scrape_company(page: Page, company: str, url: str, debug: bool = False) -> list[dict]:
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(3000)

    page_title = page.title()
    print(f"  Page title: {page_title}")

    if "verify" in page_title.lower() or "challenge" in page_title.lower():
        print(f"  [error] Bot detection triggered for {company} (page title: '{page_title}')")
        return []

    # Scroll until page height stabilises (max 20 scrolls, 1.5s each)
    prev_height = 0
    stable_rounds = 0
    for _ in range(20):
        page.keyboard.press("End")
        page.wait_for_timeout(1500)
        height = page.evaluate("document.body.scrollHeight")
        if height == prev_height:
            stable_rounds += 1
            if stable_rounds >= 3:
                break
        else:
            stable_rounds = 0
        prev_height = height

    # Primary extraction via JS — anchor-based, no Tailwind bracket selectors
    problems: list[dict] = page.evaluate("""
    () => {
      const results = [];

      const links = document.querySelectorAll("a[href*='/problems/']");

      links.forEach(link => {
        const href = link.getAttribute('href') || '';
        const slugMatch = href.match(/\\/problems\\/([^\\/]+)/);
        if (!slugMatch) return;
        const slug = slugMatch[1].split('?')[0];

        const titleEl = link.querySelector('div[class*="ellipsis"]') ||
                        link.querySelector('div[class*="line-clamp"]');
        if (!titleEl) return;
        const title = titleEl.textContent.trim().replace(/^\\d+\\.\\s*/, '');
        if (!title) return;

        const allP = link.querySelectorAll('p');
        let difficulty = 'Medium';
        allP.forEach(p => {
          const txt = p.textContent.trim();
          if (txt === 'Easy') difficulty = 'Easy';
          else if (txt === 'Hard') difficulty = 'Hard';
          else if (txt.startsWith('Med')) difficulty = 'Medium';
        });

        const bars = link.querySelectorAll('div[class*="bg-brand-orange"]');
        const freqBar = Math.min(bars.length / 8, 1.0);

        results.push({ title, slug, difficulty, freqBar });
      });

      const seen = new Set();
      return results.filter(p => {
        if (seen.has(p.slug)) return false;
        seen.add(p.slug);
        return true;
      });
    }
    """)

    # Fallback: scan all problem links directly if JS extraction returned nothing
    if not problems:
        print(f"  [warn] JS extraction returned 0 rows for {company}, trying link fallback")
        links = page.query_selector_all("a[href*='/problems/']")
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                slug_match = re.search(r"/problems/([^/?#]+)", href)
                if not slug_match:
                    continue
                slug = slug_match.group(1)
                title_el = link.query_selector("div.ellipsis")
                if not title_el:
                    continue
                title = re.sub(r"^\d+\.\s*", "", title_el.inner_text().strip())
                diff_el = link.query_selector("p")
                difficulty = "Medium"
                if diff_el:
                    txt = diff_el.inner_text().strip()
                    if txt == "Easy":
                        difficulty = "Easy"
                    elif txt == "Hard":
                        difficulty = "Hard"
                problems.append({
                    "title":      title,
                    "slug":       slug,
                    "difficulty": difficulty,
                    "tags":       [],
                    "company":    company,
                    "freq_bar":   0.5,
                })
            except Exception as e:
                print(f"  [warn] Fallback parse error: {e}")
                continue
    else:
        # Normalise JS output to match expected dict shape
        problems = [
            {
                "title":      p["title"],
                "slug":       p.get("slug", ""),
                "difficulty": p["difficulty"],
                "tags":       [],
                "company":    company,
                "freq_bar":   round(float(p.get("freqBar", 0.0)), 4),
            }
            for p in problems
        ]

    print(f"  Found {len(problems)} problems")
    for p in problems[:3]:
        print(f"    - {p['title']} [{p['difficulty']}] slug={p['slug']}")

    return problems


# ---------------------------------------------------------------------------
# Tag enrichment
# ---------------------------------------------------------------------------

_TAG_QUERY = """
query questionData($titleSlug: String!) {
    question(titleSlug: $titleSlug) {
        topicTags { name }
    }
}
"""


def enrich_with_tags(
    problems: list[dict],
    session_cookie: str,
    csrf_token: str,
) -> list[dict]:
    cache:     dict[str, list[str]] = {}
    enriched:  list[dict] = []
    cache_hits = 0
    api_calls  = 0
    total      = len(problems)

    headers = {
        "Cookie":       f"LEETCODE_SESSION={session_cookie}; csrftoken={csrf_token}",
        "x-csrftoken":  csrf_token,
        "Content-Type": "application/json",
        "Referer":      "https://leetcode.com",
    }

    for i, problem in enumerate(problems):
        slug = problem["slug"]

        if slug in cache:
            problem["tags"] = cache[slug]
            cache_hits += 1
        else:
            try:
                r = httpx.post(
                    "https://leetcode.com/graphql",
                    headers=headers,
                    json={
                        "operationName": "questionData",
                        "query":         _TAG_QUERY,
                        "variables":     {"titleSlug": slug},
                    },
                    timeout=10,
                )
                tags = [
                    t["name"]
                    for t in r.json()
                               .get("data", {})
                               .get("question", {})
                               .get("topicTags", [])
                ]
            except Exception as e:
                print(f"  [warn] Tag fetch failed for {slug}: {e}")
                tags = []
            cache[slug]     = tags
            problem["tags"] = tags
            api_calls += 1
            time.sleep(0.2)

        enriched.append(problem)

        if (i + 1) % 10 == 0:
            print(f"  Enriched {i + 1}/{total} ({cache_hits} from cache)...")

    print(f"  Tag cache: {cache_hits} hits, {api_calls} API calls made (LeetCode GraphQL)")
    return enriched


# ---------------------------------------------------------------------------
# Backend push
# ---------------------------------------------------------------------------

def push_to_backend(problems: list[dict], api_base_url: str, admin_secret: str) -> bool:
    base = api_base_url.rstrip("/")
    print(f"Pushing {len(problems)} problems to {base}...")

    print("  Waking up backend...")
    for attempt in range(10):
        try:
            health = requests.get(f"{base}/health", timeout=10)
            if health.status_code == 200:
                print("  Backend is ready")
                break
        except Exception:
            pass
        print(f"  Waiting... attempt {attempt + 1}/10")
        time.sleep(3)

    batch_size    = 100
    total_batches = (len(problems) + batch_size - 1) // batch_size
    total_ingested = 0

    for i in range(0, len(problems), batch_size):
        batch     = problems[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        try:
            r = requests.post(
                f"{base}/admin/rag/ingest",
                headers={"X-Admin-Key": admin_secret},
                json={"problems": batch},
                timeout=120,
            )
            if r.status_code == 200:
                total_ingested += len(batch)
                print(f"  Batch {batch_num}/{total_batches} OK "
                      f"({total_ingested}/{len(problems)} total)")
            else:
                print(f"  Batch {batch_num}/{total_batches} FAILED: [{r.status_code}]")
        except Exception as e:
            print(f"  Batch {batch_num}/{total_batches} ERROR: {e}")

        time.sleep(1)

    if total_ingested == len(problems):
        print(f"  Backend push: OK ({total_ingested} problems)")
        return True
    else:
        print(f"  Backend push: PARTIAL ({total_ingested}/{len(problems)})")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

LAST_SCRAPE_FILE = "last_scrape.json"


def main():
    parser = argparse.ArgumentParser(description="Scrape LeetCode company problems locally")
    parser.add_argument("--url",       default=os.getenv("API_BASE_URL", "http://localhost:8000"),
                        help="Backend API base URL")
    parser.add_argument("--company",   default=None,
                        help="Scrape only this company (e.g. google)")
    parser.add_argument("--debug",     action="store_true",
                        help="Save screenshots and dump page content for each company")
    parser.add_argument("--push-only", action="store_true",
                        help=f"Skip scraping; push {LAST_SCRAPE_FILE} directly to backend")
    args = parser.parse_args()

    admin_secret = os.getenv("ADMIN_SECRET", "")
    if not admin_secret:
        print("[error] ADMIN_SECRET not set in .env")
        sys.exit(1)

    # --push-only: load cached results and push, skip everything else
    if args.push_only:
        if not os.path.exists(LAST_SCRAPE_FILE):
            print(f"[error] {LAST_SCRAPE_FILE} not found — run without --push-only first")
            sys.exit(1)
        with open(LAST_SCRAPE_FILE) as f:
            enriched = json.load(f)
        print(f"Loaded {len(enriched)} problems from {LAST_SCRAPE_FILE}")
        print(f"Pushing to {args.url}...")
        success = push_to_backend(enriched, args.url, admin_secret)
        print(f"  Backend push: {'OK' if success else 'FAILED'}")
        return

    targets = {
        k: v for k, v in COMPANY_CONFIGS.items()
        if not args.company or args.company.lower() == k
    }
    if not targets:
        print(f"[error] Unknown company '{args.company}'. "
              f"Choices: {', '.join(COMPANY_CONFIGS)}")
        sys.exit(1)

    all_problems: list[dict] = []
    per_company:  dict[str, int] = {}

    leetcode_session = os.getenv("LEETCODE_SESSION", "")
    leetcode_csrf    = os.getenv("LEETCODE_CSRF_TOKEN", "")
    if not leetcode_session or not leetcode_csrf:
        print("[error] LEETCODE_SESSION and LEETCODE_CSRF_TOKEN must be set in .env")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # Navigate first so the domain is established, then inject cookies
        page = context.new_page()
        page.goto("https://leetcode.com/", wait_until="networkidle")

        context.add_cookies([
            {
                "name":     "LEETCODE_SESSION",
                "value":    leetcode_session,
                "domain":   "leetcode.com",
                "path":     "/",
                "httpOnly": True,
                "secure":   True,
                "sameSite": "Lax",
            },
            {
                "name":     "csrftoken",
                "value":    leetcode_csrf,
                "domain":   "leetcode.com",
                "path":     "/",
                "secure":   True,
                "sameSite": "Lax",
            },
        ])

        # Reload so the session cookies take effect
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Verify login
        if page.query_selector("text=Sign in") is not None and \
           page.query_selector("img[alt='avatar']") is None:
            print("[error] Cookie injection failed — not logged in")
            print("Please refresh your LEETCODE_SESSION in .env")
            browser.close()
            sys.exit(1)

        print("  Logged in successfully")

        for company, config in targets.items():
            print(f"Scraping {company}...")
            problems = scrape_company(page, company, config["url"], debug=args.debug)
            per_company[company] = len(problems)
            print(f"  Found {len(problems)} problems")
            all_problems.extend(problems)

        browser.close()

    print(f"\nEnriching {len(all_problems)} problems with tags...")
    enriched = enrich_with_tags(all_problems, leetcode_session, leetcode_csrf)

    with open(LAST_SCRAPE_FILE, "w") as f:
        json.dump(enriched, f)
    print(f"  Saved {len(enriched)} problems to {LAST_SCRAPE_FILE}")

    print(f"Pushing {len(enriched)} problems to {args.url}...")
    success = push_to_backend(enriched, args.url, admin_secret)

    # Summary
    print("\n--- Summary ---")
    for company, count in per_company.items():
        print(f"  {company:12s}: {count} problems")
    print(f"  {'TOTAL':12s}: {len(enriched)} problems")
    print(f"  Backend push: {'OK' if success else 'FAILED'}")


if __name__ == "__main__":
    main()
