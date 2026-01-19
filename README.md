# Blackhole Automation

> **Owner:** Prajeet Pounraj (Information Security Engineer II)  
> **Status:** Production-ready | Deployable as standalone `.exe`

Desktop GUI automation for the internal Lumen Blackhole portal. Built with Tkinter, Playwright HTTP client, async session logging, and connection pooling.

**Key Features:**
- Concurrent multi-IP operations (retrieve/create)
- High-performance batch updates (faster via connection pooling **108x**) 
- Async session logging (non-blocking)
- 1-hour inactivity auto-logout (configurable)
- Graceful shutdown & cooperative abort
- Per-IP retry logic (3 attempts with delays)
- Thread-safe UI updates
- Desktop logs auto-created on first run

---

## Installation

### For End Users (Quick Start)

1. Download `BlackholeAutomation.exe` (or extract ZIP)
2. Double-click `BlackholeAutomation.exe`
3. Wait for GUI to open
4. Log in with Blackhole portal credentials
5. Desktop logs created at: `Desktop/BlackholeAutomation_Logs/`

**No Python, venv, or dependencies needed on client machines.**

### For Developers (Local Setup)

```powershell
# Clone repository
git clone https://github.com/Prajeet-Lumen/Blackhole_Automation.git
cd Blackhole_Automation

# Create virtual environment
python -m venv venv100
.\venv100\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
python -m playwright install

# Run locally
python main_entry.py
```

---

## Usage Guide

### Tab 1: CREATE Blackholes

1. Paste IPs (one per line or space-separated)
2. Select ticket system (NTM-Remedy, Clarify, Vantive)
3. Enter ticket number (required unless auto-close provided)
4. Optional: Auto-close time (e.g., `+2d`, `+24h`)
5. Optional: Description (defaults to `CASE #<ticket>`)
6. Click **Create Blackholes**

**Behavior:** Per-IP creation with validation, progress tracking, and per-IP retry logic.

### Tab 2: RETRIEVE Records

1. Select search mode (dropdown):
   - **IP Address** — Supports CIDR; concurrent bidirectional retrieval
   - **Ticket #** — Single ticket lookup
   - **Opened by** — Username search
   - **Blackhole ID #** — Direct ID lookup
   - **Open Date** — Month/year selection
   - **Active Blackholes** — Auto-query
2. Enter search criteria
3. Click **Retrieve**

**Actions:**
- **Export Results** — Save table as CSV (all columns)
- **Copy Selected** — Copy rows as TSV (for Excel/Sheets)
- **Load for Batch** — Load selected row IDs to UPDATE tab

### Tab 3: UPDATE Batch Operations

**Load IDs (choose one method):**
- Manual: Paste comma-separated IDs
- Auto: Paste IPs → click "Collect IDs from IPs"
- From table: Select rows in RETRIEVE results → click "Load from selection"

**Perform one operation:**
- **Set Description** — Update description for all IDs
- **Set Auto-close** — Schedule auto-close (e.g., `+2d`)
- **Associate Ticket** — Link ticket to all IDs
- **Close Now** — Immediately close all IDs (requires confirmation)

**Performance:** Connection pooling makes batch operations significantly faster.

---

## Development & Building

### Create Standalone .exe (For Distribution)

**Prerequisites:**
- Python 3.10+ (already installed)
- venv100 activated

**Steps:**

```powershell
# Step 1: Install PyInstaller (one-time)
& "C:\Users\ad55004\OneDrive - Lumen\Desktop\Automation\venv100\Scripts\Activate.ps1"
pip install pyinstaller

# Step 2: Build .exe
cd "C:\Users\ad55004\OneDrive - Lumen\Desktop\Automation"
pyinstaller BlackholeAutomation.spec

# Step 3: Test
.\dist\BlackholeAutomation\BlackholeAutomation.exe

```

**Output:**
- `dist/BlackholeAutomation.exe` — Standalone executable
- `dist/BlackholeAutomation/` — All dependencies bundled (Playwright, pyee, greenlet)

---

## Architecture

### Core Modules

______________________________________________________________________
| Module                 | Purpose                                   |
|------------------------|-------------------------------------------|
| **BlackholeGUI.py**    | Main Tkinter GUI controller               |
| **AuthManager.py**     | HTTP authentication & config creation     |
| **PlayWrightUtil.py**  | Playwright utilities & connection pooling |
| **RetrievalEngine.py** | Structured HTTP retrieval & parsing       |
| **CreateBlackhole.py** | Blackhole creation via HTTP POST          |
| **BatchRemoval.py**    | Batch updates with pooling                |
| **SessionLogger.py**   | Async per-user session logging            |

### Key Design Patterns

1. **PlaywrightConfig** — Immutable config object passed to all modules (single source of truth)
2. **Connection Pooling** — Single reused request context for batch operations (~108x faster)
3. **Async Session Logging** — Non-blocking queue-based background writer thread
4. **Cooperative Abort** — Operations check abort event between iterations for graceful stops
5. **Inactivity Auto-Logout** — 1-hour timeout with background watcher thread

