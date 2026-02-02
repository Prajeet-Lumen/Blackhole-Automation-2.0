"""
**Theme.py**
Edited: January 2026
Created by: Prajeet (DDoS Response Team)

Centralized ttk theme management for the Blackhole Automation GUI.

This module defines two accessible themes, that can be applied at runtime.  The design keeps all color
constants and typography tokens in one place so that future palette updates only
require touching this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

__all__ = [
    "ThemeTokens",
    "ThemeFonts",
    "ThemeManager",
    "apply_theme",
    "get_tokens",
    "get_fonts",
    "style_log_widget",
]


@dataclass(frozen=True)
class ThemeTokens:
    """Color tokens exposed by the theme manager."""

    bg: str
    bg_panel: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    danger: str
    danger_hover: str


@dataclass
class ThemeFonts:
    """Font handles created per-root so they can be re-used across widgets."""

    body: tkfont.Font
    body_bold: tkfont.Font
    heading: tkfont.Font
    heading_small: tkfont.Font
    monospace: tkfont.Font


# Brand-aligned, WCAG-compliant palettes for light and dark variants.
_THEME_DEFINITIONS: Dict[str, ThemeTokens] = {
    "lumen.light": ThemeTokens(
        bg="#f5f7fa",
        bg_panel="#ffffff",
        border="#d0d4dc",
        text="#101820",
        text_muted="#5f6a78",
        accent="#0078d4",  # Lumen Blue
        accent_hover="#0d8bf0",
        accent_pressed="#005a9e",
        danger="#c92a2a",
        danger_hover="#a02020",
    ),
    "lumen.dark": ThemeTokens(
        bg="#000000",           # Pure black for Matrix style
        bg_panel="#0a0f0a",     # Very dark green-tinted black
        border="#00ff00",       # Matrix green border
        text="#00ff00",         # Matrix green text
        text_muted="#00aa00",   # Dimmer green
        accent="#00ff00",       # Matrix green accent
        accent_hover="#33ff33", # Brighter green on hover
        accent_pressed="#00cc00",# Darker green when pressed
        danger="#ff0000",       # Red for danger (keep visible)
        danger_hover="#cc0000", # Darker red on hover
    ),
}

_DEFAULT_THEME = "lumen.light"


def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: Iterable[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in rgb)


def _blend(color_a: str, color_b: str, ratio: float) -> str:
    """Blend two colors (0.0 -> a, 1.0 -> b)."""

    a_r, a_g, a_b = _hex_to_rgb(color_a)
    b_r, b_g, b_b = _hex_to_rgb(color_b)
    return _rgb_to_hex(
        (
            int(a_r + (b_r - a_r) * ratio),
            int(a_g + (b_g - a_g) * ratio),
            int(a_b + (b_b - a_b) * ratio),
        )
    )


def _get_or_create_font(root: tk.Misc, name: str, **options: str) -> tkfont.Font:
    try:
        font = tkfont.nametofont(name)
        font.configure(**options)
    except tk.TclError:
        # Font doesn't exist, create it
        font = tkfont.Font(root=root, name=name, **options)
    return font


def _build_fonts(root: tk.Misc) -> ThemeFonts:
    """Create or refresh the font stack for the supplied root."""

    # Try to reuse existing font objects if they exist
    try:
        body = tkfont.nametofont("LumenBodyFont")
        body.configure(family="Segoe UI", size=8, weight="normal")
    except tk.TclError:
        body = tkfont.Font(root=root, name="LumenBodyFont", family="Segoe UI", size=8)
    
    try:
        body_bold = tkfont.nametofont("LumenBodyBoldFont")
        body_bold.configure(family="Segoe UI", size=8, weight="bold")
    except tk.TclError:
        body_bold = tkfont.Font(root=root, name="LumenBodyBoldFont", family="Segoe UI", size=8, weight="bold")
    
    try:
        heading = tkfont.nametofont("LumenHeadingFont")
        heading.configure(family="Segoe UI", size=16, weight="bold")
    except tk.TclError:
        heading = tkfont.Font(root=root, name="LumenHeadingFont", family="Segoe UI", size=16, weight="bold")
    
    try:
        heading_small = tkfont.nametofont("LumenHeadingSmallFont")
        heading_small.configure(family="Segoe UI", size=12, weight="bold")
    except tk.TclError:
        heading_small = tkfont.Font(root=root, name="LumenHeadingSmallFont", family="Segoe UI", size=12, weight="bold")
    
    try:
        monospace = tkfont.nametofont("LumenMonoFont")
        monospace.configure(family="Consolas", size=8, weight="normal")
    except tk.TclError:
        monospace = tkfont.Font(root=root, name="LumenMonoFont", family="Consolas", size=8)
    
    return ThemeFonts(
        body=body,
        body_bold=body_bold,
        heading=heading,
        heading_small=heading_small,
        monospace=monospace,
    )


class ThemeManager:
    """Apply brand-aligned ttk themes across the application."""

    def __init__(self) -> None:
        self._style: ttk.Style | None = None
        self._current_theme = _DEFAULT_THEME
        self._fonts: ThemeFonts | None = None

    @property
    def current_theme(self) -> str:
        return self._current_theme

    @property
    def fonts(self) -> ThemeFonts:
        if not self._fonts:
            raise RuntimeError("Theme fonts have not been initialized yet.")
        return self._fonts
    
    def _get_style(self) -> ttk.Style:
        """Lazy initialization of ttk.Style to avoid creating Tk root at import time."""
        if self._style is None:
            self._style = ttk.Style()
        return self._style

    def apply(self, root: tk.Misc, name: str) -> ThemeTokens:
        if name not in _THEME_DEFINITIONS:
            raise ValueError(f"Unknown theme '{name}'")

        tokens = _THEME_DEFINITIONS[name]
        
        # Reuse fonts if already built, otherwise build fresh
        if not self._fonts:
            fonts = _build_fonts(root)
            self._fonts = fonts
        else:
            fonts = self._fonts

        self._register_theme(name, tokens, fonts)
        style = self._get_style()
        style.theme_use(name)
        style.configure(".", background=tokens.bg, foreground=tokens.text, font=fonts.body)
        root.configure(background=tokens.bg)
        root.option_add("*Font", fonts.body)
        root.option_add("*Label.Font", fonts.body)
        root.option_add("*Entry.Font", fonts.body)
        
        # Fix combobox dropdown colors
        root.option_add("*TCombobox*Listbox*Background", tokens.bg_panel)
        root.option_add("*TCombobox*Listbox*Foreground", tokens.text)
        root.option_add("*TCombobox*Listbox*selectBackground", tokens.accent)
        root.option_add("*TCombobox*Listbox*selectForeground", tokens.bg_panel)
        root.option_add("*Combobox*Listbox*Background", tokens.bg_panel)
        root.option_add("*Combobox*Listbox*Foreground", tokens.text)
        root.option_add("*Combobox*Listbox*selectBackground", tokens.accent)
        root.option_add("*Combobox*Listbox*selectForeground", tokens.bg_panel)

        self._current_theme = name
        return tokens

    def get_tokens(self, name: str | None = None) -> ThemeTokens:
        target = name or self._current_theme
        return _THEME_DEFINITIONS[target]

    # ------------------------------------------------------------------
    # Theme registration helpers
    # ------------------------------------------------------------------
    def _register_theme(
        self, name: str, tokens: ThemeTokens, fonts: ThemeFonts
    ) -> None:
        settings = self._build_settings(tokens, fonts)
        style = self._get_style()
        try:
            style.theme_create(name, parent="clam", settings=settings)
        except tk.TclError:
            # Theme already exists – refresh settings.
            style.theme_settings(name, settings)
        self._apply_maps(tokens)

    def _build_settings(
        self, tokens: ThemeTokens, fonts: ThemeFonts
    ) -> Dict[str, Dict[str, Dict[str, object]]]:
        secondary_bg = _blend(tokens.bg_panel, tokens.bg, 0.15)
        card_bg = tokens.bg_panel
        disabled_text = _blend(tokens.text, tokens.bg, 0.55)
        entry_disabled_bg = _blend(tokens.bg_panel, tokens.bg, 0.25)

        return {
            ".": {
                "configure": {
                    "background": tokens.bg,
                    "foreground": tokens.text,
                    "font": fonts.body,
                }
            },
            "TFrame": {"configure": {"background": tokens.bg}},
            "Card.TFrame": {
                "configure": {
                    "background": card_bg,
                    "borderwidth": 1,
                    "relief": "solid",
                    "bordercolor": tokens.border,
                    "padding": 16,
                }
            },
            "TLabel": {
                "configure": {
                    "background": tokens.bg,
                    "foreground": tokens.text,
                    "font": fonts.body,
                }
            },
            "Header.TLabel": {
                "configure": {
                    "background": tokens.bg,
                    "foreground": tokens.text,
                    "font": fonts.heading,
                }
            },
            "Section.TLabel": {
                "configure": {
                    "background": tokens.bg,
                    "foreground": tokens.text_muted,
                    "font": fonts.heading_small,
                }
            },
            "Muted.TLabel": {
                "configure": {
                    "background": tokens.bg,
                    "foreground": tokens.text_muted,
                    "font": fonts.body,
                }
            },
            "Status.TLabel": {
                "configure": {
                    "background": secondary_bg,
                    "foreground": tokens.text,
                    "font": fonts.body_bold,
                }
            },
            "TButton": {
                "configure": {
                    "background": secondary_bg,
                    "foreground": tokens.text,
                    "borderwidth": 2,
                    "padding": (6, 3),
                    "relief": "solid",
                    "focuscolor": tokens.accent,
                }
            },
            "Primary.TButton": {
                "configure": {
                    "background": tokens.accent,
                    "foreground": tokens.bg_panel,
                    "borderwidth": 2,
                    "padding": (8, 4),
                    "font": fonts.body_bold,
                    "relief": "solid",
                }
            },
            "Secondary.TButton": {
                "configure": {
                    "background": secondary_bg,
                    "foreground": tokens.text,
                    "borderwidth": 2,
                    "padding": (8, 4),
                    "font": fonts.body_bold,
                    "relief": "solid",
                }
            },
            "Danger.TButton": {
                "configure": {
                    "background": tokens.danger,
                    "foreground": tokens.bg_panel,
                    "borderwidth": 2,
                    "padding": (8, 4),
                    "font": fonts.body_bold,
                    "relief": "solid",
                }
            },
            "TEntry": {
                "configure": {
                    "padding": (6, 4),
                    "fieldbackground": card_bg,
                    "foreground": tokens.text,
                    "borderwidth": 0,
                    "relief": "flat",
                    "insertcolor": tokens.text,
                    "selectbackground": tokens.accent,
                    "selectforeground": tokens.bg_panel,
                }
            },
            "TCombobox": {
                "configure": {
                    "padding": (6, 4),
                    "fieldbackground": card_bg,
                    "foreground": tokens.text,
                    "background": card_bg,
                    "readonlybackground": card_bg,
                    "selectbackground": tokens.accent,
                    "selectforeground": tokens.bg_panel,
                    "arrowcolor": tokens.text,
                    "borderwidth": 0,
                    "relief": "flat",
                    "arrowsize": 14,
                }
            },
            "TNotebook": {
                "configure": {
                    "background": tokens.bg,
                    "borderwidth": 0,
                    "tabmargins": (0, 0, 0, 0),
                }
            },
            "TNotebook.Tab": {
                "configure": {
                    "padding": (12, 6),
                    "font": fonts.body_bold,
                    "foreground": tokens.text_muted,
                    "background": tokens.bg,
                    "borderwidth": 0,
                    "relief": "flat",
                }
            },
            "TLabelframe": {
                "configure": {
                    "background": card_bg,
                    "bordercolor": tokens.border,
                    "borderwidth": 0,
                    "relief": "flat",
                    "labeloutside": False,
                    "padding": 12,
                }
            },
            "TLabelframe.Label": {
                "configure": {
                    "background": card_bg,
                    "foreground": tokens.text,
                    "font": fonts.body_bold,
                }
            },
            "Treeview": {
                "configure": {
                    "background": card_bg,
                    "fieldbackground": card_bg,
                    "foreground": tokens.text,
                    "borderwidth": 1,
                    "rowheight": 24,
                }
            },
            "Treeview.Heading": {
                "configure": {
                    "background": tokens.bg,
                    "foreground": tokens.text,
                    "relief": "flat",
                    "font": fonts.body_bold,
                    "padding": (8, 6),
                }
            },
            "TScrollbar": {
                "configure": {
                    "background": secondary_bg,
                    "troughcolor": card_bg,
                    "borderwidth": 0,
                    "relief": "flat",
                    "width": 12,
                }
            },
            "TProgressbar": {
                "configure": {
                    "background": tokens.accent,
                    "troughcolor": card_bg,
                    "bordercolor": card_bg,
                    "lightcolor": tokens.accent_hover,
                    "darkcolor": tokens.accent_pressed,
                    "thickness": 4,
                    "borderwidth": 0,
                }
            },
        }

    def _apply_maps(self, tokens: ThemeTokens) -> None:
        style = self._get_style()
        disabled_btn_bg = _blend(tokens.bg, tokens.bg_panel, 0.15)
        disabled_text = _blend(tokens.text, tokens.bg, 0.6)
        secondary_bg = _blend(tokens.bg_panel, tokens.bg, 0.15)
        secondary_hover = _blend(tokens.bg_panel, tokens.accent, 0.12)
        readonly_field_bg = tokens.bg_panel
        entry_disabled_bg = _blend(tokens.bg_panel, tokens.bg, 0.35)

        style.map(
            "TButton",
            background=[
                ("disabled", disabled_btn_bg),
                ("pressed", tokens.accent_pressed),
                ("active", tokens.accent_hover),
            ],
            foreground=[
                ("disabled", disabled_text),
                ("!disabled", tokens.text),
            ],
        )
        style.map(
            "Primary.TButton",
            background=[
                ("disabled", _blend(tokens.accent, tokens.bg, 0.5)),
                ("pressed", tokens.accent_pressed),
                ("active", tokens.accent_hover),
            ],
            foreground=[
                ("disabled", disabled_text),
                ("!disabled", tokens.bg_panel),
            ],
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("disabled", disabled_btn_bg),
                ("pressed", secondary_hover),
                ("active", secondary_hover),
            ],
            foreground=[
                ("disabled", disabled_text),
                ("!disabled", tokens.text),
            ],
        )
        style.map(
            "Danger.TButton",
            background=[
                ("disabled", _blend(tokens.danger, tokens.bg, 0.5)),
                ("pressed", tokens.danger_hover),
                ("active", tokens.danger_hover),
            ],
            foreground=[
                ("disabled", disabled_text),
                ("!disabled", tokens.bg_panel),
            ],
        )
        style.map(
            "TEntry",
            fieldbackground=[
                ("readonly", readonly_field_bg),
                ("disabled", entry_disabled_bg),
            ],
            foreground=[("disabled", disabled_text)],
            bordercolor=[
                ("focus", tokens.accent),
                ("invalid", tokens.danger),
            ],
        )
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", readonly_field_bg),
                ("disabled", entry_disabled_bg),
                ("focus", tokens.bg_panel),
            ],
            foreground=[("disabled", disabled_text)],
            background=[
                ("readonly", readonly_field_bg),
                ("disabled", entry_disabled_bg),
            ],
            arrowcolor=[
                ("disabled", disabled_text),
                ("!disabled", tokens.text),
            ],
            bordercolor=[
                ("focus", tokens.accent),
                ("disabled", tokens.border),
            ],
        )
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", tokens.bg_panel),
                ("active", _blend(tokens.bg_panel, tokens.accent, 0.08)),
                ("!selected", tokens.bg),
            ],
            foreground=[
                ("selected", tokens.accent),
                ("active", tokens.text),
                ("!selected", tokens.text_muted),
            ],
        )
        style.map(
            "Treeview",
            background=[("selected", tokens.accent)],
            foreground=[("selected", tokens.bg_panel)],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", _blend(tokens.bg_panel, tokens.accent, 0.1))],
        )
        style.map(
            "TScrollbar",
            background=[
                ("active", _blend(secondary_bg, tokens.accent, 0.18)),
                ("!disabled", secondary_bg),
            ],
        )
        style.map(
            "TProgressbar",
            background=[
                ("!disabled", tokens.accent),
            ],
        )


# Singleton manager used by the application.
_theme_manager = ThemeManager()


def apply_theme(root: tk.Misc, name: str = _DEFAULT_THEME) -> ThemeTokens:
    """Apply the requested theme to ``root`` and return its tokens."""

    return _theme_manager.apply(root, name)


def get_tokens(name: str | None = None) -> ThemeTokens:
    """Return the tokens for the active theme (or ``name`` if provided)."""

    return _theme_manager.get_tokens(name)


def get_fonts() -> ThemeFonts:
    """Return the font stack associated with the active theme."""

    return _theme_manager.fonts


def style_log_widget(widget: tk.Text, *, theme_name: str | None = None) -> None:
    """Apply consistent styling to text-based log widgets."""

    tokens = get_tokens(theme_name)
    fonts = _theme_manager.fonts
    widget.configure(
        background=tokens.bg_panel,
        foreground=tokens.text,
        insertbackground=tokens.accent,
        selectbackground=tokens.accent,
        selectforeground=tokens.bg_panel,
        highlightthickness=1,
        highlightbackground=tokens.border,
        highlightcolor=tokens.accent,
        relief="flat",
        font=fonts.monospace,
        padx=8,
        pady=6,
    )
