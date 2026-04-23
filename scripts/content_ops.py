from __future__ import annotations

import html
import json
import os
import re
import unicodedata
from html.parser import HTMLParser
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
DEFAULT_SECURITY = {
    "public_web_only": True,
    "require_https": True,
    "allowed_domains": [],
    "max_excerpt_chars": 2500,
    "max_summary_chars": 700,
    "redact_patterns": True,
    "store_only_sanitized_urls": True,
}
DEFAULT_COMMERCIAL_TERMS = [
    "automatizacion",
    "inteligencia artificial",
    "integracion",
    "agentes",
    "enterprise",
    "business",
    "empresa",
    "empresas",
    "operaciones",
    "operacion",
    "workflow",
    "process",
    "proceso",
    "procesos",
    "crm",
    "erp",
    "ventas",
    "sales",
    "clientes",
    "customer",
    "servicio",
    "support",
    "revenue",
    "productividad",
    "back office",
    "gobernanza",
    "adopcion",
]
DEFAULT_EXCLUSION_TERMS = [
    "quantum",
    "qubit",
    "qutrit",
    "genomics",
    "protein folding",
    "drug discovery",
    "astrophysics",
    "astronomy",
    "materials science",
]
STOPWORDS = {
    "about",
    "across",
    "after",
    "antes",
    "around",
    "areas",
    "como",
    "con",
    "contra",
    "donde",
    "entre",
    "from",
    "hacia",
    "hasta",
    "para",
    "porque",
    "sobre",
    "that",
    "their",
    "these",
    "those",
    "through",
    "want",
    "with",
    "your",
    "automatizacion",
    "integracion",
    "empresa",
    "empresas",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_security() -> dict[str, Any]:
    config = load_json(CONFIG_DIR / "security.json", DEFAULT_SECURITY.copy())
    merged = DEFAULT_SECURITY.copy()
    merged.update(config)
    return merged


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "post"


def strip_html(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return clean_text(html.unescape(value))


def clean_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    folded = "".join(char for char in normalized if not unicodedata.combining(char))
    return folded.lower()


def unique_phrases(values: list[str]) -> list[str]:
    seen: set[str] = set()
    phrases: list[str] = []
    for value in values:
        phrase = clean_text(value)
        if not phrase:
            continue
        key = fold_text(phrase)
        if key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
    return phrases


def build_commercial_rules(brand: dict[str, Any] | None) -> dict[str, list[str]]:
    brand = brand or {}
    editorial_filters = brand.get("editorial_filters", {})
    raw_include: list[str] = []
    raw_include.extend(DEFAULT_COMMERCIAL_TERMS)
    raw_include.extend(brand.get("services", []))
    raw_include.extend(brand.get("audience", []))
    raw_include.extend(brand.get("editorial_goals", []))
    raw_include.extend(editorial_filters.get("include_any", []))
    if brand.get("positioning_statement"):
        raw_include.append(brand["positioning_statement"])
    if brand.get("contrarian_thesis"):
        raw_include.append(brand["contrarian_thesis"])

    include_phrases = unique_phrases(raw_include)
    include_tokens: set[str] = set()
    for phrase in include_phrases:
        for token in re.findall(r"[a-z0-9]{4,}", fold_text(phrase)):
            if token not in STOPWORDS:
                include_tokens.add(token)

    exclude_phrases = unique_phrases(DEFAULT_EXCLUSION_TERMS + editorial_filters.get("exclude_any", []))
    return {
        "include_phrases": include_phrases,
        "include_tokens": sorted(include_tokens),
        "exclude_phrases": exclude_phrases,
    }


def commercial_relevance_score(candidate: dict[str, Any], rules: dict[str, list[str]] | None) -> int:
    if not rules:
        return 0

    haystack = " ".join(
        [
            candidate.get("title", ""),
            candidate.get("summary", ""),
            candidate.get("page_excerpt", ""),
            candidate.get("source_name", ""),
        ]
    )
    folded_haystack = fold_text(haystack)
    words = set(re.findall(r"[a-z0-9]{4,}", folded_haystack))
    score = 0

    for phrase in rules.get("include_phrases", []):
        folded_phrase = fold_text(phrase)
        if not folded_phrase:
            continue
        if " " in folded_phrase:
            if folded_phrase in folded_haystack:
                score += 4
        elif folded_phrase in words:
            score += 2

    for token in rules.get("include_tokens", []):
        if token in words:
            score += 1

    for phrase in rules.get("exclude_phrases", []):
        folded_phrase = fold_text(phrase)
        if not folded_phrase:
            continue
        if " " in folded_phrase:
            if folded_phrase in folded_haystack:
                score -= 6
        elif folded_phrase in words:
            score -= 4

    if candidate.get("source_type") == "research" and score < 4:
        score -= 2

    return score


def redact_sensitive_text(value: str, enabled: bool = True) -> str:
    if not enabled or not value:
        return value
    redacted = value
    patterns = [
        (r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[redacted-email]"),
        (r"(?<!\w)(?:\+?\d[\d\-\s().]{7,}\d)(?!\w)", "[redacted-phone]"),
        (r"\bsk-[A-Za-z0-9_\-]{12,}\b", "[redacted-token]"),
        (r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", "[redacted-token]"),
        (r"\bAIza[0-9A-Za-z\-_]{20,}\b", "[redacted-token]"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)
    return clean_text(redacted)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def sanitize_url(url: str, security: dict[str, Any]) -> str | None:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url.strip())
    if security.get("require_https", True) and parsed.scheme != "https":
        return None
    domain = parsed.netloc.lower()
    if not domain:
        return None
    if security.get("public_web_only", True):
        allowed_domains = security.get("allowed_domains", [])
        if allowed_domains and not any(domain == item or domain.endswith(f".{item}") for item in allowed_domains):
            return None
    if security.get("store_only_sanitized_urls", True):
        parsed = parsed._replace(query="", fragment="")
    return urllib.parse.urlunparse(parsed)


def http_get_text(url: str, timeout: int = 30, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(
        url,
        headers=headers
        or {
            "User-Agent": "content-agents/1.0 (+https://github.com/edreirbs/conten-agents)"
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_feed_entries(feed_url: str) -> list[dict[str, Any]]:
    try:
        raw = http_get_text(feed_url)
    except (urllib.error.URLError, TimeoutError):
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    channel_items = root.findall(".//channel/item")
    atom_entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    entries = channel_items if channel_items else atom_entries
    parsed_entries: list[dict[str, Any]] = []

    for item in entries:
        title = _node_text(item, "title") or _node_text(item, "{http://www.w3.org/2005/Atom}title")
        link = _node_text(item, "link")

        if not link:
            link_node = item.find("{http://www.w3.org/2005/Atom}link")
            if link_node is not None:
                link = link_node.attrib.get("href")

        summary = (
            _node_text(item, "description")
            or _node_text(item, "summary")
            or _node_text(item, "{http://www.w3.org/2005/Atom}summary")
            or _node_text(item, "{http://www.w3.org/2005/Atom}content")
        )
        published_raw = (
            _node_text(item, "pubDate")
            or _node_text(item, "published")
            or _node_text(item, "updated")
            or _node_text(item, "{http://www.w3.org/2005/Atom}published")
            or _node_text(item, "{http://www.w3.org/2005/Atom}updated")
        )

        if not title or not link:
            continue

        parsed_entries.append(
            {
                "title": clean_text(title),
                "link": link.strip(),
                "summary": strip_html(summary or ""),
                "published_at": parse_date(published_raw).isoformat() if parse_date(published_raw) else None,
            }
        )

    return parsed_entries


def _node_text(node: ET.Element, tag: str) -> str | None:
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    return child.text


def fetch_page_excerpt(url: str, max_chars: int = 6000, security: dict[str, Any] | None = None) -> str:
    try:
        raw = http_get_text(url)
    except (urllib.error.URLError, TimeoutError):
        return ""

    text = strip_html(raw)
    if security:
        text = redact_sensitive_text(text, enabled=security.get("redact_patterns", True))
    return text[:max_chars]


def role_priority(role_id: str, candidate: dict[str, Any]) -> tuple[int, int]:
    source_type = candidate.get("source_type", "")
    text = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()

    if role_id == "hot_news":
        type_score = {"x_signal": 0, "vendor": 1, "research": 2, "education": 3}.get(source_type, 4)
        keyword_bonus = 0 if any(word in text for word in ["launch", "release", "announces", "introduces", "news"]) else 1
        return (type_score, keyword_bonus)

    if role_id == "good_practice":
        keyword_bonus = 0 if any(
            word in text for word in ["best practice", "guide", "how to", "checklist", "tips", "framework"]
        ) else 1
        type_score = {"education": 0, "research": 1, "vendor": 2, "x_signal": 3}.get(source_type, 4)
        return (keyword_bonus, type_score)

    if role_id == "tool_deep_dive":
        keyword_bonus = 0 if any(
            word in text for word in ["tool", "platform", "framework", "api", "sdk", "agent", "stack"]
        ) else 1
        type_score = {"vendor": 0, "research": 1, "education": 2, "x_signal": 3}.get(source_type, 4)
        return (keyword_bonus, type_score)

    if role_id == "reflective":
        keyword_bonus = 0 if any(
            word in text for word in ["risk", "governance", "lesson", "strategy", "tradeoff", "adoption", "future"]
        ) else 1
        type_score = {"research": 0, "education": 1, "vendor": 2, "x_signal": 3}.get(source_type, 4)
        return (keyword_bonus, type_score)

    return (9, 9)


def choose_candidates(
    sources: dict[str, Any],
    state: dict[str, Any],
    max_candidates: int,
    security: dict[str, Any],
    role_id: str = "hot_news",
    brand: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    seen_urls = set(state.get("seen_source_urls", []))
    lookback_days = int(sources.get("lookback_days", 7))
    threshold = utc_now() - timedelta(days=lookback_days)
    candidates: list[dict[str, Any]] = []
    commercial_rules = build_commercial_rules(brand)

    for source in sources.get("feeds", []):
        safe_feed_url = sanitize_url(source["url"], security)
        if not safe_feed_url:
            continue
        entries = extract_feed_entries(safe_feed_url)
        for entry in entries:
            safe_link = sanitize_url(entry["link"], security)
            if not safe_link:
                continue
            if safe_link in seen_urls:
                continue
            published_at = parse_date(entry.get("published_at"))
            if published_at and published_at < threshold:
                continue
            candidates.append(
                {
                    "source_name": source["name"],
                    "source_type": source["type"],
                    "title": redact_sensitive_text(entry["title"], enabled=security.get("redact_patterns", True)),
                    "link": safe_link,
                    "summary": redact_sensitive_text(
                        entry.get("summary", "")[: int(security.get("max_summary_chars", 700))],
                        enabled=security.get("redact_patterns", True),
                    ),
                    "published_at": entry.get("published_at"),
                    "commercial_score": 0,
                }
            )

    for candidate in candidates:
        candidate["commercial_score"] = commercial_relevance_score(candidate, commercial_rules)

    candidates.sort(
        key=lambda item: (
            -item.get("commercial_score", 0),
            role_priority(role_id, item),
            -(parse_date(item.get("published_at")).timestamp() if parse_date(item.get("published_at")) else 0),
        )
    )

    positive_fit = [item for item in candidates if item.get("commercial_score", 0) > 0]
    limited = (positive_fit or candidates)[:max_candidates]
    for item in limited:
        item["page_excerpt"] = fetch_page_excerpt(
            item["link"],
            max_chars=int(security.get("max_excerpt_chars", 2500)),
            security=security,
        )
    return limited


def fetch_x_signals(queries: list[str], security: dict[str, Any], max_items: int = 6) -> list[dict[str, Any]]:
    bearer_token = os.getenv("X_BEARER_TOKEN")
    if not bearer_token or not queries:
        return []

    collected: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    for query in queries[:3]:
        response = requests.get(
            "https://api.x.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {bearer_token}"},
            params={
                "query": query,
                "max_results": 10,
                "tweet.fields": "created_at,entities,author_id",
                "expansions": "author_id",
                "user.fields": "username,name",
            },
            timeout=45,
        )
        if not response.ok:
            continue

        payload = response.json()
        users = {user["id"]: user for user in payload.get("includes", {}).get("users", [])}
        for post in payload.get("data", []):
            entities = post.get("entities", {})
            urls = entities.get("urls", [])
            expanded_url = ""
            if urls:
                expanded_url = urls[0].get("expanded_url") or urls[0].get("unwound_url") or urls[0].get("url") or ""
            safe_link = sanitize_url(expanded_url, security)
            if not safe_link or safe_link in seen_links:
                continue

            user = users.get(post.get("author_id", ""), {})
            username = user.get("username", "signal")
            collected.append(
                {
                    "source_name": f"X / @{username}",
                    "source_type": "x_signal",
                    "title": redact_sensitive_text(post.get("text", ""), enabled=security.get("redact_patterns", True))[:180],
                    "summary": redact_sensitive_text(post.get("text", ""), enabled=security.get("redact_patterns", True))[:700],
                    "link": safe_link,
                    "published_at": post.get("created_at"),
                }
            )
            seen_links.add(safe_link)
            if len(collected) >= max_items:
                return collected
    return collected


def select_contextual_image(
    query: str,
    orientation: str = "landscape",
) -> dict[str, Any] | None:
    pexels = search_pexels_image(query, orientation=orientation)
    if pexels:
        return pexels
    unsplash = search_unsplash_image(query, orientation=orientation)
    if unsplash:
        return unsplash
    return None


def search_pexels_image(query: str, orientation: str = "landscape") -> dict[str, Any] | None:
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        return None
    response = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 1, "orientation": orientation},
        timeout=45,
    )
    if not response.ok:
        return None
    photos = response.json().get("photos", [])
    if not photos:
        return None
    photo = photos[0]
    return {
        "provider": "pexels",
        "url": photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large"),
        "alt": photo.get("alt") or query,
        "photographer": photo.get("photographer"),
        "photographer_url": photo.get("photographer_url"),
        "source_url": photo.get("url"),
        "attribution_label": "Foto vía Pexels",
    }


def search_unsplash_image(query: str, orientation: str = "landscape") -> dict[str, Any] | None:
    access_key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not access_key:
        return None
    response = requests.get(
        "https://api.unsplash.com/search/photos",
        headers={"Authorization": f"Client-ID {access_key}"},
        params={
            "query": query,
            "per_page": 1,
            "orientation": orientation,
            "content_filter": "high",
        },
        timeout=45,
    )
    if not response.ok:
        return None
    results = response.json().get("results", [])
    if not results:
        return None
    photo = results[0]
    download_location = photo.get("links", {}).get("download_location")
    if download_location:
        requests.get(
            download_location,
            headers={"Authorization": f"Client-ID {access_key}"},
            timeout=30,
        )
    user = photo.get("user", {})
    profile_url = user.get("links", {}).get("html", "")
    source_url = photo.get("links", {}).get("html", "")
    utm = "utm_source=conten_agents&utm_medium=referral"
    if profile_url:
        profile_url = f"{profile_url}?{utm}"
    if source_url:
        source_url = f"{source_url}?{utm}"
    return {
        "provider": "unsplash",
        "url": photo.get("urls", {}).get("regular"),
        "alt": photo.get("alt_description") or query,
        "photographer": user.get("name"),
        "photographer_url": profile_url,
        "source_url": source_url,
        "attribution_label": "Foto vía Unsplash",
    }


def extract_response_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return payload["output_text"]

    parts: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def openai_json_response(
    *,
    api_key: str,
    model: str,
    instructions: str,
    input_payload: str,
    effort: str = "low",
) -> dict[str, Any]:
    candidate_models = [model, "gpt-5-mini", "gpt-4.1-mini"]
    seen_models: set[str] = set()
    last_error: str | None = None

    for candidate_model in candidate_models:
        if not candidate_model or candidate_model in seen_models:
            continue
        seen_models.add(candidate_model)

        request_payload = {
            "model": candidate_model,
            "store": False,
            "instructions": instructions,
            "input": input_payload,
        }
        if candidate_model.startswith("gpt-5"):
            request_payload["reasoning"] = {"effort": effort}

        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=120,
        )

        if response.ok:
            payload = response.json()
            output_text = extract_response_text(payload)
            try:
                return json.loads(output_text)
            except json.JSONDecodeError as exc:
                snippet = output_text[:600].replace("\n", " ")
                raise RuntimeError(
                    f"OpenAI devolvio texto que no es JSON valido con el modelo {candidate_model}: {snippet}"
                ) from exc

        body_snippet = response.text[:700].replace("\n", " ")
        last_error = f"{response.status_code} con modelo {candidate_model}: {body_snippet}"

        if response.status_code not in {400, 404, 429}:
            break

    raise RuntimeError(f"Error llamando a OpenAI Responses API: {last_error}")


def refresh_linkedin_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    redirect_uri: str,
) -> dict[str, Any] | None:
    response = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=60,
    )
    if not response.ok:
        return None
    return response.json()


def post_to_linkedin(
    *,
    access_token: str,
    organization_urn: str,
    commentary: str,
    linkedin_version: str,
) -> dict[str, Any]:
    response = requests.post(
        "https://api.linkedin.com/rest/posts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": linkedin_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        },
        json={
            "author": organization_urn,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        },
        timeout=90,
    )
    if not response.ok:
        snippet = response.text[:500].replace("\n", " ")
        raise RuntimeError(f"LinkedIn devolvio {response.status_code}: {snippet}")
    location = response.headers.get("x-restli-id") or response.headers.get("location")
    return {"status_code": response.status_code, "post_reference": location}


def sanitize_article_html(value: str) -> str:
    scrubbed = re.sub(r"<(script|style|iframe|object|embed)[\s\S]*?</\1>", "", value, flags=re.IGNORECASE)
    parser = SafeHTMLParser()
    parser.feed(scrubbed)
    parser.close()
    return parser.render()


class SafeHTMLParser(HTMLParser):
    allowed_tags = {"p", "h2", "h3", "ul", "ol", "li", "strong", "em", "a", "blockquote", "code"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.allowed_tags:
            return
        safe_attrs: list[str] = []
        if tag == "a":
            href = ""
            for key, value in attrs:
                if key == "href" and value:
                    href = value.strip()
            if href.startswith("https://"):
                safe_attrs.extend(
                    [
                        f'href="{html.escape(href, quote=True)}"',
                        'target="_blank"',
                        'rel="noopener noreferrer"',
                    ]
                )
        if safe_attrs:
            self.parts.append(f"<{tag} {' '.join(safe_attrs)}>")
        else:
            self.parts.append(f"<{tag}>")
        self.tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.allowed_tags:
            self.parts.append(f"</{tag}>")
            if self.tag_stack and self.tag_stack[-1] == tag:
                self.tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if data and self.tag_stack:
            self.parts.append(html.escape(data))

    def render(self) -> str:
        return "".join(self.parts)
