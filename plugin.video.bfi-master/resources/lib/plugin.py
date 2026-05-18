# -*- coding: utf-8 -*-
"""Main plugin file - Handles the various routes"""
__author__ = "fraser"

import logging

import requests
import routing
import xbmc
import xbmcaddon
import xbmcplugin
from xbmcgui import ListItem

from resources.lib import kodilogging
from resources.lib import kodiutils as ku
from resources.lib import search as bfis
from resources.lib import auth as bfi_auth

kodilogging.config()
logger = logging.getLogger(__name__)
plugin = routing.Plugin()

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name")  # BFI Player

PLAYER_ID_ATTR = "data-ref-id"
PLAYER_ACCOUNT_ATTR = "data-account"
PLAYER_PLAYER_ATTR = "data-player"
# BFI+ redesign (2024-25): cards are <a class="film-card ..."> elements.
# The <a> tag is both the card container AND the clickable link (href on the card itself).
JIG = {
    "category": {
        "card": ["a", "film-card"],
        "title": ["span", "field--name-title"],
        "plot": ["p", {"data-component-id": "nuplayer:details"}],
        "meta": ["li", {"data-component-id": "nuplayer:chip"}]
    },
    "collection": {
        "card": ["a", "film-card"],
        "title": ["span", "field--name-title"],
        "plot": ["p", {"data-component-id": "nuplayer:details"}],
        "meta": ["li", {"data-component-id": "nuplayer:chip"}]
    },
    "subscription": {
        "card": ["a", "film-card"],
        "title": ["span", "field--name-title"],
        "plot": ["p", {"data-component-id": "nuplayer:details"}],
        "meta": ["li", {"data-component-id": "nuplayer:chip"}]
    },
    # Collections overview pages (/subscription/collections, /free/collections) use
    # <a class="collection-card"> with h3 title and p description — no meta chips.
    # Use {} (not None) as the attrs arg: None gets coerced to {'class': None} by BS4
    # which requires the element to have NO class, so h3[class="dark"] is never found.
    "collections_overview": {
        "card": ["a", "collection-card"],
        "title": ["h3", {}],
        "plot": ["p", {}]
    }
}


def add_menu_item(method, label, **kwargs):
    # type: (callable, Union[str, int], Any) -> None
    """wrapper for xbmcplugin.addDirectoryItem"""
    args = kwargs.get("args", {})
    label = ku.localize(label) if isinstance(label, int) else label
    list_item = ListItem(label)
    list_item.setArt(kwargs.get("art") or {})
    list_item.setInfo("video", kwargs.get("info") or {})
    if method == search and "q" in args:
        list_item.addContextMenuItems([(
            ku.localize(32019),
            "XBMC.RunPlugin({})".format(plugin.url_for(search, delete=True, q=label))
        )])
    if method == play_film:
        list_item.setProperty("IsPlayable", "true")
        kwargs["directory"] = False
    xbmcplugin.addDirectoryItem(
        plugin.handle,
        plugin.url_for(method, **args),
        list_item,
        kwargs.get("directory", True))


def get_arg(key, default=None):
    # type: (str, Any) -> Any
    """Get the argument value or default"""
    if default is None:
        default = ""
    return plugin.args.get(key, [default])[0]


def paginate(query, count, total, offset):
    # type: (str, int, int, int) -> None
    """Adds search partition menu items"""
    if count < total and count == bfis.SEARCH_MAX_RESULTS:
        offset += 1
        next_page = "[{} {}]".format(ku.localize(32011), offset + 1)  # [Page n+1]
        first_page = "[{} 1]".format(ku.localize(32011))  # [Page 1]
        main_menu = "[{}]".format(ku.localize(32012))  # [Menu]
        if offset > 1:
            add_menu_item(search, first_page, args={"q": query, "offset": 0})
        add_menu_item(search, next_page, args={"q": query, "offset": offset})
        add_menu_item(index, main_menu)


def parse_search_results(data, query, offset):
    # type: (dict, str, int) -> None
    """Adds menu items for search result data"""
    if not data:
        return
    hits = data.get("hits")
    if not hits:
        return
    results = hits.get("hits", [])
    paginate(query, len(results), int(hits.get("total", 0)), offset)
    for element in results:
        data = element.get("_source", False)
        if not data:
            continue
        title = data.get("title", "")
        duration = data.get("duration")
        info = {
            "originaltitle": data.get("original_title", ""),
            "plot": bfis.html_to_text(data.get("standfirst", "")),
            "genre": data.get("genre", ""),
            "cast": data.get("cast", ""),
            "director": data.get("director", ""),
            "year": int(data.get("release_date", 0)),
            "duration": int(duration) * 60 if duration else 0,
            "mediatype": "video"
        }
        add_menu_item(show_film,
                      title,
                      args={"href": data.get("url")},
                      art=ku.art("", data.get("image", ["Default.png"])[0]),
                      info=info)



