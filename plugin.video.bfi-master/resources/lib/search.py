# -*- coding: utf-8 -*-
"""BFI  searcher and helpers"""
__author__ = "fraser"

import json
import re

import requests
import xbmc
from bs4 import BeautifulSoup

from . import kodiutils as ku
from . import auth as bfi_auth
from cache import Cache, Store, conditional_headers

BFI_URI = "https://player.bfi.org.uk/"
BFI_ORIGIN = "https://player.bfi.org.uk"  # no trailing slash — Brightcove domain policy requires exact match
THE_CUT_URI = "{}the-cut".format(BFI_URI)
SEARCH_URI = "https://search-es.player.bfi.org.uk/prod-films/_search"
# Ooyala was shut down ~2022; kept only as last-resort fallback (will not work)
PLAYER_URI = "https://player.ooyala.com/hls/player/all/"
# Brightcove replaced Ooyala as BFI's video platform
BRIGHTCOVE_PLAYBACK_API = "https://edge.api.brightcove.com/playback/v1/accounts/{}/videos/{}"
BRIGHTCOVE_PLAYER_JS = "https://players.brightcove.net/{}/{}_default/index.min.js"

# BFI's Brightcove account credentials — publicly visible on every BFI Player
# page. data-account and data-player are injected by JavaScript so they cannot
# be scraped from static HTML; these constants are the reliable fallback.
BFI_BRIGHTCOVE_ACCOUNT_ID = "6057949427001"     # free-content Brightcove account
BFI_BRIGHTCOVE_PLAYER_ID = "hndK61Wvr"         # free-content player
BFI_BRIGHTCOVE_SUB_ACCOUNT_ID = "6057940601001" # subscriber Brightcove account (different!)
BFI_BRIGHTCOVE_SUB_PLAYER_ID = "MLNFA1L1R"     # subscriber DRM player

# Policy key for the subscriber-only Brightcove player (MLNFA1L1R).
# This cannot be scraped from the player JS (it returns 404 — private player).
# If you can extract it from browser DevTools (see README), paste it here.
# Leave empty to rely on page-HTML extraction each time.
BFI_BRIGHTCOVE_SUBSCRIBER_POLICY_KEY = ""

# Brightcove edge-auth endpoint — used when a JWT token is available instead
# of a policy key (Brightcove Playback Authorization Service / PAS).
BRIGHTCOVE_EDGE_AUTH_API = "https://edge-auth.api.brightcove.com/playback/v1/accounts/{}/videos/{}"

SEARCH_MAX_RESULTS = ku.get_setting_as_int("search_max_results")
SEARCH_DEFAULT_OPERATOR = ku.get_setting("search_default_operator")
SEARCH_LENIENT = ku.get_setting_as_bool("search_lenient")
SEARCH_SAVED = ku.get_setting_as_bool("search_saved")
RECENT_SAVED = ku.get_setting_as_bool("recent_saved")
SEARCH_TIMEOUT = 60

searches = Store("app://saved-searches")
recents = Store("app://recently-viewed")


def query_encode(query):
    # type: (str) -> str
    """Replaces " " for "+" in query"""
    return query.replace(" ", "+")


def query_decode(query):
    # type: (str) -> str
    """Replaces "+" for " " in query"""
    return query.replace("+", " ")


def html_to_text(text):
    # type: (str) -> str
    soup = BeautifulSoup(text, "html.parser")
    return '\n'.join(soup.stripped_strings)


def duration_to_seconds(text):
    # type: (str) -> int
    """Attempts to covert string of digits representing minutes to seconds"""
    try:
        seconds = int("".join(x for x in text if x.isdigit())) * 60
        return seconds if seconds else 60
    except ValueError:
        return 0


