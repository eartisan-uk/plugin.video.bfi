# -*- coding: utf-8 -*-

import logging
import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

logger = logging.getLogger(__name__)

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo("path")
ADDON_NAME = ADDON.getAddonInfo("name")
MEDIA_URI = os.path.join(ADDON_PATH, "resources", "media")


def art(domain, image):
    if "src" not in image:
        # Plain string URL (e.g. from og:image meta tag)
        return {
            "thumb": "{}{}".format(domain, image),
            "fanart": "{}{}".format(domain, image),
            "poster": "{}{}".format(domain, image)
        }
    # Film cards use data-img-800/960/1440; collection cards use data-img-200/285/344.
    # Fall back through all sizes so both card types get a usable image.
    thumb = (image.get("data-img-800") or
             image.get("data-img-480") or
             image.get("data-img-344") or
             image.get("data-img-285") or
             image.get("data-img-200") or "")
    fanart = (image.get("data-img-1440") or
              image.get("data-img-960") or
              image.get("data-img-800") or
              image.get("data-img-344") or "")
    poster = (image.get("data-img-960") or
              image.get("data-img-344") or
              image.get("data-img-285") or "")
    return {
        "thumb": "{}{}".format(domain, thumb),
        "fanart": "{}{}".format(domain, fanart),
        "poster": "{}{}".format(domain, poster)
    }


def icon(image):
    # type (str) -> dict
    """Creates the application folder icon info for main menu items"""
    return {"icon": os.path.join(MEDIA_URI, image)}


def user_input():
    keyboard = xbmc.Keyboard("", "{} {}".format(localize(32007), ADDON_NAME))  # Search
    keyboard.doModal()
    if keyboard.isConfirmed():
        return keyboard.getText()
    return False


def confirm():
    return xbmcgui.Dialog().yesno("BFI Player", localize(32023))  # Are you sure?


def notification(header, message, time=5000, image=ADDON.getAddonInfo("icon"), sound=True):
    xbmcgui.Dialog().notification(header, message, image, time, sound)


def translate_path(path):
    # xbmc.translatePath removed in Kodi 19; use xbmcvfs.translatePath
    return xbmcvfs.translatePath(path)


def show_settings():
    ADDON.openSettings()


def get_setting(setting):
    return ADDON.getSetting(setting).strip()


def set_setting(setting, value):
    ADDON.setSetting(setting, str(value))


def get_setting_as_bool(setting):
    # type (str) -> bool
    return get_setting(setting).lower() == "true"


def get_setting_as_float(setting):
    # type (str) -> float
    try:
        return float(get_setting(setting))
    except ValueError:
        return 0


def get_setting_as_int(setting):
    # type (str) -> int
    try:
        return int(get_setting_as_float(setting))
    except ValueError:
        return 0


def localize(string_id):
    # type (str) -> str
    return ADDON.getLocalizedString(string_id)
