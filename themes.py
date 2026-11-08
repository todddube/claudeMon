"""Colour themes. Values are xterm-256 colour indices; -1 is the terminal default.

`grad` runs low → high and colours graphs and gauges by height, btop-style.
`series` colours one line per model or project.
"""

THEMES = {
    "claude": dict(
        bg=-1, fg=252, dim=244, border=239, title=216, accent=209, hl_bg=237,
        ok=114, warn=221, crit=203, info=110,
        grad=[66, 73, 179, 209, 203], series=[209, 110, 150, 183, 221, 116, 174]),
    "btop": dict(
        bg=-1, fg=253, dim=245, border=60, title=255, accent=81, hl_bg=236,
        ok=118, warn=220, crit=196, info=75,
        grad=[34, 40, 184, 214, 196], series=[81, 213, 118, 220, 141, 208, 51]),
    "dracula": dict(
        bg=235, fg=255, dim=103, border=61, title=212, accent=141, hl_bg=238,
        ok=84, warn=228, crit=203, info=117,
        grad=[61, 141, 212, 215, 203], series=[141, 212, 117, 84, 228, 215, 203]),
    "nord": dict(
        bg=236, fg=253, dim=246, border=60, title=110, accent=109, hl_bg=238,
        ok=108, warn=222, crit=167, info=110,
        grad=[67, 109, 110, 222, 167], series=[110, 108, 222, 139, 109, 173, 167]),
    "gruvbox": dict(
        bg=235, fg=223, dim=245, border=239, title=214, accent=208, hl_bg=237,
        ok=142, warn=214, crit=167, info=109,
        grad=[106, 142, 214, 208, 167], series=[208, 109, 142, 175, 214, 108, 167]),
    "matrix": dict(
        bg=16, fg=46, dim=28, border=22, title=118, accent=82, hl_bg=22,
        ok=46, warn=190, crit=196, info=48,
        grad=[22, 28, 34, 40, 46], series=[46, 118, 48, 190, 82, 156, 120]),
    "amber": dict(
        bg=16, fg=214, dim=130, border=94, title=220, accent=208, hl_bg=52,
        ok=214, warn=220, crit=196, info=178,
        grad=[94, 130, 172, 214, 220], series=[214, 178, 220, 172, 208, 136, 222]),
    "c64": dict(
        bg=19, fg=147, dim=104, border=63, title=231, accent=153, hl_bg=61,
        ok=120, warn=228, crit=210, info=153,
        grad=[63, 105, 147, 153, 231], series=[153, 120, 228, 210, 183, 116, 231]),
    "synthwave": dict(
        bg=17, fg=225, dim=97, border=54, title=213, accent=51, hl_bg=53,
        ok=51, warn=227, crit=197, info=87,
        grad=[54, 91, 163, 205, 227], series=[213, 51, 227, 141, 205, 87, 197]),
    "mono": dict(
        bg=-1, fg=252, dim=243, border=240, title=255, accent=255, hl_bg=238,
        ok=252, warn=255, crit=255, info=250,
        grad=[240, 244, 248, 252, 255], series=[255, 250, 245, 252, 247, 243, 254]),
}

ORDER = list(THEMES)
