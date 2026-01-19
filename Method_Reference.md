# Method Reference — Detailed Method & Class Documentation

This document contains detailed API documentation for all modules. For quick start and operational guides, see [README.md](README.md).

---

## PlayWrightUtil.py — Playwright Utilities & Configuration

**`PlaywrightConfig` (Immutable Configuration Object)**
```python
class PlaywrightConfig:
    def __init__(
        self,
        base_url: str,
        storage_state: Optional[Dict[str, Any]] = None,
        verify_ssl: bool = False,
        http_user: str = "",
        http_pass: str = "",
    ):
        """
        Immutable configuration for authenticated Playwright requests.
        Created once at login; passed to all modules.
        """
        self.base_url  # Blackhole portal URL (normalized with trailing /)
        self.storage_state  # Cookies/session from auth
        self.verify_ssl  # TLS verification (False = ignore errors)
        self.http_user  # HTTP basic auth username
        self.http_pass  # HTTP basic auth password

    def to_request_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs suitable for pw.request.new_context()."""
```

**`PlaywrightClient` (Pooled Request Context Manager)**
```python
class PlaywrightClient:
    def __init__(self, config: PlaywrightConfig):
        """
        Manages Playwright instance with single pooled request context.
        Reuses context across many operations (high performance).
        """

    def get(self, path: str, params: Dict = None, timeout: int = 30000) -> Response:
        """GET request; reuses pooled context."""

    def post(self, path: str, form: Dict = None, timeout: int = 30000) -> Response:
        """POST request; reuses pooled context."""

    def dispose(self) -> None:
        """Close request context and Playwright instance."""
```

**Helper Functions**
```python
def build_request_kwargs(
    base_url: str,
    storage_state: Dict,
    verify_ssl: bool,
    http_user: str,
    http_pass: str,
) -> Dict[str, Any]:
    """Build kwargs for pw.request.new_context()."""

def read_env_config() -> Dict[str, Any]:
    """Read TLS and HTTP credentials from environment variables."""

def suppress_cleanup_warning(e: Exception) -> bool:
    """Check if exception is harmless Playwright cleanup error."""
```

---

## AuthManager.py — HTTP Authentication & Config Creation

**`AuthManager` Class**
```python
class AuthManager:
    def __init__(self, base_url: str = "https://blackhole.ip.qwest.net/") -> None:
        """
        Initialize authentication manager with base URL.
        TLS policy configured from BH_FORCE_SSL_VERIFY env var.
        """
        self.base_url  # Portal URL
        self.browser  # Playwright browser instance
        self.context  # Playwright context
        self.page  # Playwright page
        self.logged_in: bool  # Login status
        self.logged_in_user: Optional[str]  # Authenticated username
        self.storage_state: Optional[Dict]  # Session/cookies
        self.pw_config: Optional[PlaywrightConfig]  # Config for other modules
        self.verify_ssl: bool  # TLS verification policy
        self.last_login_status_details: Optional[str]  # Last login error details

    def login_with_http_credentials(
        self,
        username: str,
        password: str,
        headless: bool = False,
    ) -> bool:
        """
        Authenticate using HTTP Basic/Digest auth.
        Captures storage_state and creates PlaywrightConfig.
        
        Returns:
            True if login successful (2xx/3xx status)
            False if login failed
        
        Raises:
            AuthError: If Playwright initialization fails
        """

    def get_storage_state(self) -> Optional[Dict[str, Any]]:
        """Retrieve captured session state (cookies/auth tokens)."""

    def get_config(self) -> Optional[PlaywrightConfig]:
        """
        Retrieve PlaywrightConfig for passing to other modules.
        Contains: base_url, storage_state, verify_ssl, http_user, http_pass
        """

    def close(self) -> None:
        """Cleanup Playwright resources (page, context, browser)."""
```

**Private Methods (Internal Use)**
```python
def _ensure_playwright(self) -> None:
    """Lazy-import Playwright with exception handling."""

def _cleanup_resources(self) -> None:
    """Safe shutdown with cleanup warning suppression."""
```

