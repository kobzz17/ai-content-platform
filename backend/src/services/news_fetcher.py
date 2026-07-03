"""RSS / YouTube feed fetcher with in-memory cache (no API key required)."""
import asyncio
import logging
import random
import time
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# ── Feed list ─────────────────────────────────────────────────────────────────
# YouTube channel RSS (no key needed):
#   https://www.youtube.com/feeds/videos.xml?channel_id=<CHANNEL_ID>
# To find a channel_id: open youtube.com/@ChannelName → view page source → search "channelId"

RSS_FEEDS: list[tuple[str, str]] = [
    ("Lenta.ru", "https://lenta.ru/rss/"),
    ("RIA Новости", "https://ria.ru/export/rss2/archive/index.xml"),
    ("РБК", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("ТАСС", "https://tass.ru/rss/v2.xml"),
    # Add YouTube channels below, for example:
    # ("YT: Wylsacom", "https://www.youtube.com/feeds/videos.xml?channel_id=UCX3_h_Xn8RhFjmTLY3WLKEA"),
    # ("YT: Vert Dider", "https://www.youtube.com/feeds/videos.xml?channel_id=UCF4-M9H4jY1Y1Z5m_KYJGBA"),
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
    """Return a random cached item {title, url, source}, refreshing if stale."""
    await refresh()
    return random.choice(_cache) if _cache else None
