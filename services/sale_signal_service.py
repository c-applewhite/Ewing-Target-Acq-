"""Sale Signal service.

A *factual web-search signal* that checks whether a company appears to be
publicly listed for sale. This is deliberately NOT a score, NOT AI, and NOT a
market rating -- it never feeds the acquisition scoring/ranking pipeline. It
performs a SMALL number of official Brave Web Search requests per company
(one general query, plus one targeted marketplace query only when needed) and
returns a conservative status based on the *evidence found* combined with a
deterministic *identity match* against the business we searched for.

Statuses (user-facing)
-----------------------
``Confirmed For Sale``  Clear sale evidence (a marketplace listing / an
                        unambiguous "for sale" listing) that STRONGLY matches
                        the business searched.
``Possible Signal``     Sale evidence with a plausible-but-not-certain match to
                        the business.
``Needs Review``        Ambiguous or conflicting evidence/identity -- a human
                        should look.
``No Signal``           The search ran successfully but found no credible
                        MATCHING sale evidence. This is NOT proof the business
                        is not for sale -- only that nothing credible surfaced.

Internal state
--------------
``Not Checked``         Default / never checked / ANY API failure / missing
                        key. On any failure (timeout, non-200, exception, bad
                        JSON, missing key) the status stays ``Not Checked`` --
                        it is NEVER downgraded to ``No Signal``. ``No Signal``
                        is reserved for a *successful* search that simply found
                        nothing credible.

``Confirmed For Sale`` is also the value an analyst assigns manually (via the
verify endpoint in app.py); this service only produces it automatically when a
strong marketplace match justifies it.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests

# Official Brave Web Search endpoint (NOT the Abacus routellm proxy).
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

# Sensible per-request timeout (seconds).
BRAVE_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Status constants (single source of truth).
# ---------------------------------------------------------------------------
STATUS_NOT_CHECKED = "Not Checked"      # internal / never-checked / any error
STATUS_CONFIRMED = "Confirmed For Sale"  # strong marketplace match (or analyst)
STATUS_POSSIBLE = "Possible Signal"     # sale evidence, plausible match
STATUS_NEEDS_REVIEW = "Needs Review"    # ambiguous / conflicting
STATUS_NO_SIGNAL = "No Signal"          # searched OK, nothing credible matched

# Ranking used to pick the "best" signal across candidate results / queries.
_STATUS_RANK = {
    STATUS_CONFIRMED: 3,
    STATUS_POSSIBLE: 2,
    STATUS_NEEDS_REVIEW: 1,
    STATUS_NO_SIGNAL: 0,
    STATUS_NOT_CHECKED: 0,
}

# ---------------------------------------------------------------------------
# Centralized marketplace / broker domain list -- the SINGLE source of truth
# for "this result is a genuine business-for-sale listing".
# ---------------------------------------------------------------------------
SALE_MARKETPLACE_DOMAINS = [
    "bizbuysell.com",
    "bizquest.com",
    "businessesforsale.com",
    "dealstream.com",
    "sunbeltnetwork.com",
    "transworldma.com",
]

# For-sale / listing context tokens: the second (weaker) form of sale evidence
# used when a result is NOT on a known marketplace domain.
FOR_SALE_TOKENS = (
    "for sale",
    "business for sale",
    "asking price",
    "owner retiring",
    "owner financing",
    "established business for sale",
    "acquisition opportunity",
    "now for sale",
    "listing price",
)

# Very common tokens that must not, on their own, count toward a name match.
_STOPWORDS = {
    "the", "and", "of", "for", "llc", "inc", "co", "company", "corp", "ltd",
    "&", "supply", "supplies", "services", "service", "group", "the",
}


def _brave_api_key() -> str:
    """Return the configured Brave key (loaded from the environment/.env)."""
    return os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------

def build_query(company_name: str, city: str = "", state: str = "") -> str:
    """Build the GENERAL Brave query: quoted name + city + state + "for sale".

    e.g. ``"Acme Pool Supply" "Chandler" "AZ" for sale``.
    """
    name = (company_name or "").strip()
    parts = []
    if name:
        parts.append(f'"{name}"')
    if city and city.strip():
        parts.append(f'"{city.strip()}"')
    if state and state.strip():
        parts.append(f'"{state.strip()}"')
    parts.append("for sale")
    return " ".join(parts).strip()


def build_marketplace_query(company_name: str) -> str:
    """Build ONE targeted marketplace query using Brave's index.

    Combines all marketplace domains into a single ``site:`` OR filter so we
    intentionally check indexed for-sale marketplaces with just ONE extra
    request (no scraping, no per-domain fan-out). e.g.::

        "Acme Pool Supply" (site:bizbuysell.com OR site:bizquest.com OR ...)
    """
    name = (company_name or "").strip()
    sites = " OR ".join(f"site:{d}" for d in SALE_MARKETPLACE_DOMAINS)
    quoted = f'"{name}"' if name else ""
    return f"{quoted} ({sites})".strip()


# ---------------------------------------------------------------------------
# Tokenization / domain helpers
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    """Return meaningful lowercased alphanumeric tokens from arbitrary text."""
    raw = "".join(
        ch.lower() if (ch.isalnum() or ch.isspace()) else " "
        for ch in (text or "")
    )
    return {
        token
        for token in raw.split()
        if len(token) > 2 and token not in _STOPWORDS
    }


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _domain_of(url: str) -> str:
    """Return the bare registrable-ish host for a URL, lowercased."""
    try:
        host = urlparse(url if "://" in url else f"http://{url}").netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _is_marketplace_domain(domain: str) -> bool:
    return any(
        domain == mkt or domain.endswith("." + mkt)
        for mkt in SALE_MARKETPLACE_DOMAINS
    )


# ---------------------------------------------------------------------------
# Deterministic identity matching (centralized, single helper)
#
# Answers ONE question: "does this search result likely refer to the business
# we searched for?" -- by comparing result text (title + url + description)
# against the available business data (name, city, state, website, phone,
# address). It is deliberately NOT a general company-matching system.
# ---------------------------------------------------------------------------

# Identity outcomes.
MATCH_STRONG = "strong"
MATCH_POSSIBLE = "possible"
MATCH_WEAK = "weak"          # weak-or-conflicting
MATCH_UNRELATED = "unrelated"


def match_identity(result: dict, company: dict) -> str:
    """Classify how well ``result`` matches ``company``.

    Fields compared (whatever is available on the company):
      * business name  -> token coverage in title/url/description
      * city / state   -> presence in the result text
      * website domain -> result domain equal to the company's own domain
                          (own-site result = conflicting sale evidence)
      * phone          -> normalized digits present in the result text
      * address        -> address tokens present in the result text

    Returns one of ``strong`` / ``possible`` / ``weak`` / ``unrelated``.
    """
    title = str(result.get("title") or "")
    url = str(result.get("url") or "")
    description = str(result.get("description") or "")
    haystack = f"{title} {description} {url}".lower()
    digit_haystack = _digits(haystack)

    name_tokens = _tokens(company.get("name", ""))
    if not name_tokens:
        return MATCH_UNRELATED

    matched = {t for t in name_tokens if t in haystack}
    coverage = len(matched) / len(name_tokens)

    # No name overlap at all -> the result is about some other business.
    if coverage == 0:
        return MATCH_UNRELATED

    # Corroborating identity signals (geo / phone / address / website).
    geo_hits = 0
    city = str(company.get("city") or "").strip().lower()
    state = str(company.get("state") or "").strip().lower()
    if city and city in haystack:
        geo_hits += 1
    if state and re.search(rf"\b{re.escape(state)}\b", haystack):
        geo_hits += 1

    phone_digits = _digits(company.get("phone", ""))
    if len(phone_digits) >= 7 and phone_digits[-7:] in digit_haystack:
        geo_hits += 1

    addr_tokens = _tokens(company.get("address", ""))
    # Street-number-ish / street-name tokens shared with the result.
    if addr_tokens and len(addr_tokens & _tokens(haystack)) >= 2:
        geo_hits += 1

    # Conflicting signal: the result is the company's OWN website (their home
    # page), not a third-party sale listing -> not sale evidence about a sale.
    own_domain = _domain_of(company.get("website", ""))
    result_domain = _domain_of(url)
    is_own_site = bool(own_domain) and (
        result_domain == own_domain or result_domain.endswith("." + own_domain)
    )
    if is_own_site:
        # Own homepage surfacing under a "for sale" query is conflicting/weak
        # evidence at best -- never a strong match.
        return MATCH_WEAK

    # Strong: the full business name is represented AND at least one
    # corroborating identity field agrees.
    strong_name = coverage >= 0.75
    if strong_name and geo_hits >= 1:
        return MATCH_STRONG
    if strong_name and geo_hits == 0:
        return MATCH_POSSIBLE
    # Partial name overlap.
    if geo_hits >= 1:
        return MATCH_POSSIBLE
    return MATCH_WEAK


# ---------------------------------------------------------------------------
# Evidence + identity -> sale signal assignment
# ---------------------------------------------------------------------------

def _sale_evidence(result: dict) -> str:
    """Return the sale-evidence level for a result: marketplace/listing/none."""
    url = str(result.get("url") or "")
    domain = _domain_of(url)
    if _is_marketplace_domain(domain):
        return "marketplace"
    haystack = (
        f"{result.get('title') or ''} {result.get('description') or ''}"
    ).lower()
    if any(token in haystack for token in FOR_SALE_TOKENS):
        return "listing"
    return "none"


def _classify_result(result: dict, company: dict) -> str:
    """Combine sale evidence + identity match into a status for one result."""
    identity = match_identity(result, company)
    if identity == MATCH_UNRELATED:
        return STATUS_NO_SIGNAL  # ignore -- unrelated results yield no signal

    evidence = _sale_evidence(result)
    if evidence == "none":
        return STATUS_NO_SIGNAL  # not a sale result at all

    if evidence == "marketplace":
        # Clear sale evidence on a genuine marketplace domain.
        if identity == MATCH_STRONG:
            return STATUS_CONFIRMED
        if identity == MATCH_POSSIBLE:
            return STATUS_POSSIBLE
        return STATUS_NEEDS_REVIEW  # weak / conflicting -> human check

    # evidence == "listing" (for-sale context, but not a marketplace domain).
    if identity == MATCH_STRONG:
        return STATUS_POSSIBLE
    if identity == MATCH_POSSIBLE:
        return STATUS_NEEDS_REVIEW
    return STATUS_NEEDS_REVIEW


def _evaluate_results(results: list, company: dict) -> dict:
    """Return the best sale signal across all candidate results.

    Result dict always has ``status``; on a signal it also carries
    ``sale_source`` / ``sale_result_title`` / ``sale_result_url``.
    """
    best = {"status": STATUS_NO_SIGNAL}
    best_rank = 0

    for item in results:
        if not isinstance(item, dict):
            continue
        status = _classify_result(item, company)
        rank = _STATUS_RANK.get(status, 0)
        if rank > best_rank:
            best_rank = rank
            best = {
                "status": status,
                "sale_source": _domain_of(str(item.get("url") or "")) or None,
                "sale_result_title": str(item.get("title") or "").strip()
                or None,
                "sale_result_url": str(item.get("url") or "").strip() or None,
            }
        if best_rank == _STATUS_RANK[STATUS_CONFIRMED]:
            break  # cannot do better than Confirmed -- stop scanning results

    return best


# ---------------------------------------------------------------------------
# Brave request (single request, reused for both queries)
# ---------------------------------------------------------------------------

def _run_query(api_key: str, query: str) -> tuple[bool, list]:
    """Run one Brave web search. Returns ``(ok, results)``.

    ``ok`` is ``True`` only for a successful 200 with parseable JSON. On any
    failure (timeout, non-200, bad JSON, exception) returns ``(False, [])`` so
    the caller can keep the row ``Not Checked`` rather than asserting anything.
    """
    try:
        response = requests.get(
            BRAVE_ENDPOINT,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            params={"q": query, "count": 10},
            timeout=BRAVE_TIMEOUT,
        )
    except Exception:
        return False, []

    if response.status_code != 200:
        return False, []

    try:
        payload = response.json()
    except Exception:
        return False, []

    web = payload.get("web") if isinstance(payload, dict) else None
    results = (web or {}).get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        results = []
    return True, results


def check_sale_signal(company: dict) -> dict:
    """Check whether ``company`` appears publicly listed for sale.

    ``company`` is a plain dict with at least ``name`` and optional ``city``,
    ``state``, ``website``, ``phone``, ``address`` (used for identity
    matching). Returns a dict always containing ``sale_signal`` and, on a
    signal, ``sale_source`` / ``sale_result_title`` / ``sale_result_url``.

    Query strategy (minimal): run ONE general query first. If it already yields
    a strong marketplace match (``Confirmed For Sale``) we stop -- one request.
    Otherwise run ONE targeted marketplace query (all marketplaces combined in
    a single ``site:`` OR filter) and keep the best signal across both. So at
    most TWO Brave requests per company, never per-domain fan-out.

    On ANY failure of the primary query (missing key, timeout, non-200, bad
    JSON) the returned ``sale_signal`` is ``Not Checked`` -- never
    ``No Signal``.
    """
    name = str(company.get("name") or "").strip()
    result: dict = {"sale_signal": STATUS_NOT_CHECKED}

    if not name:
        return result  # nothing to search on

    api_key = _brave_api_key()
    if not api_key:
        return result  # missing key -> stays Not Checked

    city = str(company.get("city") or "").strip()
    state = str(company.get("state") or "").strip()

    # --- Query 1: general -------------------------------------------------
    ok1, results1 = _run_query(api_key, build_query(name, city, state))
    if not ok1:
        # Primary search failed -> we cannot assert anything: stay Not Checked.
        return result

    best = _evaluate_results(results1, company)
    best_rank = _STATUS_RANK.get(best.get("status"), 0)

    # Stop early if the general query already confirmed via a marketplace.
    if best_rank < _STATUS_RANK[STATUS_CONFIRMED]:
        # --- Query 2: targeted marketplaces (best-effort) -----------------
        ok2, results2 = _run_query(api_key, build_marketplace_query(name))
        if ok2:
            best2 = _evaluate_results(results2, company)
            if _STATUS_RANK.get(best2.get("status"), 0) > best_rank:
                best = best2
                best_rank = _STATUS_RANK.get(best.get("status"), 0)

    result["sale_signal"] = best.get("status", STATUS_NO_SIGNAL)
    for field in ("sale_source", "sale_result_title", "sale_result_url"):
        if best.get(field):
            result[field] = best[field]
    return result
