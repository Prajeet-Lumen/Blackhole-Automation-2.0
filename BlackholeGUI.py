#!/usr/bin/env python3
"""
**BlackholeGUI.py**
Edited: January 2026
Created by: Prajeet (DDoS Response Team)

Main Tkinter GUI controller for Blackhole Automation. Orchestrates login, retrieval, creation,
batch updates, and result export. Features include concurrent multi-IP operations with progress tracking,
inactivity-based auto-logout after 1 hour of no user activity, session logging, graceful shutdown,
and cooperative abort for long-running tasks. Supports CIDR-aware operations and dynamic UI resizing.
"""
from __future__ import annotations

import os
import csv
import time
import queue
import threading
import re
import signal
import sys
from typing import List, Optional, Callable, Any, Dict
import tkinter as tk
from tkinter import ttk, messagebox
import logging

# --- Local modules ---
try:
    from AuthManager import AuthManager
except Exception:
    AuthManager = None

try:
    import RetrievalEngine as retrieval_module
except Exception:
    retrieval_module = None

try:
    from CreateBlackhole import BlackholeCreator
except Exception:
    BlackholeCreator = None

try:
    from BatchRemoval import BatchRemoval
except Exception:
    BatchRemoval = None

# Logging utilities
try:
    from SessionLogger import SessionLogger, ensure_session_dir
except Exception:
    SessionLogger = None
    ensure_session_dir = None

# Logging to stderr for critical errors and diagnostics
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


# --------------------------
# Utilities
# --------------------------
def validate_ipv4(ip_str: str) -> bool:
    """Validate that a bare IP (no CIDR) is a valid IPv4 address.
    Returns True if valid IPv4 (4 octets, each 0-255), False otherwise.
    Rejects reserved/special IPs like 0.0.0.0, 8.8.8.8, 127.x.x.x, etc.
    """
    # Blocklist of reserved/special IPs that should not be processed
    BLOCKED_IPS = {
        "0.0.0.0",         # This network
        "8.8.8.8",         # Google DNS
        "8.8.4.4",         # Google DNS
        "1.1.1.1",         # Cloudflare DNS
        "1.0.0.1",         # Cloudflare DNS
        "9.9.9.9",         # Quad9 DNS
        "9.9.9.10",        # Quad9 DNS
        "4.2.2.1",         # Level3 DNS
        "4.2.2.2",         # Level3 DNS
        "208.67.222.222",  # OpenDNS
        "208.67.220.220",  # OpenDNS
        "127.0.0.1",       # Localhost
        "127.0.0.2",       # Localhost
        "255.255.255.255", # Broadcast
    }
    
    parts = ip_str.split(".")
    if len(parts) != 4:
        return False
    
    # Check if IP is in blocklist
    if ip_str in BLOCKED_IPS:
        return False
    
    # Check if IP starts with 127 (localhost range)
    if parts[0] == "127":
        return False
    
    try:
        for part in parts:
            if not part.isdigit():
                return False
            num = int(part)
            if num < 0 or num > 255:
                return False
        return True
    except (ValueError, AttributeError):
        return False


def parse_ip_text(text: str, auto_add_cidr: bool = True, validate: bool = True) -> List[str]:
    """Parse pasted IP text into a cleaned list of IP/CIDR strings.
    If validate=True, reject any IPs that don't match valid IPv4 format.
    """
    if not text:
        return []
    tokens: List[str] = []
    for line in text.splitlines():
        for part in line.split(","):
            tokens.extend(part.split())
    result: List[str] = []
    invalid: List[str] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        # Extract bare IP for validation
        bare_ip = token.split("/")[0].strip() if "/" in token else token
        if validate and not validate_ipv4(bare_ip):
            invalid.append(token)
            continue
        if auto_add_cidr and "/" not in token:
            token = f"{token}/32"
        result.append(token)
    if invalid:
        logger.warning(f"Skipped invalid IPv4 addresses: {invalid}")
    return result


def sanitize_ip_for_search(ip: str) -> str:
    """Strip CIDR if present and return bare IP (portal single-IP search expects no CIDR)."""
    if not ip:
        return ""
    return ip.split("/")[0].strip()


def get_ipv4_validation_error(text: str) -> Optional[str]:
    """Return a user-friendly error message if any IPs in text are invalid IPv4.
    Returns None if all IPs are valid.
    """
    if not text:
        return None
    tokens: List[str] = []
    for line in text.splitlines():
        for part in line.split(","):
            tokens.extend(part.split())
    invalid: List[str] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        bare_ip = token.split("/")[0].strip() if "/" in token else token
        if not validate_ipv4(bare_ip):
            invalid.append(token)
    if invalid:
        return f"Invalid IPv4 format: {', '.join(invalid[:5])}{'...' if len(invalid) > 5 else ''}"
    return None


def is_cidr(value: str) -> bool:
    """Return True if value looks like CIDR (e.g., '1.2.3.0/24')."""
    if not value or "/" not in value:
        return False
    parts = value.split("/")
    return len(parts) == 2 and parts[1].isdigit()


def now_stamp() -> str:
    """Return a filesystem-friendly timestamp."""
    return time.strftime("%Y%m%d_%H%M%S")


