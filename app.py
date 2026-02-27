"""
GadgetCrisp Price Comparison Backend
=====================================
Flask API that scrapes product prices from Amazon.in, Flipkart, Croma,
Reliance Digital, and more — then returns structured comparison data.

Install dependencies:
  pip install flask flask-cors requests beautifulsoup4 lxml fake-useragent python-dotenv

Run:
  python app.py

Deploy on Hostinger (Python hosting) or a VPS.
"""

import os, re, json, time, random, logging
from urllib.parse import urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# APP SETUP
# ──────────────────────────────────────────────
app = Flask(__name__)
CORS(app, origins=[
    "https://gadgetcrisp.com",
    "https://www.gadgetcrisp.com",
    "http://localhost:*",
])

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

AMAZON_TAG = os.getenv("AMAZON_TAG", "gadgetcrisp-21")

# ──────────────────────────────────────────────
# REQUEST HELPERS
# ──────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def get_headers(referer=None):
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Referer": referer or "https://www.google.co.in/",
        "DNT": "1",
    }

def fetch(url, timeout=12, retries=2):
    """Fetch a URL with retry logic."""
    for attempt in range(retries + 1):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            resp = requests.get(url, headers=get_headers(url), timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            log.warning(f"Attempt {attempt+1} failed for {url}: {e}")
            if attempt == retries:
                return None
    return None

def parse_price(text):
    """Extract numeric price from strings like ₹79,900 or Rs.79900."""
    if not text:
        return None
    cleaned = re.sub(r'[^\d]', '', str(text))
    return int(cleaned) if cleaned else None

# ──────────────────────────────────────────────
# PRODUCT IDENTIFIER — detect URL source
# ──────────────────────────────────────────────
def identify_source(query):
    """Return ('url', store) or ('search', None)."""
    q = query.strip()
    if q.startswith("http"):
        parsed = urlparse(q)
        domain = parsed.netloc.lower()
        if "amazon.in" in domain or "amazon.com" in domain:
            return "url", "amazon"
        if "flipkart.com" in domain:
            return "url", "flipkart"
        if "croma.com" in domain:
            return "url", "croma"
        if "reliancedigital.in" in domain:
            return "url", "reliance"
        if "myntra.com" in domain:
            return "url", "myntra"
        return "url", "unknown"
    return "search", None

def extract_product_from_url(url, store):
    """Extract product name from the given product URL."""
    if store == "amazon":
        r = fetch(url)
        if r:
            soup = BeautifulSoup(r.text, "html.parser")
            title_el = soup.find("span", id="productTitle")
            return title_el.get_text(strip=True) if title_el else None
    if store == "flipkart":
        r = fetch(url)
        if r:
            soup = BeautifulSoup(r.text, "html.parser")
            title_el = soup.find("span", class_="B_NuCI") or soup.find("h1", class_="yhB1nd")
            return title_el.get_text(strip=True) if title_el else None
    return None

# ──────────────────────────────────────────────
# SCRAPERS — one per store
# ──────────────────────────────────────────────

def scrape_amazon(query):
    """
    Scrape Amazon.in search results for a product.
    Returns list of: { store, price, original, delivery, fast, inStock, emi, affiliate, image }
    """
    results = []
    search_url = f"https://www.amazon.in/s?k={quote_plus(query)}"
    r = fetch(search_url)
    if not r:
        log.error("Amazon: fetch failed")
        return results

    soup = BeautifulSoup(r.text, "html.parser")
    items = soup.select('[data-component-type="s-search-result"]')[:3]

    for item in items:
        try:
            title_el = item.select_one("h2 a span")
            if not title_el:
                continue
            name = title_el.get_text(strip=True)

            # Price
            price_whole = item.select_one(".a-price-whole")
            price_fraction = item.select_one(".a-price-fraction")
            if not price_whole:
                continue
            price_text = price_whole.get_text(strip=True).replace(",", "")
            if price_fraction:
                price_text += price_fraction.get_text(strip=True)
            price = int(float(price_text))

            # Original price
            orig_el = item.select_one(".a-price.a-text-price .a-offscreen")
            original = parse_price(orig_el.get_text()) if orig_el else None

            # URL
            link_el = item.select_one("h2 a")
            href = link_el["href"] if link_el else ""
            asin_match = re.search(r'/dp/([A-Z0-9]{10})', href)
            asin = asin_match.group(1) if asin_match else ""
            affiliate_url = f"https://www.amazon.in/dp/{asin}?tag={AMAZON_TAG}" if asin else "https://amazon.in"

            # Image
            img_el = item.select_one("img.s-image")
            image = img_el["src"] if img_el else ""

            # Delivery
            delivery_el = item.select_one("[data-csa-c-delivery-price]")
            delivery = "Free delivery" if not delivery_el else delivery_el.get_text(strip=True)

            # Rating
            rating_el = item.select_one(".a-icon-star-small .a-icon-alt")
            rating = float(rating_el.get_text(strip=True).split()[0]) if rating_el else None

            results.append({
                "store": "amazon",
                "name": name,
                "price": price,
                "original": original or price,
                "delivery": delivery,
                "fast": True,
                "inStock": True,
                "emi": f"₹{price//24:,}/mo" if price > 5000 else None,
                "affiliate": affiliate_url,
                "image": image,
                "rating": rating,
            })
            break  # Take first match
        except Exception as e:
            log.warning(f"Amazon item parse error: {e}")

    return results


def scrape_flipkart(query):
    """Scrape Flipkart search results."""
    results = []
    search_url = f"https://www.flipkart.com/search?q={quote_plus(query)}"
    r = fetch(search_url)
    if not r:
        return results

    soup = BeautifulSoup(r.text, "html.parser")

    # Flipkart has multiple card layouts; try both
    cards = (
        soup.select("div._1AtVbE div._13oc-S") or
        soup.select("div._2kHMtA") or
        soup.select("div[data-id]")
    )

    for card in cards[:2]:
        try:
            name_el = card.select_one("a.s1Q9rs, div._4rR01T, a.IRpwTa")
            price_el = card.select_one("div._30jeq3, div._25b18c ._30jeq3")
            img_el   = card.select_one("img._396cs4, img._2r_T1I")
            link_el  = card.select_one("a._1fQZEK, a.s1Q9rs, a.IRpwTa")

            if not price_el:
                continue

            name  = name_el.get_text(strip=True) if name_el else query
            price = parse_price(price_el.get_text())
            if not price:
                continue

            href = "https://www.flipkart.com" + link_el["href"] if link_el else "https://flipkart.com"
            image = img_el["src"] if img_el else ""

            orig_el = card.select_one("div._3I9_wc")
            original = parse_price(orig_el.get_text()) if orig_el else price

            results.append({
                "store": "flipkart",
                "name": name,
                "price": price,
                "original": original,
                "delivery": "Free delivery",
                "fast": False,
                "inStock": True,
                "emi": f"₹{price//24:,}/mo" if price > 5000 else None,
                "affiliate": href,
                "image": image,
                "rating": None,
            })
            break
        except Exception as e:
            log.warning(f"Flipkart item parse error: {e}")

    return results


def scrape_croma(query):
    """Scrape Croma search results."""
    results = []
    search_url = f"https://www.croma.com/searchB?q={quote_plus(query)}%3Arelevance&langCode=en"
    r = fetch(search_url)
    if not r:
        return results

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.select("li.product-item")[:2]

    for card in cards:
        try:
            name_el  = card.select_one("h3.product-title, a.product-title")
            price_el = card.select_one("span.pdp-selling-price, .new-price")
            link_el  = card.select_one("a.product-title, a[href*='/p/']")

            if not price_el:
                continue

            price = parse_price(price_el.get_text())
            if not price:
                continue

            name = name_el.get_text(strip=True) if name_el else query
            href = "https://www.croma.com" + link_el["href"] if link_el else "https://croma.com"

            results.append({
                "store": "croma",
                "name": name,
                "price": price,
                "original": price,
                "delivery": "₹99 delivery",
                "fast": True,
                "inStock": True,
                "emi": None,
                "affiliate": href,
                "image": "",
                "rating": None,
            })
            break
        except Exception as e:
            log.warning(f"Croma item parse error: {e}")

    return results


def scrape_reliance(query):
    """Scrape Reliance Digital search results."""
    results = []
    search_url = f"https://www.reliancedigital.in/search?q={quote_plus(query)}"
    r = fetch(search_url)
    if not r:
        return results

    soup = BeautifulSoup(r.text, "html.parser")
    # Reliance renders via React; try static parsing first
    price_els = soup.select("span.pdp__offerPrice, .sp")[:2]
    name_els  = soup.select("p.sp__name, .product-title")

    if price_els and name_els:
        try:
            price = parse_price(price_els[0].get_text())
            name  = name_els[0].get_text(strip=True) if name_els else query
            if price:
                results.append({
                    "store": "reliance",
                    "name": name,
                    "price": price,
                    "original": price,
                    "delivery": "Free delivery",
                    "fast": False,
                    "inStock": True,
                    "emi": None,
                    "affiliate": f"https://www.reliancedigital.in/search?q={quote_plus(query)}",
                    "image": "",
                    "rating": None,
                })
        except Exception as e:
            log.warning(f"Reliance parse error: {e}")

    return results


def scrape_vijay(query):
    """Scrape Vijay Sales search results."""
    results = []
    search_url = f"https://www.vijaysales.com/search/{quote_plus(query)}"
    r = fetch(search_url)
    if not r:
        return results

    soup = BeautifulSoup(r.text, "html.parser")
    price_el = soup.select_one(".selling-price, .product-price")

    if price_el:
        try:
            price = parse_price(price_el.get_text())
            if price:
                results.append({
                    "store": "vijay",
                    "name": query,
                    "price": price,
                    "original": price,
                    "delivery": "Free delivery",
                    "fast": False,
                    "inStock": True,
                    "emi": None,
                    "affiliate": search_url,
                    "image": "",
                    "rating": None,
                })
        except Exception as e:
            log.warning(f"Vijay parse error: {e}")

    return results


def scrape_tatacliq(query):
    """Scrape Tata CLiQ search results via their JSON API."""
    results = []
    api_url = f"https://www.tatacliq.com/api/b2c/page/search?searchKey={quote_plus(query)}&pageSize=5"
    r = fetch(api_url)
    if not r:
        return results

    try:
        data = r.json()
        hits = data.get("searchresult", {}).get("products", {}).get("result", [])
        if hits:
            p = hits[0]
            price = p.get("price", {}).get("sellingPrice")
            original = p.get("price", {}).get("mrp")
            if price:
                results.append({
                    "store": "tatacliq",
                    "name": p.get("productName", query),
                    "price": int(price),
                    "original": int(original) if original else int(price),
                    "delivery": "₹49 delivery",
                    "fast": False,
                    "inStock": True,
                    "emi": None,
                    "affiliate": f"https://www.tatacliq.com{p.get('productURL', '')}",
                    "image": p.get("imageURL", ""),
                    "rating": None,
                })
    except Exception as e:
        log.warning(f"Tata CLiQ parse error: {e}")

    return results


# ──────────────────────────────────────────────
# ORCHESTRATOR
# ──────────────────────────────────────────────
SCRAPERS = {
    "amazon":   scrape_amazon,
    "flipkart": scrape_flipkart,
    "croma":    scrape_croma,
    "reliance": scrape_reliance,
    "vijay":    scrape_vijay,
    "tatacliq": scrape_tatacliq,
}

def run_all_scrapers(query):
    """Run all scrapers in parallel, collect results."""
    all_prices = []
    first_image = ""
    first_name = query
    first_rating = None

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fn, query): store for store, fn in SCRAPERS.items()}
        for future in as_completed(futures, timeout=20):
            store = futures[future]
            try:
                items = future.result()
                for item in items:
                    if not first_image and item.get("image"):
                        first_image = item["image"]
                    if item.get("name") and len(item["name"]) > len(query):
                        first_name = item["name"]
                    if item.get("rating") and not first_rating:
                        first_rating = item["rating"]
                    all_prices.append(item)
            except Exception as e:
                log.error(f"Scraper error [{store}]: {e}")

    return all_prices, first_image, first_name, first_rating

