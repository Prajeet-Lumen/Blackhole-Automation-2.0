#!/usr/bin/env python3
"""
**AuthManager.py**
Edited: January 2026
Created by: Prajeet Pounraj

Authentication manager for Blackhole Automation using Playwright HTTP credentials.
Handles login via HTTP Basic/Digest auth, captures and manages session state, and
creates PlaywrightConfig for safe credential and storage_state sharing with other modules.
"""
from __future__ import annotations
import os
import sys
import logging
from typing import Optional, Dict, Any
from PlayWrightUtil import PlaywrightConfig

logger = logging.getLogger(__name__)

class AuthError(RuntimeError):
    """Authentication-related error."""

class AuthManager:
    """
    Manage HTTP credentials login for the Blackhole portal.
    Typical use:
    mgr = AuthManager()
    ok = mgr.login_with_http_credentials("user", "pass", headless=False)
    if ok:
        storage = mgr.get_storage_state()
        # pass `storage` to retrieval/create modules
    """

    def __init__(self, base_url: str = "https://blackhole.ip.qwest.net/") -> None:
        """Initialize base URL and state containers; configure TLS policy."""
        self.base_url: str = base_url.rstrip("/") + "/"
        self._pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.logged_in: bool = False
        self.logged_in_user: Optional[str] = None
        self.storage_state: Optional[Dict[str, Any]] = None
        self.pw_config: Optional[PlaywrightConfig] = None
        self.last_login_status_details: Optional[str] = None

        # TLS policy: ignore HTTPS errors by default unless overridden
        force_verify = os.environ.get("BH_FORCE_SSL_VERIFY") in ("1", "true", "True")
        self.verify_ssl: bool = bool(force_verify)

    # Internal helper
    def _ensure_playwright(self) -> None:
        """Lazy-import Playwright factory (context entered at call sites)."""
        if self._pw:
            return
        try:
            from playwright.sync_api import sync_playwright # type: ignore[import]
        except Exception as exc:
            logger.error("Playwright import failed. Install with 'pip install playwright' and run 'python -m playwright install'.")
            raise AuthError(
                "Playwright is required. Install with 'pip install playwright' and run 'python -m playwright install'."
            ) from exc
        self._pw = sync_playwright

    def login_with_http_credentials(self, username: str, password: str, headless: bool = False) -> bool:
        """
        Satisfy HTTP Basic/Digest auth using Playwright browser context `http_credentials`.
        On success: sets `logged_in`, `logged_in_user`, `storage_state`, returns True.
        On failure: closes resources and returns False.
        """
        self._ensure_playwright()

        # Wrap entire login in try/finally for guaranteed cleanup
        try:
            with self._pw() as _pw:
                self.browser = _pw.chromium.launch(headless=headless)
                self.context = self.browser.new_context(
                    http_credentials={"username": username, "password": password},
                    ignore_https_errors=(not self.verify_ssl),
                )
                self.page = self.context.new_page()
                try:
                    resp = self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=15000)
                    status = int(getattr(resp, "status", 0) or 0)

                    # Treat 2xx/3xx as success
                    if 200 <= status < 400:
                        try:
                            self.storage_state = self.context.storage_state()
                        except Exception as e:
                            logger.exception("Failed to capture storage_state: %s", e)
                            self.storage_state = None
                        # Create PlaywrightConfig for other modules
                        self.pw_config = PlaywrightConfig(
                            base_url=self.base_url,
                            storage_state=self.storage_state,
                            verify_ssl=self.verify_ssl,
                            http_user=os.environ.get("BH_HTTP_USER") or "",
                            http_pass=os.environ.get("BH_HTTP_PASS") or "",
                        )
                        self.logged_in = True
                        self.logged_in_user = username
                        self.last_login_status_details = f"status={status}; url={self.page.url!r}"
                        return True

                    # Failure path
                    self.last_login_status_details = f"status={status}; url={self.page.url!r}"
                    logger.warning("Login failed: %s", self.last_login_status_details)
                    return False

                except Exception as exc:
                    self.last_login_status_details = f"exception during login: {exc!r}"
                    logger.exception("Login exception: %s", exc)
                    return False

        finally:
            # Ensure cleanup even on exceptions
            self._cleanup_resources()

    def _cleanup_resources(self) -> None:
        """Close Playwright resources safely."""
        for resource_name in ["page", "context", "browser"]:
            resource = getattr(self, resource_name, None)
            if resource:
                try:
                    resource.close()
                except Exception as e:
                    msg = str(e)
                    if "Event loop is closed" in msg or "already stopped" in msg:
                        logger.debug("Suppressed Playwright cleanup warning for %s: %s", resource_name, msg)
                    else:
                        logger.warning("Failed to close %s: %s", resource_name, msg)
                setattr(self, resource_name, None)
        self._pw = None

    def get_storage_state(self) -> Optional[Dict[str, Any]]:
        """Return storage_state captured during login (if any)."""
        return self.storage_state

    def get_config(self) -> Optional[PlaywrightConfig]:
        """Return PlaywrightConfig for use by other modules (RetrievalEngine, CreateBlackhole, BatchRemoval)."""
        return self.pw_config

    def close(self) -> None:
        """Close any remaining Playwright resources."""
        self._cleanup_resources()
        self.logged_in = False
        self.logged_in_user = None
        self.pw_config = None
        # Do not clear storage_state; downstream modules rely on it.

# CLI for quick smoke-test. (TEMP..)
if __name__ == "__main__":
    print("Auth helper for blackhole automation (HTTP credentials only)")
    try:
        import getpass
        user = input("Username: ").strip()
        pwd = getpass.getpass("Password: ")
        mgr = AuthManager()
        ok = mgr.login_with_http_credentials(user, pwd, headless=False)
        print("HTTP auth result:", "OK" if ok else "Failed")
        print("Diagnostics:", mgr.last_login_status_details)
    except Exception as exc:
        print("Error during HTTP auth:", exc, file=sys.stderr)
    finally:
        print("Done.")
