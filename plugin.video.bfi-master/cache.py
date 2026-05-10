# -*- coding: utf-8 -*-
"""
Lightweight replacement for script.module.cache.
Bundled directly in the addon to avoid the external dependency.

Provides:
  Cache               -- simple file-backed HTTP response cache
  Store               -- persistent list store (searches, recently viewed)
  conditional_headers -- builds If-None-Match / If-Modified-Since headers
"""

import json
import os
import time

import xbmcaddon
import xbmcvfs

_ADDON = xbmcaddon.Addon()
_PROFILE = xbmcvfs.translatePath(_ADDON.getAddonInfo("profile"))
_CACHE_FILE = os.path.join(_PROFILE, "http_cache.json")
_TTL = 3600          # seconds before a cached response is considered stale
_MAX_ENTRIES = 200   # cap to avoid unbounded file growth


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_profile():
    if not xbmcvfs.exists(_PROFILE):
        xbmcvfs.mkdirs(_PROFILE)


def conditional_headers(cached):
    # type: (dict) -> dict
    """Return ETag / Last-Modified headers for a conditional HTTP request."""
    headers = {}
    if isinstance(cached, dict):
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
    return headers


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class Cache:
    """Context-manager HTTP cache backed by a single JSON file.

    Usage::

        with Cache() as c:
            entry = c.get(url)
            if entry and entry["fresh"]:
                return entry["blob"]
            ...
            c.set(url, response_content, response_headers)
    """

    def __init__(self):
        self._data = {}

    def __enter__(self):
        _ensure_profile()
        try:
            if xbmcvfs.exists(_CACHE_FILE):
                fh = xbmcvfs.File(_CACHE_FILE)
                raw = fh.read()
                fh.close()
                self._data = json.loads(raw or "{}")
        except Exception:
            self._data = {}
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            _ensure_profile()
            # Trim oldest entries when over the cap
            if len(self._data) > _MAX_ENTRIES:
                sorted_keys = sorted(
                    self._data, key=lambda k: self._data[k].get("ts", 0)
                )
                for key in sorted_keys[: len(self._data) - _MAX_ENTRIES]:
                    del self._data[key]
            fh = xbmcvfs.File(_CACHE_FILE, "w")
            fh.write(json.dumps(self._data))
            fh.close()
        except Exception:
            pass
        return False  # do not suppress exceptions

    # ------------------------------------------------------------------

    def get(self, url):
        # type: (str) -> dict
        """Return cached entry dict or None.  Entry has key ``fresh`` (bool)."""
        entry = self._data.get(url)
        if not entry:
            return None
        entry = dict(entry)  # shallow copy so callers can mutate freely
        entry["fresh"] = (time.time() - entry.get("ts", 0)) < _TTL
        return entry

    def set(self, url, data, headers):
        # type: (str, object, object) -> None
        """Store *data* for *url*, recording ETag / Last-Modified from *headers*."""
        if isinstance(data, bytes):
            blob = data.decode("utf-8", errors="replace")
        elif isinstance(data, (dict, list)):
            blob = json.dumps(data)
        else:
            blob = str(data)

        etag = ""
        last_modified = ""
        if hasattr(headers, "get"):
            etag = headers.get("ETag") or headers.get("etag") or ""
            last_modified = (headers.get("Last-Modified") or
                             headers.get("last_modified") or "")

        self._data[url] = {
            "blob": blob,
            "ts": time.time(),
            "etag": etag,
            "last_modified": last_modified,
        }

    def touch(self, url, headers):
        # type: (str, object) -> None
        """Refresh timestamp and conditional headers without changing blob."""
        if url in self._data:
            self._data[url]["ts"] = time.time()
            if hasattr(headers, "get"):
                etag = headers.get("ETag") or headers.get("etag")
                last_mod = headers.get("Last-Modified") or headers.get("last_modified")
                if etag:
                    self._data[url]["etag"] = etag
                if last_mod:
                    self._data[url]["last_modified"] = last_mod

    def clear(self):
        # type: () -> None
        self._data = {}


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    """Persistent ordered list backed by a JSON file.

    Usage::

        searches = Store("app://saved-searches")
        searches.append("my query")
        for q in searches.retrieve():
            ...
    """

    _MAX_ITEMS = 100

    def __init__(self, name):
        # type: (str) -> None
        # Convert "app://saved-searches" -> "saved-searches.json"
        slug = name.replace("app://", "").replace("/", "_").replace(":", "_")
        self._path = os.path.join(_PROFILE, "{}.json".format(slug))

    # ------------------------------------------------------------------

    def _load(self):
        # type: () -> list
        try:
            _ensure_profile()
            if xbmcvfs.exists(self._path):
                fh = xbmcvfs.File(self._path)
                raw = fh.read()
                fh.close()
                return json.loads(raw or "[]")
        except Exception:
            pass
        return []

    def _save(self, items):
        # type: (list) -> None
        try:
            _ensure_profile()
            fh = xbmcvfs.File(self._path, "w")
            fh.write(json.dumps(items[: self._MAX_ITEMS]))
            fh.close()
        except Exception:
            pass

    # ------------------------------------------------------------------

    def append(self, item):
        # type: (object) -> None
        """Prepend *item*, removing any existing duplicate."""
        items = self._load()
        try:
            items.remove(item)
        except (ValueError, TypeError):
            pass
        items.insert(0, item)
        self._save(items)

    def retrieve(self):
        # type: () -> list
        return self._load()

    def remove(self, item):
        # type: (object) -> None
        items = self._load()
        try:
            items.remove(item)
            self._save(items)
        except (ValueError, TypeError):
            pass

    def clear(self):
        # type: () -> None
        self._save([])
