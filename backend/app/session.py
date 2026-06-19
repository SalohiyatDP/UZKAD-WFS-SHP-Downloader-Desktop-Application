"""Session / authentication handling for the UZKAD WFS endpoint.

There are two ways the app obtains an authorised session:

1. **In-app portal session (preferred).** The Electron frontend opens a portal
   window at ``mulk.kadastr.uz`` (any ready portal link, e.g. a transaction
   details URL). The user signs in (OneID / ERI) if prompted — they may already
   be signed in in another window. Electron then captures the ``kadastr.uz``
   cookies and any ``Authorization`` bearer token used by the portal's API/WFS
   calls and POSTs them here (``set_session``). These are reused for WFS requests.

2. **Browser cookie auto-detection (fallback).** If no in-app session has been
   captured, ``browser_cookie3`` is used to read cookies for the WFS domain
   straight from an installed desktop browser.

The captured session is persisted to ``storage/session.json`` so it survives a
backend restart within the same work session.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Dict, List, Optional, Tuple

from . import config
from .logging_setup import get_logger

log = get_logger("session")

# --------------------------------------------------------------------------- #
# In-app captured session store (cookies + headers), thread-safe + persisted
# --------------------------------------------------------------------------- #
_LOCK = threading.Lock()
_SESSION: Dict[str, object] = {
    "cookies": {},      # {name: value}
    "headers": {},      # {header_name: value}, e.g. {"Authorization": "Bearer ..."}
    "source": None,     # "in-app" | "browser" | None
    "captured_at": None,
}


def _persist() -> None:
    try:
        config.SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.SESSION_FILE.open("w", encoding="utf-8") as fh:
            json.dump(_SESSION, fh)
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not persist session: %s", exc)


def _load_persisted() -> None:
    try:
        if config.SESSION_FILE.exists():
            with config.SESSION_FILE.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("cookies") is not None:
                _SESSION.update(data)
                log.info(
                    "Loaded persisted session (%s cookies) from %s",
                    len(_SESSION.get("cookies") or {}),
                    config.SESSION_FILE,
                )
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not load persisted session: %s", exc)


_load_persisted()


def set_session(
    cookies: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
    source: str = "in-app",
) -> Dict[str, object]:
    """Store cookies/headers captured by the in-app login window."""
    with _LOCK:
        _SESSION["cookies"] = dict(cookies or {})
        _SESSION["headers"] = {k: v for k, v in (headers or {}).items() if v}
        _SESSION["source"] = source
        _SESSION["captured_at"] = time.time()
        _persist()
    log.info(
        "Captured %s session: %s cookies, %s headers",
        source,
        len(_SESSION["cookies"]),
        len(_SESSION["headers"]),
    )
    return get_session_status()


def clear_session() -> None:
    with _LOCK:
        _SESSION["cookies"] = {}
        _SESSION["headers"] = {}
        _SESSION["source"] = None
        _SESSION["captured_at"] = None
        _persist()
    log.info("Session cleared")


def get_active_cookies() -> Dict[str, str]:
    """Return the cookies to use for WFS: in-app capture first, else browser."""
    with _LOCK:
        if _SESSION["cookies"]:
            return dict(_SESSION["cookies"])  # type: ignore[arg-type]
    cookies, _ = get_cookies_for_domain()
    return cookies


def get_active_headers() -> Dict[str, str]:
    with _LOCK:
        return dict(_SESSION["headers"])  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# browser_cookie3 fallback
# --------------------------------------------------------------------------- #
def _load_browser_cookie3():
    try:
        import browser_cookie3  # type: ignore

        return browser_cookie3
    except ImportError:
        log.warning(
            "browser_cookie3 not installed; browser cookie auto-detection "
            "disabled. Use the in-app login instead."
        )
        return None


_BROWSER_FUNCS = {
    "chrome": "chrome",
    "edge": "edge",
    "brave": "brave",
    "chromium": "chromium",
    "firefox": "firefox",
}


def get_cookies_for_domain(
    domain: str = config.SESSION_DOMAIN,
    preferred_browsers: Optional[List[str]] = None,
) -> Tuple[Dict[str, str], Optional[str]]:
    """Return ``({cookie_name: value}, browser_used)`` for ``domain``."""
    bc3 = _load_browser_cookie3()
    if bc3 is None:
        return {}, None

    browsers = preferred_browsers or config.SUPPORTED_BROWSERS
    for browser in browsers:
        func_name = _BROWSER_FUNCS.get(browser)
        if not func_name or not hasattr(bc3, func_name):
            continue
        try:
            cj = getattr(bc3, func_name)(domain_name=domain)
        except Exception as exc:  # noqa: BLE001 - locked DB, no browser, etc.
            log.debug("Cookie read from %s failed: %s", browser, exc)
            continue

        cookies = {c.name: c.value for c in cj if domain in (c.domain or "")}
        if cookies:
            log.info("Loaded %s cookies from %s for %s", len(cookies), browser, domain)
            return cookies, browser

    log.info("No cookies found for %s in any supported browser", domain)
    return {}, None


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def get_session_status() -> Dict[str, object]:
    """Status used by the UI session indicator."""
    with _LOCK:
        in_app_cookies = dict(_SESSION["cookies"])  # type: ignore[arg-type]
        in_app_headers = dict(_SESSION["headers"])  # type: ignore[arg-type]
        source = _SESSION["source"]

    if in_app_cookies or in_app_headers:
        return {
            "authenticated": True,
            "source": source or "in-app",
            "browser": None,
            "cookie_count": len(in_app_cookies),
            "has_token": bool(in_app_headers.get("Authorization")),
            "message": (
                f"Sessiya faol (ilova orqali): {len(in_app_cookies)} cookie"
                + (", auth token bor" if in_app_headers.get("Authorization") else "")
            ),
        }

    # Fall back to browser detection.
    cookies, browser = get_cookies_for_domain()
    if cookies:
        return {
            "authenticated": True,
            "source": "browser",
            "browser": browser,
            "cookie_count": len(cookies),
            "has_token": False,
            "message": f"Sessiya brauzerdan ({browser}): {len(cookies)} cookie",
        }

    return {
        "authenticated": False,
        "source": None,
        "browser": None,
        "cookie_count": 0,
        "has_token": False,
        "message": (
            "Tizimga kirilmagan. \"Portalni ochish\" orqali "
            "mulk.kadastr.uz portal havolasini oching va sessiyani import qiling."
        ),
    }


def cookie_header(cookies: Dict[str, str]) -> str:
    """Render cookies as an HTTP Cookie header string."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())