def parse_card(card):
    # type: (Any) -> Optional[tuple]
    """Parse a watchlist .card element into (href, title, info, art).

    The /account/watchlist page uses a different HTML structure from subscription
    listing pages: link is <a class="card__action">, meta chips are
    <span class="card__info__item">.  Returns None when the card is unusable.
    """
    link = card.find("a", "card__action")
    if not link:
        return None
    href = link.get("href", "")
    if not href:
        return None
    title = link.get("aria-label", "").strip()
    if not title:
        span = link.find("span", "h-e")
        if span:
            inner = span.find("span")
            title = inner.text.strip() if inner else span.text.strip()
    if not title:
        return None
    info = {"genre": [], "mediatype": "video"}
    for item in card.find_all("span", "card__info__item"):
        text = item.text.strip()
        if not text:
            continue
        if text.isdigit():
            info["year"] = int(text)
        elif "min" in text.lower():
            info["duration"] = bfis.duration_to_seconds(text)
        else:
            info["genre"].append(text)
    img_tag = card.find("img")
    art = ku.art(bfis.BFI_URI, img_tag.attrs if img_tag else {})
    return href, title, info, art


@plugin.route("/clear/<idx>")
def clear(idx):
    # type: (str) -> None
    """Clear cache, searches or recently played items"""
    if idx == "cache" and ku.confirm():
        bfis.cache_clear()
    if idx == "recent" and ku.confirm():
        bfis.recents.clear()
    if idx == "search" and ku.confirm():
        bfis.searches.clear()


@plugin.route("/")
def index():
    # type: () -> None
    """Main menu"""
    # BFI+ Subscription section (login-gated)
    if ku.get_setting_as_bool("show_bfi_plus"):
        if bfi_auth.is_logged_in():
            add_menu_item(show_subscription_menu, 32038,  # Subscription
                          art=ku.icon("subscription.png"))
            if ku.get_setting_as_bool("show_watchlist"):
                add_menu_item(show_watchlist, 32042,  # Watchlist
                              art=ku.icon("saved.png"))
        else:
            # Not signed in — show a prompt item that opens Settings
            add_menu_item(settings,
                          "[BFI+ {}]".format(ku.localize(32028)),  # [BFI+ Sign In]
                          art=ku.icon("subscription.png"))
    # Free content section
    if ku.get_setting_as_bool("show_free_menu"):
        add_menu_item(show_free_menu, 32008,  # Free
                      art=ku.icon("free.png"))
    if ku.get_setting_as_bool("show_search"):
        add_menu_item(search, 32007, args={"menu": True}, art=ku.icon("search.png"))
    if ku.get_setting_as_bool("show_recent"):
        add_menu_item(recent, 32021, art=ku.icon("saved.png"))
    if ku.get_setting_as_bool("show_settings"):
        add_menu_item(settings, 32010, art=ku.icon("settings.png"), directory=False)
    xbmcplugin.setPluginCategory(plugin.handle, ADDON_NAME)
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route("/settings")
def settings():
    # type: () -> None
    """Plugin setting config"""
    ku.show_settings()
    xbmc.executebuiltin("Container.Refresh()")


