"""
Lumina — Centralized color palette.

Import pattern in screen modules:
    from app.ui.palette import CARD as _CARD, BORDER as _BORDER, ...
"""

# ── Backgrounds ───────────────────────────────────────────────────────────────
BG      = "#0D0E1A"
BG2     = "#0F1120"
SIDEBAR = "#1a1b27"

# ── Surfaces ──────────────────────────────────────────────────────────────────
CARD    = "rgba(255,255,255,0.04)"
BORDER  = "rgba(255,255,255,0.08)"

# ── Text ──────────────────────────────────────────────────────────────────────
TEXT  = "#FFFFFF"
TEXT2 = "#F1F5F9"   # slightly warmer white for content-heavy screens
SUB   = "#94A3B8"
MUTED = "#64748B"

# ── Accents ───────────────────────────────────────────────────────────────────
ACCENT       = "#007AFF"    # iOS blue — primary action color
ACCENT2      = "#34AADC"    # secondary blue used in the scan ring gradient
ACCENT_HOVER = "#005FCC"    # darker hover state for primary buttons

# Selection highlight (Tailwind blue-500) — used for checkbox/card selection
ACCENT_SELECTION = "#3B82F6"

# ── Status ────────────────────────────────────────────────────────────────────
OK     = "#34C759"
OK_BG  = "rgba(52,199,89,0.1)"
WARN   = "#F59E0B"
ERR    = "#EF4444"

# ── Interactive ───────────────────────────────────────────────────────────────
HOVER   = "rgba(255,255,255,0.05)"
HBORDER = "rgba(0,122,255,0.5)"   # disk card hover border (HomeScreen)
