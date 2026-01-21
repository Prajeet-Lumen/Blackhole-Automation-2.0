#!/usr/bin/env python3
"""
**RetrievalEngine.py**
Edited: January 2026
Created by: Prajeet Pounraj

Retrieval engine for the internal Blackhole site using Playwright HTTP requests.
Supports structured HTTP retrieval with query filtering (by ID, ticket, IP, user, date, or active holes).
Parses returned HTML tables into structured dict format. Accepts optional PlaywrightConfig
for connection pooling and credential sharing; falls back to legacy env-var reading if not provided.
Endpoints: GET view.cgi, POST search.cgi.
"""
from __future__ import annotations
import os
import sys
import logging
import html as html_mod
import re
from typing import Any, Dict, List, Optional
from PlayWrightUtil import build_request_kwargs, suppress_cleanup_warning, PlaywrightConfig, PlaywrightClient

logger = logging.getLogger(__name__)

class RetrievalError(RuntimeError):
    """Raised when retrieval operations fail (network, auth, parsing, etc.)."""

class RetrievalEngine:
    """
    Structured & GUI retrieval of blackhole records.
    Public API:
    - retrieve(filters: dict) -> list[dict]
    - autofill_and_submit(filters: dict) -> None
    """

    def __init__(
        self,
        base_url: str = "https://blackhole.ip.qwest.net/",
        storage_state: Optional[Dict[str, Any]] = None,
        verify_ssl: Optional[bool] = None,
        headless_default: bool = True,
        config: Optional[PlaywrightConfig] = None,
    ) -> None:
        """Initialize base URL, storage_state, and TLS policy.
        
        If config is provided, use it instead of reading environment variables.
        Otherwise, fall back to legacy behavior (read env vars on each call).
        """
        # If a config object is provided, use it; otherwise use legacy init
        if config:
            self.config = config
            self.base_url = config.base_url
            self.storage_state = config.storage_state
            self.verify_ssl = config.verify_ssl
        else:
            self.base_url = base_url.rstrip("/") + "/"
            self.storage_state = storage_state
            force_verify = os.environ.get("BH_FORCE_SSL_VERIFY") in ("1", "true", "True")
            self.verify_ssl = False if (verify_ssl is None and not force_verify) else bool(verify_ssl or force_verify)
            self.config = None
        
        self.control_url = self.base_url + "control.html"
        self.headless_default = bool(headless_default)

    # -------------------- Payload Builders --------------------
    def _normalize_ticket_system(self, raw: str) -> str:
        val = (raw or "").strip()
        return "NTM-Remedy" if val.lower().replace("/", "-") == "ntm-remedy" else val

    def _build_payload(self, filters: Dict[str, Any]) -> (str, Dict[str, str]):
        endpoint = "search.cgi"
        payload: Dict[str, str] = {}

        if filters.get("blackhole_id_value"):
            endpoint = "view.cgi"
            payload = {"searchby": "blackhole_id", "id": str(filters.get("blackhole_id_value", ""))}
            return endpoint, payload

        if filters.get("ticket_number_value"):
            payload = {
                "searchby": "ticket",
                "ticket_system": self._normalize_ticket_system(str(filters.get("ticket_system", "NTM-Remedy"))),
                "ticket_number": str(filters.get("ticket_number_value", "")),
            }
            return endpoint, payload

        if filters.get("opened_by_value"):
            payload = {"searchby": "open_user", "user": str(filters.get("opened_by_value", ""))}
            return endpoint, payload

        if filters.get("ip_address_value") or filters.get("search_value"):
            payload = {
                "searchby": "ipaddress",
                "ipaddress": str(filters.get("ip_address_value") or filters.get("search_value", "")),
                "view": str(filters.get("view", "Both")),
            }
            return endpoint, payload

        if filters.get("month") or filters.get("year") or filters.get("open_date_value"):
            month = filters.get("month") or "01"
            month = self._month_to_number(month) if isinstance(month, str) else month
            year = str(filters.get("year") or "2020")
            payload = {"searchby": "open_date", "month": month, "year": year, "description": str(filters.get("description", ""))}
            return endpoint, payload

        payload = {"searchby": "active_holes"}
        return endpoint, payload

    # -------------------- Parsing --------------------
    def _parse_tables_in_page(self, page: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        tables = page.query_selector_all("table")
        br_re = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)

        for t in tables:
            trs = t.query_selector_all("tr")
            if not trs:
                continue

            # header detection
            header_idx: Optional[int] = None
            for i, tr in enumerate(trs):
                if tr.query_selector_all("th"):
                    header_idx = i
                    break

            start_idx = 0
            if header_idx is not None:
                ths = trs[header_idx].query_selector_all("th")
                headers = [(th.inner_text() or "").strip() for th in ths]
                if any(headers):
                    out.append({"header": True, "cells": headers})
                start_idx = header_idx + 1

            # rows
            for tr in trs[start_idx:]:
                tds = tr.query_selector_all("td")
                if not tds:
                    continue
                banner_text = " ".join([(td.inner_text() or "").strip() for td in tds]).lower()
                if ("logged in as" in banner_text) or ("blackhole route" in banner_text):
                    continue

                cells: List[str] = []
                for td in tds:
                    raw_html = td.inner_html() or ""
                    normalized_html = br_re.sub("\n", raw_html)
                    unescaped = html_mod.unescape(normalized_html)
                    text_only = re.sub(r"<[^>]+>", "", unescaped)
                    lines = [ln.strip() for ln in text_only.splitlines()]
                    final_text = "\n".join([ln for ln in lines if ln])
                    cells.append(final_text)

                if not any(cells):
                    continue
                out.append({"cells": cells})

        return out if out else [{"cells": []}]

    def _month_to_number(self, month_input: str) -> str:
        month_map = {
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12",
            "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06", "jul": "07",
            "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        }
        normalized = str(month_input).lower().strip()
        if normalized in month_map:
            return month_map[normalized]
        try:
            num = int(month_input)
            return f"{num:02d}"
        except ValueError:
            print(f"Warning: Invalid month input '{month_input}', defaulting to 01", file=sys.stderr)
            return "01"

    # -------------------- HTTP Fetch --------------------
    def _http_fetch_and_parse(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.storage_state:
            raise RetrievalError("No storage_state available for HTTP retrieval")

        endpoint, payload = self._build_payload(filters)
        from playwright.sync_api import sync_playwright

        browser = None
        try:
            with sync_playwright() as pw:
                kw = build_request_kwargs(
                    self.base_url,
                    storage_state=self.storage_state,
                    verify_ssl=self.verify_ssl,
                    http_user=os.environ.get("BH_HTTP_USER") or "",
                    http_pass=os.environ.get("BH_HTTP_PASS") or "",
                )
                req = pw.request.new_context(**kw)
                resp = req.get(endpoint, params=payload, timeout=30000) if endpoint == "view.cgi" else req.post(endpoint, form=payload, timeout=30000)
                status = int(resp.status or 0)

                if status == 401:
                    raise RetrievalError("HTTP 401 (Playwright request): credentials missing/invalid")
                if status >= 400:
                    raise RetrievalError(f"HTTP search returned status {status} (Playwright request)")

                html = resp.text()
                browser = pw.chromium.launch(headless=True)
                ctx = browser.new_context(ignore_https_errors=(not self.verify_ssl))
                page = ctx.new_page()
                page.set_content(html)
                rows = self._parse_tables_in_page(page)

                # Cleanup
                try:
                    page.close()
                    ctx.close()
                except Exception as e:
                    if not suppress_cleanup_warning(e):
                        logger.warning("Failed to close page/context: %s", e)
                    else:
                        logger.debug("Suppressed Playwright cleanup warning: %s", e)
                return rows

        except Exception as exc:
            logger.exception("Retrieval error: %s", exc)
            raise RetrievalError(f"Retrieval failed: {exc}") from exc
        finally:
            if browser:
                try:
                    browser.close()
                except Exception as e:
                    if not suppress_cleanup_warning(e):
                        logger.warning("Failed to close browser: %s", e)
                    else:
                        logger.debug("Suppressed Playwright cleanup warning: %s", e)

    # -------------------- Public API --------------------
    def retrieve(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._http_fetch_and_parse(filters)
    # NOTE: GUI autofill/browser flow removed. (The browser-based helper has been removed.)
