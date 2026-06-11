"""Read-only Shopify access for Nova via the Admin GraphQL API.

Reads the store domain + token from config (.env) and returns short text that
the brain turns into a spoken answer. No write/mutation operations."""
import datetime
import json
import time

import httpx

import config

API_VERSION = config.SHOPIFY_API_VERSION or "2026-01"

# Cached client-credentials access token (these last 24h; we refresh early).
_token_cache = {"value": None, "exp": 0.0}


def _store_host():
    store = (config.SHOPIFY_STORE or "").strip()
    store = store.replace("https://", "").replace("http://", "").strip("/")
    if store and "." not in store:
        store = store + ".myshopify.com"
    return store


def _endpoint():
    return f"https://{_store_host()}/admin/api/{API_VERSION}/graphql.json"


def is_configured():
    """True if we can talk to Shopify: a store + either a static Admin API token
    or a client id/secret pair (the new Dev Dashboard client-credentials grant)."""
    if not _store_host():
        return False
    if (config.SHOPIFY_TOKEN or "").strip():
        return True
    return bool((config.SHOPIFY_CLIENT_ID or "").strip()
                and (config.SHOPIFY_CLIENT_SECRET or "").strip())


def _access_token():
    """Return (token, error). Prefers a static shpat_ token; otherwise fetches one
    via the client-credentials grant (Dev Dashboard apps) and caches it. Those
    tokens expire in 24h, so Nova refreshes automatically — the user never
    handles a token, just the Client ID + Secret."""
    static = (config.SHOPIFY_TOKEN or "").strip()
    if static:
        return static, None
    cid = (config.SHOPIFY_CLIENT_ID or "").strip()
    secret = (config.SHOPIFY_CLIENT_SECRET or "").strip()
    if not (cid and secret and _store_host()):
        return None, "Shopify isn't connected yet."
    now = time.time()
    if _token_cache["value"] and now < _token_cache["exp"]:
        return _token_cache["value"], None
    try:
        r = httpx.post(
            f"https://{_store_host()}/admin/oauth/access_token",
            data={"grant_type": "client_credentials", "client_id": cid,
                  "client_secret": secret},
            timeout=15,
        )
    except Exception as e:  # noqa: BLE001
        return None, f"Couldn't reach Shopify for a token: {e}"
    if r.status_code >= 400:
        return None, (f"Shopify wouldn't issue a token ({r.status_code}). Check the client "
                      f"secret, and that the app is installed on the store with read scopes.")
    try:
        d = r.json()
        tok = d["access_token"]
        exp = float(d.get("expires_in", 86399))
    except Exception:  # noqa: BLE001
        return None, "Shopify returned an unexpected token response."
    _token_cache["value"] = tok
    _token_cache["exp"] = now + max(60.0, exp - 120.0)  # refresh a couple minutes early
    return tok, None