---

## RetrievalEngine.py — Structured Retrieval & Parsing

**`RetrievalEngine` Class**
```python
class RetrievalEngine:
    def __init__(
        self,
        base_url: str = "https://blackhole.ip.qwest.net/",
        storage_state: Optional[Dict[str, Any]] = None,
        verify_ssl: Optional[bool] = None,
        headless_default: bool = True,
        config: Optional[PlaywrightConfig] = None,
    ) -> None:
        """
        Initialize retrieval engine.
        If config provided, use it (avoids re-reading env vars).
        Falls back to legacy behavior if not provided.
        """

    def retrieve(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Query Blackhole records with filters.
        
        Supported filter modes:
        
        1. By Blackhole ID:
           filters = {"blackhole_id_value": "12345"}
        
        2. By Ticket:
           filters = {
               "ticket_number_value": "INC0123456",
               "ticket_system": "NTM-Remedy"  # or Clarify, Vantive
           }
        
        3. By IP Address (supports CIDR):
           filters = {
               "ip_address_value": "10.0.0.1",
               "view": "Both"  # or Open, Closed
           }
        
        4. By Opened by (username):
           filters = {"opened_by_value": "username"}
        
        5. By Open Date:
           filters = {
               "month": "January",  # or 01-12 or month name
               "year": "2026"
           }
        
        6. Active Blackholes:
           filters = {"searchby": "active_holes"}
        
        Returns:
            List of dicts with header row (cells + header flag) and data rows
            Example: [
                {"header": True, "cells": ["ID", "IP", "Description", ...]},
                {"cells": ["12345", "10.0.0.1", "DDoS attack", ...]},
                {"cells": ["12346", "10.0.0.2", "Malicious activity", ...]},
            ]
        """

    def _http_fetch_and_parse(self, filters) -> List[Dict]:
        """HTTP request and HTML table parsing."""

    def _parse_tables_in_page(self, html) -> List[Dict]:
        """Parse HTML <table> into structured format."""

    def _month_to_number(self, month_input: str) -> str:
        """Normalize month names/numbers (January → 01, etc.)."""
```

---

## CreateBlackhole.py — Create Blackholes via HTTP POST

**`BlackholeCreator` Class**
```python
class BlackholeCreator:
    # Class constants
    TIMEOUT_MS = 30000  # 30 second timeout per request
    MAX_RETRIES = 3  # 3 retry attempts per IP
    RETRY_DELAY = 2  # 2 second delay between retries

    def __init__(
        self,
        base_url: str = "https://blackhole.ip.qwest.net/",
        storage_state: Optional[Dict[str, Any]] = None,
        config: Optional[PlaywrightConfig] = None,
    ) -> None:
        """
        Initialize creator.
        If config provided, use it; otherwise fall back to legacy behavior.
        """

    def submit_blackholes_http(
        self,
        ip_list: List[str],
        ticket_number: str = "",
        autoclose_time: str = "",
        description: str = "",
        ticket_system: str = "NTM-Remedy",
    ) -> List[Dict[str, Any]]:
        """
        Create blackholes for list of IPs.
        
        Args:
            ip_list: List of IPv4 addresses or CIDR ranges (e.g., ["10.0.0.1", "10.0.0.0/24"])
            ticket_number: Ticket ID (REQUIRED unless autoclose_time provided)
            autoclose_time: Auto-close time, e.g., "+2d", "+24h", "+1w" (REQUIRED unless ticket_number provided)
            description: Optional description (defaults to "CASE #<ticket_number>")
            ticket_system: "NTM-Remedy", "Clarify", or "Vantive" (default: NTM-Remedy)
        
        Returns:
            List of result dicts:
            [
                {
                    "ip": "10.0.0.1",
                    "ticket_number": "INC0123456",
                    "success": True,
                    "status": "Created",
                    "message": "Blackhole created successfully",
                    "response_time": 0.542,  # seconds
                },
                ...
            ]
        
        Raises:
            CreateBlackholeError: If storage_state not available
        
        Features:
        - Per-IP retry logic (3 attempts, 2-sec delays)
        - Timeout per request: 30 seconds
        - Returns detailed per-IP status
        """
```