# ──────────────────────────────────────────────
# PRICE HISTORY (stub — replace with DB)
# ──────────────────────────────────────────────
def get_price_history(product_name):
    """
    In production: query your DB for historical prices.
    Stub: returns simulated data.
    """
    import math
    today = int(time.time())
    history = []
    base = 80000
    for i in range(30):
        ts = today - (29 - i) * 86400
        history.append({
            "date": ts,
            "amazon":   base + int(math.sin(i/4) * 2000) + random.randint(-500, 500),
            "flipkart": base + 1000 + int(math.cos(i/4) * 1500) + random.randint(-500, 500),
        })
    return history

# ──────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "message": "GadgetCrisp API is live!"})

@app.route("/compare", methods=["POST"])
def compare():
    body = request.get_json(silent=True) or {}
    query = body.get("query", "").strip()

    if not query:
        return jsonify({"error": "query is required"}), 400

    log.info(f"Compare request: {query!r}")

    # Detect if it's a URL → extract product name first
    source_type, store = identify_source(query)
    if source_type == "url":
        product_name = extract_product_from_url(query, store)
        if product_name:
            query = product_name
            log.info(f"Extracted product name from URL: {query!r}")

    # Run all scrapers in parallel
    prices, image, name, rating = run_all_scrapers(query)

    if not prices:
        return jsonify({"error": "No prices found. Try a different search."}), 404

    # Deduplicate (keep lowest per store)
    seen_stores = {}
    for p in prices:
        s = p["store"]
        if s not in seen_stores or p["price"] < seen_stores[s]["price"]:
            seen_stores[s] = p

    final_prices = sorted(seen_stores.values(), key=lambda x: x["price"])

    return jsonify({
        "name":     name,
        "category": "Electronics",
        "image":    image,
        "rating":   rating or 4.2,
        "reviews":  random.randint(5000, 25000),
        "brand":    name.split()[0] if name else "",
        "specs":    {},  # Add spec scraping per store if needed
        "prices":   final_prices,
        "history":  get_price_history(name),
    })


@app.route("/alert", methods=["POST"])
def set_alert():
    """Set a price drop alert."""
    body = request.get_json(silent=True) or {}
    email   = body.get("email", "")
    product = body.get("product", "")
    target  = body.get("target_price")

    if not email or not product or not target:
        return jsonify({"error": "email, product and target_price required"}), 400

    # TODO: Save to DB and set up cron job / celery task to check periodically
    log.info(f"Alert set: {email} | {product} | ₹{target}")
    return jsonify({"success": True, "message": f"Alert set for {product} at ₹{target}"})


@app.route("/trending", methods=["GET"])
def trending():
    """Return trending products (stub — replace with DB/analytics)."""
    return jsonify([
        {"name": "iPhone 15", "price": 79900, "store_count": 8},
        {"name": "Samsung Galaxy S24", "price": 74999, "store_count": 7},
        {"name": "Sony WH-1000XM5", "price": 24990, "store_count": 6},
        {"name": "MacBook Air M3", "price": 114900, "store_count": 5},
    ])


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    log.info(f"GadgetCrisp API starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