# --------------------------
# GUI
# --------------------------
class BlackholeGUI:
    """Main window controller for Blackhole Automation."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Blackhole Automation - GUI")
        # Install a global Tkinter exception handler for callback exceptions
        try:
            self.root.report_callback_exception = self._tk_exception_handler
        except Exception:
            logger.exception("Failed to install Tkinter callback exception handler")
        self.session_logger: Optional[SessionLogger] = None
        self.pw_config = None  # PlaywrightConfig created at login

        # Thread management for graceful shutdown
        self.shutdown_event = threading.Event()
        self.active_threads: List[threading.Thread] = []
        self.threads_lock = threading.Lock()
        # Inactivity / auto-logout
        self.last_activity_ts: float = time.time()
        self.inactivity_timeout_seconds: int = int(os.environ.get("BH_INACTIVITY_TIMEOUT", 3600))
        self._inactivity_thread: Optional[threading.Thread] = None
        self._inactivity_lock = threading.Lock()
        # Cooperative abort for long-running tasks (CREATE / UPDATE / RETRIEVE)
        self.abort_event = threading.Event()
        # Optional override for shutdown wait time (seconds) set per long job
        self._shutdown_wait_override: Optional[int] = None
        # Track progress: { task_name: { 'total': int, 'processed': int, 'aborted': bool } }
        self.task_progress: Dict[str, Dict[str, Any]] = {}
        self.progress_lock = threading.Lock()

        # Configure notebook tab style to make tabs taller
        style = ttk.Style()
        style.configure('TNotebook.Tab', padding=[20, 12])

        # Top-level layout (window-wide)
        self.mainframe = ttk.Frame(root, padding="8 8 8 8")
        self.mainframe.grid(column=0, row=0, sticky=("nsew"))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        # Authentication row
        top_row = ttk.Frame(self.mainframe)
        top_row.grid(column=0, row=0, sticky="ew")
        self.mainframe.columnconfigure(0, weight=1)
        ttk.Label(top_row, text="Authentication:").pack(side=tk.LEFT)
        self.login_button = ttk.Button(top_row, text="Log-in", command=self.on_login)
        self.login_button.pack(side=tk.RIGHT)
        self.abort_button = ttk.Button(top_row, text="Abort", command=self.on_abort, state=tk.DISABLED)
        self.abort_button.pack(side=tk.RIGHT, padx=(0, 6))
        self.quit_button = ttk.Button(top_row, text="Quit", command=self.on_quit)
        self.quit_button.pack(side=tk.RIGHT, padx=(0, 6))

        # Global IP input (applies to Create/Retrieve/Update)
        ttk.Separator(self.mainframe, orient=tk.HORIZONTAL).grid(column=0, row=1, sticky="ew", pady=(6, 6))
        ip_global = ttk.Frame(self.mainframe)
        ip_global.grid(column=0, row=2, sticky="nsew")
        self.mainframe.rowconfigure(2, weight=2)
        ip_global.columnconfigure(0, weight=1)
        ttk.Label(ip_global, text="Paste IPs (one-per-line or space-separated):").grid(column=0, row=0, sticky=tk.W, padx=6, pady=(0, 3))
        ttk.Label(ip_global, text="(/32 will be added to bare IPs)", foreground="gray").grid(column=0, row=1, sticky=tk.W, padx=6, pady=(0, 6))
        self.ip_text = tk.Text(ip_global, height=10, wrap=tk.WORD)
        self.ip_text.grid(column=0, row=2, sticky="nsew", padx=6, pady=6)
        ip_global.rowconfigure(2, weight=1)

        # Open Date (state variables)
        self.open_date_month_var = tk.StringVar(value="January")
        self.open_date_year_var = tk.StringVar(value=str(time.localtime().tm_year))

        # Notebook with three tabs (Create | Retrieve | Update)
        self.notebook = ttk.Notebook(self.mainframe)
        self.notebook.grid(column=0, row=3, sticky=("nsew"), pady=(8, 8))
        self.mainframe.rowconfigure(3, weight=3)

        # --- Create Tab ---
        self.tab_create = ttk.Frame(self.notebook, padding="12 12 12 12")
        self.notebook.add(self.tab_create, text="CREATE")
        self._build_create_tab()

        # --- Retrieve Tab ---
        self.tab_retrieve = ttk.Frame(self.notebook, padding="12 12 12 12")
        self.notebook.add(self.tab_retrieve, text="RETRIEVE")
        self._build_retrieve_tab()

        # --- Update Tab ---
        self.tab_update = ttk.Frame(self.notebook, padding="12 12 12 12")
        self.notebook.add(self.tab_update, text="UPDATE")
        self._build_update_tab()

        # Log / Status (below tabs)
        ttk.Separator(self.mainframe, orient=tk.HORIZONTAL).grid(column=0, row=4, sticky="ew", pady=(8, 8))
        log_frame = ttk.Frame(self.mainframe)
        log_frame.grid(column=0, row=5, sticky="nsew")
        self.mainframe.rowconfigure(5, weight=2)
        log_frame.columnconfigure(0, weight=1)
        ttk.Label(log_frame, text="Log / Status:").grid(column=0, row=0, sticky=tk.W, padx=6, pady=(0, 4))
        self.result_text = tk.Text(log_frame, height=14, wrap=tk.WORD, state=tk.DISABLED)
        self.result_text.grid(column=0, row=1, sticky="nsew", padx=6, pady=6)

        # Bottom status bar
        status_bar = ttk.Frame(self.mainframe)
        status_bar.grid(column=0, row=6, sticky="ew")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status_bar, textvariable=self.status_var).pack(side=tk.LEFT, padx=6)

        # State
        self.logged_in = False
        self.logged_in_user = None
        self.auth_manager = None
        self._table: Optional[ttk.Treeview] = None
        self._table_columns: List[str] = []
        self._table_rows_visible: List[List[str]] = []
        self._table_rows_full: List[List[str]] = []
        self.message_queue: queue.Queue = queue.Queue()

        # Queue pump
        self._check_queue()

    # --------------------------
    # Build Tabs
    # --------------------------
    def _build_create_tab(self) -> None:
        f = self.tab_create
        # Grid config for resize
        for c in range(0, 6):
            f.columnconfigure(c, weight=1)

        ttk.Label(f, text="CREATE", font=("Segoe UI", 12, "bold")).grid(column=0, row=0, sticky=tk.W, padx=6, pady=(0, 6))
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=6, sticky="ew", padx=6, pady=(0, 6))

        # Row for fields (compact horizontal grouping)
        ttk.Label(f, text="Ticket system:").grid(column=0, row=2, sticky=tk.W, padx=6, pady=6)
        self.ticket_system = ttk.Combobox(f, values=["NTM-Remedy", "Clarify", "Vantive"], state="readonly", width=18)
        self.ticket_system.set("NTM-Remedy")
        self.ticket_system.grid(column=1, row=2, sticky="ew", padx=6, pady=6)

        ttk.Label(f, text="Ticket number:").grid(column=2, row=2, sticky=tk.W, padx=6, pady=6)
        self.ticket_number_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.ticket_number_var).grid(column=3, row=2, sticky="ew", padx=6, pady=6)

        ttk.Label(f, text="Auto-close (blank = No Auto-close):").grid(column=0, row=3, sticky=tk.W, padx=6, pady=6)
        self.auto_close_var = tk.StringVar(value="+2d")
        ttk.Entry(f, textvariable=self.auto_close_var).grid(column=1, row=3, sticky="ew", padx=6, pady=6)

        ttk.Label(f, text="Description:").grid(column=2, row=3, sticky=tk.W, padx=6, pady=6)
        self.description_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.description_var).grid(column=3, row=3, sticky="ew", padx=6, pady=6)

        # Create button + status
        btn_frame = ttk.Frame(f)
        btn_frame.grid(column=0, row=4, columnspan=6, sticky="ew", padx=6, pady=(12, 6))
        btn_frame.columnconfigure(0, weight=0)
        btn_frame.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(btn_frame, text="Create Blackholes", command=self.on_create_http)
        self.run_button.grid(column=0, row=0, sticky=tk.W)
        self.create_status_var = tk.StringVar(value="Ready")
        ttk.Label(btn_frame, textvariable=self.create_status_var, foreground="gray").grid(column=1, row=0, sticky="w", padx=(12, 0))

    def _build_retrieve_tab(self) -> None:
        f = self.tab_retrieve
        # Grid config for resize
        for c in range(0, 8):
            f.columnconfigure(c, weight=1)
        f.rowconfigure(6, weight=2)  # results frame grows

        ttk.Label(f, text="RETRIEVE", font=("Segoe UI", 12, "bold")).grid(column=0, row=0, sticky=tk.W, padx=6, pady=(0, 6))
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=8, sticky="ew", padx=6, pady=(0, 6))

        # Controls row
        ttk.Label(f, text="Search by:").grid(column=0, row=2, sticky=tk.W, padx=6, pady=6)
        # NOTE: 'Display on Web (GUI)' feature removed.

        self.search_by = ttk.Combobox(
            f,
            values=["Blackhole ID #", "Ticket #", "Opened by", "IP Address", "Open Date", "Active Blackholes"],
            state="readonly",
            width=20,
        )
        self.search_by.set("IP Address")
        self.search_by.grid(column=2, row=2, sticky="ew", padx=6, pady=6)
        self.search_by.bind("<<ComboboxSelected>>", self._on_search_by_changed)

        # Single free-text field (used only for Blackhole ID #, Ticket #, Opened by)
        self.search_value_var = tk.StringVar()
        self.search_value_entry = ttk.Entry(f, textvariable=self.search_value_var)
        self.search_value_entry.grid(column=3, row=2, sticky="ew", padx=6, pady=6)

        # Month/Year (shown only for Open Date)
        self.open_date_month_label = ttk.Label(f, text="Month:")
        self.open_date_month = ttk.Combobox(
            f,
            values=[
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            ],
            state="readonly",
            textvariable=self.open_date_month_var,
            width=12,
        )

        self.open_date_year_label = ttk.Label(f, text="Year:")
        self.open_date_year = ttk.Combobox(
            f,
            values=[str(y) for y in range(2018, 2036)],
            state="readonly",
            textvariable=self.open_date_year_var,
            width=8,
        )

        # Retrieve button (status shown in global Log / Status area)
        self.retrieve_button = ttk.Button(f, text="Retrieve", command=self.on_retrieve)
        self.retrieve_button.grid(column=7, row=2, sticky="e", padx=6)

        # Results area
        ttk.Label(f, text="Results:").grid(column=0, row=4, sticky=tk.W, padx=6, pady=(6, 2))
        self.results_header = ttk.Label(f, text="", anchor="w", justify="left")
        self.results_header.grid(column=0, row=5, columnspan=8, sticky="ew", padx=6, pady=(0, 4))

        self.results_frame = ttk.Frame(f)
        self.results_frame.grid(column=0, row=6, columnspan=8, sticky="nsew", padx=6, pady=4)

        # Copy & Export row
        actions_row = ttk.Frame(f)
        actions_row.grid(column=0, row=7, columnspan=8, sticky="ew", padx=6, pady=(4, 0))
        actions_row.columnconfigure(0, weight=0)
        actions_row.columnconfigure(1, weight=0)
        actions_row.columnconfigure(2, weight=1)
        self.copy_button = ttk.Button(actions_row, text="Copy Selected", command=self.on_copy_selected)
        self.copy_button.grid(column=0, row=0, sticky=tk.W)
        self.export_button = ttk.Button(actions_row, text="Export Results (CSV)", command=self.on_export_results)
        self.export_button.grid(column=1, row=0, sticky=tk.W, padx=(8, 0))

        # Ensure correct initial visibility
        self._update_search_mode_ui(initial=True)

    def _build_update_tab(self) -> None:
        f = self.tab_update
        # Grid for resize
        for c in range(0, 6):
            f.columnconfigure(c, weight=1)

        ttk.Label(f, text="UPDATE", font=("Segoe UI", 12, "bold")).grid(column=0, row=0, sticky=tk.W, padx=6, pady=(0, 6))
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(column=0, row=1, columnspan=6, sticky="ew", padx=6, pady=(0, 6))

        # IDs row
        ttk.Label(f, text="Blackhole ID(s):").grid(column=0, row=2, sticky=tk.W, padx=6, pady=6)
        self.batch_ids_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.batch_ids_var).grid(column=1, row=2, sticky="ew", padx=6, pady=6)
        ttk.Button(f, text="Load from selection", command=self._batch_load_ids_from_table).grid(column=2, row=2, sticky="w", padx=6, pady=6)
        ttk.Button(f, text="Collect IDs from IPs", command=self.on_collect_ids_from_pasted_ips).grid(column=3, row=2, sticky="w", padx=6, pady=6)

        # Description row
        ttk.Label(f, text="Description:").grid(column=0, row=3, sticky=tk.W, padx=6, pady=6)
        self.batch_desc_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.batch_desc_var).grid(column=1, row=3, sticky="ew", padx=6, pady=6)
        ttk.Button(f, text="Set Description", command=self.on_batch_set_description).grid(column=2, row=3, sticky="w", padx=6, pady=6)

        # Auto-close row
        ttk.Label(f, text="Auto-close time (blank = No Auto-close):").grid(column=0, row=4, sticky=tk.W, padx=6, pady=6)
        self.batch_close_text_var = tk.StringVar(value="+2d")
        ttk.Entry(f, textvariable=self.batch_close_text_var).grid(column=1, row=4, sticky="ew", padx=6, pady=6)
        ttk.Button(f, text="Set Auto-close", command=self.on_batch_set_autoclose).grid(column=2, row=4, sticky="w", padx=6, pady=6)

        # Ticket row
        ttk.Label(f, text="Ticket system:").grid(column=0, row=5, sticky=tk.W, padx=6, pady=6)
        self.batch_ticket_sys_var = tk.StringVar(value="Clarify")
        ttk.Combobox(f, values=["NTM-Remedy", "Clarify", "Vantive"], state="readonly", textvariable=self.batch_ticket_sys_var, width=15).grid(column=1, row=5, sticky="w", padx=6, pady=6)
        ttk.Label(f, text="Ticket #").grid(column=2, row=5, sticky=tk.W, padx=6, pady=6)
        self.batch_ticket_num_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.batch_ticket_num_var).grid(column=3, row=5, sticky="ew", padx=6, pady=6)
        ttk.Button(f, text="Associate Ticket", command=self.on_batch_associate_ticket).grid(column=4, row=5, sticky="w", padx=6, pady=6)

        # Close Now row
        ttk.Button(f, text="Close Now (confirm)", command=self.on_batch_close_now).grid(column=0, row=6, sticky="w", padx=6, pady=(12, 6))

        ttk.Separator(f, orient=tk.HORIZONTAL).grid(column=0, row=7, columnspan=6, sticky="ew", padx=6, pady=(6, 6))

    # --------------------------
    # Queue pump
    # --------------------------
    def _check_queue(self) -> None:
        # Stop pumping queue if shutdown is signaled
        if self.shutdown_event.is_set():
            return
        
        try:
            while True:
                msg_type, msg_data = self.message_queue.get_nowait()
                if msg_type == "log":
                    try:
                        logger.info(msg_data)
                    except Exception:
                        pass
                    self.log(msg_data)
                elif msg_type == "error":
                    logger.error("Queued error: %s", msg_data)
                    self.log(msg_data)
                    try:
                        messagebox.showerror("Error", msg_data)
                    except Exception:
                        logger.exception("Failed to show error messagebox")
                elif msg_type == "info":
                    logger.info("Queued info: %s", msg_data)
                    self.log(msg_data)
                    try:
                        messagebox.showinfo("Info", msg_data)
                    except Exception:
                        logger.exception("Failed to show info messagebox")
                elif msg_type == "status":
                    try:
                        self.status_var.set(msg_data)
                    except Exception:
                        logger.exception("Failed to set status_var")
                elif msg_type == "call":
                    # Execute a callable on the main thread: (callable, args, kwargs)
                    try:
                        func, args, kwargs = msg_data
                        func(*args, **(kwargs or {}))
                    except Exception:
                        logger.exception("Error while executing queued UI call")
        except queue.Empty:
            pass
        
        # Reschedule queue pump unless shutdown is signaled
        if not self.shutdown_event.is_set():
            self.root.after(100, self._check_queue)

    # --------------------------
    # Inactivity tracking / auto-logout
    # --------------------------
    def touch_activity(self) -> None:
        """Record user activity to reset inactivity timeout.

        Call this at the start of any user action that should be considered "activity":
        create, update, retrieve, batch operations, etc.
        """
        try:
            with self._inactivity_lock:
                self.last_activity_ts = time.time()
        except Exception:
            logger.exception("Failed to touch activity timestamp")

    def _start_inactivity_watcher(self) -> None:
        """Start background thread that watches for inactivity and auto-logs out."""
        if self._inactivity_thread and self._inactivity_thread.is_alive():
            return

        def _loop():
            try:
                while not self.shutdown_event.is_set():
                    # Only check when logged in
                    if self.logged_in:
                        try:
                            with self._inactivity_lock:
                                last = self.last_activity_ts
                        except Exception:
                            last = time.time()
                        idle = time.time() - (last or time.time())
                        if idle >= self.inactivity_timeout_seconds:
                            try:
                                self._auto_logout(reason="inactivity timeout")
                            except Exception:
                                logger.exception("Auto-logout failed")
                            # After auto-logout stop checking until next login
                            break
                    # Sleep a short while
                    time.sleep(30)
            except Exception:
                logger.exception("Inactivity watcher thread crashed")

        self._inactivity_thread = threading.Thread(target=_loop, daemon=True)
        self._inactivity_thread.start()

    def _auto_logout(self, reason: str = "inactivity") -> None:
        """Perform automatic logout: abort work, close auth resources, close session log, notify user."""
        try:
            # Prevent re-entrancy
            if not self.logged_in:
                return

            self._append_session_log(f"[AUTO-LOGOUT] reason={reason}")

            # Signal cooperative abort to background workers
            try:
                self.abort_event.set()
            except Exception:
                pass

            # Close auth manager (Playwright resources)
            try:
                if self.auth_manager and hasattr(self.auth_manager, "close"):
                    self.auth_manager.close()
            except Exception:
                logger.exception("Error closing auth_manager during auto-logout")

            # Close session logger after writing a final message
            try:
                if self.session_logger:
                    try:
                        self.session_logger.append("[AUTO-LOGOUT] Session closed due to inactivity")
                    except Exception:
                        pass
                    try:
                        self.session_logger.close()
                    except Exception:
                        logger.exception("Failed to close session_logger during auto-logout")
                    self.session_logger = None
            except Exception:
                logger.exception("Error while handling session_logger during auto-logout")

            # Mark as logged out and clear user
            try:
                self.logged_in = False
                self.logged_in_user = None
            except Exception:
                pass

            # Notify user via message queue (will show messagebox on main thread)
            try:
                self.message_queue.put(("info", "Session timed out due to inactivity. Please log in again."))
            except Exception:
                try:
                    self._call_in_main(messagebox.showinfo, "Session", "Session timed out due to inactivity. Please log in again.")
                except Exception:
                    pass

            # Restore UI to logged-out state (enable login button)
            try:
                self._call_in_main(self.login_button.config, state=tk.NORMAL)
                self._call_in_main(self.run_button.config, state=tk.DISABLED)
                self._call_in_main(self.retrieve_button.config, state=tk.DISABLED)
                self._call_in_main(self.abort_button.config, state=tk.DISABLED)
            except Exception:
                logger.exception("Failed to update UI buttons during auto-logout")

            logger.info("Auto-logout completed due to %s", reason)
        except Exception:
            logger.exception("Unhandled error in auto-logout")

    def _call_in_main(self, func: Callable, *args: Any, **kwargs: Any) -> None:
        """Enqueue a callable to be executed on the Tk main thread via the message queue."""
        try:
            self.message_queue.put(("call", (func, args, kwargs)))
        except Exception:
            logger.exception("Failed to enqueue UI call")

    def _tk_exception_handler(self, exc_type, exc_value, exc_tb) -> None:
        """Global Tkinter callback exception handler: logs and notifies the user."""
        try:
            import traceback

            tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            logger.error("Unhandled Tkinter exception:\n%s", tb_text)
            try:
                messagebox.showerror("Application Error", f"An unexpected error occurred:\n{exc_value}")
            except Exception:
                logger.exception("Failed to show Tkinter exception messagebox")
        except Exception:
            logger.exception("Error in Tkinter exception handler")

    # --------------------------
    # Login
    # --------------------------
    def on_login(self) -> None:
        self._append_session_log("[START] Task=Login")
        if not AuthManager:
            messagebox.showerror("Error", "AuthManager not available")
            return
        self.login_button.config(state=tk.DISABLED)
        self.status_var.set("Connecting...")

        def do_login():
            try:
                creds = self._prompt_for_credentials()
                if not creds:
                    self.message_queue.put(("log", "Login cancelled"))
                    self.message_queue.put(("status", "Not connected"))
                    self._append_session_log("[FAIL] Task=Login reason=cancelled")
                    return
                auth_mgr = AuthManager(base_url="https://blackhole.ip.qwest.net/")
                self.auth_manager = auth_mgr
                self.message_queue.put(("log", "Attempting HTTP credentials login..."))
                ok = auth_mgr.login_with_http_credentials(creds["username"], creds["password"], headless=False)
                if ok:
                    self.logged_in = True
                    self.logged_in_user = auth_mgr.logged_in_user or creds.get("username")
                    # Get PlaywrightConfig from auth_mgr for use by other modules
                    self.pw_config = auth_mgr.get_config()
                    if SessionLogger:
                        self.session_logger = SessionLogger(self.logged_in_user)
                        self.session_logger.append(f"Session log initialized for {self.logged_in_user}")
                    # HTTP Basic for BatchRemoval / RetrievalEngine / CreateBlackhole
                    os.environ["BH_HTTP_USER"] = creds["username"]
                    os.environ["BH_HTTP_PASS"] = creds["password"]
                    self.message_queue.put(("status", "Connected"))
                    self.message_queue.put(("log", f"Login successful: {self.logged_in_user}"))
                    self._append_session_log("[OK] Task=Login")
                    # Record activity and start inactivity watcher
                    try:
                        self.touch_activity()
                        self._start_inactivity_watcher()
                    except Exception:
                        logger.exception("Failed to start inactivity watcher after login")
                else:
                    self.logged_in = False
                    details = getattr(auth_mgr, "last_login_status_details", "No details")
                    self.message_queue.put(("error", "Login failed."))
                    self.message_queue.put(("log", f"Login result: {details[:400]}"))
                    self.message_queue.put(("status", "Not connected"))
                    self._append_session_log(f"[FAIL] Task=Login details={details[:200]}")
            except Exception as e:
                self.logged_in = False
                self.message_queue.put(("error", f"Login error: {e}"))
                self.message_queue.put(("status", "Not connected"))
                self._append_session_log(f"[FAIL] Task=Login error={e}")
            finally:
                try:
                    self._call_in_main(self.login_button.config, state=tk.NORMAL)
                except Exception:
                    logger.exception("Failed to restore login button state")

        self._run_in_thread(do_login)

    def _prompt_for_credentials(self) -> Optional[Dict[str, str]]:
        dialog = tk.Toplevel(self.root)
        dialog.title("HTTP Credentials")
        dialog.geometry("340x160")
        dialog.transient(self.root)
        dialog.grab_set()
        creds: Dict[str, str] = {}
        ttk.Label(dialog, text="Username:").grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
        u = ttk.Entry(dialog, width=30)
        u.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(dialog, text="Password:").grid(row=1, column=0, sticky=tk.W, padx=6, pady=4)
        p = ttk.Entry(dialog, width=30, show="*")
        p.grid(row=1, column=1, sticky="ew", padx=6, pady=4)

        def ok():
            creds["username"] = u.get()
            creds["password"] = p.get()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        ttk.Button(dialog, text="OK", command=ok).grid(row=2, column=0, padx=6, pady=8, sticky="w")
        ttk.Button(dialog, text="Cancel", command=cancel).grid(row=2, column=1, padx=6, pady=8, sticky="e")
        dialog.columnconfigure(1, weight=1)
        self.root.wait_window(dialog)
        return creds if creds.get("username") else None

    # --------------------------
    # Retrieve
    # --------------------------
    def _show_open_date_controls(self, show: bool) -> None:
        """Show/hide Month/Year controls."""
        f = self.tab_retrieve
        if show:
            self.open_date_month_label.grid(column=4, row=2, sticky=tk.E, padx=6)
            self.open_date_month.grid(column=5, row=2, sticky="ew", padx=6)
            self.open_date_year_label.grid(column=4, row=3, sticky=tk.E, padx=6)
            self.open_date_year.grid(column=5, row=3, sticky="ew", padx=6)
        else:
            for w in (self.open_date_month_label, self.open_date_month, self.open_date_year_label, self.open_date_year):
                w.grid_remove()

    def _update_search_mode_ui(self, initial: bool = False) -> None:
        """Show/hide the free-text field vs Month/Year based on Search by."""
        sel = self.search_by.get().strip()
        # Free-text entry is used only for IDs, Ticket, Opened by
        use_text = sel in ("Blackhole ID #", "Ticket #", "Opened by")
        self.search_value_entry.grid_remove()
        if use_text:
            self.search_value_entry.grid(column=3, row=2, sticky="ew", padx=6)
        # Month/Year for Open Date
        self._show_open_date_controls(sel == "Open Date")
        # Nothing extra for IP Address or Active Blackholes

    def _on_search_by_changed(self, event: Optional[Any] = None) -> None:
        self._update_search_mode_ui()

    def on_retrieve(self) -> None:
        self._append_session_log("[START] Task=Retrieve")
        # Record user activity for inactivity timeout
        try:
            self.touch_activity()
        except Exception:
            logger.exception("Failed to touch activity on retrieve start")
        if not self.logged_in:
            messagebox.showerror("Not logged in", "Please log in first")
            self._append_session_log("[FAIL] Task=Retrieve reason=not_logged_in")
            return

        sel = self.search_by.get().strip()
        explicit = self.search_value_var.get().strip()
        ip_tokens = parse_ip_text(self.ip_text.get("1.0", tk.END), auto_add_cidr=False)

        # Update global status + disable button
        try:
            self.message_queue.put(("status", "Retrieving…"))
        except Exception:
            try:
                self._call_in_main(self.status_var.set, "Retrieving…")
            except Exception:
                pass
        self.retrieve_button.config(state=tk.DISABLED)
        
        # Enable abort button
        self.abort_event.clear()
        try:
            self.abort_button.config(state=tk.NORMAL)
        except Exception as e:
            logger.exception("Failed to enable abort button: %s", e)

        def do_retrieve():
            try:
                storage_state = self.auth_manager.get_storage_state() if self.auth_manager else None
                if not storage_state:
                    raise Exception("No authenticated session available. Please log in.")

                aggregated: List[dict] = []

                if sel == "IP Address":
                    # Multi-IP (and CIDR-aware) bidirectional retrieval using global IPs
                    ips_to_query = ip_tokens[:]
                    if not ips_to_query:
                        raise Exception("Paste IPs above to retrieve by IP Address.")
                    
                    # Bidirectional concurrent retrieval
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    
                    total = len(ips_to_query)
                    processed = 0
                    
                    # Track progress
                    with self.progress_lock:
                        self.task_progress['RETRIEVE'] = {'total': total, 'processed': 0, 'aborted': False}
                    
                    # Split IPs: first half processes top-down, second half bottom-up
                    mid = (total + 1) // 2
                    top_half = ips_to_query[:mid]
                    bottom_half = ips_to_query[mid:]
                    bottom_half_reversed = list(reversed(bottom_half))
                    all_ips = top_half + bottom_half_reversed
                    
                    def fetch_ip(ip: str) -> tuple[str, List[dict]]:
                        """Fetch results for one IP using independent engine."""
                        if self.abort_event.is_set():
                            return ip, []
                        try:
                            # Independent engine per thread (with config if available)
                            engine = retrieval_module.RetrievalEngine(storage_state=storage_state, verify_ssl=False, config=self.pw_config)
                            query_val = ip.strip() if is_cidr(ip) else sanitize_ip_for_search(ip)
                            query_msg = f"[Retrieve] Querying: {query_val}"
                            self.message_queue.put(("log", query_msg))
                            self._append_session_log(query_msg)  # Also log to session file
                            res = engine.retrieve({"ip_address_value": query_val, "view": "Both"})
                            return ip, res
                        except Exception as e:
                            logger.exception("Error retrieving IP %s: %s", ip, e)
                            self._append_session_log(f"[ERROR] Error retrieving {ip}: {e}")
                            return ip, []
                    
                    workers = min(16, max(1, (os.cpu_count() or 2) * 2))
                    
                    with ThreadPoolExecutor(max_workers=workers) as exc:
                        futures = {exc.submit(fetch_ip, ip): ip for ip in all_ips}
                        header_added = False
                        
                        for fut in as_completed(futures):
                            processed += 1
                            with self.progress_lock:
                                self.task_progress['RETRIEVE']['processed'] = processed
                            
                            # Update global status with progress
                            status_msg = f"Retrieving… ({processed}/{total})"
                            try:
                                self.message_queue.put(("status", status_msg))
                            except Exception:
                                self._call_in_main(self.status_var.set, status_msg)
                            
                            if self.abort_event.is_set():
                                with self.progress_lock:
                                    self.task_progress['RETRIEVE']['aborted'] = True
                                abort_msg = f"RETRIEVE aborted: {processed - 1}/{total} IPs processed"
                                self._append_session_log(f"[ABORT] {abort_msg}")
                                self.message_queue.put(("warning", abort_msg))
                                break
                            
                            try:
                                ip, res = fut.result()
                                if res:
                                    if header_added and (isinstance(res[0], dict) and res[0].get("header")):
                                        aggregated.extend(res[1:])  # skip header
                                    else:
                                        aggregated.extend(res)
                                        if isinstance(res[0], dict) and res[0].get("header"):
                                            header_added = True
                            except Exception as e:
                                logger.exception("Error processing IP result: %s", e)
                elif sel == "Ticket #":
                    engine = retrieval_module.RetrievalEngine(storage_state=storage_state, verify_ssl=False, config=self.pw_config)
                    aggregated = engine.retrieve({"ticket_number_value": explicit, "ticket_system": "NTM-Remedy"})
                elif sel == "Opened by":
                    engine = retrieval_module.RetrievalEngine(storage_state=storage_state, verify_ssl=False, config=self.pw_config)
                    aggregated = engine.retrieve({"opened_by_value": explicit or self.logged_in_user or ""})
                elif sel == "Blackhole ID #":
                    engine = retrieval_module.RetrievalEngine(storage_state=storage_state, verify_ssl=False, config=self.pw_config)
                    aggregated = engine.retrieve({"blackhole_id_value": explicit})
                elif sel == "Open Date":
                    engine = retrieval_module.RetrievalEngine(storage_state=storage_state, verify_ssl=False)
                    aggregated = engine.retrieve({"month": self.open_date_month_var.get(), "year": self.open_date_year_var.get()})
                else:  # Active Blackholes
                    engine = retrieval_module.RetrievalEngine(storage_state=storage_state, verify_ssl=False)
                    aggregated = engine.retrieve({"searchby": "active_holes"})

                self._on_retrieve_complete(aggregated, f"Retrieved via {sel}")
                self._append_session_log("[OK] Task=Retrieve mode=Structured")
            except Exception as e:
                self._on_retrieve_error(e, f"Retrieve via {sel}")
                self._append_session_log(f"[FAIL] Task=Retrieve error={e}")
            finally:
                try:
                    self.message_queue.put(("status", "Ready"))
                    self._call_in_main(self.retrieve_button.config, state=tk.NORMAL)
                    self._call_in_main(self.abort_button.config, state=tk.DISABLED)
                except Exception:
                    logger.exception("Failed to restore retrieve UI state")
                try:
                    self.abort_event.clear()
                except Exception:
                    pass

        self._run_in_thread(do_retrieve)

    def _on_retrieve_complete(self, results: List[dict], context: str) -> None:
        total = self._render_results_table(results)
        header_txt = (
            f"Session Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"User: {self.logged_in_user or 'unknown'}\n"
            f"Number of Results: {total}"
        )
        self.results_header.config(text=header_txt, justify="left")
        line = f"{context} \n rows={total}"
        self._append_session_log(line)
        self.log(line)

    def _on_retrieve_error(self, err: Exception, context: str) -> None:
        self.message_queue.put(("log", f"Retrieval failed: {err}"))
        self.message_queue.put(("error", f"Retrieval failed: {err}"))

    # --------------------------
    # Create (HTTP) — with per-IP progress
    # --------------------------
    def _set_create_status(self, text: str) -> None:
        """Thread-safe status label update for Create tab."""
        try:
            # Use global bottom status bar for all status updates so Log/Status shows progress
            try:
                self.message_queue.put(("status", text))
            except Exception:
                # Fallback to main-thread call if queueing fails
                if threading.current_thread() is threading.main_thread():
                    self.status_var.set(text)
                else:
                    self._call_in_main(self.status_var.set, text)
        except Exception:
            logger.exception("Failed to update create status")

    def on_create_http(self) -> None:
        self._append_session_log("[START] Task=CreateHTTP")
        # Record user activity for inactivity timeout
        try:
            self.touch_activity()
        except Exception:
            logger.exception("Failed to touch activity on create start")
        raw_ips = self.ip_text.get("1.0", tk.END)
        # Validate IPv4 format before parsing
        error = get_ipv4_validation_error(raw_ips)
        if error:
            messagebox.showerror("Invalid IP Format", error)
            self._append_session_log(f"[FAIL] Task=CreateHTTP reason=invalid_ipv4 details={error}")
            return
        ips = parse_ip_text(raw_ips, auto_add_cidr=True, validate=False)
        if not ips:
            messagebox.showerror("Input error", "Provide at least one IP/CIDR")
            self._append_session_log("[FAIL] Task=CreateHTTP reason=no_ips")
            return

        ticket_system = self.ticket_system.get().strip()
        ticket_number = self.ticket_number_var.get().strip()
        autoclose_time = self.auto_close_var.get().strip()  # blank = No Auto-close
        description = self.description_var.get().strip() or (f"CASE #{ticket_number}" if ticket_number else "")

        # Validation: at least ticket_number or (non-blank) autoclose_time
        if not ticket_number and not autoclose_time:
            messagebox.showerror("Missing inputs", "Either ticket number or auto-close time is required")
            self._append_session_log("[FAIL] Task=CreateHTTP reason=missing_inputs")
            return

        if not self.logged_in:
            messagebox.showerror("Not logged in", "Please log in first")
            self._append_session_log("[FAIL] Task=CreateHTTP reason=not_logged_in")
            return

        info = (
            f"Create request → IPs={ips} \n ticket_system={ticket_system} \n "
            f"ticket_number={ticket_number} \n autoclose_time={autoclose_time or 'BLANK'} \n description={description}"
        )
        self._append_session_log(info)
        self.log("Submitting HTTP create...")

        # Status label + disable button
        self._set_create_status("Creating…")
        self.run_button.config(state=tk.DISABLED)
        # Prepare abort flag and enable Abort button
        try:
            self.abort_event.clear()
            self.abort_button.config(state=tk.NORMAL)
        except Exception:
            pass

        # Warn for very large batches
        if len(ips) > 100:
            proceed = messagebox.askyesno(
                "Large Batch",
                f"You are about to create {len(ips)} IP(s). This may take a long time and impact system resources.\nProceed?",
            )
            if not proceed:
                self._append_session_log("[FAIL] Task=CreateHTTP reason=user_cancel_large_batch")
                self._set_create_status("Ready")
                self._call_in_main(self.run_button.config, state=tk.NORMAL)
                return
        def run_create():
            try:
                # Inform shutdown routine how long to wait: IPs * 2s
                try:
                    self._shutdown_wait_override = max(5, len(ips) * 2)
                except Exception:
                    self._shutdown_wait_override = None
                storage_state = self.auth_manager.get_storage_state() if self.auth_manager else None
                if not storage_state:
                    raise Exception("No authenticated session available.")
                creator = BlackholeCreator(storage_state=storage_state, config=self.pw_config)

                results: List[Dict[str, Any]] = []
                total = len(ips)
                # Track progress for this task
                with self.progress_lock:
                    self.task_progress['CREATE'] = {'total': total, 'processed': 0, 'aborted': False}

                for idx, ip in enumerate(ips, start=1):
                    # Per-IP start
                    if self.abort_event.is_set():
                        with self.progress_lock:
                            self.task_progress['CREATE']['aborted'] = True
                            self.task_progress['CREATE']['processed'] = idx - 1
                        abort_msg = f"CREATE aborted: {idx - 1}/{total} IPs processed → stopped at {ip}"
                        self._append_session_log(f"[ABORT] {abort_msg}")
                        self.message_queue.put(("warning", abort_msg))
                        break
                    self._set_create_status(f"Creating… ({idx}/{total}: {ip})")
                    self.message_queue.put(("log", f"[Create] {idx}/{total} Starting → {ip}"))
                    self._append_session_log(f"[Create] {idx}/{total} Starting → {ip}")

                    # Submit one IP (keeping CreateBlackhole’s HTTP session)
                    per_results = creator.submit_blackholes_http(
                        [ip], ticket_number, autoclose_time, description, ticket_system
                    )
                    # Append and log per-IP result
                    for r in per_results:
                        results.append(r)
                        with self.progress_lock:
                            self.task_progress['CREATE']['processed'] = idx
                        self._append_session_log(
                            f"Result → ip={r.get('ip')} \n success={r.get('success')} \n status={r.get('status')} \n "
                            f"message={r.get('message')} \n response_time={r.get('response_time')}s"
                        )
                        self.message_queue.put(("log", f"[Create] {idx}/{total} Finished (status={r.get('status')}, success={r.get('success')}) → {ip}"))

                successes = sum(1 for r in results if r.get("success"))
                self.log(f"Create (HTTP) complete. Total={total} Successes={successes} Failures={total - successes}")

                # Show compact grid summary
                rows = [
                    {
                        "#": str(i + 1),
                        "ID": "",
                        "Open Time (UTC)": "",
                        "Close Time (UTC)": "",
                        "Auto-Close Time (UTC)": r.get("autoclose_time", ""),
                        "IP": r.get("ip", ""),
                        "Ticket": r.get("ticket_number", ""),
                        "Description": description,
                    }
                    for i, r in enumerate(results)
                ]
                self._render_results_table(rows, fixed_columns=True)

                # Verify via Opened by user & CIDR-aware fallback
                self._append_session_log("[START] Task=CreateHTTP.Verify")
                try:
                    created_set = self._verify_creation_by_open_user(ips)
                    matched = [ip for ip in ips if ip in created_set]
                    missing = [ip for ip in ips if ip not in created_set]
                    self.log(f"Verification → matched={len(matched)} missing={len(missing)}")
                    self._append_session_log(f"[OK] Task=CreateHTTP.Verify matched={matched} missing={missing}")
                except Exception as ve:
                    self._append_session_log(f"[FAIL] Task=CreateHTTP.Verify error={ve}")
                    self.log(f"Verification error: {ve}")

                self._append_session_log(f"[OK] Task=CreateHTTP successes={successes}/{total}")
            except Exception as e:
                self.message_queue.put(("error", str(e)))
                self._append_session_log(f"[FAIL] Task=CreateHTTP error={e}")
            finally:
                # Clear override after job completes
                try:
                    self._shutdown_wait_override = None
                except Exception:
                    pass
                try:
                    self._set_create_status("Ready")
                    self._call_in_main(self.run_button.config, state=tk.NORMAL)
                    # disable Abort button and clear abort flag
                    try:
                        self._call_in_main(self.abort_button.config, state=tk.DISABLED)
                        self.abort_event.clear()
                    except Exception:
                        pass
                except Exception:
                    logger.exception("Failed to restore create UI state")

        self._run_in_thread(run_create)

    def _verify_creation_by_open_user(self, ips_submitted: List[str]) -> set:
        """
        Retrieve records opened by the logged-in user and cross-reference IPs.
        Fallback per search:
          - For CIDR entries, try a CIDR range search first
          - For single IPs, search by bare IP
        Returns a set of IPs confirmed present (strings as originally submitted).
        """
        storage_state = self.auth_manager.get_storage_state() if self.auth_manager else None
        if not storage_state:
            raise Exception("No authenticated session available.")
        engine = retrieval_module.RetrievalEngine(storage_state=storage_state, verify_ssl=False)

        # 1) Retrieve by Opened by (user)
        results = engine.retrieve({"opened_by_value": self.logged_in_user})
        header = []
        data = results
        if results and isinstance(results[0], dict) and results[0].get("header"):
            header = [c.strip().lower() for c in results[0].get("cells", [])]
            data = results[1:]

        ip_idx = header.index("ip") if "ip" in header else None
        found_ips: set = set()
        for r in data:
            cells = r.get("cells", []) if isinstance(r, dict) else (r if isinstance(r, list) else [])
            if ip_idx is not None and ip_idx < len(cells):
                candidate = cells[ip_idx].strip()
                if candidate:
                    found_ips.add(candidate)

        # 2) Fallback for missing submissions
        missing = [ip for ip in ips_submitted if ip not in found_ips]
        for ip in missing:
            if is_cidr(ip):
                # CIDR search first
                cidr_res = engine.retrieve({"ip_address_value": ip.strip(), "view": "Both"})
                if cidr_res and not (len(cidr_res) == 1 and not cidr_res[0].get("cells")):
                    found_ips.add(ip)
                    continue
            else:
                # Single-IP fallback (bare, no CIDR)
                bare = sanitize_ip_for_search(ip)
                ip_res = engine.retrieve({"ip_address_value": bare, "view": "Both"})
                if ip_res and not (len(ip_res) == 1 and not ip_res[0].get("cells")):
                    found_ips.add(ip)

        return found_ips

    # --------------------------
    # Update (Batch Update)
    # --------------------------
    def _batch_engine(self) -> Optional[BatchRemoval]:
        if not (self.logged_in and self.auth_manager and BatchRemoval):
            return None
        return BatchRemoval(storage_state=self.auth_manager.get_storage_state(), config=self.pw_config)

    def _get_batch_ids(self) -> List[str]:
        return [x.strip() for x in self.batch_ids_var.get().split(",") if x.strip()]

    def _batch_load_ids_from_table(self) -> None:
        """Load the current selection's ID column values into the entry; always overwrites."""
        if not self._table:
            messagebox.showinfo("Batch Update", "No table available.")
            return
        ids: List[str] = []
        for item_id in self._table.selection() or []:
            values = self._table.item(item_id)["values"]
            if len(values) >= 2 and str(values[1]).strip():
                ids.append(str(values[1]).strip())  # ID column
        if not ids:
            messagebox.showinfo("Batch Update", "Select one or more rows.")
            return
        self.batch_ids_var.set(",".join(ids))

    def on_batch_set_description(self) -> None:
        # Record user activity for inactivity timeout
        try:
            self.touch_activity()
        except Exception:
            logger.exception("Failed to touch activity on batch set description start")
        eng = self._batch_engine()
        ids = self._get_batch_ids()
        desc = self.batch_desc_var.get().strip()
        if not (eng and ids and desc):
            messagebox.showerror("Batch Update", "Provide BH ID(s) and Description.")
            return
        self._append_session_log("[START] Task=Batch.SetDescription ids=" + ",".join(ids))
        def worker():
            try:
                # Build operations
                total = len(ids)
                ops = [(bh, {"id": bh, "action": "description", "description": desc, "Set": "Set"}) for bh in ids]
                workers = min(8, max(1, (os.cpu_count() or 2)))
                # Track progress
                with self.progress_lock:
                    self.task_progress['UPDATE'] = {'total': total, 'processed': 0, 'aborted': False}
                results = eng.batch_post_views(ops, max_workers=workers, abort_event=self.abort_event)
                succ = sum(1 for r in results if r.get("success"))
                fail = len(results) - succ
                aborted = [r for r in results if str(r.get("text", "")).lower().find("abort") != -1 or r.get("text") == "aborted"]
                with self.progress_lock:
                    if aborted:
                        self.task_progress['UPDATE']['aborted'] = True
                    self.task_progress['UPDATE']['processed'] = len(results)
                for r in results:
                    self.log(f"SetDescription id={r.get('id')} status={r.get('status')} success={r.get('success')}")
                    self._append_session_log(f"SetDescription id={r.get('id')} status={r.get('status')} success={r.get('success')}")
                if aborted:
                    abort_msg = f"UPDATE aborted: {len(results)-len(aborted)}/{total} IDs processed"
                    self._append_session_log(f"[ABORT] {abort_msg}")
                    self.message_queue.put(("warning", abort_msg))
                else:
                    self._append_session_log(f"[OK] Task=Batch.SetDescription successes={succ} failures={fail}")
                    self.message_queue.put(("log", f"Batch description complete: {succ} success, {fail} failed"))
            except Exception as e:
                self._append_session_log(f"[FAIL] Task=Batch.SetDescription error={e}")
                self.message_queue.put(("error", str(e)))

            finally:
                try:
                    self._shutdown_wait_override = None
                except Exception:
                    pass
                try:
                    self._call_in_main(self.abort_button.config, state=tk.DISABLED)
                    self.abort_event.clear()
                except Exception:
                    pass

        # Prepare abort flag and enable Abort button
        try:
            self.abort_event.clear()
            self._call_in_main(self.abort_button.config, state=tk.NORMAL)
        except Exception:
            pass

        # Advise shutdown to wait for this batch: IDs * 2s
        try:
            self._shutdown_wait_override = max(5, len(ids) * 2)
        except Exception:
            self._shutdown_wait_override = None
        self._run_in_thread(worker)

    def on_batch_set_autoclose(self) -> None:
        # Record user activity for inactivity timeout
        try:
            self.touch_activity()
        except Exception:
            logger.exception("Failed to touch activity on batch set autoclose start")
        eng = self._batch_engine()
        ids = self._get_batch_ids()
        close_text = self.batch_close_text_var.get().strip()  # blank = No Auto-close
        if not (eng and ids):
            messagebox.showerror("Batch Update", "Provide BH ID(s).")
            return
        self._append_session_log("[START] Task=Batch.SetAutoclose ids=" + ",".join(ids))
        def worker():
            try:
                total = len(ids)
                ops = [(bh, {"id": bh, "action": "autoclose", "close_text": close_text, "Set auto-close time": "Set auto-close time"}) for bh in ids]
                workers = min(8, max(1, (os.cpu_count() or 2)))
                # Track progress
                with self.progress_lock:
                    self.task_progress['UPDATE'] = {'total': total, 'processed': 0, 'aborted': False}
                results = eng.batch_post_views(ops, max_workers=workers, abort_event=self.abort_event)
                succ = sum(1 for r in results if r.get("success"))
                fail = len(results) - succ
                aborted = [r for r in results if str(r.get("text", "")).lower().find("abort") != -1 or r.get("text") == "aborted"]
                with self.progress_lock:
                    if aborted:
                        self.task_progress['UPDATE']['aborted'] = True
                    self.task_progress['UPDATE']['processed'] = len(results)
                for r in results:
                    self.log(f"SetAutoclose id={r.get('id')} status={r.get('status')} success={r.get('success')}")
                    self._append_session_log(f"SetAutoclose id={r.get('id')} status={r.get('status')} success={r.get('success')}")
                if aborted:
                    abort_msg = f"UPDATE aborted: {len(results)-len(aborted)}/{total} IDs processed"
                    self._append_session_log(f"[ABORT] {abort_msg}")
                    self.message_queue.put(("warning", abort_msg))
                else:
                    self._append_session_log(f"[OK] Task=Batch.SetAutoclose successes={succ} failures={fail}")
                    self.message_queue.put(("log", f"Batch autoclose complete: {succ} success, {fail} failed"))
            except Exception as e:
                self._append_session_log(f"[FAIL] Task=Batch.SetAutoclose error={e}")
                self.message_queue.put(("error", str(e)))

            finally:
                try:
                    self._shutdown_wait_override = None
                except Exception:
                    pass
                try:
                    self._call_in_main(self.abort_button.config, state=tk.DISABLED)
                    self.abort_event.clear()
                except Exception:
                    pass

        try:
            self.abort_event.clear()
            self._call_in_main(self.abort_button.config, state=tk.NORMAL)
        except Exception:
            pass
        try:
            self._shutdown_wait_override = max(5, len(ids) * 2)
        except Exception:
            self._shutdown_wait_override = None
        self._run_in_thread(worker)

    def on_batch_associate_ticket(self) -> None:
        # Record user activity for inactivity timeout
        try:
            self.touch_activity()
        except Exception:
            logger.exception("Failed to touch activity on batch associate ticket start")
        eng = self._batch_engine()
        ids = self._get_batch_ids()
        sys = self.batch_ticket_sys_var.get().strip()
        num = self.batch_ticket_num_var.get().strip()
        if not (eng and ids and sys and num):
            messagebox.showerror("Batch Update", "Provide BH ID(s), Ticket system, and number.")
            return
        self._append_session_log("[START] Task=Batch.AssociateTicket ids=" + ",".join(ids))
        def worker():
            try:
                total = len(ids)
                ops = [(bh, {"id": bh, "action": "ticket", "ticket_system": sys, "ticket_number": num, "Associate with ticket": "Associate with ticket"}) for bh in ids]
                workers = min(8, max(1, (os.cpu_count() or 2)))
                # Track progress
                with self.progress_lock:
                    self.task_progress['UPDATE'] = {'total': total, 'processed': 0, 'aborted': False}
                results = eng.batch_post_views(ops, max_workers=workers, abort_event=self.abort_event)
                succ = sum(1 for r in results if r.get("success"))
                fail = len(results) - succ
                aborted = [r for r in results if str(r.get("text", "")).lower().find("abort") != -1 or r.get("text") == "aborted"]
                with self.progress_lock:
                    if aborted:
                        self.task_progress['UPDATE']['aborted'] = True
                    self.task_progress['UPDATE']['processed'] = len(results)
                for r in results:
                    self.log(f"AssociateTicket id={r.get('id')} status={r.get('status')} success={r.get('success')}")
                    self._append_session_log(f"AssociateTicket id={r.get('id')} status={r.get('status')} success={r.get('success')}")
                if aborted:
                    abort_msg = f"UPDATE aborted: {len(results)-len(aborted)}/{total} IDs processed"
                    self._append_session_log(f"[ABORT] {abort_msg}")
                    self.message_queue.put(("warning", abort_msg))
                else:
                    self._append_session_log(f"[OK] Task=Batch.AssociateTicket successes={succ} failures={fail}")
                    self.message_queue.put(("log", f"Batch ticket association complete: {succ} success, {fail} failed"))
            except Exception as e:
                self._append_session_log(f"[FAIL] Task=Batch.AssociateTicket error={e}")
                self.message_queue.put(("error", str(e)))

            finally:
                try:
                    self._shutdown_wait_override = None
                except Exception:
                    pass
                try:
                    self._call_in_main(self.abort_button.config, state=tk.DISABLED)
                    self.abort_event.clear()
                except Exception:
                    pass

        try:
            self.abort_event.clear()
            self._call_in_main(self.abort_button.config, state=tk.NORMAL)
        except Exception:
            pass
        try:
            self._shutdown_wait_override = max(5, len(ids) * 2)
        except Exception:
            self._shutdown_wait_override = None
        self._run_in_thread(worker)

    def on_batch_close_now(self) -> None:
        # Record user activity for inactivity timeout
        try:
            self.touch_activity()
        except Exception:
            logger.exception("Failed to touch activity on batch close now start")
        eng = self._batch_engine()
        ids = self._get_batch_ids()
        if not (eng and ids):
            messagebox.showerror("Batch Update", "Provide BH ID(s).")
            return
        if not messagebox.askyesno("Confirm Close Now", f"This will close {len(ids)} blackhole(s) immediately.\nProceed?"):
            self._append_session_log("[FAIL] Task=Batch.CloseNow reason=user_cancel")
            return
        self._append_session_log("[START] Task=Batch.CloseNow ids=" + ",".join(ids))
        def worker():
            try:
                total = len(ids)
                ops = [(bh, {"id": bh, "action": "close", "Close Now": "Close Now"}) for bh in ids]
                workers = min(8, max(1, (os.cpu_count() or 2)))
                # Track progress
                with self.progress_lock:
                    self.task_progress['UPDATE'] = {'total': total, 'processed': 0, 'aborted': False}
                results = eng.batch_post_views(ops, max_workers=workers, abort_event=self.abort_event)
                succ = sum(1 for r in results if r.get("success"))
                fail = len(results) - succ
                aborted = [r for r in results if str(r.get("text", "")).lower().find("abort") != -1 or r.get("text") == "aborted"]
                with self.progress_lock:
                    if aborted:
                        self.task_progress['UPDATE']['aborted'] = True
                    self.task_progress['UPDATE']['processed'] = len(results)
                for r in results:
                    self.log(f"CloseNow id={r.get('id')} status={r.get('status')} success={r.get('success')}")
                    self._append_session_log(f"CloseNow id={r.get('id')} status={r.get('status')} success={r.get('success')}")
                if aborted:
                    abort_msg = f"UPDATE aborted: {len(results)-len(aborted)}/{total} IDs processed"
                    self._append_session_log(f"[ABORT] {abort_msg}")
                    self.message_queue.put(("warning", abort_msg))
                else:
                    self._append_session_log(f"[OK] Task=Batch.CloseNow successes={succ} failures={fail}")
                    self.message_queue.put(("log", f"Batch close complete: {succ} closed, {fail} failed"))
            except Exception as e:
                self._append_session_log(f"[FAIL] Task=Batch.CloseNow error={e}")
                self.message_queue.put(("error", str(e)))

            finally:
                try:
                    self._shutdown_wait_override = None
                except Exception:
                    pass
                try:
                    self._call_in_main(self.abort_button.config, state=tk.DISABLED)
                    self.abort_event.clear()
                except Exception:
                    pass

        try:
            self.abort_event.clear()
            self._call_in_main(self.abort_button.config, state=tk.NORMAL)
        except Exception:
            pass
        try:
            self._shutdown_wait_override = max(5, len(ids) * 2)
        except Exception:
            self._shutdown_wait_override = None
        self._run_in_thread(worker)

    def on_collect_ids_from_pasted_ips(self) -> None:
        """From the IPs above, collect Blackhole IDs and load into Update.
        
        REFACTORED: Calls on_retrieve() internally to avoid code duplication,
        then extracts IDs from the aggregated results.
        """
        if not self.logged_in:
            messagebox.showerror("Batch Update", "Please log in first.")
            return
        # Record user activity for inactivity timeout
        try:
            self.touch_activity()
        except Exception:
            logger.exception("Failed to touch activity on collect IDs start")
        raw_ips = self.ip_text.get("1.0", tk.END)
        # Validate IPv4 format before parsing
        error = get_ipv4_validation_error(raw_ips)
        if error:
            messagebox.showerror("Invalid IP Format", error)
            return
        ip_tokens = parse_ip_text(raw_ips, auto_add_cidr=False, validate=False)
        # Normalize & deduplicate tokens while preserving order so totals match pasted list
        seen = set()
        ip_tokens = [p for p in ip_tokens if not (p in seen or seen.add(p))]
        if not ip_tokens:
            messagebox.showinfo("Batch Update", "Paste IPs first.")
            return
        self._append_session_log("[START] Task=Batch.CollectIDs ips=" + ",".join(ip_tokens))

        def worker():
            try:
                # Use on_retrieve() internally with IP Address search mode to get full results
                # Save current search params, call on_retrieve(), then restore
                original_search_by = self.search_by.get()
                original_search_value = self.search_value_var.get()
                
                # Set to IP Address mode (single IP at a time would be inefficient)
                self.search_by.set("IP Address")
                
                storage_state = self.auth_manager.get_storage_state() if self.auth_manager else None
                ids: List[str] = []

                # Use bidirectional concurrent retrieval same as on_retrieve()
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                total = len(ip_tokens)
                processed = 0
                
                with self.progress_lock:
                    self.task_progress['RETRIEVE'] = {'total': total, 'processed': 0, 'aborted': False}

                # Split IPs: first half processes top-down, second half bottom-up
                mid = (total + 1) // 2
                top_half = ip_tokens[:mid]
                bottom_half = ip_tokens[mid:]
                bottom_half_reversed = list(reversed(bottom_half))

                def fetch_for_ip(ip: str) -> tuple[str, List[str]]:
                    """Fetch IDs for one IP using independent engine. Extract from cell results.
                    Returns (ip, ids_found)."""
                    if self.abort_event.is_set():
                        return ip, []
                    try:
                        # Create independent engine instance per thread to avoid Playwright context sharing
                        engine = retrieval_module.RetrievalEngine(storage_state=storage_state, verify_ssl=False)
                        query_value = ip.strip() if is_cidr(ip) else sanitize_ip_for_search(ip)
                        # Log the query attempt in both message queue (for UI) and session log
                        query_msg = f"[Batch.CollectIDs] Querying: {query_value}"
                        self.message_queue.put(("log", query_msg))
                        self._append_session_log(query_msg)
                        
                        results = engine.retrieve({"ip_address_value": query_value, "view": "Both"})
                        header = []
                        data = results
                        if results and isinstance(results[0], dict) and results[0].get("header"):
                            header = [c.strip().lower() for c in results[0].get("cells", [])]
                            data = results[1:]
                        id_idx = header.index("id") if "id" in header else None
                        local_ids: List[str] = []
                        for r in data:
                            cells = r.get("cells", []) if isinstance(r, dict) else (r if isinstance(r, list) else [])
                            if id_idx is not None and id_idx < len(cells):
                                candidate = cells[id_idx].strip()
                                if candidate and candidate.isdigit():
                                    local_ids.append(candidate)
                        return ip, local_ids
                    except Exception as e:
                        logger.exception("Error fetching ID for IP %s: %s", ip, e)
                        self._append_session_log(f"[ERROR] Failed to fetch ID for {ip}: {e}")
                        return ip, []

                # Use ThreadPoolExecutor with bidirectional processing
                # Top half: 0→N (normal order), Bottom half: N→0 (reversed order)
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                workers = min(16, max(1, (os.cpu_count() or 2) * 2))
                
                with ThreadPoolExecutor(max_workers=workers) as exc:
                    # Submit all IPs: top half in order, bottom half reversed
                    all_ips = top_half + bottom_half_reversed
                    futures = {exc.submit(fetch_for_ip, ip): ip for ip in all_ips}
                    
                    for fut in as_completed(futures):
                        if self.abort_event.is_set():
                            with self.progress_lock:
                                self.task_progress['RETRIEVE']['aborted'] = True
                            abort_msg = f"BATCH.COLLECTIDS aborted: {processed}/{total} IPs processed"
                            self._append_session_log(f"[ABORT] {abort_msg}")
                            self.message_queue.put(("warning", abort_msg))
                            break
                        try:
                            try:
                                ip, local = fut.result()
                            except Exception as e:
                                logger.exception("Error fetching ID for IP: %s", e)
                                self._append_session_log(f"[ERROR] Error processing IP {futures.get(fut)}: {e}")
                                # Count it as processed even if failure
                                processed += 1
                                with self.progress_lock:
                                    self.task_progress['RETRIEVE']['processed'] = processed
                                # Update status bar
                                status_msg = f"Collecting IDs… ({processed}/{total})"
                                try:
                                    self.message_queue.put(("status", status_msg))
                                except Exception:
                                    self._call_in_main(self.status_var.set, status_msg)
                                continue

                            processed += 1
                            with self.progress_lock:
                                self.task_progress['RETRIEVE']['processed'] = processed

                            # Always log progress (even when zero IDs found) to keep counts clear
                            result_msg = f"[Batch.CollectIDs] {processed}/{total} Found {len(local)} ID(s) → {ip}"
                            if local:
                                ids.extend(local)
                            self.message_queue.put(("log", result_msg))
                            self._append_session_log(result_msg)

                            # Update status bar
                            status_msg = f"Collecting IDs… ({processed}/{total})"
                            try:
                                self.message_queue.put(("status", status_msg))
                            except Exception:
                                self._call_in_main(self.status_var.set, status_msg)

                        except Exception as e:
                            logger.exception("Error fetching ID for IP: %s", e)
                            self._append_session_log(f"[ERROR] Error processing IP: {e}")

                ids = sorted(set(ids), key=lambda x: int(x))
                if not ids:
                    self.message_queue.put(("info", "No Blackhole IDs found for pasted IPs."))
                    self._append_session_log("[OK] Task=Batch.CollectIDs found=0")
                    return
                self.batch_ids_var.set(",".join(ids))
                self.message_queue.put(("log", f"Collected {len(ids)} ID(s) from {processed}/{total} IPs."))
                self._append_session_log(f"[OK] Task=Batch.CollectIDs found={len(ids)} ips_processed={processed}/{total}")
            except Exception as e:
                self._append_session_log(f"[FAIL] Task=Batch.CollectIDs error={e}")
                self.message_queue.put(("error", str(e)))
            finally:
                try:
                    self._call_in_main(self.abort_button.config, state=tk.DISABLED)
                except Exception as e:
                    logger.exception("Failed to disable abort button: %s", e)
                try:
                    self.abort_event.clear()
                except Exception:
                    pass
        
        # Prepare abort flag and enable Abort button for retrieval
        self.abort_event.clear()
        try:
            self.abort_button.config(state=tk.NORMAL)
        except Exception as e:
            logger.exception("Failed to enable abort button: %s", e)
        
        self._run_in_thread(worker)

    # --------------------------
    # Table rendering / copy / export
    # --------------------------
    def _render_results_table(self, results: List[dict], fixed_columns: bool = False) -> int:
        """
        Render results with fixed layout:
        # | ID | Open Time (UTC) | Close Time (UTC) | Auto-Close Time (UTC) | IP | Ticket | Description
        Returns: number of data rows rendered.
        """

        # Clear host
        for w in self.results_frame.winfo_children():
            try:
                w.destroy()
            except Exception as e:
                logger.exception("Error destroying child widget: %s", e)

        self._table_columns = [
            "#",
            "ID",
            "Open Time (UTC)",
            "Close Time (UTC)",
            "Auto-Close Time (UTC)",
            "IP",
            "Ticket",
            "Description",
        ]
        self._table_rows_visible = []
        self._table_rows_full = []
        normalized_visible: List[List[str]] = []
        normalized_full: List[List[str]] = []

        def normalize_with_header_map(header_cells: List[str], data_cells: List[str], idx: int) -> List[List[str]]:
            """Map website header names to fixed grid columns (visible + full rows)."""

            def norm(h: str) -> str:
                h = h.lower().strip()
                h = re.sub(r"\s*\(utc\)\s*", "", h, flags=re.IGNORECASE)
                h = re.sub(r"\s+", " ", h)  # collapse whitespace/newlines
                h = h.replace("–", "-").replace("—", "-")
                h = h.replace("auto close", "auto-close")
                return h

            header_norm = [norm(h) for h in header_cells]
            aliases = {
                "id": "id",
                "open time": "open time",
                "open": "open time",
                "close time": "close time",
                "close": "close time",
                "auto-close": "auto-close time",
                "auto close": "auto-close time",
                "auto-close time": "auto-close time",
                "ip": "ip",
                "ip address": "ip",
                "ticket": "ticket",
                "ticket number": "ticket",
                "description": "description",
                "desc": "description",
            }

            def find_value(key_canonical: str) -> str:
                if key_canonical in header_norm:
                    i = header_norm.index(key_canonical)
                    return data_cells[i] if i < len(data_cells) else ""
                for k, v in aliases.items():
                    if v == key_canonical and k in header_norm:
                        i = header_norm.index(k)
                        return data_cells[i] if i < len(data_cells) else ""
                return ""

            id_val = find_value("id")
            open_time = find_value("open time")
            close_time = find_value("close time")
            auto_close = find_value("auto-close time")
            ip_val = find_value("ip")
            ticket_val = find_value("ticket")  # may be multi-line
            desc_val = find_value("description")

            # Visible ticket: single-line
            def ticket_single_line(t: str) -> str:
                parts = [p.strip() for p in (t.splitlines() if t else []) if p.strip()]
                if not parts:
                    return ""
                if len(parts) == 1:
                    return parts[0]
                return f"{parts[0]} {parts[-1]}"

            ticket_display = ticket_single_line(ticket_val)
            row_visible = [
                str(idx),
                id_val,
                open_time,
                close_time,
                auto_close,
                ip_val,
                ticket_display,
                desc_val,
            ]
            row_full = [
                str(idx),
                id_val,
                open_time,
                close_time,
                auto_close,
                ip_val,
                ticket_val,
                desc_val,
            ]
            return [row_visible, row_full]

        if fixed_columns:
            for i, r in enumerate(results, start=1):
                vis = [
                    r.get("#", str(i)),
                    r.get("ID", ""),
                    r.get("Open Time (UTC)", ""),
                    r.get("Close Time (UTC)", ""),
                    r.get("Auto-Close Time (UTC)", ""),
                    r.get("IP", ""),
                    r.get("Ticket", ""),
                    r.get("Description", ""),
                ]
                normalized_visible.append(vis)
                normalized_full.append(vis[:])
        else:
            header_cells: List[str] = []
            data_iter = results[:]
            if data_iter and isinstance(data_iter[0], dict) and data_iter[0].get("header"):
                header_cells = [c.strip() for c in data_iter[0].get("cells", [])]
                data_iter = data_iter[1:]
            idx = 1
            for r in data_iter:
                if isinstance(r, dict) and r.get("cells"):
                    cells = [str(c).strip() for c in r["cells"]]
                elif isinstance(r, list):
                    cells = [str(c).strip() for c in r]
                else:
                    cells = []
                if not cells or not any(cells):
                    continue
                pair = normalize_with_header_map(header_cells, cells, idx) if header_cells else [cells, cells]
                normalized_visible.append(pair[0])
                normalized_full.append(pair[1])
                idx += 1

        # Save for Copy/Export
        self._table_rows_visible = normalized_visible
        self._table_rows_full = normalized_full

        # Create Treeview
        tree = ttk.Treeview(self.results_frame, columns=self._table_columns, show="headings")
        for col in self._table_columns:
            tree.heading(col, text=col)

        # Column widths
        for col in self._table_columns:
            if col == "Description":
                tree.column(col, anchor="w", width=1, stretch=False)
            elif col == "Ticket":
                tree.column(col, anchor="w", width=160, stretch=True)
            elif col == "IP":
                tree.column(col, anchor="w", width=140, stretch=True)
            else:
                tree.column(col, anchor="w", width=120, stretch=True)

        for values in self._table_rows_visible:
            tree.insert("", "end", values=values)

        # Scrollbar
        vsb = ttk.Scrollbar(self.results_frame, orient="vertical", command=tree.yview)
        tree.configure(yscroll=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.results_frame.rowconfigure(0, weight=1)
        self.results_frame.columnconfigure(0, weight=1)
        self._table = tree

        # Auto-fit columns to width
        def _auto_fit_columns(event: Optional[Any] = None):
            try:
                total_w = self.results_frame.winfo_width() - 16
                if total_w <= 120:
                    return
                visible_cols = [c for c in self._table_columns if c != "Description"]
                base_w = max(90, int(total_w / max(1, len(visible_cols))))
                for col in visible_cols:
                    w = base_w
                    if col == "Ticket":
                        w = int(base_w * 1.4)
                    elif col == "IP":
                        w = int(base_w * 1.2)
                    tree.column(col, width=w, stretch=True)
            except Exception:
                logger.exception("Error auto-fitting columns")

        self.results_frame.bind("<Configure>", _auto_fit_columns)
        self.results_frame.update_idletasks()
        _auto_fit_columns()

        return len(self._table_rows_visible)

    def on_copy_selected(self) -> None:
        """Copy selected table rows to clipboard as TSV (includes header; uses visible values)."""
        if not self._table:
            messagebox.showinfo("Copy", "No table to copy.")
            return
        selection = self._table.selection()
        rows = (
            [self._table.item(item_id)["values"] for item_id in selection]
            if selection
            else self._table_rows_visible
        )
        lines = ["\t".join(self._table_columns)]
        for r in rows:
            lines.append("\t".join(str(x) for x in r))
        tsv = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(tsv)
        messagebox.showinfo("Copy", f"Copied {len(rows)} row(s) to clipboard.")

    def on_export_results(self) -> None:
        """Export the current table to a CSV file under ./session_logs with a timestamp (uses full values)."""
        if not self._table_rows_full:
            messagebox.showinfo("Export", "No results to export.")
            return
        folder = ensure_session_dir()
        fname = os.path.join(folder, f"results_{now_stamp()}.csv")
        try:
            with open(fname, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self._table_columns)
                for r in self._table_rows_full:
                    writer.writerow(r)
            messagebox.showinfo("Export", f"Exported {len(self._table_rows_full)} row(s).")
        except Exception as e:
            messagebox.showerror("Export error", str(e))

    # --------------------------
    # Log & Quit
    # --------------------------
    def log(self, *lines: str) -> None:
        """Append lines to the log pane and auto-scroll; fixed enable/disable handling."""
        try:
            self.result_text.config(state=tk.NORMAL)
            for line in lines:
                self.result_text.insert(tk.END, line + "\n")
            # Trim log to keep UI responsive (prevent widget from growing unbounded)
            try:
                max_lines = 2000
                current_lines = int(self.result_text.index('end-1c').split('.')[0])
                if current_lines > max_lines:
                    # delete oldest lines
                    to_delete = current_lines - max_lines
                    self.result_text.delete('1.0', f'{to_delete + 1}.0')
            except Exception:
                pass
            self.result_text.see(tk.END)
        finally:
            self.result_text.config(state=tk.DISABLED)

    def _append_session_log(self, line: str) -> None:
        try:
            if self.session_logger:
                self.session_logger.append(line)
        except Exception as e:
            logger.exception("Failed to append to session log: %s", e)
            try:
                self.message_queue.put(("log", f"Session log error: {e}"))
            except Exception:
                logger.exception("Failed to enqueue session log error")

    def _run_in_thread(self, worker_func: Callable) -> None:
        def worker_wrapper():
            try:
                worker_func()
            except Exception as e:
                logger.exception("Unhandled exception in worker thread")
                try:
                    self.message_queue.put(("error", f"Thread error: {str(e)}"))
                except Exception:
                    logger.exception("Failed to enqueue thread error")
            finally:
                # Remove thread from active list when it exits
                with self.threads_lock:
                    try:
                        self.active_threads.remove(threading.current_thread())
                    except ValueError:
                        pass
        
        thread = threading.Thread(target=worker_wrapper, daemon=True)
        with self.threads_lock:
            self.active_threads.append(thread)
        thread.start()

    def _graceful_shutdown(self) -> None:
        """Perform graceful shutdown sequence."""
        logger.info("Initiating graceful shutdown...")
        
        # Signal shutdown to all components
        self.shutdown_event.set()
        
        # Stop the queue pump
        self._append_session_log("[START] Task=GracefulShutdown")
        
        # Capture final logs and state
        try:
            text = self.result_text.get("1.0", tk.END)
            if self.session_logger:
                self.session_logger.append("Application shutdown initiated")
                if text and text.strip():
                    self.session_logger.append_block("FINAL UI LOG SNAPSHOT", text)
        except Exception:
            logger.exception("Error capturing final session log")
        
        # Wait for worker threads to complete (with timeout)
        # If a job set a specific wait time (e.g., number of IPs * 2s), use it
        max_wait_time = self._shutdown_wait_override if self._shutdown_wait_override is not None else max(5, len(self.active_threads) * 2)
        start_time = time.time()
        while True:
            with self.threads_lock:
                remaining_threads = [t for t in self.active_threads if t.is_alive()]
            
            if not remaining_threads:
                logger.info("All worker threads have completed")
                break
            
            elapsed = time.time() - start_time
            if elapsed > max_wait_time:
                logger.warning(f"Timeout waiting for threads after {max_wait_time}s")
                break
            
            time.sleep(0.1)
        
        # Close auth_manager to clean up Playwright resources
        if self.auth_manager:
            try:
                if hasattr(self.auth_manager, "close"):
                    self.auth_manager.close()
                    logger.info("Auth manager resources cleaned up")
            except Exception:
                logger.exception("Error while closing auth_manager")
        
        self._append_session_log("[OK] Task=GracefulShutdown")
        
        logger.info("Graceful shutdown complete. Destroying window.")
        
        try:
            self.root.destroy()
        except Exception:
            logger.exception("Error while destroying window")
        # Reset override after shutdown
        self._shutdown_wait_override = None

    def on_quit(self) -> None:
        """Handle quit event triggered by user clicking Quit button."""
        self._graceful_shutdown()

    def _on_window_close(self) -> None:
        """Handle window close event (X button)."""
        logger.info("Window close event triggered")
        self._graceful_shutdown()

    def _on_signal(self, signum: int, frame: Any) -> None:
        """Handle signals (SIGINT from Ctrl+C, SIGTERM from task manager)."""
        logger.info(f"Signal {signum} received, initiating graceful shutdown")
        self._graceful_shutdown()

    def on_abort(self) -> None:
        """User-initiated abort for long-running CREATE or UPDATE operations."""
        if not self.abort_event.is_set():
            self.abort_event.set()
            self._append_session_log("[ACTION] User requested abort")
            self.message_queue.put(("info", "Abort requested — stopping after current operation."))
            try:
                self.abort_button.config(state=tk.DISABLED)
            except Exception:
                pass



# Entry
def main() -> None:
    root = tk.Tk()
    # Make the window resizable and start at a sensible size for deployment
    # Standard laptop/monitor resolution friendly with good content visibility
    root.geometry("1100x950")
    # Set minimum window size to prevent UI elements from being hidden
    root.minsize(950, 700)
    app = BlackholeGUI(root)
    
    # Register window close protocol handler (handles X button)
    root.protocol("WM_DELETE_WINDOW", app._on_window_close)
    
    # Register signal handlers for graceful shutdown (Ctrl+C, task manager SIGTERM)
    try:
        signal.signal(signal.SIGINT, lambda signum, frame: app._on_signal(signum, frame))
        signal.signal(signal.SIGTERM, lambda signum, frame: app._on_signal(signum, frame))
    except Exception as e:
        logger.exception(f"Failed to register signal handlers: {e}")
    
    root.mainloop()


if __name__ == "__main__":
    main()
