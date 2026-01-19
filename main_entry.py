#!/usr/bin/env python3
"""
**main_entry.py**
Created: January 2026
Edited: January 2026
Created by: Prajeet (DDoS Response Team)

Entry point for the packaged .exe. Ensures desktop log folder structure exists
before launching the GUI. This script is the primary target for PyInstaller to create
the standalone .exe file.
"""
import os
import sys

def ensure_desktop_logs():
    """
    Create a logs folder on the user's Desktop if it does not exist.
    This is called once at startup before the GUI launches.
    """
    try:
        desktop = os.path.expanduser("~/Desktop")
        logs_folder = os.path.join(desktop, "BlackholeAutomation_Logs")
        os.makedirs(logs_folder, exist_ok=True)
        print(f"[INFO] Logs folder ready: {logs_folder}", file=sys.stderr)
        return logs_folder
    except Exception as e:
        print(f"[WARNING] Failed to create logs folder on Desktop: {e}", file=sys.stderr)
        return None

def main():
    """Ensure logs folder, then launch the GUI."""
    ensure_desktop_logs()
    
    # Import and launch the GUI main function
    from BlackholeGUI import main as gui_main
    gui_main()

if __name__ == "__main__":
    main()
