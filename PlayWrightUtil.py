#!/usr/bin/env python3
"""
**PlayWrightUtil.py**
Edited: January 2026
Created by: Prajeet (DDoS Response Team)

Centralized Playwright utilities for request context creation, cleanup, and TLS/credential handling.
Provides PlaywrightConfig (immutable configuration object) and PlaywrightClient (pooled request
context manager) to reduce code duplication across RetrievalEngine, CreateBlackhole, and
BatchRemoval modules. Supports connection pooling for high-throughput batch operations.
"""
from __future__ import annotations
import os
import sys
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


class PlaywrightConfig:
    """Immutable configuration for Playwright requests.
    
    Created once at login (in AuthManager) and passed to all modules
    to avoid re-reading environment variables and duplicating credential logic.
    """
    def __init__(
        self,
        base_url: str,
        storage_state: Optional[Dict[str, Any]] = None,
        verify_ssl: bool = False,
        http_user: str = "",
        http_pass: str = "",
    ):
        self.base_url = base_url.rstrip("/") + "/" if base_url else "https://blackhole.ip.qwest.net/"
        self.storage_state = storage_state
        self.verify_ssl = verify_ssl
        self.http_user = http_user
        self.http_pass = http_pass

    def to_request_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs suitable for pw.request.new_context()."""
        return build_request_kwargs(
            self.base_url,
            storage_state=self.storage_state,
            verify_ssl=self.verify_ssl,
            http_user=self.http_user,
            http_pass=self.http_pass,
        )


@dataclass
class _RequestSession:
    manager: Any
    playwright: Any
    request: Any
    thread_id: int
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        try:
            if self.request:
                self.request.dispose()
        except Exception as exc:
            if not suppress_cleanup_warning(exc):
                logger.warning("Failed to dispose Playwright request context: %s", exc)
            else:
                logger.debug("Suppressed Playwright cleanup warning: %s", exc)
        finally:
            try:
                if self.manager:
                    self.manager.__exit__(None, None, None)
            except Exception as exc:
                if not suppress_cleanup_warning(exc):
                    logger.warning("Failed to close Playwright manager: %s", exc)
                else:
                    logger.debug("Suppressed Playwright manager warning: %s", exc)
            self.closed = True


class PlaywrightClient:
    """
    Manages Playwright instance and request contexts with optional pooling.
    
    For single-threaded use: creates one request context and reuses it.
    For multi-threaded use: creates one context per thread safely.
    For batch operations: reuses a single request context across many operations (faster).
    
    Usage:
        config = PlaywrightConfig(base_url, storage_state=state, http_user=u, http_pass=p)
        client = PlaywrightClient(config)
        resp = client.get("view.cgi", params={"id": "123"}, timeout=30000)
        text = resp.text()
        client.dispose()
    """
    def __init__(self, config: PlaywrightConfig):
        self.config = config
        self._factory = None
        self._lock = threading.Lock()
        self._thread_local = threading.local()
        self._sessions: List[_RequestSession] = []

    def _ensure_factory(self) -> None:
        if self._factory:
            return
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            logger.error("Playwright import failed. Install with 'pip install playwright'.")
            raise
        self._factory = sync_playwright

    def _create_session(self) -> _RequestSession:
        self._ensure_factory()
        manager = self._factory()
        try:
            playwright = manager.__enter__()
            kwargs = self.config.to_request_kwargs()
            request = playwright.request.new_context(**kwargs)
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            try:
                manager.__exit__(exc_type, exc_value, exc_tb)
            except Exception:
                logger.debug("Failed to unwind Playwright manager during session creation", exc_info=True)
            raise

        session = _RequestSession(manager=manager, playwright=playwright, request=request, thread_id=threading.get_ident())
        with self._lock:
            self._sessions.append(session)
        self._thread_local.session = session
        return session

    def _get_session(self) -> _RequestSession:
        session = getattr(self._thread_local, "session", None)
        if session and not session.closed:
            return session
        return self._create_session()

    def _get_request_context(self):
        session = self._get_session()
        return session.request

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30000):
        """Perform GET request using pooled context."""
        ctx = self._get_request_context()
        return ctx.get(path, params=params, timeout=timeout)

    def post(self, path: str, form: Optional[Dict[str, str]] = None, timeout: int = 30000):
        """Perform POST request using pooled context."""
        ctx = self._get_request_context()
        return ctx.post(path, form=form, timeout=timeout)

    def dispose(self):
        """Close the request context and Playwright instance."""
        sessions: List[_RequestSession]
        with self._lock:
            sessions = list(self._sessions)
            self._sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception:
                logger.debug("Session close raised", exc_info=True)
        if hasattr(self._thread_local, "session"):
            try:
                del self._thread_local.session
            except Exception:
                self._thread_local.session = None
        self._factory = None


def read_env_config() -> Dict[str, Any]:
    """Read shared environment configuration (TLS policy, HTTP credentials).
    Returns a dict with keys: verify_ssl, http_user, http_pass.
    """
    force_verify = os.environ.get("BH_FORCE_SSL_VERIFY") in ("1", "true", "True")
    return {
        "verify_ssl": bool(force_verify),
        "http_user": os.environ.get("BH_HTTP_USER") or "",
        "http_pass": os.environ.get("BH_HTTP_PASS") or "",
    }


def build_request_kwargs(
    base_url: str,
    storage_state: Optional[Dict[str, Any]] = None,
    verify_ssl: bool = False,
    http_user: str = "",
    http_pass: str = "",
) -> Dict[str, Any]:
    """Build keyword arguments dict for Playwright request context creation.
    
    Args:
        base_url: base URL for requests
        storage_state: Playwright storage state dict (optional)
        verify_ssl: whether to enforce SSL verification (default False for internal CA)
        http_user: HTTP Basic username (optional)
        http_pass: HTTP Basic password (optional)
    
    Returns:
        Dict suitable for `pw.request.new_context(**kwargs)`
    """
    kw: Dict[str, Any] = {
        "base_url": base_url,
        "ignore_https_errors": (not verify_ssl),
    }
    if storage_state:
        kw["storage_state"] = storage_state
    if http_user and http_pass:
        kw["http_credentials"] = {"username": http_user, "password": http_pass}
    return kw


def suppress_cleanup_warning(e: Exception) -> bool:
    """Return True if the exception is a harmless Playwright cleanup warning."""
    msg = str(e)
    return "Event loop is closed" in msg or "already stopped" in msg
