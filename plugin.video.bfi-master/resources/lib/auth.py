# -*- coding: utf-8 -*-
"""BFI+ subscriber authentication

Handles email/password login against the BFI Player website (Drupal-based).
Session cookies are persisted to addon userdata so the user stays signed in
between Kodi sessions.

Login endpoint: POST https://player.bfi.org.uk/user/login?_format=json
  Body:   {"name": "<email>", "pass": "<password>"}
  200 OK  -> sets SESS* cookie + returns {"csrf_token": "...", "current_user": {...}}
  400     -> bad credentials
"""
__author__ = "fraser"

import json
import logging
import os

import requests
import xbmc
import xbmcvfs

from . import kodiutils as ku

logger = logging.getLogger(__name__)

BFI_LOGIN_URL = "https://player.bfi.org.uk/user/login?_format=json"
BFI_LOGOUT_URL = "https://player.bfi.org.uk/user/logout"

_SESSION_FILENAME = "session.json"
_ADDON_DATA_PATH = "special://userdata/addon_data/plugin.video.bfi/"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_credentials():
    # type: () -> tuple
    """Returns (email, password) from addon settings."""
    return ku.get_setting("bfi_email"), ku.get_setting("bfi_password")


def is_logged_in():
    # type: () -> bool
    """Returns True when a persisted session cookie exists."""
    data = _load_session()
    return bool(data and data.get("cookies"))


def get_session_cookies():
    # type: () -> dict
    """Returns stored session cookies, or an empty dict."""
    data = _load_session()
    return data.get("cookies", {}) if data else {}


def get_csrf_token():
    # type: () -> str
    """Returns stored CSRF token, or empty string."""
    data = _load_session()
    return data.get("csrf_token", "") if data else ""


def login(email, password):
    # type: (str, str) -> tuple
    """Attempt to sign in with *email* and *password*.

    Returns (success: bool, message: str).
    """
    if not email or not password:
        return False, ku.localize(32033)  # "Enter your email and password in Settings"

    logger.debug("auth.login: attempting login for %s", email)
    try:
        resp = requests.post(
            BFI_LOGIN_URL,
            json={"name": email, "pass": password},
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30,
        )
        logger.debug("auth.login: status %s", resp.status_code)

        if resp.status_code == 200:
            body = resp.json()
            _save_session({
                "email": email,
                "csrf_token": body.get("csrf_token", ""),
                "cookies": dict(resp.cookies),
            })
            return True, ku.localize(32034)  # "Signed in successfully"

        if resp.status_code == 400:
            logger.debug("auth.login: 400 body: %s", resp.text[:300])
            return False, ku.localize(32035)  # "Sign in failed..."

        logger.debug("auth.login: unexpected status %s", resp.status_code)
        return False, ku.localize(32035)

    except Exception as exc:
        logger.error("auth.login exception: %s", exc)
        return False, str(exc)


def logout():
    # type: () -> None
    """Clear the stored session (and optionally hit the logout endpoint)."""
    cookies = get_session_cookies()
    csrf = get_csrf_token()
    if cookies:
        try:
            requests.get(
                BFI_LOGOUT_URL,
                cookies=cookies,
                headers={"X-CSRF-Token": csrf} if csrf else {},
                timeout=10,
            )
        except Exception:
            pass  # best-effort; we always clear locally
    _clear_session()
    logger.debug("auth.logout: session cleared")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _session_path():
    # type: () -> str
    """Resolved path to the session JSON file on disk."""
    directory = xbmcvfs.translatePath(_ADDON_DATA_PATH)
    if not xbmcvfs.exists(directory):
        xbmcvfs.mkdirs(directory)
    return os.path.join(directory, _SESSION_FILENAME)


def _load_session():
    # type: () -> dict
    path = _session_path()
    try:
        if xbmcvfs.exists(path):
            f = xbmcvfs.File(path)
            raw = f.read()
            f.close()
            if raw:
                return json.loads(raw)
    except Exception as exc:
        logger.debug("auth._load_session error: %s", exc)
    return {}


def _save_session(data):
    # type: (dict) -> None
    path = _session_path()
    try:
        f = xbmcvfs.File(path, "w")
        f.write(json.dumps(data))
        f.close()
    except Exception as exc:
        logger.debug("auth._save_session error: %s", exc)


def _clear_session():
    # type: () -> None
    path = _session_path()
    try:
        if xbmcvfs.exists(path):
            xbmcvfs.delete(path)
    except Exception as exc:
        logger.debug("auth._clear_session error: %s", exc)