def _gql(query, variables=None):
    if not is_configured():
        return None, "Shopify isn't connected yet."
    token, err = _access_token()
    if err:
        return None, err
    try:
        r = httpx.post(
            _endpoint(),
            headers={"X-Shopify-Access-Token": token,
                     "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
            timeout=20,
        )
    except Exception as e:  # noqa: BLE001
        return None, f"Couldn't reach Shopify: {e}"
    if r.status_code in (401, 403):
        _token_cache["value"] = None  # force a fresh token on the next call
        return None, "Shopify rejected the credentials (check the app's scopes and that it's installed)."
    if r.status_code >= 400:
        return None, f"Shopify error {r.status_code}: {r.text[:160]}"
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return None, "Shopify returned an unexpected response."
    if data.get("errors"):
        return None, f"Shopify query problem: {json.dumps(data['errors'])[:240]}"
    return data.get("data"), None


def shop_info():
    data, err = _gql("{ shop { name myshopifyDomain currencyCode plan { displayName } } }")
    if err:
        return err
    s = data["shop"]
    return (f"Store '{s['name']}' at {s['myshopifyDomain']}, currency "
            f"{s['currencyCode']}, plan {s['plan']['displayName']}.")


def recent_orders(days=7, limit=25):
    days = int(days or 7)
    limit = min(int(limit or 25), 50)
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    q = """query($q:String!,$n:Int!){
      orders(first:$n, query:$q, sortKey:CREATED_AT, reverse:true){
        edges{ node{ name createdAt displayFinancialStatus displayFulfillmentStatus
          totalPriceSet{ shopMoney{ amount currencyCode } }
          customer{ displayName } } } } }"""
    data, err = _gql(q, {"q": f"created_at:>={since}", "n": limit})
    if err:
        return err
    edges = data["orders"]["edges"]
    if not edges:
        return f"No orders in the last {days} days."
    total, cur, lines = 0.0, "", []
    for e in edges:
        n = e["node"]
        m = n["totalPriceSet"]["shopMoney"]
        total += float(m["amount"])
        cur = m["currencyCode"]
        who = (n.get("customer") or {}).get("displayName") or "Guest"
        lines.append(f"{n['name']} {m['amount']} {cur} {n['displayFinancialStatus']}, {who}")
    head = f"{len(edges)} orders in the last {days} days totaling {round(total, 2)} {cur}."
    return head + " Most recent: " + "; ".join(lines[:8])


def dashboard_summary():
    """Structured today's-sales summary for the dashboard card (not spoken)."""
    if not is_configured():
        return {"status": "not_connected"}
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    q = """query($q:String!){
      shop{ name currencyCode }
      orders(first:100, query:$q){ edges{ node{
        totalPriceSet{ shopMoney{ amount currencyCode } } } } } }"""
    data, err = _gql(q, {"q": f"created_at:>={today}"})
    if err:
        return {"status": "error", "message": err}
    shop = data.get("shop") or {}
    edges = (data.get("orders") or {}).get("edges", [])
    total, cur = 0.0, shop.get("currencyCode", "")
    for e in edges:
        m = e["node"]["totalPriceSet"]["shopMoney"]
        total += float(m["amount"])
        cur = m["currencyCode"]
    return {"status": "connected", "shop": shop.get("name", ""), "currency": cur,
            "orders_today": len(edges), "sales_today": round(total, 2)}


def search_products(query="", limit=10):
    limit = min(int(limit or 10), 25)
    q = """query($q:String!,$n:Int!){
      products(first:$n, query:$q){
        edges{ node{ title status totalInventory
          priceRangeV2{ minVariantPrice{ amount currencyCode } } } } } }"""
    data, err = _gql(q, {"q": query or "", "n": limit})
    if err:
        return err
    edges = data["products"]["edges"]
    if not edges:
        return f"No products match '{query}'."
    lines = []
    for e in edges:
        n = e["node"]
        p = n["priceRangeV2"]["minVariantPrice"]
        lines.append(f"{n['title']}: {p['amount']} {p['currencyCode']}, "
                     f"stock {n.get('totalInventory')}, {n['status']}")
    return "; ".join(lines)


def query_graphql(query=""):
    low = (query or "").strip().lower()
    if not low:
        return "No query provided."
    if low.startswith("mutation") or low.replace(" ", "").startswith("mutation"):
        return "This Shopify access is read-only, so I can't make changes."
    data, err = _gql(query)
    if err:
        return err
    return json.dumps(data)[:2000]


TOOLS = [
    {"name": "shopify_shop_info",
     "description": "Get basic info about the user's Shopify store (name, domain, currency, plan).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "shopify_recent_orders",
     "description": "List recent Shopify orders and total sales over the last N days. Use for "
                    "questions about orders, revenue, or sales in a recent period.",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer", "description": "How many days back (default 7)."},
         "limit": {"type": "integer", "description": "Max orders to list (default 25)."}}}},
    {"name": "shopify_search_products",
     "description": "Search the store's products by title/keyword; returns price, stock, and "
                    "status. Use for questions about a product, its price, or stock level.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Product title or keyword."},
         "limit": {"type": "integer", "description": "Max products (default 10)."}},
         "required": ["query"]}},
    {"name": "shopify_graphql",
     "description": "Run a READ-ONLY Shopify Admin GraphQL query for things the other tools don't "
                    "cover (customers, analytics, specific fields). Mutations are blocked.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "A Shopify Admin API GraphQL query string."}},
         "required": ["query"]}},
]

_DISPATCH = {
    "shopify_shop_info": lambda i: shop_info(),
    "shopify_recent_orders": lambda i: recent_orders(i.get("days", 7), i.get("limit", 25)),
    "shopify_search_products": lambda i: search_products(i.get("query", ""), i.get("limit", 10)),
    "shopify_graphql": lambda i: query_graphql(i.get("query", "")),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown Shopify tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Shopify tool '{name}' failed: {e}"
