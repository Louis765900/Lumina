"""
Lumina — Windows 98 color palette.

Import pattern in screen modules:
    from app.ui.palette import CARD as _CARD, BORDER as _BORDER, ...
"""

# ── Win98 core ────────────────────────────────────────────────────────────────
WIN98_SILVER  = "#E6E9EF"   # window surface / button face
WIN98_WHITE   = "#FFFFFF"   # highlight edge (top/left bevel)
WIN98_GRAY    = "#B7BEC9"   # shadow edge (bottom/right bevel)
WIN98_DARK    = "#667085"   # darker shadow for deep recesses
WIN98_BLACK   = "#111827"   # outer shadow / text
WIN98_NAVY    = "#163F73"   # title bar start, selection background
WIN98_TEAL    = "#DCE3EC"   # desktop background
WIN98_TITLE1  = "#12396D"   # title bar gradient start
WIN98_TITLE2  = "#1C6EAE"   # title bar gradient end

# ── Backgrounds ───────────────────────────────────────────────────────────────
BG      = WIN98_TEAL        # desktop canvas
BG2     = WIN98_SILVER      # window inner surface
SIDEBAR = WIN98_SILVER      # sidebar panel

# ── Surfaces ──────────────────────────────────────────────────────────────────
CARD    = WIN98_SILVER
BORDER  = WIN98_GRAY

# ── Text ──────────────────────────────────────────────────────────────────────
TEXT  = WIN98_BLACK
TEXT2 = WIN98_BLACK
SUB   = "#475467"
MUTED = "#7B8494"

# ── Accents ───────────────────────────────────────────────────────────────────
ACCENT            = WIN98_NAVY
ACCENT2           = WIN98_TITLE2
ACCENT_HOVER      = "#0F315B"
ACCENT_SELECTION  = WIN98_NAVY

# ── Status ────────────────────────────────────────────────────────────────────
OK     = "#16864C"
OK_BG  = "#EAF7EF"
WARN   = "#A15C00"
ERR    = "#9F1D1D"

# ── Interactive ───────────────────────────────────────────────────────────────
HOVER   = "#EDF3FA"
HBORDER = WIN98_NAVY

# ── Bevel helpers (for inline widget styles) ──────────────────────────────────
# Raised (button default): top/left white, bottom/right gray
BEVEL_LIGHT  = WIN98_WHITE
BEVEL_SHADOW = WIN98_GRAY

# Sunken (input / clicked): top/left gray, bottom/right white
BEVEL_INSET_LIGHT  = WIN98_GRAY
BEVEL_INSET_SHADOW = WIN98_WHITE

# Title bar text
TITLE_TEXT = "#FFFFFF"
