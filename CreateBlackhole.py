#!/usr/bin/env python3
"""
**CreateBlackhole.py**
Created: December 2026
Edited: January 2026
Created by: Prajeet (DDoS Response Team)

Create blackholes via HTTP POST to new.cgi endpoint. Accepts optional PlaywrightConfig for
connection pooling and credential sharing; falls back to env-var reading if not provided.
Validates that ticket_number or autoclose_time is provided. Supports per-IP retry logic
with configurable timeout and retry count. Returns detailed results for each IP.
"""
from __future__ import annotations
import os
import sys
import time
from typing import Any, Dict, List, Optional
from PlayWrightUtil import build_request_kwargs, suppress_cleanup_warning, PlaywrightConfig

class CreateBlackholeError(RuntimeError):
    """Raised when create-blackhole HTTP operations fail."""

class BlackholeCreator:
    """Create blackholes via direct HTTP POST to new.cgi using Playwright Request context."""

    TIMEOUT_MS = 30000  # Centralized timeout
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self, base_url: str = "https://blackhole.ip.qwest.net/", storage_state: Optional[Dict[str, Any]] = None, config: Optional[PlaywrightConfig] = None) -> None:
        # If a config object is provided, use it; otherwise use legacy behavior
        if config:
            self.config = config
            self.base_url = config.base_url
            self.storage_state = config.storage_state
            self.verify_ssl = config.verify_ssl
        else:
            self.config = None
            self.base_url = base_url.rstrip("/") + "/"
            self.storage_state = storage_state
            self.verify_ssl = os.environ.get("BH_FORCE_SSL_VERIFY") in ("1", "true", "True")
        
        self.new_cgi_url = self.base_url + "new.cgi"

    def submit_blackholes_http(
        self,
        ip_list: List[str],
        ticket_number: str = "",
        autoclose_time: str = "",
        description: str = "",
        ticket_system: str = "NTM-Remedy",
    ) -> List[Dict[str, Any]]:
        if not ip_list:
            raise CreateBlackholeError("No IPs provided.")
        if not ticket_number and not autoclose_time:
            raise CreateBlackholeError("Either ticket_number or autoclose_time must be provided (blank = No Auto-close).")
        if not self.storage_state:
            raise CreateBlackholeError("No storage_state. Please log in first.")

        # Normalize description
        if not description and ticket_number:
            description = f"CASE #{ticket_number}"

        from playwright.sync_api import sync_playwright
        results: List[Dict[str, Any]] = []

        with sync_playwright() as pw:
            kw = build_request_kwargs(
                self.base_url,
                storage_state=self.storage_state,
                verify_ssl=self.verify_ssl,
                http_user=os.environ.get("BH_HTTP_USER") or "",
                http_pass=os.environ.get("BH_HTTP_PASS") or "",
            )
            req = pw.request.new_context(**kw)

            try:
                for ip in ip_list:
                    start = time.time()
                    result: Dict[str, Any] = {
                        "ip": ip,
                        "ticket_number": ticket_number,
                        "ticket_system": ticket_system,
                        "autoclose_time": autoclose_time,
                        "description": description,
                        "success": False,
                        "status": 0,
                        "message": "",
                        "response_time": 0.0,
                    }

                    attempt = 0
                    while attempt < self.MAX_RETRIES:
                        attempt += 1
                        try:
                            payload = {
                                "ipaddress": ip,
                                "ticket_system": ticket_system,
                                "ticket_number": ticket_number,
                                "autoclose_time": autoclose_time,
                                "description": description,
                            }
                            resp = req.post("new.cgi", form=payload, timeout=self.TIMEOUT_MS)
                            status = int(resp.status or 0)
                            result["status"] = status

                            if status == 401:
                                raise CreateBlackholeError("HTTP 401 (POST new.cgi): credentials missing/invalid")
                            if status >= 400:
                                raise CreateBlackholeError(f"HTTP POST returned status {status}")

                            text_lower = (resp.text() or "").lower()
                            if any(k in text_lower for k in ("successfully created", "blackhole created", "success")):
                                result["success"] = True
                                result["message"] = "Blackhole created successfully (POST)"
                            else:
                                result["success"] = True
                                result["message"] = "POST submitted (no error detected)"
                            break  # success, exit retry loop

                        except Exception as exc:
                            print(f"[Attempt {attempt}] POST error for IP {ip}: {exc}", file=sys.stderr)
                            result["message"] = f"POST error: {exc}"
                            if attempt < self.MAX_RETRIES:
                                print(f"Retrying in {self.RETRY_DELAY}s...", file=sys.stderr)
                                time.sleep(self.RETRY_DELAY)
                            else:
                                print(f"Max retries reached for IP {ip}. Marking as failed.", file=sys.stderr)
                                result["success"] = False
                                result["message"] = f"Failed after {self.MAX_RETRIES} attempts: {exc}"

                    result["response_time"] = round(time.time() - start, 2)
                    print(f"[Final] IP {ip} → success={result['success']} status={result['status']} message={result['message']}", file=sys.stderr)
                    results.append(result)

            finally:
                try:
                    req.dispose()  # Ensure request context cleanup
                except Exception as e:
                    if not suppress_cleanup_warning(e):
                        print(f"Warning: Failed to dispose request context: {e}", file=sys.stderr)
                    else:
                        pass

        return results
