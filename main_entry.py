#!/usr/bin/env python3
"""
**main_entry.py**
Edited: January 2026
Created by: Prajeet (DDoS Response Team)

Entry point for the packaged .exe. Ensures desktop log folder structure exists
before launching the GUI. This script is the primary target for PyInstaller to create
the standalone .exe file.

Modernized with new theme system and modular architecture while maintaining
full feature parity with the legacy BlackholeGUI implementation.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk

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
    """Launch the GUI with new theme system applied."""
    ensure_desktop_logs()
    
    # Try to use new theme system
    try:
        import theme
        from BlackholeGUI import BlackholeGUI
        
        root = tk.Tk()
        
        # Hide window until it's fully built and styled
        root.withdraw()
        
        # Set window size and constraints
        root.geometry("950x800")  # Slightly smaller default size
        root.minsize(850, 650)    # Minimum size to keep UI usable
        
        # Apply modern theme (default to light mode)
        use_dark = os.environ.get("BH_DARK_MODE", "0") == "1"
        theme_name = "lumen.dark" if use_dark else "lumen.light"
        theme.apply_theme(root, theme_name)
        
        # Build the GUI (it will use the themed widgets automatically)
        gui = BlackholeGUI(root)
        
        # Add theme toggle to existing menu
        try:
            # Find the View menu that BlackholeGUI creates
            menubar = root.cget("menu")
            if menubar:
                menu_obj = root.nametowidget(menubar)
                # Check if View menu exists
                view_menu_index = None
                for i in range(menu_obj.index("end") + 1):
                    try:
                        label = menu_obj.entrycget(i, "label")
                        if label == "View":
                            view_menu_index = i
                            break
                    except Exception:
                        pass
                
                if view_menu_index is not None:
                    # Get the View submenu
                    view_menu = menu_obj.nametowidget(menu_obj.entrycget(view_menu_index, "menu"))
                    
                    # Add theme switching functions
                    def _apply_theme_mode(theme_name: str, dark: bool) -> None:
                        """Reapply theme and trigger double refresh for full widget update."""
                        theme.apply_theme(root, theme_name)
                        gui.dark_mode.set(dark)
                        gui.refresh_theme()
                        root.after(50, gui.refresh_theme)

                    def apply_light_theme():
                        _apply_theme_mode("lumen.light", False)

                    def apply_dark_theme():
                        _apply_theme_mode("lumen.dark", True)
                    
                    # Replace the existing Dark Mode toggle with our new ones
                    try:
                        # Remove old checkbutton
                        last_index = view_menu.index("end")
                        for i in range(last_index + 1):
                            try:
                                label = view_menu.entrycget(i, "label")
                                if "Dark Mode" in label or "Theme" in label:
                                    view_menu.delete(i)
                                    break
                            except Exception:
                                pass
                    except Exception:
                        pass
                    
                    # Add theme menu items with proper shortcuts
                    view_menu.add_separator()
                    view_menu.add_command(
                        label="Light Mode",
                        command=apply_light_theme,
                        accelerator="Ctrl+L"
                    )
                    view_menu.add_command(
                        label="Dark Mode (Matrix Style)",
                        command=apply_dark_theme,
                        accelerator="Ctrl+D"
                    )
                    
                    # Bind keyboard shortcuts
                    root.bind("<Control-l>", lambda e: apply_light_theme())
                    root.bind("<Control-d>", lambda e: apply_dark_theme())
        except Exception as e:
            print(f"[WARNING] Failed to enhance menu: {e}", file=sys.stderr)
        
        # Show the window now that it's fully built and styled
        root.deiconify()
        
        root.mainloop()
        
    except ImportError as e:
        print(f"[WARNING] New theme not available, using default: {e}", file=sys.stderr)
        # Fallback to legacy BlackholeGUI without theme enhancement
        from BlackholeGUI import main as gui_main
        gui_main()

def show_readme(root):
    """Display README in a new window."""
    import os
    readme_path = os.path.join(os.path.dirname(__file__), "README.md")
    if not os.path.exists(readme_path):
        from tkinter import messagebox
        messagebox.showinfo("Help", "README.md not found.")
        return
    
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        help_win = tk.Toplevel(root)
        help_win.title("User Guide")
        help_win.geometry("800x600")
        
        text = tk.Text(help_win, wrap="word", padx=20, pady=20)
        text.pack(fill="both", expand=True)
        text.insert("1.0", content)
        text.configure(state="disabled")
        
        scrollbar = ttk.Scrollbar(help_win, command=text.yview)
        scrollbar.pack(side="right", fill="y")
        text.configure(yscrollcommand=scrollbar.set)
    except Exception as e:
        from tkinter import messagebox
        messagebox.showerror("Error", f"Failed to open README: {e}")

if __name__ == "__main__":
    main()