@plugin.route("/recent")
def recent():
    # type: () -> None
    """Show recently viewed films"""
    data = bfis.recents.retrieve()
    for url, video_id in data:
        soup = bfis.get_html(url)
        title = soup.find("h1").text.strip()
        description = soup.find("meta", {"name": "description"}).get("content")
        image = soup.find("meta", {"property": "og:image"}).get("content")
        add_menu_item(play_film,
                      title,
                      args={"href": url, "video_id": video_id},
                      info={"plot": description, "mediatype": "video"},
                      art=ku.art("", image),
                      directory=False)
    xbmcplugin.setContent(plugin.handle, "videos")
    xbmcplugin.setPluginCategory(plugin.handle, ku.localize(32021))  # Recently Viewed
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route('/the_cut')
def the_cut():
    # type: () -> None
    """Shows the-cut menu and sub-menu items"""
    href = get_arg("href")
    category = get_arg("title", "The Cut")
    if not href:
        # The Cut top-level menu: list of themed collections
        # BFI+ uses the same film-card <a> structure as main category pages
        soup = bfis.get_html(bfis.THE_CUT_URI)
        for card in soup.find_all("a", "film-card"):
            card_href = card.get("href", "")
            if not card_href:
                continue
            title_tag = card.find("span", "field--name-title")
            plot_tag = card.find("p", {"data-component-id": "nuplayer:details"})
            title = title_tag.text.strip() if title_tag else card.get("aria-label", "").strip()
            if not title:
                continue
            img_tag = card.find("img")
            add_menu_item(the_cut,
                          title,
                          args={"href": card_href, "title": title},
                          info={"plot": plot_tag.text.strip() if plot_tag else ""},
                          art=ku.art(bfis.BFI_URI, img_tag.attrs if img_tag else {}))
    else:
        # The Cut sub-page: playable film items
        # Films on sub-pages use the same film-card structure
        soup = bfis.get_html(bfis.get_page_url(href))
        for card in soup.find_all("a", "film-card"):
            card_href = card.get("href", "")
            if not card_href:
                continue
            title_tag = card.find("span", "field--name-title")
            plot_tag = card.find("p", {"data-component-id": "nuplayer:details"})
            title = title_tag.text.strip() if title_tag else card.get("aria-label", "").strip()
            if not title:
                continue
            img_tag = card.find("img")
            add_menu_item(show_film,
                          title,
                          args={"href": card_href},
                          info={"mediatype": "video",
                                "plot": plot_tag.text.strip() if plot_tag else ""},
                          art=ku.art(bfis.BFI_URI, img_tag.attrs if img_tag else {}))
        xbmcplugin.setContent(plugin.handle, "videos")
    xbmcplugin.setPluginCategory(plugin.handle, category)
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route("/subscription_menu")
def show_subscription_menu():
    # type: () -> None
    """BFI+ Subscription sub-menu with all confirmed section URLs."""
    category = ku.localize(32038)  # Subscription
    add_menu_item(show_category, 32039,  # Subscription Exclusives
                  args={
                      "href": "subscription/collection/subscription-exclusives",
                      "title": ku.localize(32039),
                      "key": "subscription"
                  },
                  art=ku.icon("exclusives.png"))
    add_menu_item(show_category, 32040,  # Recently Added
                  args={
                      "href": "subscription/collection/recently-added",
                      "title": ku.localize(32040),
                      "key": "subscription"
                  },
                  art=ku.icon("recently-added.png"))
    add_menu_item(show_category, 32026,  # Kermode Introduces
                  args={
                      "href": "subscription/kermode-introduces",
                      "title": ku.localize(32026),
                      "key": "subscription",
                      "target": "play-kermode-introduces"
                  },
                  art=ku.icon("kermode.png"))
    add_menu_item(show_category, 32005,  # Popular
                  args={
                      "href": "subscription/popular",
                      "title": ku.localize(32005),
                      "key": "subscription"
                  },
                  art=ku.icon("popular.png"))
    add_menu_item(show_category, 32006,  # Collections
                  args={
                      "key": "collections_overview",
                      "href": "subscription/collections",
                      "title": ku.localize(32006),
                      "sub_directory": True
                  },
                  art=ku.icon("collection.png"))
    add_menu_item(show_category, 32041,  # Coming Soon
                  args={
                      "href": "subscription/coming-soon",
                      "title": ku.localize(32041),
                      "key": "subscription"
                  },
                  art=ku.icon("coming-soon.png"))
    # A-Z: BFI uses a query-parameter URL (/search/subscription?sort=...) that is
    # not compatible with the current film-card scraper. TODO: wire up once confirmed.
    xbmcplugin.setPluginCategory(plugin.handle, category)
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route("/free_menu")
def show_free_menu():
    # type: () -> None
    """Free content sub-menu."""
    category = ku.localize(32008)  # Free
    add_menu_item(show_category, 32005,  # Popular
                  args={
                      "href": "free/collection/popular",
                      "title": ku.localize(32005)
                  },
                  art=ku.icon("popular.png"))
    add_menu_item(show_category, 32043,  # Inside Film
                  args={
                      "href": "free/inside-film",
                      "title": ku.localize(32043)
                  },
                  art=ku.icon("inside-film.png"))
    add_menu_item(show_category, 32044,  # Shorts
                  args={
                      "href": "free/shorts",
                      "title": ku.localize(32044)
                  },
                  art=ku.icon("shorts.png"))
    add_menu_item(show_category, 32006,  # Collections
                  args={
                      "key": "collections_overview",
                      "href": "free/collections",
                      "title": ku.localize(32006),
                      "sub_directory": True
                  },
                  art=ku.icon("collection.png"))
    xbmcplugin.setPluginCategory(plugin.handle, category)
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route("/watchlist")
def show_watchlist():
    # type: () -> None
    """Show the user's BFI+ Watchlist from /account/watchlist."""
    if not bfi_auth.is_logged_in():
        ku.notification(ADDON_NAME, ku.localize(32033), time=6000)
        ku.show_settings()
        return
    soup = bfis.get_html(bfis.get_page_url("account/watchlist"), use_auth=True)
    if not soup:
        return
    if bfis.is_login_page(soup):
        bfi_auth.logout()
        ku.notification(ADDON_NAME, ku.localize(32046), time=6000)
        ku.show_settings()
        return
    found = False
    for card in soup.find_all("div", "card"):
        result = parse_card(card)
        if not result:
            continue
        href, title, info, art = result
        add_menu_item(show_film,
                      title,
                      args={"href": href},
                      art=art,
                      info=info)
        found = True
    if not found:
        # Watchlist is empty — show a friendly placeholder
        add_menu_item(index, "[{}]".format(ku.localize(32012)))  # [Menu]
    xbmcplugin.setContent(plugin.handle, "videos")
    xbmcplugin.setPluginCategory(plugin.handle, ku.localize(32042))  # Watchlist
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_GENRE)
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route("/category")
def show_category():
    # type: () -> None
    """Shows the category menu (based on supplied key)"""
    key = get_arg("key", "category")
    href = get_arg("href", "free")
    target = get_arg("target")
    sub_directory = bool(get_arg("sub_directory", False))
    category = get_arg("title", ku.localize(32008))
    soup = bfis.get_html(bfis.get_page_url(href))
    for card in soup.find_all(*JIG[key]["card"]):
        # BFI+ (2024-25): the <a class="film-card"> element IS the link
        card_href = card.get("href", "")
        if not card_href:
            continue
        # Title
        title_tag = card.find(*JIG[key]["title"])
        title = title_tag.text.strip() if title_tag else card.get("aria-label", "").strip()
        if not title:
            continue
        # Plot
        plot_tag = card.find(*JIG[key]["plot"])
        info = {"plot": plot_tag.text.strip() if plot_tag else "", "genre": []}
        # Meta chips (year, duration, genre)
        if "meta" in JIG[key]:
            bfis.parse_meta_info(card.find_all(*JIG[key]["meta"]), info)
        if target == "play-kermode-introduces":
            info.pop("duration", None)
        # Art: film-cards use data-img-800/960/1440; collection-cards use data-img-200/285/344.
        # ku.art() falls back through all sizes so both card types resolve correctly.
        img_tag = card.find("img")
        art = ku.art(bfis.BFI_URI, img_tag.attrs if img_tag else {})
        add_menu_item(show_category if sub_directory else show_film,
                      title,
                      args={"href": card_href, "title": title},
                      art=art,
                      info=info,
                      directory=True)
    xbmcplugin.setPluginCategory(plugin.handle, category)
    xbmcplugin.setContent(plugin.handle, "videos")
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_GENRE)
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_DURATION)
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route("/show")
def show_film():
    # type: () -> None
    """Film detail screen: Watch Now, Trailer (if available), Watchlist toggle."""
    href = get_arg("href")
    details = bfis.scrape_film_details(href)
    if not details:
        return

    title = details.get("title") or get_arg("title", "")
    info = {
        "title": title,
        "originaltitle": title,
        "plot": details.get("plot", ""),
        "plotoutline": details.get("plotoutline", ""),
        "director": details.get("director", ""),
        "cast": details.get("cast", []),
        "genre": ", ".join(details.get("genre", [])),
        "year": details.get("year", 0),
        "duration": details.get("duration", 0),
        "country": details.get("country", ""),
        "mpaa": details.get("mpaa", ""),
        "mediatype": "movie",
    }
    art = {}
    fanart = details.get("fanart", "")
    if fanart:
        art["fanart"] = fanart

    def _add_playable(label, item_info, extra_args=None):
        item = ListItem(label)
        item.setInfo("video", item_info)
        item.setArt(art)
        item.setProperty("IsPlayable", "true")
        args = {"href": href}
        if extra_args:
            args.update(extra_args)
        xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(play_film, **args), item, False)

    _add_playable("Watch Now", info)

    trailer_id = details.get("trailer_video_id", "")
    if trailer_id:
        trailer_info = dict(info)
        trailer_info["title"] = title + " - Trailer"
        trailer_info["duration"] = 0
        _add_playable("Watch Trailer", trailer_info, {
            "video_id": trailer_id,
            "account_id": details.get("trailer_account_id", ""),
            "player_id": details.get("trailer_player_id", "hndK61Wvr"),
        })

    wl_url = details.get("watchlist_url", "")
    if wl_url and bfi_auth.is_logged_in():
        in_wl = details.get("in_watchlist", False)
        wl_label = "Remove from Watchlist" if in_wl else "Add to Watchlist"
        wl_item = ListItem(wl_label)
        wl_item.setInfo("video", info)
        wl_item.setArt(art)
        xbmcplugin.addDirectoryItem(
            plugin.handle,
            plugin.url_for(toggle_watchlist, watchlist_url=wl_url),
            wl_item,
            False
        )

    xbmcplugin.setPluginCategory(plugin.handle, title)
    xbmcplugin.setContent(plugin.handle, "videos")
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route("/watchlist_toggle")
def toggle_watchlist():
    # type: () -> None
    """Toggle watchlist by calling the BFI flag/unflag URL (contains CSRF token)."""
    watchlist_url = get_arg("watchlist_url")
    if not watchlist_url:
        return
    cookies = bfi_auth.get_session_cookies()
    if not cookies:
        ku.notification(ADDON_NAME, ku.localize(32033), time=4000)
        return
    try:
        resp = requests.get(
            watchlist_url,
            cookies=cookies,
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            ku.notification(ADDON_NAME, "Watchlist updated")
        else:
            ku.notification(ADDON_NAME, "Watchlist update failed ({})".format(resp.status_code))
    except Exception as exc:
        ku.notification(ADDON_NAME, str(exc))
    xbmc.executebuiltin("Container.Refresh")


@plugin.route("/film")
def play_film():
    # type: () -> None
    """Attempts to find the m3u8 file for a given href and play it"""
    url = bfis.get_page_url(get_arg("href"))
    video_id = get_arg("video_id")
    explicit_account = get_arg("account_id")  # set by show_film for trailers
    explicit_player = get_arg("player_id")    # set by show_film for trailers
    target = get_arg("target")

    if explicit_account and explicit_player and video_id:
        # Explicit credentials provided (trailer) — skip page fetch and subscriber override
        account_id = explicit_account
        player_id = explicit_player
    else:
        soup = bfis.get_html(url)

        # Extract ALL Brightcove credentials from the already-fetched soup.
        # This avoids a second HTTP round-trip inside get_brightcove_url() which
        # was returning None because BFI's page differs between a cached/first
        # fetch and a subsequent bare requests.get().
        account_id = ""
        player_id = "default"

        video_tag = (
            soup.find("video-js", attrs={PLAYER_ID_ATTR: True}) or
            soup.find("video", attrs={PLAYER_ID_ATTR: True}) or
            soup.find(True, attrs={PLAYER_ID_ATTR: True, PLAYER_ACCOUNT_ATTR: True})
        )
        if video_tag:
            account_id = video_tag.get(PLAYER_ACCOUNT_ATTR, "")
            player_id = video_tag.get(PLAYER_PLAYER_ATTR, "default")
            if not video_id:
                video_id = video_tag.get(PLAYER_ID_ATTR, "")
        elif not video_id:
            # Fallback for target-based lookup (e.g. Kermode Introduces)
            el = soup.find(id=target) if target else soup.find(True, attrs={PLAYER_ID_ATTR: True})
            if el:
                video_id = el.get(PLAYER_ID_ATTR, "")

        # data-account and data-player are injected by JavaScript so they may be
        # absent from static HTML. Fall back to BFI's known Brightcove credentials.
        if not account_id:
            account_id = bfis.BFI_BRIGHTCOVE_ACCOUNT_ID
        if player_id == "default":
            player_id = bfis.BFI_BRIGHTCOVE_PLAYER_ID

        # For subscriber pages, the video-js data attributes may point at the wrong
        # Brightcove account (6057949427001 instead of the subscriber account
        # 6057940601001). The <script> tags are the authoritative source — parse
        # them to get the correct account ID, player ID, and actual video ID.
        if "/subscription/" in url:
            sub_account, sub_player, sub_video = bfis.extract_subscriber_credentials(soup)
            if sub_account and sub_video:
                account_id = sub_account
                player_id = sub_player
                video_id = sub_video
                logger.debug("play_film: subscriber override: account=%s player=%s video=%s",
                             account_id, player_id, video_id)

    logger.debug("play_film: video_id=%s account_id=%s player_id=%s", video_id, account_id, player_id)
    if video_id:
        if bfis.RECENT_SAVED and not explicit_account:
            bfis.recents.append((url, video_id))
        stream = bfis.get_stream_info(video_id, account_id=account_id, player_id=player_id, page_url=url)
        logger.debug("play_film: stream=%s", stream)
        if stream:
            stream_url = stream["url"]
            manifest_type = stream.get("manifest_type", "hls")
            license_url = stream.get("license_url", "")
            policy_key = stream.get("policy_key", "")

            list_item = ListItem(path=stream_url)

            width = stream.get("width", 0)
            height = stream.get("height", 0)
            if width and height:
                list_item.addStreamInfo("video", {
                    "width": width,
                    "height": height,
                    "aspect": float(width) / float(height),
                })

            if manifest_type == "mpd":
                # DASH + Widevine DRM — requires inputstream.adaptive and Widevine CDM
                list_item.setProperty("inputstream", "inputstream.adaptive")
                list_item.setProperty("inputstream.adaptive.manifest_type", "mpd")
                list_item.setMimeType("application/dash+xml")
                list_item.setContentLookup(False)
                if license_url:
                    # licence_key format: url|request_headers|post_data|response
                    headers = "Content-Type=application%2Foctet-stream"
                    if policy_key:
                        headers += "&BCOV-Policy={}".format(policy_key)
                    list_item.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
                    list_item.setProperty(
                        "inputstream.adaptive.license_key",
                        "{}|{}|R{{SSM}}|".format(license_url, headers))
            elif manifest_type == "hls":
                list_item.setMimeType("application/x-mpegURL")
                list_item.setContentLookup(False)

            xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
            xbmcplugin.setResolvedUrl(plugin.handle, True, list_item)


@plugin.route('/search')
def search():
    # type: () -> Optional[bool]
    """Search the archive"""
    query = get_arg("q")
    offset = int(get_arg("offset", 0))
    # remove saved search item
    if bool(get_arg("delete", False)):
        bfis.searches.remove(query)
        xbmc.executebuiltin("Container.Refresh()")
        return True
    # View saved search menu
    if bool(get_arg("menu", False)):
        add_menu_item(search, "[{}]".format(ku.localize(32016)), args={"new": True})  # [New Search]
        for item in bfis.searches.retrieve():
            add_menu_item(search, item, args={"q": item})
        xbmcplugin.setPluginCategory(plugin.handle, ku.localize(32007))  # Search
        xbmcplugin.endOfDirectory(plugin.handle)
        return True
    # look-up
    if bool(get_arg("new", False)):
        query = ku.user_input()
        if not query:
            return False
        if bfis.SEARCH_SAVED:
            bfis.searches.append(query)
    # process results
    search_url = bfis.get_search_url(query, offset)
    data = bfis.get_json(search_url)
    parse_search_results(data, query, offset)
    xbmcplugin.setPluginCategory(plugin.handle, "{} '{}'".format(ku.localize(32007), bfis.query_decode(query)))
    xbmcplugin.setContent(plugin.handle, "videos")
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_GENRE)
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_DURATION)
    xbmcplugin.endOfDirectory(plugin.handle)


@plugin.route("/login")
def login():
    # type: () -> None
    """Sign in to BFI+ using credentials stored in addon settings.

    Called from Settings > Account > Sign In, or from the main menu when the
    user taps the [Sign In] prompt item.
    """
    email, password = bfi_auth.get_credentials()
    if not email or not password:
        ku.notification(
            ADDON_NAME,
            ku.localize(32033),  # "Enter your email address and password in Settings..."
            time=6000
        )
        ku.show_settings()
        return
    success, message = bfi_auth.login(email, password)
    ku.notification(ADDON_NAME, message, time=5000)
    if success:
        xbmc.executebuiltin("Container.Refresh()")


@plugin.route("/logout")
def logout():
    # type: () -> None
    """Sign out of BFI+."""
    bfi_auth.logout()
    ku.notification(ADDON_NAME, ku.localize(32036), time=4000)  # "Signed out"
    xbmc.executebuiltin("Container.Refresh()")


def run():
    plugin.run()
