"""Browser session / cookie extraction for the UZKAD WFS endpoint.

The user signs in to mulk.kadastr.uz in a normal browser (OneID + ERI). This
module reads the authenticated cookies for the session domain straight from the
browser cookie store, so the app never needs its own login window.

Uses the ``browser_cookie3`` library which supports Chrome / Edge / Brave /
Chromium / Firefox across Windows, macOS and Linux. If it is not installed or
no cookies are found, the functions degrade gracefully.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import config
from .logging_setup import get_logger

log = get_logger("session")


def _load_browser_cookie3():
    try:
        import browser_cookie3  # type: ignore

        return browser_cookie3
    except ImportError:
        log.warning(
            "browser_cookie3 not installed; cookie auto-detection disabled. "
            "Install with: pip install browser_cookie3"
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
    """Return ``({cookie_name: value}, browser_used)`` for ``domain``.

    Tries each supported browser in priority order and returns the first one
    that yields cookies for the domain.
    """
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


def get_session_status(
    domain: str = config.SESSION_DOMAIN,
) -> Dict[str, object]:
    """Lightweight status check used by the UI session indicator."""
    cookies, browser = get_cookies_for_domain(domain)
    authenticated = len(cookies) > 0
    if authenticated:
        message = f"Authenticated via {browser} ({len(cookies)} cookies)"
    else:
        message = (
            "Not signed in. Open https://mulk.kadastr.uz in Chrome and log in "
            "with OneID / ERI, then refresh."
        )
    return {
        "authenticated": authenticated,
        "browser": browser,
        "cookie_count": len(cookies),
        "message": message,
    }


def cookie_header(cookies: Dict[str, str]) -> str:
    """Render cookies as an HTTP Cookie header string."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())