---

## BatchRemoval.py — Batch Updates with Connection Pooling

**`BatchRemoval` Class**
```python
class BatchRemoval:
    def __init__(
        self,
        base_url: str = "https://blackhole.ip.qwest.net/",
        storage_state: Optional[Dict[str, Any]] = None,
        config: Optional[PlaywrightConfig] = None,
    ) -> None:
        """
        Initialize batch removal engine.
        If config provided, use it; otherwise fall back to legacy behavior.
        """

    def view_details_html(self, blackhole_id: str) -> str:
        """GET view.cgi to fetch blackhole HTML details."""

    def set_description(
        self,
        blackhole_id: str,
        description: str,
    ) -> Dict[str, Any]:
        """
        POST to update blackhole description.
        Returns: {id, success, status, text}
        """

    def set_autoclose(
        self,
        blackhole_id: str,
        close_text: str,
    ) -> Dict[str, Any]:
        """
        POST to set/remove auto-close time.
        Args:
            close_text: Auto-close time (e.g., "+2d") or empty string to remove
        Returns: {id, success, status, text}
        """

    def associate_ticket(
        self,
        blackhole_id: str,
        ticket_system: str,
        ticket_number: str,
    ) -> Dict[str, Any]:
        """
        POST to associate ticket.
        Returns: {id, success, status, text}
        """

    def close_now(self, blackhole_id: str) -> Dict[str, Any]:
        """
        POST to immediately close blackhole.
        Returns: {id, success, status, text}
        """

    def batch_post_views(
        self,
        operations: List[Tuple[str, Dict[str, str]]],
        max_workers: int = 5,
        timeout: int = 30000,
        abort_event: Optional[threading.Event] = None,
    ) -> List[Dict]:
        """
        ⚡ HIGH-PERFORMANCE batch operations using connection pooling.
        
        Args:
            operations: List of (blackhole_id, form_dict) tuples
                Example: [
                    ("12345", {"id": "12345", "action": "description", "description": "New desc"}),
                    ("12346", {"id": "12346", "action": "autoclose", "close_text": "+2d"}),
                ]
            max_workers: Thread pool size (default: 5)
            timeout: Request timeout in milliseconds (default: 30000)
            abort_event: Optional threading.Event for cooperative abort
        
        Returns:
            List of result dicts: [{id, success, status, text}, ...]
        
        Performance:
        - Reuses single PlaywrightClient with pooled request context
        - Thread pool executes operations concurrently
        - Result: ~10x faster than per-operation context creation
        
        Example:
        ```python
        operations = [
            ("12345", {"id": "12345", "action": "description", "description": "DDoS attack"}),
            ("12346", {"id": "12346", "action": "autoclose", "close_text": "+2d"}),
            ("12347", {"id": "12347", "action": "ticket", "ticket_system": "NTM-Remedy", "ticket_number": "INC0123"}),
        ]
        results = batch_removal.batch_post_views(
            operations,
            max_workers=10,
            abort_event=abort_event
        )
        for result in results:
            print(f"ID {result['id']}: {result['status']}")
        ```
        """
```

---

## SessionLogger.py — Async Session Logging

**Functions**
```python
def ensure_session_dir() -> str:
    """
    Ensure app-relative session_logs directory exists.
    Returns: Path to session_logs directory
    """

def session_filename(user: str) -> str:
    """
    Generate unique filename per login.
    Format: SESSION_<YYYYMMDD>_<HHMMSS>_<USERNAME>.log
    Example: SESSION_20260118_143052_prajeet.log
    """
```

