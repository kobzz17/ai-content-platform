"""RSS news + YouTube search (via Invidious public API, no key required)."""
import asyncio
import logging
import random
import time
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# ── RSS feeds ─────────────────────────────────────────────────────────────────
RSS_FEEDS: list[tuple[str, str]] = [
    ("Lenta.ru", "https://lenta.ru/rss/"),
    ("RIA Новости", "https://ria.ru/export/rss2/archive/index.xml"),
    ("РБК", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("ТАСС", "https://tass.ru/rss/v2.xml"),
]

# ── Invidious instances for YouTube search (no API key needed) ────────────────
# Bots dynamically search by their persona topics — no fixed channel list required.
_INVIDIOUS = [
    "https://inv.nadeko.net",
    "https://invidious.privacydev.net",
    "https://yt.drgnz.club",
    "https://invidious.nerdvpn.de",
    "https://invidious.fdn.fr",
]

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache: list[dict] = []
_last_refresh: float = 0.0
_REFRESH_INTERVAL = 3600  # 1 hour
_lock = asyncio.Lock()


async def _fetch_one(source: str, url: str, client: httpx.AsyncClient) -> list[dict]:
    items: list[dict] = []
    try:
        r = await client.get(url, timeout=12)
        r.raise_for_status()
        root = ET.fromstring(r.text)

        # RSS 2.0
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title and link and len(title) > 8:
                items.append({"title": title, "url": link, "source": source})
                if len(items) >= 8:
                    return items

        # Atom (YouTube RSS uses this format)
        atom = "{http://www.w3.org/2005/Atom}"
        for entry in root.findall(f"{atom}entry"):
            title_el = entry.find(f"{atom}title")
            link_el = entry.find(f"{atom}link")
            title = (title_el.text or "").strip() if title_el is not None else ""
            link = link_el.get("href", "").strip() if link_el is not None else ""
            if title and link:
                items.append({"title": title, "url": link, "source": source})
                if len(items) >= 8:
                    return items
    except Exception as e:
        logger.debug("RSS %s failed: %s", source, e)
    return items


async def _do_refresh() -> None:
    global _cache, _last_refresh
    try:
        async with httpx.AsyncClient(follow_redirects=True) as cl:
            results = await asyncio.gather(
                *[_fetch_one(src, url, cl) for src, url in RSS_FEEDS],
                return_exceptions=True,
            )
        items = [item for r in results if isinstance(r, list) for item in r]
        if items:
            _cache = items
            _last_refresh = time.time()
            logger.info("RSS refreshed: %d items from %d feeds", len(items), len(RSS_FEEDS))
    except Exception as e:
        logger.warning("RSS refresh failed: %s", e)


async def refresh() -> None:
    """Refresh cache if stale (called lazily before each use)."""
    if time.time() - _last_refresh < _REFRESH_INTERVAL:
        return
    async with _lock:
        if time.time() - _last_refresh < _REFRESH_INTERVAL:
            return
        await _do_refresh()


async def random_item() -> dict | None:
    """Return a random cached news item {title, url, source}, refreshing if stale."""
    await refresh()
    return random.choice(_cache) if _cache else None


async def search_youtube(query: str, limit: int = 8) -> list[dict]:
    """Search YouTube via public Invidious instances. No API key needed.
    Returns list of {title, url, source} or empty list on failure.
    """
    instances = random.sample(_INVIDIOUS, len(_INVIDIOUS))
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as cl:
        for instance in instances[:3]:  # try up to 3 before giving up
            try:
                r = await cl.get(
                    f"{instance}/api/v1/search",
                    params={"q": query, "type": "video", "sort_by": "upload_date"},
                )
                if r.status_code != 200:
                    continue
                results = []
                for item in r.json()[:limit]:
                    vid_id = item.get("videoId", "")
                    title = (item.get("title") or "").strip()
                    channel = item.get("author", "")
                    # Skip very short or clearly auto-generated titles
                    if vid_id and len(title) > 8:
                        results.append({
                            "title": title,
                            "url": f"https://www.youtube.com/watch?v={vid_id}",
                            "source": f"YouTube / {channel}" if channel else "YouTube",
                        })
                if results:
                    logger.debug("YouTube search '%s' → %d results via %s", query, len(results), instance)
                    return results
            except Exception as e:
                logger.debug("Invidious %s failed: %s", instance, e)
    return []