def get_raw_page_text(url):
    # type: (str) -> str
    """Fetch a page's raw HTML text including script tags, with auth cookies.

    Used as a fallback to search for Brightcove policy keys or JWT tokens
    embedded in subscriber pages that the player JS normally provides.
    """
    cookies = bfi_auth.get_session_cookies()
    try:
        r = requests.get(
            url,
            headers={
                "Accept": "text/html",
                "Accept-encoding": "gzip",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            cookies=cookies if cookies else None,
            timeout=SEARCH_TIMEOUT,
        )
        if r.status_code == 200:
            return r.text
    except Exception as exc:
        xbmc.log("[BFI] get_raw_page_text error: {}".format(exc), xbmc.LOGDEBUG)
    return ""


def extract_policy_key(html_text):
    # type: (str) -> str
    """Search raw HTML (including script blocks) for a Brightcove policy key.

    Tries several patterns covering: player config JSON, inline script
    variables, and data- attributes.  Returns the first BCpk... value found,
    or empty string if none.
    """
    patterns = [
        r'policyKey["\s:\']+["\']?(BCpk[A-Za-z0-9_\-]+)',
        r'["\']policy_key["\']\s*:\s*["\']?(BCpk[A-Za-z0-9_\-]+)',
        r'BCOV-Policy["\s:=\']+["\']?(BCpk[A-Za-z0-9_\-]+)',
        r'data-policy-key\s*=\s*["\']?(BCpk[A-Za-z0-9_\-]+)',
        r'(BCpk[A-Za-z0-9_\-]{40,})',  # broad catch-all for any BCpk value
    ]
    for pat in patterns:
        m = re.search(pat, html_text)
        if m:
            return m.group(1)
    return ""


def extract_brightcove_jwt(html_text):
    # type: (str) -> str
    """Search raw HTML for a Brightcove PAS JWT token (Authorization Bearer).

    Returns the JWT string or empty string.
    """
    patterns = [
        r'["\']?bcov_auth["\']?\s*[:=]\s*["\']([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)',
        r'Authorization["\s:\']+Bearer\s+([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)',
        r'["\']?jwt["\']?\s*[:=]\s*["\']([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)',
    ]
    for pat in patterns:
        m = re.search(pat, html_text)
        if m:
            return m.group(1)
    return ""


def parse_meta_info(meta, info):
    # type: (list, dict) -> None
    """Attempts to append year, duration and genre items to given info"""
    info["mediatype"] = "video"
    for item in meta:
        text = item.text.strip()  # BFI+ chip text has surrounding whitespace
        if not text:
            continue
        if text.isdigit():
            info["year"] = int(text)
        elif "min" in text.lower():
            info["duration"] = duration_to_seconds(text)
        else:
            info["genre"].append(text)


def extract_subscriber_credentials(soup):
    # type: (BeautifulSoup) -> tuple
    """Extract the correct Brightcove account, player, and video ID for a
    subscriber film page by parsing its <script> tags.

    BFI uses a separate Brightcove account (6057940601001) for subscriber
    content with the MLNFA1L1R DRM player.  The account ID, player ID, and
    actual video ID are all encoded in the player <script> element:

        <script id="script_{video_id}"
                src="https://players.brightcove.net/{account_id}/{player_id}_default/index.min.js">

    Returns (account_id, player_id, video_id) or ("", "", "") if not found.
    """
    for script in soup.find_all("script", src=True):
        src = script.get("src", "")
        m = re.search(
            r'players\.brightcove\.net/(\d+)/([A-Za-z0-9]+)_default/index', src)
        if not m:
            continue
        scr_account = m.group(1)
        scr_player = m.group(2)
        if scr_player != BFI_BRIGHTCOVE_SUB_PLAYER_ID:
            continue
        scr_id = script.get("id", "")
        scr_video = scr_id.replace("script_", "") if scr_id.startswith("script_") else ""
        if scr_video:
            xbmc.log("[BFI] subscriber script tag: account={} player={} video={}".format(
                scr_account, scr_player, scr_video), xbmc.LOGDEBUG)
            return scr_account, scr_player, scr_video
    return "", "", ""


def get_search_url(query, offset):
    # type: (str, int) -> str
    return "{}?q=pillar:free+{}&size={}&from={}&lenient={}&default_operator={}".format(
        SEARCH_URI,
        query_encode(query),
        SEARCH_MAX_RESULTS,
        SEARCH_MAX_RESULTS * offset,
        "true" if SEARCH_LENIENT else "false",
        SEARCH_DEFAULT_OPERATOR)


def get_brightcove_url(page_url):
    # type: (str) -> str
    """Resolves a Brightcove HLS stream URL from a BFI Player page.

    BFI switched from Ooyala to Brightcove around 2022.  The page embeds a
    <video-js> element with data-account and data-video-id attributes.  We
    fetch raw HTML (bypassing the script-stripping cache) to extract
    Brightcove credentials, retrieve the policy key from the player JS, then
    call the Brightcove Playback API for an HLS source.
    """
    try:
        # Fetch raw HTML so script tags (containing Brightcove config) survive
        raw_resp = requests.get(
            page_url,
            headers={"Accept": "text/html", "Accept-encoding": "gzip"},
            timeout=SEARCH_TIMEOUT
        )
        if raw_resp.status_code != 200:
            return None
        html_text = raw_resp.text
        soup = BeautifulSoup(html_text, "html.parser")

        # --- Locate Brightcove credentials ---
        account_id = ""
        video_id = ""
        player_id = "default"

        # 1. Look for <video-js> or <video> element with data attributes
        # BFI+ uses data-ref-id (Brightcove reference ID), not data-video-id
        video_tag = (
            soup.find("video-js", attrs={"data-ref-id": True}) or
            soup.find("video", attrs={"data-ref-id": True}) or
            soup.find("video-js", attrs={"data-video-id": True}) or
            soup.find("video", attrs={"data-video-id": True}) or
            soup.find(attrs={"data-ref-id": True, "data-account": True})
        )
        ref_id = ""
        if video_tag:
            account_id = video_tag.get("data-account", "")
            player_id = video_tag.get("data-player", "default")
            ref_id = video_tag.get("data-ref-id", "")
            video_id = video_tag.get("data-video-id", "") if not ref_id else ""

        # 2. Regex fallback for JS-embedded config (e.g. JSON blobs in <script>)
        if not (account_id and (ref_id or video_id)):
            acct_m = (re.search(r'["\']accountId["\']\s*:\s*["\'](\d+)["\']', html_text) or
                      re.search(r'data-account=["\'](\d+)["\']', html_text))
            ref_m = re.search(r'data-ref-id=["\']([^"\']+)["\']', html_text)
            vid_m = (re.search(r'["\']videoId["\']\s*:\s*["\'](\d+)["\']', html_text) or
                     re.search(r'data-video-id=["\'](\d+)["\']', html_text))
            if acct_m:
                account_id = acct_m.group(1)
            if ref_m:
                ref_id = ref_m.group(1)
            elif vid_m:
                video_id = vid_m.group(1)

        if not (account_id and (ref_id or video_id)):
            return None

        # Use ref: prefix for ref IDs in the Brightcove Playback API
        video_lookup = "ref:{}".format(ref_id) if ref_id else video_id

        # --- Retrieve policy key from the Brightcove player JS bundle ---
        policy_key = None
        try:
            js_url = BRIGHTCOVE_PLAYER_JS.format(account_id, player_id)
            js_resp = requests.get(js_url, timeout=SEARCH_TIMEOUT)
            if js_resp.status_code == 200:
                match = re.search(r'policyKey["\s:\']+["\']?(BCpk[A-Za-z0-9_\-]+)', js_resp.text)
                if match:
                    policy_key = match.group(1)
        except Exception:
            pass

        # --- Call the Brightcove Playback API ---
        api_url = BRIGHTCOVE_PLAYBACK_API.format(account_id, video_lookup)
        api_headers = {
            "Accept": "application/json",
            "Origin": BFI_ORIGIN,
            "Referer": BFI_URI,
        }
        if policy_key:
            api_headers["BCOV-Policy"] = policy_key

        api_resp = requests.get(api_url, headers=api_headers, timeout=SEARCH_TIMEOUT)
        if api_resp.status_code == 200:
            data = api_resp.json()
            # Prefer DASH MPD; fall back to HLS; skip FairPlay-only sources
            for source in data.get("sources", []):
                src = source.get("src", "")
                mime = source.get("type", "")
                if mime == "application/dash+xml" and src:
                    return src
            for source in data.get("sources", []):
                src = source.get("src", "")
                mime = source.get("type", "")
                ks = source.get("key_systems", {})
                is_fairplay = isinstance(ks, dict) and any(
                    "fps" in k or "fairplay" in k.lower() for k in ks)
                if ("m3u8" in src or mime == "application/x-mpegURL") and not is_fairplay and src:
                    return src
            for source in data.get("sources", []):
                if source.get("src", ""):
                    return source["src"]
    except Exception:
        pass
    return None


def get_brightcove_stream(account_id, ref_id, player_id="default", page_url=None):
    # type: (str, str, str, str) -> dict
    """Calls the Brightcove Playback API with already-extracted credentials.

    Returns a dict:
        {"url": str, "manifest_type": "mpd"|"hls", "license_url": str, "policy_key": str}
    or None on failure.

    Policy key resolution order (stops at first success):
      1. Brightcove player JS bundle (works for public players like hndK61Wvr)
      2. BFI_BRIGHTCOVE_SUBSCRIBER_POLICY_KEY constant (hardcoded fallback)
      3. Raw authenticated page HTML — searches script blocks for BCpk value
      4. Brightcove edge-auth endpoint with JWT from page HTML (PAS flow)

    BFI streams are all DRM-protected (Widevine DASH or FairPlay HLS).  We
    prefer DASH + Widevine because Kodi can play that via inputstream.adaptive
    on Windows/Linux/Android.  FairPlay HLS is Apple-only and not supported.
    """
    xbmc.log("[BFI] get_brightcove_stream: account={} ref_id={} player={}".format(
        account_id, ref_id, player_id), xbmc.LOGDEBUG)
    try:
        video_lookup = "ref:{}".format(ref_id)

        # --- Stage 1: policy key from the Brightcove player JS bundle ---
        # The MLNFA1L1R (subscriber) player JS is restricted by Referer on
        # Brightcove's CDN — the browser sends Referer: player.bfi.org.uk
        # automatically; we must add it explicitly or get a 404.
        policy_key = None
        js_status = None
        try:
            js_url = BRIGHTCOVE_PLAYER_JS.format(account_id, player_id)
            xbmc.log("[BFI] fetching player JS: {}".format(js_url), xbmc.LOGDEBUG)
            js_resp = requests.get(
                js_url,
                headers={"Referer": BFI_URI, "Origin": BFI_ORIGIN},
                timeout=SEARCH_TIMEOUT,
            )
            js_status = js_resp.status_code
            xbmc.log("[BFI] player JS status: {}".format(js_status), xbmc.LOGDEBUG)
            if js_status == 200:
                match = re.search(r'policyKey["\s:\']+["\']?(BCpk[A-Za-z0-9_\-]+)', js_resp.text)
                if match:
                    policy_key = match.group(1)
                    xbmc.log("[BFI] policy key found in player JS: {}...".format(policy_key[:20]), xbmc.LOGDEBUG)
                else:
                    xbmc.log("[BFI] policy key NOT found in player JS", xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log("[BFI] player JS error: {}".format(e), xbmc.LOGDEBUG)

        # --- Stage 1.5: fallback to the known-public player (hndK61Wvr) ---
        # The subscriber film pages embed data-player="MLNFA1L1R" in the HTML
        # but actually LOAD hndK61Wvr_default/index.min.js — the same free-content
        # player script.  So try extracting the policy key from hndK61Wvr when the
        # declared player's JS is unavailable (404).
        if not policy_key and js_status != 200 and player_id != BFI_BRIGHTCOVE_PLAYER_ID:
            xbmc.log("[BFI] player JS unavailable — trying fallback player {}".format(
                BFI_BRIGHTCOVE_PLAYER_ID), xbmc.LOGDEBUG)
            try:
                fallback_js_url = BRIGHTCOVE_PLAYER_JS.format(account_id, BFI_BRIGHTCOVE_PLAYER_ID)
                fallback_resp = requests.get(
                    fallback_js_url,
                    headers={"Referer": BFI_URI, "Origin": BFI_ORIGIN},
                    timeout=SEARCH_TIMEOUT,
                )
                xbmc.log("[BFI] fallback player JS status: {}".format(
                    fallback_resp.status_code), xbmc.LOGDEBUG)
                if fallback_resp.status_code == 200:
                    match = re.search(
                        r'policyKey["\s:\']+["\']?(BCpk[A-Za-z0-9_\-]+)', fallback_resp.text)
                    if match:
                        policy_key = match.group(1)
                        xbmc.log("[BFI] fallback policy key found: {}...".format(
                            policy_key[:20]), xbmc.LOGDEBUG)
                    else:
                        xbmc.log("[BFI] policy key NOT found in fallback player JS", xbmc.LOGDEBUG)
            except Exception as e:
                xbmc.log("[BFI] fallback player JS error: {}".format(e), xbmc.LOGDEBUG)

        # --- Stage 2: hardcoded subscriber policy key constant ---
        if not policy_key and BFI_BRIGHTCOVE_SUBSCRIBER_POLICY_KEY:
            policy_key = BFI_BRIGHTCOVE_SUBSCRIBER_POLICY_KEY
            xbmc.log("[BFI] using hardcoded subscriber policy key", xbmc.LOGDEBUG)

        # --- Stage 3: search raw authenticated page HTML for embedded policy key ---
        page_html = ""
        if not policy_key and page_url:
            xbmc.log("[BFI] player JS unavailable — searching page HTML for policy key", xbmc.LOGDEBUG)
            page_html = get_raw_page_text(page_url)
            if page_html:
                policy_key = extract_policy_key(page_html)
                if policy_key:
                    xbmc.log("[BFI] policy key found in page HTML: {}...".format(policy_key[:20]), xbmc.LOGDEBUG)
                else:
                    xbmc.log("[BFI] policy key NOT found in page HTML (len={})".format(len(page_html)), xbmc.LOGDEBUG)
            else:
                xbmc.log("[BFI] page HTML fetch returned empty", xbmc.LOGDEBUG)

        # --- Stage 4: try Brightcove edge-auth endpoint with a JWT from page HTML ---
        # This handles Brightcove Playback Authorization Service (PAS) where BFI
        # embeds a signed JWT in the page for authenticated subscribers.
        if not policy_key and page_url:
            if not page_html:
                page_html = get_raw_page_text(page_url)
            jwt_token = extract_brightcove_jwt(page_html) if page_html else ""
            if jwt_token:
                xbmc.log("[BFI] found JWT in page HTML — trying edge-auth endpoint", xbmc.LOGDEBUG)
                edge_url = BRIGHTCOVE_EDGE_AUTH_API.format(account_id, video_lookup)
                edge_headers = {
                    "Accept": "application/json",
                    "Origin": BFI_ORIGIN,
                    "Referer": BFI_URI,
                    "Authorization": "Bearer {}".format(jwt_token),
                }
                edge_resp = requests.get(edge_url, headers=edge_headers, timeout=SEARCH_TIMEOUT)
                xbmc.log("[BFI] edge-auth status: {}".format(edge_resp.status_code), xbmc.LOGDEBUG)
                if edge_resp.status_code == 200:
                    return _parse_brightcove_sources(edge_resp.json(), policy_key="")
                else:
                    xbmc.log("[BFI] edge-auth error: {}".format(edge_resp.text[:300]), xbmc.LOGDEBUG)
            else:
                xbmc.log("[BFI] no JWT found in page HTML", xbmc.LOGDEBUG)

        # --- Call the standard Brightcove Playback API ---
        api_url = BRIGHTCOVE_PLAYBACK_API.format(account_id, video_lookup)
        api_headers = {
            "Accept": "application/json",
            # BFI_ORIGIN has no trailing slash — Brightcove domain policy rejects
            # Origin values that don't exactly match the registered domain.
            "Origin": BFI_ORIGIN,
            "Referer": BFI_URI,
        }
        if policy_key:
            api_headers["BCOV-Policy"] = policy_key
        else:
            xbmc.log("[BFI] WARNING: calling Brightcove API with no policy key — expect 401", xbmc.LOGDEBUG)

        xbmc.log("[BFI] calling Brightcove API: {}".format(api_url), xbmc.LOGDEBUG)
        api_resp = requests.get(api_url, headers=api_headers, timeout=SEARCH_TIMEOUT)
        xbmc.log("[BFI] Brightcove API status: {}".format(api_resp.status_code), xbmc.LOGDEBUG)
        if api_resp.status_code == 200:
            return _parse_brightcove_sources(api_resp.json(), policy_key=policy_key or "")
        else:
            xbmc.log("[BFI] Brightcove API error body: {}".format(api_resp.text[:300]), xbmc.LOGDEBUG)
    except Exception as e:
        xbmc.log("[BFI] get_brightcove_stream exception: {}".format(e), xbmc.LOGDEBUG)
    return None


def _parse_brightcove_sources(data, policy_key=""):
    # type: (dict, str) -> dict
    """Pick the best playable source from a Brightcove Playback API response.

    Prefers DASH + Widevine (works via inputstream.adaptive on Kodi/Windows/
    Linux/Android).  FairPlay HLS (Apple-only) is skipped.
    Returns a stream info dict or None.
    """
    dash_source = None
    hls_source = None
    fallback = None
    best_width = 0
    best_height = 0
    for source in data.get("sources", []):
        src = source.get("src", "")
        if not src:
            continue
        mime = source.get("type", "")
        ks = source.get("key_systems", {})
        w = source.get("width", 0)
        h = source.get("height", 0)
        if w and h and w > best_width:
            best_width = w
            best_height = h
        if mime == "application/dash+xml":
            if not dash_source:
                license_url = ""
                if isinstance(ks, dict):
                    wv = ks.get("com.widevine.alpha", {})
                    license_url = wv.get("license_url", "") if isinstance(wv, dict) else ""
                dash_source = {
                    "url": src,
                    "manifest_type": "mpd",
                    "license_url": license_url,
                    "policy_key": policy_key,
                }
        elif "m3u8" in src or mime == "application/x-mpegURL":
            is_fairplay = False
            if isinstance(ks, dict) and any("fps" in k or "fairplay" in k.lower() for k in ks):
                is_fairplay = True
            elif isinstance(ks, list) and any("fps" in k or "fairplay" in k.lower() for k in ks):
                is_fairplay = True
            if not is_fairplay and not hls_source:
                hls_source = {
                    "url": src,
                    "manifest_type": "hls",
                    "license_url": "",
                    "policy_key": policy_key,
                }
        elif not fallback:
            fallback = {"url": src, "manifest_type": "hls", "license_url": "", "policy_key": ""}

    result = dash_source or hls_source or fallback
    if result and best_width and best_height:
        result["width"] = best_width
        result["height"] = best_height
    xbmc.log("[BFI] stream result: {}".format(result), xbmc.LOGDEBUG)
    return result


def get_stream_info(video_id, account_id="", player_id="default", page_url=None):
    # type: (str, str, str, str) -> dict
    """Gets full stream info dict for a given video.

    Returns {"url": str, "manifest_type": "mpd"|"hls", "license_url": str,
             "policy_key": str} or None.

    Preferred path: use pre-extracted Brightcove credentials supplied by
    play_film() — page_url is passed through so get_brightcove_stream() can
    search the authenticated page HTML for a policy key when the player JS
    is not publicly accessible (e.g. the subscriber-only MLNFA1L1R player).
    Fallback: re-fetch the page via get_brightcove_url() (for recents).
    """
    if account_id and video_id:
        info = get_brightcove_stream(account_id, video_id, player_id, page_url=page_url)
        if info:
            return info
    if page_url:
        url = get_brightcove_url(page_url)
        if url:
            return {"url": url, "manifest_type": "hls", "license_url": "", "policy_key": ""}
    return None


def get_m3u8_url(video_id, account_id="", player_id="default", page_url=None):
    # type: (str, str, str, str) -> str
    """Legacy wrapper — returns URL string only.  Use get_stream_info() for DRM support."""
    info = get_stream_info(video_id, account_id=account_id, player_id=player_id, page_url=page_url)
    if info:
        return info["url"]
    # Legacy Ooyala fallback - non-functional since ~2022, kept as last resort
    return "{}{}.m3u8?ssl=true".format(PLAYER_URI, video_id)


def get_page_url(href):
    # type: (str) -> str
    """Gets a full URL to a BFI html page"""
    return href if href.startswith("http") else "{}{}".format(BFI_URI, href.lstrip("/"))


def is_login_page(soup):
    # type: (Any) -> bool
    """Returns True when the BFI site served the sign-in page instead of the requested content.
    This happens when session cookies have expired — the site returns HTTP 200 but with the
    login page HTML, so status-code checks alone can't detect it.
    """
    if soup is None:
        return False
    title = soup.find("title")
    return bool(title and "Sign in" in title.text)


def cache_clear():
    # type: () -> None
    with Cache() as c:
        c.clear()


def get_html(url, use_auth=False):
    # type: (str, bool) -> BeautifulSoup
    """Gets cached or live HTML from the url.

    When *use_auth* is True (or when the URL path starts with /subscription),
    stored session cookies are included so that subscriber-only pages are
    served correctly.  Authenticated responses are not cached to avoid
    storing personalised content.
    """
    # Always attach auth cookies for subscription or account URLs, or when requested
    needs_auth = use_auth or "/subscription" in url or "/account/" in url
    cookies = bfi_auth.get_session_cookies() if needs_auth else {}

    headers = {
        "Accept": "text/html",
        "Accept-encoding": "gzip"
    }
    # Skip the cache for authenticated requests (content is personalised).
    # Do NOT strip <script> tags here — play_film() needs them to extract
    # the correct Brightcove account ID and video ID for subscriber content.
    if cookies:
        r = requests.get(url, headers=headers, cookies=cookies, timeout=SEARCH_TIMEOUT)
        if r.status_code == 200:
            return BeautifulSoup(r.content, "html.parser")
        return None

    with Cache() as c:
        cached = c.get(url)
        if cached:
            headers.update(conditional_headers(cached))
            if cached["fresh"]:
                return BeautifulSoup(cached["blob"], "html.parser")
        r = requests.get(url, headers=headers, timeout=SEARCH_TIMEOUT)
        if 200 == r.status_code:
            soup = BeautifulSoup(r.content, "html.parser")
            # pre-cache clean-up
            for x in soup(["script", "style"]):
                x.extract()
            c.set(url, r.content, r.headers)
            return soup
        elif 304 == r.status_code:
            c.touch(url, r.headers)
            return BeautifulSoup(cached["blob"], "html.parser")


def get_json(url):
    # type: (str) -> dict
    """Gets cached or live JSON from the url"""
    headers = {
        "Accept": "application/json",
        "Accept-encoding": "gzip"
    }
    with Cache() as c:
        cached = c.get(url)
        if cached:
            headers.update(conditional_headers(cached))
            if cached["fresh"]:
                return json.loads(cached["blob"])
        r = requests.get(url, headers=headers, timeout=SEARCH_TIMEOUT)
        if 200 == r.status_code:
            c.set(url, r.json(), r.headers)
            return r.json()
        elif 304 == r.status_code:
            c.touch(url, r.headers)
            return json.loads(cached["blob"])


def scrape_film_details(href):
    # type: (str) -> dict
    """Scrape the film detail page for rich metadata.

    Returns a dict with keys: title, plot, plotoutline, director, cast, genre,
    year, duration, country, language, mpaa, fanart, trailer_video_id,
    trailer_account_id, trailer_player_id, in_watchlist, film_entity_id,
    watchlist_url. Missing fields are omitted.
    """
    url = get_page_url(href)
    soup = get_html(url)
    if not soup:
        return {}

    result = {}

    # Title
    h1 = soup.find("h1")
    if h1:
        span = h1.find("span", "film-title__maintitle")
        result["title"] = (span or h1).get_text(strip=True)

    # Hero fanart from page header
    header = soup.find("header", {"data-component-id": "nuplayer:film_page_header"})
    if header:
        hero = header.find("img", loading="lazy")
        if hero:
            src = hero.get("src", "")
            if src and not src.startswith("http"):
                src = BFI_URI + src
            if src:
                result["fanart"] = src

    # BBFC rating
    bbfc = soup.find("img", {"data-component-id": "nuplayer:bbfc_rating"})
    if bbfc:
        result["mpaa"] = bbfc.get("alt", "").replace(" rating", "").strip()

    # Metadata summary (genre, year, duration, director, country, language)
    summary = soup.find("div", "film-metadata-summary")
    if summary:
        g = summary.find("div", {"aria-label": "Genre"})
        if g:
            result["genre"] = [g.get_text(strip=True)]
        y = summary.find("div", {"aria-label": "Release Date"})
        if y:
            try:
                result["year"] = int(y.get_text(strip=True))
            except (ValueError, TypeError):
                pass
        d = summary.find("div", {"aria-label": "Duration"})
        if d:
            result["duration"] = duration_to_seconds(d.get_text(strip=True))
        for p in summary.find_all("p"):
            if "Directed by" in p.get_text():
                a = p.find("a")
                result["director"] = a.get_text(strip=True) if a else \
                    p.get_text(strip=True).replace("Directed by", "").strip()
                break
        c = summary.find("div", {"aria-label": "Country of Origin"})
        if c:
            result["country"] = c.get_text(strip=True)
        lang = summary.find("div", {"aria-label": "Language"})
        if lang:
            result["language"] = lang.get_text(strip=True)

    # Film description
    film_desc = soup.find("div", "film-description")
    if film_desc:
        sf = film_desc.find("p", "standfirst")
        if sf:
            result["plotoutline"] = sf.get_text(strip=True)
        paras = [p.get_text(strip=True) for p in film_desc.find_all("p") if p.get_text(strip=True)]
        if paras:
            result["plot"] = "\n\n".join(paras)

    # Full metadata section (cast, full genre list, certificate)
    meta = soup.find("div", {"data-component-id": "nuplayer:film_page_metadata"})
    if meta:
        featuring = meta.find("dd", "featuring")
        if featuring:
            result["cast"] = [a.get_text(strip=True) for a in featuring.find_all("a")]
        genres_dd = meta.find("dd", "genres")
        if genres_dd:
            result["genre"] = [a.get_text(strip=True) for a in genres_dd.find_all("a")]
        if "mpaa" not in result:
            cert_dd = meta.find("dd", "certificate")
            if cert_dd:
                cert_img = cert_dd.find("img")
                if cert_img:
                    result["mpaa"] = cert_img.get("alt", "").replace(" rating", "").strip()

    # Trailer credentials — button.js__trailer carries data-video-id and data_ac (BFI HTML typo)
    trailer_btn = soup.find("button", "js__trailer")
    if trailer_btn:
        t_vid = trailer_btn.get("data-video-id", "")
        t_ac = trailer_btn.get("data_ac", "") or trailer_btn.get("data-ac", "")
        if t_vid:
            result["trailer_video_id"] = t_vid
            result["trailer_account_id"] = t_ac
            t_vjs = soup.find(attrs={"data-bundle": "trailer", "data-pid": True})
            result["trailer_player_id"] = t_vjs.get("data-pid", "hndK61Wvr") if t_vjs else "hndK61Wvr"

    # Watchlist state — div class encodes current state and film entity ID
    wl_div = soup.find("div", {"data-component-id": "nuplayer:watchlist_button"})
    if wl_div:
        classes = wl_div.get("class", [])
        result["in_watchlist"] = "watchlist--remove" in classes
        for cls in classes:
            if cls.startswith("js-flag-watchlist-"):
                result["film_entity_id"] = cls.replace("js-flag-watchlist-", "")
                break
        wl_btn = wl_div.find("button")
        if wl_btn:
            btn_href = wl_btn.get("href", "")
            if btn_href:
                result["watchlist_url"] = get_page_url(btn_href)

    return result