**`SessionLogger` Class**
```python
class SessionLogger:
    def __init__(self, user: str) -> None:
        """
        Initialize per-session file logger.
        Starts daemon writer thread; ready to accept log entries immediately.
        
        Args:
            user: Username (used in log filename)
        
        Creates:
        - Log file at: session_logs/SESSION_<date>_<time>_<user>.log
        - Background writer thread (daemon)
        """

    def append(self, line: str) -> None:
        """
        Enqueue single timestamped line.
        Returns immediately (non-blocking).
        
        Example:
            logger.append("User logged in")
            logger.append(f"[CREATE] Created blackhole for 10.0.0.1")
        """

    def append_block(self, title: str, text: str) -> None:
        """
        Enqueue titled block with content.
        Returns immediately (non-blocking).
        
        Example:
            logger.append_block("RETRIEVE RESULTS", "Found 5 blackholes...")
        """

    def append_json(self, title: str, obj: Any) -> None:
        """
        Enqueue titled JSON dump.
        Returns immediately (non-blocking).
        
        Example:
            logger.append_json("CREATE RESULT", result_dict)
        """

    def close(self, timeout: float = 5.0) -> None:
        """
        Signal stop to writer thread; join with timeout.
        All pending log entries written before thread exits.
        """

# Writer Thread Behavior (Background)
# - Drains queue continuously (blocking pop with timeout)
# - Writes entries to SESSION_*.log file (UTF-8)
# - Stops on sentinel or when signaled and queue empty
# - All I/O non-blocking to main thread
```

---

## BlackholeGUI.py — Main GUI Controller