**For detailed API documentation, see [API_REFERENCE.md](API_REFERENCE.md)**

---

## Configuration

### Environment Variables

__________________________________________________________________________________________
| Variable                | Default       | Purpose                                      |
|-------------------------|---------------|----------------------------------------------|
| `BH_FORCE_SSL_VERIFY`   | 0             | 1 = enforce SSL; 0 = ignore (internal CA)    |
| `BH_INACTIVITY_TIMEOUT` | 3600          | Auto-logout timeout (seconds)                |
| `BH_HTTP_USER`          | (from login)  | HTTP basic auth username                     |
| `BH_HTTP_PASS`          | (from login)  | HTTP basic auth password                     |


### Session Logging

**Log Location:** `C:\Users\{user}\Desktop\BlackholeAutomation_Logs\`

**Filename Format:** `SESSION_<YYYYMMDD>_<HHMMSS>_<USERNAME>.log`

**Example Log Entry:**
```
[2026-01-18 14:30:52] [LOGIN] authenticated
[2026-01-18 14:31:05] [CREATE] 1/100 Starting → 10.0.0.1
[2026-01-18 14:31:06] Result → success=True; duration=0.92s
[2026-01-18 14:35:12] [AUTO-LOGOUT] Session closed due to inactivity
```

---

## Troubleshooting & FAQ

### Common Issues
______________________________________________________________________________________________________________
| Problem                    | Cause                              | Solution                                 |
|----------------------------|------------------------------------|------------------------------------------|
| "Login Failed"             | Wrong credentials or no API access | Verify creds in web UI; check network    |
| GUI won't open             | Tkinter missing or display issue   | Update graphics drivers; try from cmd    |
| "Connection Timed Out"     | Network/firewall/service down      | Ping target; check port 443; verify VPN  |
| Logs folder not created    | Permissions issue                  | Check Desktop folder permissions         |
| Slow performance (>500 IPs)| API / CPU / 16 GB Ram constraint   | Expected ~15–30 min; can't optimize      |


### Tab-Specific Issues

**CREATE Tab:**
- **IP Validation Failed** — Check IP format (no reserved/broadcast); CIDR supported
- **Retry Exhausted** — Network issue or service error; check session log for details
- **Per-IP Timeout** — Expected after 30 sec; 3 retries attempted automatically

**RETRIEVE Tab:**
- **No Results** — IP/ticket may not exist; verify via web browser
- **Slow for 500+ IPs** — Expected; ~2–5 sec per IP; API constraint
- **CIDR not working** — Use format `10.0.0.0/24`; app expands automatically

**UPDATE Tab:**
- **Can't load IDs from IPs** — IPs must exist
- **Batch update slow for 1–2 IDs** — Overhead-bound; expected; no optimization possible
- **Operations stall** — Click "Abort" to stop gracefully; check network

### Performance Tips

- **50+ IPs batch operations:** Significantly faster with connection pooling
- **Single operations:** Normal performance (no pooling overhead)
- **Large IP ranges (>500):** Run from same network as service for best results
- **Slow retrieval:** Check network latency; consider VPN or local network access

### FAQ

**Q: Can I use on Mac or Linux?**  
A: Yes. Run `pyinstaller BlackholeAutomation.spec` on target OS. No code changes needed.

**Q: Is my password saved?**  
A: No. Password used only for HTTP login; session ends on logout or 1-hour timeout.

**Q: Can I export bulk IPs?**  
A: Yes. Paste IPs into CREATE/RETRIEVE; export via "Export Results (CSV)"; copy rows as TSV.

**Q: Multiple users simultaneously?**  
A: Yes. Each user gets timestamped session log; Desktop logs folder is per-user.

**Q: Update to new version?**  
A: Download new .exe; replace old one; run. Session logs auto-created.

**Q: Maximum IPs at once?**  
A: No hard limit. Tested with 100+ IPs. Recommend batching < 500 IPs for clarity.

---

## Project Files


| File                       | Purpose                          |
|----------------------------|----------------------------------|
| `main_entry.py`            | Entry point; ensures logs folder |
| `BlackholeAutomation.spec` | PyInstaller config               |
| `requirements.txt`         | Python dependencies              |
| `Build_Reqs.yaml`          | Architecture notes               |
| `README.md`                | Main documentation               |
| `API_REFERENCE.md`         | Detailed method/class API        |
| `AuthManager.py`           | HTTP authentication              |
| `PlayWrightUtil.py`        | Playwright utilities             |
| `RetrievalEngine.py`       | Retrieval engine                 |
| `CreateBlackhole.py`       | Creation logic                   |
| `BatchRemoval.py`          | Batch operations                 |
| `SessionLogger.py`         | Session logging                  |
| `BlackholeGUI.py`          | Main GUI controller              |


---

**Status:** Production-ready | Deployable as standalone `.exe` | No external dependencies on client machines

**Repository:** https://github.com/Prajeet-Lumen/Blackhole_Automation
