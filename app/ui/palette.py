"""
Lumina — Windows 98 color palette.

Import pattern in screen modules:
    from app.ui.palette import CARD as _CARD, BORDER as _BORDER, ...
"""

# ── Win98 core ────────────────────────────────────────────────────────────────
WIN98_SILVER  = "#C0C0C0"   # window surface / button face
WIN98_WHITE   = "#FFFFFF"   # highlight edge (top/left bevel)
WIN98_GRAY    = "#808080"   # shadow edge (bottom/right bevel)
WIN98_DARK    = "#404040"   # darker shadow for deep recesses
WIN98_BLACK   = "#000000"   # outer shadow / text
WIN98_NAVY    = "#000080"   # title bar start, selection background
WIN98_TEAL    = "#008080"   # desktop background
WIN98_TITLE1  = "#000080"   # title bar gradient start
WIN98_TITLE2  = "#1084D0"   # title bar gradient end

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
SUB   = "#404040"
MUTED = WIN98_GRAY

# ── Accents ───────────────────────────────────────────────────────────────────
ACCENT            = WIN98_NAVY
ACCENT2           = WIN98_TITLE2
ACCENT_HOVER      = "#000060"
ACCENT_SELECTION  = WIN98_NAVY

# ── Status ────────────────────────────────────────────────────────────────────
OK     = "#008000"
OK_BG  = "#C0C0C0"
WARN   = "#808000"
ERR    = "#800000"

# ── Interactive ───────────────────────────────────────────────────────────────
HOVER   = "#D4D0C8"
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
