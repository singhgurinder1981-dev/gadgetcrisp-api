"""
GadgetCrisp API v3.0
- Price compare engine
- Smart fallback
- WordPress gadget auto-publisher
Python 3.13 compatible
"""

import os
import re
import time
import random
import base64
import logging
from urllib.parse import quote_plus, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

WP_URL = os.getenv("WP_URL", "https://gadgetcrisp.com")
WP_USER = os.getenv("WP_USER")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

AMAZON_TAG = os.getenv("AMAZON_TAG", "gadgetcrisp-21")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# --------------------------------------------------
# USER AGENTS
# --------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) Chrome/122.0 Safari/537.36",
]

def headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-IN,en;q=0.9",
    }

# --------------------------------------------------
# WORDPRESS AUTH
# --------------------------------------------------

def wp_headers():
    token = base64.b64encode(
        f"{WP_USER}:{WP_APP_PASSWORD}".encode()
    ).decode()

    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json"
    }

# --------------------------------------------------
# FEATURED IMAGE UPLOAD
# --------------------------------------------------

def upload_image(image_url, title):
    try:
        img = requests.get(image_url, headers=headers(), timeout=15)
        if img.status_code != 200:
            return None

        filename = re.sub(r'[^a-zA-Z0-9]', '-', title.lower()) + ".jpg"

        upload_headers = wp_headers()
        upload_headers.update({
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/jpeg"
        })

        r = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            headers=upload_headers,
            data=img.content
        )

        if r.status_code in (200, 201):
            return r.json().get("id")

    except Exception as e:
        log.error("Image upload error: %s", e)

    return None

# --------------------------------------------------
# CATEGORY FETCH
# --------------------------------------------------

def get_category_id(slug):
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/gadget_category?slug={slug}",
        headers=wp_headers()
    )
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    return None

# --------------------------------------------------
# PUBLISH GADGET
# --------------------------------------------------

def publish_gadget(data):

    title = data.get("title")
    content = data.get("content")
    category_slug = data.get("category", "smartphones")
    image_url = data.get("image")

    if not title or not content:
        return {"error": "Title and content required"}, 400

    category_id = get_category_id(category_slug)
    featured_id = upload_image(image_url, title) if image_url else None

    payload = {
        "title": title,
        "content": content,
        "status": "publish",
        "slug": re.sub(r'[^a-z0-9]+', '-', title.lower()),
        "featured_media": featured_id,
        "gadget_category": [category_id] if category_id else []
    }

    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/gadget",
        headers=wp_headers(),
        json=payload
    )

    if r.status_code in (200, 201):
        post = r.json()
        return {
            "success": True,
            "post_id": post["id"],
            "link": post["link"]
        }, 200

    return {"error": r.text}, 500

# --------------------------------------------------
# DEMO COMPARE ENGINE (Simple)
# --------------------------------------------------

def detect_category(q):
    q = q.lower()
    if "iphone" in q or "samsung" in q:
        return "Smartphones"
    if "laptop" in q or "macbook" in q:
        return "Laptops"
    return "Electronics"

@app.route("/compare", methods=["GET"])
def compare():
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "Provide query"}), 400

    base_price = random.randint(20000, 90000)

    return jsonify({
        "name": q.title(),
        "category": detect_category(q),
        "rating": round(random.uniform(4.0, 4.7), 1),
        "reviews": random.randint(2000, 25000),
        "prices": [
            {
                "store": "amazon",
                "price": base_price,
                "affiliate": f"https://www.amazon.in/s?k={quote_plus(q)}&tag={AMAZON_TAG}"
            }
        ],
        "source": "demo"
    })

# --------------------------------------------------
# PUBLISH ROUTE
# --------------------------------------------------

@app.route("/publish", methods=["POST"])
def publish():
    data = request.get_json()
    return publish_gadget(data)

# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route("/")
def index():
    return jsonify({"status": "GadgetCrisp API v3 running 🚀"})

# --------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
