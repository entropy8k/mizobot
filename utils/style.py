"""Shared look & feel so every embed matches."""
import re
import time
import discord

CURRENCY = "M$"

class C:
    BRAND = 0x9B7BFF     # mizo purple
    OK = 0x57F287
    BAD = 0xED4245
    WARN = 0xFEE75C
    INFO = 0x5865F2
    MOD = 0xFF6B6B
    GOLD = 0xF1C40F
    DARK = 0x2B2D31

def money(n: int) -> str:
    return f"**{CURRENCY}{n:,}**"

def embed(title=None, description=None, color=C.BRAND, footer=True) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
    if footer:
        e.set_footer(text="mizobot ✦")
    return e

def ts(unix: int, style="R") -> str:
    return f"<t:{int(unix)}:{style}>"

_DUR = re.compile(r"(\d+)\s*([smhdw])", re.I)
_MULT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

def parse_duration(text: str):
    """'10m', '2h30m', '1d' -> seconds. None if unparsable."""
    parts = _DUR.findall(text or "")
    if not parts or _DUR.sub("", text).strip():
        return None
    return sum(int(n) * _MULT[u.lower()] for n, u in parts)

def fmt_duration(seconds: int) -> str:
    out = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            out.append(f"{seconds // size}{name}")
            seconds %= size
    return " ".join(out) or "0s"


_NAMED = {"red": 0xED4245, "orange": 0xE67E22, "yellow": 0xFEE75C, "green": 0x57F287, "blue": 0x5865F2,
          "purple": 0x9B7BFF, "pink": 0xFF69B4, "white": 0xFFFFFF, "black": 0x010101, "gold": 0xF1C40F, "cyan": 0x1ABC9C}

def parse_color(text):
    """'#ff00aa', 'f0a', or a name like 'red' -> int. Empty -> None meaning 'use default'. Invalid -> False."""
    t = (text or "").strip().lower().lstrip("#")
    if not t:
        return None
    if t in _NAMED:
        return _NAMED[t]
    if re.fullmatch(r"[0-9a-f]{3}", t):
        t = "".join(c * 2 for c in t)
    if re.fullmatch(r"[0-9a-f]{6}", t):
        return int(t, 16)
    return False