**`BlackholeGUI` Class**
```python
class BlackholeGUI:
    """Main window controller for Blackhole Automation."""

    # Initialization
    def __init__(self, root: tk.Tk) -> None:
        """
        Initialize GUI with Tkinter root window.
        Sets up three tabs: CREATE, RETRIEVE, UPDATE.
        Starts queue pump for thread-safe UI updates.
        """

    # User Action Methods (Main Tab Operations)
    def on_login(self) -> None:
        """
        Prompt for HTTP credentials; authenticate; create PlaywrightConfig; start inactivity watcher.
        Runs in separate thread to avoid blocking GUI.
        """

    def on_retrieve(self) -> None:
        """
        Retrieve blackhole records by search mode.
        Modes: IP Address (concurrent), Ticket #, Opened by, ID, Open Date, Active Blackholes.
        Concurrent multi-IP retrieval uses bidirectional processing (top-down & bottom-up).
        Progress updates per IP.
        """

    def on_create_http(self) -> None:
        """
        Create blackholes from pasted IPs.
        Requires: ticket_number OR autoclose_time.
        Optional: description (defaults to "CASE #<ticket>").
        Per-IP retry logic built into CreateBlackhole.
        Progress updates per IP; verification via "Opened by user" search.
        """

    def on_batch_set_description(self) -> None:
        """Batch set description for multiple blackhole IDs."""

    def on_batch_set_autoclose(self) -> None:
        """Batch set auto-close time for multiple blackhole IDs."""

    def on_batch_associate_ticket(self) -> None:
        """Batch associate ticket for multiple blackhole IDs."""

    def on_batch_close_now(self) -> None:
        """Batch close multiple blackhole IDs immediately."""

    def on_collect_ids_from_pasted_ips(self) -> None:
        """
        Retrieve blackhole IDs for pasted IPs using "Opened by" search.
        Useful for batch operations when you have IPs but need IDs.
        Uses concurrent retrieval (bidirectional processing).
        """

    def on_copy_selected(self) -> None:
        """Copy selected table rows as tab-separated values."""

    def on_export_results(self) -> None:
        """Export full results table to CSV file."""

    def on_quit(self) -> None:
        """Graceful shutdown: abort workers, close resources, destroy window."""

    # Inactivity & Auto-Logout
    def touch_activity(self) -> None:
        """Record user activity timestamp; reset inactivity timer."""

    def _start_inactivity_watcher(self) -> None:
        """Start background thread checking inactivity every 1 second."""

    def _auto_logout(self, reason: str = "inactivity") -> None:
        """
        Automatic logout:
        1. Abort active workers
        2. Close AuthManager and SessionLogger resources
        3. Clear login state
        4. Notify user
        """

    # Helper & Internal Methods
    def _render_results_table(self, results: List[dict], fixed_columns: bool = False) -> int:
        """
        Render results into Treeview with fixed column layout.
        Normalizes header names and creates visible + full row variants.
        Returns: number of data rows rendered.
        """

    def _append_session_log(self, line: str) -> None:
        """Enqueue line to session logger (non-blocking)."""

    def _call_in_main(self, func: Callable, *args, **kwargs) -> None:
        """Enqueue callable to execute on main thread via message queue."""

    def _tk_exception_handler(self, exc_type, exc_value, exc_tb) -> None:
        """Global Tkinter exception handler: logs and shows error dialog."""

    def _run_in_thread(self, worker_func: Callable) -> None:
        """Execute worker function in background thread with exception handling."""

    def _graceful_shutdown(self) -> None:
        """
        Graceful shutdown sequence:
        1. Signal shutdown to all components
        2. Abort active operations
        3. Wait for threads to complete (with timeout)
        4. Close resources
        5. Destroy window
        """

    # Exception Handling
    def _on_retrieve_complete(self, results: List[dict], context: str) -> None:
        """Handle successful retrieve; render table; update header."""

    def _on_retrieve_error(self, err: Exception, context: str) -> None:
        """Handle retrieve error; show message box."""

# State Attributes
    root: tk.Tk  # Main window
    pw_config: Optional[PlaywrightConfig]  # Config passed to modules
    auth_manager: Optional[AuthManager]  # Authentication instance
    session_logger: Optional[SessionLogger]  # Per-session logger
    abort_event: threading.Event  # Cooperative abort signal
    message_queue: queue.Queue  # Thread→UI messaging
    logged_in: bool  # Login status
    logged_in_user: Optional[str]  # Authenticated username
    status_var: tk.StringVar  # Bottom status bar text
    
# Table State
    _table: Optional[ttk.Treeview]  # Results treeview
    _table_columns: List[str]  # ["#", "ID", "Open Time (UTC)", ...]
    _table_rows_visible: List[List[str]]  # UI display rows (Ticket single-line)
    _table_rows_full: List[List[str]]  # Full rows for CSV export (Ticket multi-line)

# Inactivity Tracking
    last_activity_ts: float  # Timestamp of last user activity
    inactivity_timeout_seconds: int  # Timeout in seconds (default: 3600)
    _inactivity_thread: Optional[threading.Thread]  # Watcher thread
```

---

## HTTP Endpoints & Payload Details

### Supported Endpoints

**GET view.cgi** — Retrieve single blackhole by ID
```
URL: https://blackhole.ip.qwest.net/view.cgi?id=<ID>
Response: HTML page with details
```

**POST search.cgi** — Search blackholes
```
URL: https://blackhole.ip.qwest.net/search.cgi
Form params depend on search mode:
  - blackhole_id: By ID
  - ticket_number, ticket_system: By ticket
  - ipaddress, view: By IP (view=Open/Closed/Both)
  - open_user: By username
  - month, year: By date
  - searchby=active_holes: Active blackholes
```

**POST new.cgi** — Create blackhole
```
URL: https://blackhole.ip.qwest.net/new.cgi
Form params:
  - ipaddress: Target IP
  - ticket_system: NTM-Remedy|Clarify|Vantive
  - ticket_number: Ticket ID
  - autoclose_time: e.g., +2d (optional)
  - description: User description (optional)
```

**POST view.cgi** — Update blackhole
```
URL: https://blackhole.ip.qwest.net/view.cgi
Form params (vary by action):
  - id: Blackhole ID
  - action: description|autoclose|ticket|close
  - description: New description (if action=description)
  - close_text: Auto-close time (if action=autoclose)
  - ticket_system, ticket_number: (if action=ticket)
```
