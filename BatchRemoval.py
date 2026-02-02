#!/usr/bin/env python3
"""
**BatchRemoval.py**
Edited: January 2026
Created by: Prajeet (DDoS Response Team)

Batch update engine for blackhole records (description, auto-close time, ticket association, close).
Provides individual POST operations via view_details_html and set_* methods, plus a high-performance
batch_post_views method that uses PlaywrightClient connection pooling to reuse a single request context
across many operations. Accepts optional PlaywrightConfig for credential/state sharing.
"""
from __future__ import annotations
import os
import sys
import logging
from typing import Dict, Any, Optional, List, Tuple, Callable

logger = logging.getLogger(__name__)
import concurrent.futures
import threading
from PlayWrightUtil import build_request_kwargs, suppress_cleanup_warning, PlaywrightConfig, PlaywrightClient

class BatchRemovalError(RuntimeError):
    pass

class BatchRemoval:
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
        
        self.client: Optional[PlaywrightClient] = None

    def _require_state(self):
        if not self.storage_state:
            raise BatchRemovalError("No storage_state. Please log in first.")

    def _context_kwargs(self) -> Dict[str, Any]:
        return build_request_kwargs(
            self.base_url,
            storage_state=self.storage_state,
            verify_ssl=self.verify_ssl,
            http_user=os.environ.get("BH_HTTP_USER") or "",
            http_pass=os.environ.get("BH_HTTP_PASS") or "",
        )

    def _post_view(self, id_value: str, form: Dict[str, str]) -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright
        self._require_state()
        try:
            with sync_playwright() as pw:
                req = pw.request.new_context(**self._context_kwargs())
                try:
                    resp = req.post("view.cgi", params={"id": id_value}, form=form, timeout=30000)
                    status = int(resp.status or 0)
                    text = resp.text() or ""
                    ok = 200 <= status < 400
                    return {"success": ok, "status": status, "text": text}
                except Exception as e:
                    print(f"Error during POST to view.cgi for ID {id_value}: {e}", file=sys.stderr)
                    return {"success": False, "status": 0, "text": str(e)}
                finally:
                    try:
                        req.dispose()
                    except Exception as e:
                        if not suppress_cleanup_warning(e):
                            print(f"Warning: Failed to dispose request context: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Playwright error in _post_view: {e}", file=sys.stderr)
            return {"success": False, "status": 0, "text": str(e)}

    def view_details_html(self, blackhole_id: str) -> str:
        from playwright.sync_api import sync_playwright
        self._require_state()
        try:
            with sync_playwright() as pw:
                req = pw.request.new_context(**self._context_kwargs())
                try:
                    resp = req.get("view.cgi", params={"id": blackhole_id}, timeout=30000)
                    status = int(resp.status or 0)
                    if status == 401:
                        raise BatchRemovalError("GET view.cgi failed: 401 (check HTTP credentials)")
                    if status >= 400:
                        raise BatchRemovalError(f"GET view.cgi failed: {resp.status}")
                    return resp.text() or ""
                except Exception as e:
                    print(f"Error during GET view.cgi for ID {blackhole_id}: {e}", file=sys.stderr)
                    raise
                finally:
                    try:
                        req.dispose()
                    except Exception as e:
                        print(f"Warning: Failed to dispose request context: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Playwright error in view_details_html: {e}", file=sys.stderr)
            raise

    def set_description(self, blackhole_id: str, description: str) -> Dict[str, Any]:
        return self._post_view(blackhole_id, {
            "id": blackhole_id,
            "action": "description",
            "description": description,
            "Set": "Set",
        })

    def set_autoclose(self, blackhole_id: str, close_text: str) -> Dict[str, Any]:
        # blank = No Auto-close
        return self._post_view(blackhole_id, {
            "id": blackhole_id,
            "action": "autoclose",
            "close_text": close_text,  # "" means remove auto-close
            "Set auto-close time": "Set auto-close time",
        })

    def associate_ticket(self, blackhole_id: str, ticket_system: str, ticket_number: str) -> Dict[str, Any]:
        return self._post_view(blackhole_id, {
            "id": blackhole_id,
            "action": "ticket",
            "ticket_system": ticket_system,
            "ticket_number": ticket_number,
            "Associate with ticket": "Associate with ticket",
        })

    def close_now(self, blackhole_id: str) -> Dict[str, Any]:
        return self._post_view(blackhole_id, {
            "id": blackhole_id,
            "action": "close",
            "Close Now": "Close Now",
        })

    def batch_post_views(
        self,
        operations: List[Tuple[str, Dict[str, str]]],
        max_workers: int = 5,
        timeout: int = 30000,
        abort_event: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        diagnostics_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform many POST view.cgi operations efficiently using a pooled request context.

        operations: list of (blackhole_id, form_dict)
        Returns list of results with keys: id, success, status, text
        """
        if not operations:
            return []

        results: List[Dict[str, Any]] = []
        total_ops = len(operations)
        processed = 0

        def emit_diag(msg: str) -> None:
            if diagnostics_callback:
                try:
                    diagnostics_callback(f"UPDATE[{id(self)}] {msg}")
                except Exception:
                    logger.debug("Diagnostics callback failed", exc_info=True)

        emit_diag(f"batch start ops={total_ops} max_workers={max_workers}")

        # Use PlaywrightClient for pooled request context (reused across all operations)
        try:
            # Create or reuse a client from this instance
            if not self.client:
                if self.config:
                    self.client = PlaywrightClient(self.config)
                    emit_diag("client created from shared config")
                else:
                    # Fallback: create a temporary client from scratch
                    cfg = PlaywrightConfig(
                        base_url=self.base_url,
                        storage_state=self.storage_state,
                        verify_ssl=self.verify_ssl,
                        http_user=os.environ.get("BH_HTTP_USER") or "",
                        http_pass=os.environ.get("BH_HTTP_PASS") or "",
                    )
                    self.client = PlaywrightClient(cfg)
                    emit_diag("client created from fallback config")
            else:
                emit_diag("client reuse")

            def _do_op(item: Tuple[str, Dict[str, str]]) -> Dict[str, Any]:
                bh_id, form = item
                # Check abort signal before starting
                if abort_event and abort_event.is_set():
                    emit_diag(f"op skip id={bh_id} reason=abort")
                    return {"id": bh_id, "success": False, "status": 0, "text": "aborted"}
                try:
                    emit_diag(f"op start id={bh_id}")
                    # Use the pooled client instead of creating a new context each time
                    resp = self.client.post("view.cgi", params={"id": bh_id}, form=form, timeout=timeout)
                    status = int(resp.status or 0)
                    text = resp.text() or ""
                    ok = 200 <= status < 400
                    emit_diag(f"op done id={bh_id} status={status} success={ok}")
                    return {"id": bh_id, "success": ok, "status": status, "text": text}
                except Exception as e:
                    emit_diag(f"op error id={bh_id} error={e}")
                    return {"id": bh_id, "success": False, "status": 0, "text": str(e)}

            # Run with a thread pool but keep a single pooled request context
            max_workers = max(1, int(max_workers or 1))
            emit_diag(f"threadpool start max_workers={max_workers}")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exc:
                futures = {exc.submit(_do_op, op): op for op in operations}
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        res = fut.result()
                    except Exception as e:
                        op = futures.get(fut)
                        bh_id = op[0] if op else "?"
                        res = {"id": bh_id, "success": False, "status": 0, "text": str(e)}
                    results.append(res)
                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total_ops)
                        except Exception as cb_exc:
                            logger.debug("batch_post_views progress callback failed: %s", cb_exc)
            emit_diag(f"threadpool complete processed={processed}/{total_ops}")
        except Exception as e:
            # If client initialization failed, return failures for all
            for bh_id, _ in operations:
                results.append({"id": bh_id, "success": False, "status": 0, "text": str(e)})
            emit_diag(f"batch error {e}")

        return results

    def close(self) -> None:
        """Dispose of any pooled Playwright client resources."""
        if self.client:
            try:
                self.client.dispose()
            except Exception:
                logger.debug("Playwright client disposal raised", exc_info=True)
            finally:
                self.client = None
