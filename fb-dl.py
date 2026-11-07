#!/usr/bin/env python3
"""fb-dl - download every post (text, photos, videos, reels, stories) of a Facebook profile or page,
from the first post to today, in the best quality.

How it works
------------
1. Log in        --login opens a browser window, you log in yourself and the cookies are saved to
                 fb-session.json (or pass --cookies with a cookies.txt / JSON export).
2. Collect       Job + Timeline: Playwright opens the profile in Edge / Chrome and scrolls to the
                 first post. Every GraphQL response (and the JSON embedded in the first page) is parsed
                 into stories (parse_graphql() + find_stories()), then into post dicts (parse_story()).
                 Ads and posts of other pages are dropped (is_own()). Active stories are read from the
                 story viewer page without clicking anything (Timeline._stories()).
3. Plan          plan_post(): photos are completed from the photo viewer (PhotoViewer, plain requests)
                 when the timeline only has previews or part of a big album.
4. Download      Run.consume() downloads in its own thread while the timeline is still being scrolled:
                 photos with aria2c (or requests), videos with yt-dlp + ffmpeg (cookies in memory),
                 falling back to the direct MP4 links.
                 The Photos / Albums tabs are read in the same browser (Timeline._tabs(); the grid already
                 has the full-size links) and saved with aria2c (Run.tabs()). Photos already on disk are
                 hard-linked instead of downloaded again.
5. Save          posts/ (text), images/, videos/, reels/, stories/, photos/, albums/, metadata/<id>.json,
                 posts.csv, failed.txt. Progress is kept in .progress.db, so a re-run skips finished posts.

The logged-in account is never printed (mask_name()) nor saved (hide_viewer(), scrub()).
Messages are bilingual: t("English", "Tiếng Việt"). Please add both when you add a message.
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional
from urllib.parse import parse_qs, urlparse

import requests

__version__ = "1.2.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
FB = "https://www.facebook.com"
SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_FILE = SCRIPT_DIR / "fb-session.json"

LANG = "en"


def t(en: str, vi: str) -> str:
    """Pick the message for the current language."""
    return vi if LANG == "vi" else en


def detect_lang(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1].lower()
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1].lower()
    env = os.environ.get("FB_DL_LANG", "").lower()
    if env in ("en", "vi"):
        return env
    try:
        import locale
        name = (locale.getlocale()[0] or "").lower()
    except Exception:
        name = ""
    return "vi" if name.startswith(("vi", "vietnam")) else "en"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Console output
# --------------------------------------------------------------------------- #

_print_lock = threading.RLock()
_status_line = ""
_COLOR = False
_TTY = sys.stdout.isatty()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _style(code: str):
    return lambda s: f"\x1b[{code}m{s}\x1b[0m" if _COLOR else str(s)


bold = _style("1")
gray = _style("90")
red = _style("31")
green = _style("32")
yellow = _style("33")
blue = _style("34")
magenta = _style("35")
cyan = _style("36")
bold_red = _style("1;31")
bold_green = _style("1;32")
bold_cyan = _style("1;36")
link = _style("4;34")


def init_colors(enabled: bool) -> None:
    """Enable ANSI colors when running in a terminal (Windows 10+ needs VT mode switched on)."""
    global _COLOR
    forced = bool(os.environ.get("FORCE_COLOR"))
    if not enabled or os.environ.get("NO_COLOR") or not (_TTY or forced):
        _COLOR = False
        return
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            for handle_id in (-11, -12):
                handle = kernel32.GetStdHandle(handle_id)
                mode = ctypes.c_uint32()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(handle, mode.value | 0x0004)   # 0x0004 = virtual terminal (ANSI)
        except Exception:
            _COLOR = False
            return
    _COLOR = True


def visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _width() -> int:
    return max(40, shutil.get_terminal_size((100, 20)).columns - 1)


def _clear_status() -> None:
    if _status_line and _TTY:
        sys.stdout.write("\r" + " " * _width() + "\r")


def _draw_status() -> None:
    if not (_status_line and _TTY):
        return
    w = _width()
    line = _status_line
    if visible_len(line) > w:
        line = _ANSI_RE.sub("", line)[:w]
    sys.stdout.write("\r" + line + " " * max(0, w - visible_len(line)))
    sys.stdout.flush()


_LOG_FILE = None   # fb-dl.log of the profile being downloaded (open_log())


def log(msg: str = "", err: bool = False) -> None:
    """Print a log line above the status line, then redraw it. Also written to fb-dl.log, without
    colors and with the time."""
    with _print_lock:
        _clear_status()
        sys.stdout.flush()
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)
        _draw_status()
        if _LOG_FILE:
            stamp = datetime.now().strftime("%H:%M:%S")
            try:
                for line in _ANSI_RE.sub("", str(msg)).splitlines() or [""]:
                    _LOG_FILE.write(f"{stamp}  {line}\n" if line.strip() else "\n")
                _LOG_FILE.flush()
            except (OSError, ValueError):
                pass


def open_log(path: Path, title: str) -> None:
    """Append this run to `path` (fb-dl.log in the profile folder)."""
    global _LOG_FILE
    close_log()
    try:
        _LOG_FILE = open(path, "a", encoding="utf-8")
        _LOG_FILE.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} · fb-dl {__version__} · {title} =====\n")
    except OSError:
        _LOG_FILE = None


def close_log() -> None:
    global _LOG_FILE
    with _print_lock:
        if _LOG_FILE:
            try:
                _LOG_FILE.close()
            except OSError:
                pass
        _LOG_FILE = None


def status(msg: str) -> None:
    """Set the bottom status line (empty string clears it). Only shown in a terminal."""
    global _status_line
    with _print_lock:
        _clear_status()
        _status_line = msg
        _draw_status()


def warn(msg: str) -> str:
    return f"  {yellow('!')} {yellow(msg)}"


def fmt_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0 or seconds > 99 * 3600:
        return "--:--"
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def fmt_int(v) -> str:
    try:
        return f"{int(v):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "?"


class ProgressBar:
    """The live status line, redrawn 8 times per second.

    While the timeline is still being scrolled, the number of posts keeps growing:
        ⠹ Scrolling · 640 found, back to 2016-03  │  ━━━━━━╸━━━━━━━━━  120/640 saved  │  1.9 GB · 12.4 MB/s  │  0 failed
    Once scrolling is done it becomes a normal bar with a percentage and ETA:
        ⠹ ━━━━━━━━━━━━━╸━━━━━━━━   42%  525/1250 saved  │  1.9 GB · 12.4 MB/s  │  ETA 08:12  │  0 failed
    Parts that do not fit the terminal width are left out, least important first.
    """

    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, total: int = 0, scrolling: bool = False, unit: tuple[str, str] = ("saved", "đã lưu")):
        self.total = total
        self.scrolling = scrolling
        self.oldest = 0                        # oldest post found so far (while scrolling)
        self.note = ""                         # what the browser is doing, shown instead of the scroll text
        self.unit = unit
        self.ok = self.failed = 0
        self.base_bytes = 0
        self.watched: list[Path] = []          # files aria2c is writing right now
        self.live: dict[str, int] = {}         # bytes of files being written by yt-dlp / requests
        self.samples: list[tuple[float, int]] = []
        self.started = time.monotonic()
        self.frame = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        status("")

    # -- counters --------------------------------------------------------- #

    def found(self, n: int = 1, created: int = 0) -> None:
        """More posts to download (while scrolling)."""
        with self._lock:
            self.total += n
            if created and (not self.oldest or created < self.oldest):
                self.oldest = created

    def scroll_done(self) -> None:
        with self._lock:
            self.scrolling = False
            self.note = ""

    def set_note(self, text: str) -> None:
        with self._lock:
            self.note = text

    def post_done(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.ok += 1
            else:
                self.failed += 1

    # -- bytes ------------------------------------------------------------ #

    def watch(self, paths: list[Path]) -> None:
        """Count the bytes aria2c writes to these files (they are all re-downloaded from zero)."""
        with self._lock:
            self.watched = list(paths)

    def unwatch(self) -> None:
        """Keep the bytes of the watched files that are still there (invalid ones are deleted first)."""
        with self._lock:
            self.base_bytes += sum(p.stat().st_size for p in self.watched if p.exists())
            self.watched = []

    def add(self, n: int) -> None:
        with self._lock:
            self.base_bytes += n

    def set_live(self, key: str, n: int) -> None:
        with self._lock:
            self.live[key] = n

    def forget(self, prefix: str) -> None:
        """Drop the in-progress bytes of a download that failed or was handed over."""
        with self._lock:
            for key in [k for k in self.live if k.startswith(prefix)]:
                del self.live[key]

    def ytdl_hook(self, d: dict) -> None:
        key = d.get("filename") or d.get("tmpfilename") or "?"
        got = int(d.get("downloaded_bytes") or 0)
        with self._lock:
            if d.get("status") == "finished":
                self.base_bytes += got or int(d.get("total_bytes") or 0)
                self.live.pop(key, None)
            else:
                self.live[key] = got

    def _bytes(self) -> int:
        with self._lock:
            watched = list(self.watched)
            total = self.base_bytes + sum(self.live.values())
        for p in watched:
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    # -- drawing ---------------------------------------------------------- #

    def _loop(self) -> None:
        while not self._stop.wait(0.125):
            self.render()

    @staticmethod
    def _bar(frac: float, width: int) -> str:
        if _COLOR:
            halves = int(frac * width * 2)
            full, half = divmod(halves, 2)
            done = "━" * full + ("╸" if half else "")
            rest = "━" * (width - full - (1 if half else 0))
            return (green if frac >= 1 else cyan)(done) + gray(rest)
        eighths = int(frac * width * 8)
        full, part = divmod(eighths, 8)
        partial = " ▏▎▍▌▋▊▉"[part] if part else ""
        return "█" * full + partial + "░" * (width - full - (1 if partial else 0))

    def line(self, width: int) -> str:
        """The status line for a terminal `width` columns wide."""
        now = time.monotonic()
        got = self._bytes()
        self.samples = [s for s in self.samples if now - s[0] <= 5] + [(now, got)]
        t0, b0 = self.samples[0]
        speed = (got - b0) / (now - t0) if now - t0 >= 0.5 else 0.0
        with self._lock:
            total, ok, failed, scrolling, oldest = self.total, self.ok, self.failed, self.scrolling, self.oldest
            note = self.note
        finished = ok + failed
        frac = min(1.0, finished / total) if total else 0.0
        self.frame = (self.frame + 1) % len(self.SPINNER)
        sep = gray("  │  ")
        spinner = cyan(self.SPINNER[self.frame]) if _COLOR else "*"

        head = ""
        if note:
            head = cyan(note) + sep
        elif scrolling:
            back = f"{datetime.fromtimestamp(oldest):%Y-%m}" if oldest else "..."
            head = cyan(t(f"Scrolling · {total} found, back to {back}",
                          f"Đang cuộn · thấy {total} bài, tới {back}")) + sep
        pct = "" if scrolling else bold(f"{frac * 100:3.0f}%") + "  "
        counter = f"{pct}{bold(f'{finished}/{total}')} {t(*self.unit)}"
        # (text, importance): when the line is too long the least important part goes first.
        parts = [(f"{fmt_bytes(got)} · {cyan(fmt_bytes(speed) + '/s')}", 2)]
        if not scrolling:
            eta = (now - self.started) / finished * (total - finished) if finished else None
            parts.append((f"ETA {yellow(fmt_eta(eta))}", 3))
        parts.append(((red if failed else gray)(t(f"{failed} failed", f"{failed} lỗi")), 4))

        def build(bar_w: int) -> str:
            middle = f"{self._bar(frac, bar_w)}  {counter}" if bar_w else counter
            return f"  {spinner} {head}" + sep.join([middle] + [p for p, _ in parts])

        while True:
            bar_w = min(30, width - visible_len(build(0)) - 2)
            if bar_w >= 10 or not parts:
                break
            parts.remove(min(parts, key=lambda x: x[1]))
        return build(bar_w if bar_w >= 10 else 0)

    def render(self) -> None:
        status(self.line(_width()))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

class ScrapeError(Exception):
    pass


def find_tool(name: str) -> Optional[str]:
    """Prefer an executable next to fb-dl.py (aria2c.exe, ffmpeg.exe), then PATH."""
    for cand in (SCRIPT_DIR / f"{name}.exe", SCRIPT_DIR / name):
        if cand.is_file():
            return str(cand)
    return shutil.which(name)


def find_ffmpeg() -> Optional[str]:
    path = find_tool("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def utf16_len(text: str) -> int:
    """Length as Windows counts it (an emoji is 2 units)."""
    return len(text.encode("utf-16-le")) // 2


def sanitize(text: str, limit: int = 50) -> str:
    """Safe file-name part: no forbidden / invisible characters, at most `limit` UTF-16 units."""
    text = re.sub(r"[\r\n\t]+", " ", text or "")
    # Windows-forbidden characters, plus bidi / zero-width control characters that can hide the real name.
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f#\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]', "", text)
    text = re.sub(r"\s+", " ", text).strip()
    while text and utf16_len(text) > limit:
        text = text[:-1]
    text = text.rstrip(". ")
    return f"{text}_" if text.upper() in WINDOWS_RESERVED else text


def json_unescape(s: str) -> str:
    """Decode a JSON string body cut out of a page with a regex (\\/ \\u00e9 ...)."""
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s.replace("\\/", "/")


def looks_like_media(data: bytes) -> bool:
    """False for an HTML / JSON error page served instead of a file."""
    return bool(data) and data.lstrip()[:1] not in (b"<", b"{")


def to_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def uniq(seq) -> list:
    return list(dict.fromkeys(x for x in seq if x))


def first(obj, key: str, pred: Optional[Callable] = None, skip: tuple = ("attached_story",)):
    """Depth-first search for the first value stored under `key` (optionally matching `pred`)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if key in cur and (pred is None or pred(cur[key])):
                return cur[key]
            stack.extend(v for k, v in reversed(list(cur.items())) if k not in skip)
        elif isinstance(cur, list):
            stack.extend(reversed(cur))
    return None


def iter_dicts(obj, pred: Callable[[dict], bool]) -> Iterator[dict]:
    """Every nested dict matching `pred` (not looking inside a match)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if pred(cur):
                yield cur
                continue
            stack.extend(reversed(list(cur.values())))
        elif isinstance(cur, list):
            stack.extend(reversed(cur))


def dig(obj, *keys, default=None):
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        elif isinstance(obj, list) and isinstance(k, int) and -len(obj) <= k < len(obj):
            obj = obj[k]
        else:
            return default
    return obj


def parse_date(text: Optional[str], end: bool = False) -> Optional[int]:
    if not text:
        return None
    try:
        d = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(t(f"bad date {text!r}, use YYYY-MM-DD",
                                           f"ngày {text!r} sai, dùng dạng YYYY-MM-DD"))
    ts = int(d.timestamp())
    return ts + 86399 if end else ts   # --until includes the whole day (up to 23:59:59)


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #

POST_RE = re.compile(
    r"/(?:[^/?#]+/posts/|permalink\.php|story\.php|photo(?:\.php)?/?\?|[^/?#]+/photos/|reel/|"
    r"[^/?#]+/videos/|watch/?\?|share/[prv]/|groups/[^/?#]+/(?:posts|permalink)/|videos/)", re.I)
RESERVED = {"login", "home.php", "watch", "groups", "events", "marketplace", "reel", "reels", "share",
            "photo", "photo.php", "story.php", "permalink.php", "media", "pages", "help", "settings"}


class Target:
    """What the user typed, turned into the URL to open and a folder name."""

    def __init__(self, text: str):
        raw = text.strip()
        if raw.startswith("@"):
            raw = raw[1:]
        if re.match(r"^(?:https?://)?fb\.watch/", raw, re.I):
            raw = raw if raw.lower().startswith("http") else f"https://{raw}"
        elif not re.match(r"^https?://", raw, re.I):
            if "facebook.com" in raw.lower():
                raw = f"https://{raw}"
            elif re.fullmatch(r"\d{5,}", raw):
                raw = f"{FB}/profile.php?id={raw}"
            elif re.fullmatch(r"[\w.\-]{2,80}", raw):
                raw = f"{FB}/{raw}"
            else:
                raise ScrapeError(t(f'not a Facebook profile, page or post: "{text}"',
                                    f'không nhận ra profile, page hay bài Facebook: "{text}"'))
        u = urlparse(raw)
        host = u.netloc.lower()
        if not (host.endswith("facebook.com") or host == "fb.watch"):
            raise ScrapeError(t(f'not a Facebook link: "{text}"', f'không phải link Facebook: "{text}"'))
        path = u.path or "/"
        self.is_post = bool(host == "fb.watch" or POST_RE.search(path + ("?" + u.query if u.query else "")))
        # Always use www.facebook.com (m. / web. / mbasic. links work the same way).
        self.url = raw if host == "fb.watch" else f"{FB}{path}" + (f"?{u.query}" if u.query else "")
        self.slug = ""
        if not self.is_post:
            qs = parse_qs(u.query)
            parts = [p for p in path.split("/") if p]
            if path.startswith("/profile.php") and qs.get("id"):
                self.slug = qs["id"][0]
                self.url = f"{FB}/profile.php?id={self.slug}"
            elif len(parts) >= 3 and parts[0] == "people":
                self.slug = parts[2]
                self.url = f"{FB}/profile.php?id={self.slug}"
            elif parts and parts[0].lower() not in RESERVED:
                self.slug = parts[0]
                self.url = f"{FB}/{self.slug}"
            else:
                raise ScrapeError(t(f'not a Facebook profile or page: "{text}"',
                                    f'không nhận ra profile hay page Facebook: "{text}"'))


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #

def load_cookies(path: Optional[str]) -> list[dict]:
    """Cookies as Playwright dicts, from --cookies or the saved fb-session.json.

    Accepted formats: Netscape cookies.txt, JSON list (Cookie-Editor / EditThisCookie export),
    Playwright storage state, or a plain "c_user=...; xs=..." header line.
    """
    src = Path(path) if path else (SESSION_FILE if SESSION_FILE.is_file() else None)
    if not src:
        return []
    try:
        raw = src.read_text(encoding="utf-8-sig").strip()
    except OSError as e:
        raise ScrapeError(t(f"cannot read cookie file {src}: {e}", f"không đọc được file cookie {src}: {e}"))
    cookies: list[dict] = []
    if raw.startswith(("{", "[")):
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise ScrapeError(t(f"cookie file is not valid JSON: {e}", f"file cookie JSON bị lỗi: {e}"))
        items = data.get("cookies", []) if isinstance(data, dict) else data
        for c in items:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            exp = c.get("expires", c.get("expirationDate"))
            cookies.append({
                "name": c["name"], "value": str(c.get("value", "")),
                "domain": c.get("domain") or ".facebook.com", "path": c.get("path") or "/",
                "expires": float(exp) if exp not in (None, "") else -1,
                "secure": bool(c.get("secure", True)), "httpOnly": bool(c.get("httpOnly", False)),
            })
    elif "\t" in raw:
        for line in raw.splitlines():
            http_only = line.startswith("#HttpOnly_")   # curl cookie files mark HttpOnly cookies this way
            if http_only:
                line = line[len("#HttpOnly_"):]
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _, cpath, secure, exp, name, value = parts[:7]
            cookies.append({"name": name, "value": value, "domain": domain, "path": cpath or "/",
                            "expires": float(exp) if exp.isdigit() and int(exp) > 0 else -1,
                            "secure": secure.upper() == "TRUE", "httpOnly": http_only})
    else:
        for part in raw.replace("\n", ";").split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name:
                cookies.append({"name": name.strip(), "value": value.strip(), "domain": ".facebook.com",
                                "path": "/", "expires": -1, "secure": True, "httpOnly": False})
    cookies = [c for c in cookies if "facebook.com" in c["domain"]]
    names = {c["name"] for c in cookies}
    if not {"c_user", "xs"} <= names:
        raise ScrapeError(t(f"{src} has no Facebook login cookies (c_user and xs are needed). "
                            "Run: python fb-dl.py --login",
                            f"{src} không có cookie đăng nhập Facebook (cần c_user và xs). "
                            "Chạy: python fb-dl.py --login"))
    return cookies


def http_session(cookies: list[dict]) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
    })
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=".facebook.com", path="/")
    return s


# --------------------------------------------------------------------------- #
# Browser (Playwright)
# --------------------------------------------------------------------------- #

def launch_browser(pw, choice: str, headless: bool):
    """Use Edge or Chrome already installed on the computer, else Playwright's own Chromium."""
    channels = [choice] if choice != "auto" else ["msedge", "chrome", "chromium"]
    errors = []
    for ch in channels:
        try:
            return pw.chromium.launch(
                channel=None if ch == "chromium" else ch, headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--mute-audio"])
        except Exception as e:
            errors.append(f"{ch}: {str(e).splitlines()[0]}")
    raise ScrapeError(t("could not start a browser (" + "; ".join(errors) + "). Install Edge or Chrome, "
                        "or run: python -m playwright install chromium",
                        "không mở được trình duyệt (" + "; ".join(errors) + "). Cài Edge hoặc Chrome, "
                        "hoặc chạy: python -m playwright install chromium"))


def import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ScrapeError(t("Playwright is not installed. Run: pip install -r requirements.txt",
                            "chưa cài Playwright. Chạy: pip install -r requirements.txt"))
    return sync_playwright


VIEWER_KEYS = {"viewer_actor", "current_actor", "actor_provider", "comment_composer_placeholder",
               "viewer", "viewer_feedback_reaction_info", "viewer_current_actor", "ghl_mocked_footer_info"}


def scrub(obj, uids: set[str], name: str):
    """Remove the logged-in account (id, name, avatar) from Facebook's raw data before saving it.
    `uids`: the account id(s) (page data and the c_user cookie)."""
    if isinstance(obj, dict):
        return {k: scrub(v, uids, name) for k, v in obj.items() if k not in VIEWER_KEYS}
    if isinstance(obj, list):
        return [scrub(v, uids, name) for v in obj]
    if isinstance(obj, str):
        for uid in uids:
            if uid and uid != "0" and uid in obj:
                obj = obj.replace(uid, "0")
        if name and len(name) > 2 and name in obj:
            obj = obj.replace(name, "(viewer)")
    return obj


def mask_name(name: str) -> str:
    """'Nguyen Van A' -> 'N*** V*** A***': shows that the login works without printing who you are
    (the terminal may end up in a screenshot)."""
    words = [w for w in (name or "").split() if w]
    return " ".join(f"{w[0]}***" for w in words) or t("(hidden)", "(đã ẩn)")


def page_user(html: str) -> tuple[str, str]:
    """(user id, name) of the logged-in account from a Facebook page, ("0", "") when logged out."""
    # CurrentUserInitialData is Facebook's marker that a logged-in session is present.
    m = re.search(r'"CurrentUserInitialData",\[\],\{[^}]*?"USER_ID":"(\d+)"[^}]*?"NAME":"((?:[^"\\]|\\.)*)"', html)
    return (m.group(1), json_unescape(m.group(2))) if m else ("0", "")


def do_login(opts) -> None:
    """Open a visible browser window; the user logs in by hand and the cookies are saved."""
    sync_playwright = import_playwright()
    log(bold_cyan(t("━━ Facebook login ", "━━ Đăng nhập Facebook ")) + gray("━" * 20))
    log(t("  A browser window opens. Log in to Facebook there (with 2FA if asked).",
          "  Một cửa sổ trình duyệt sẽ mở ra. Hãy đăng nhập Facebook trong đó (kể cả 2FA nếu có)."))
    log(gray(t("  The window closes by itself once you are logged in. Waiting up to 10 minutes...",
               "  Cửa sổ tự đóng khi bạn đăng nhập xong. Chờ tối đa 10 phút...")))
    with sync_playwright() as pw:
        browser = launch_browser(pw, opts.browser, headless=False)
        ctx = browser.new_context(locale="en-US", viewport=None)
        page = ctx.new_page()
        page.goto(f"{FB}/login", wait_until="domcontentloaded", timeout=60000)
        deadline = time.monotonic() + 600
        ok = False
        while time.monotonic() < deadline:
            try:
                names = {c["name"] for c in ctx.cookies(FB)}
                url = page.url
            except Exception:   # window closed by the user
                break
            if {"c_user", "xs"} <= names and "/checkpoint" not in url and "/login" not in url:
                ok = True
                break
            page.wait_for_timeout(1000)
        if ok:
            page.wait_for_timeout(3000)   # let Facebook finish setting its cookies
            ctx.storage_state(path=str(SESSION_FILE))
            uid, name = page_user(page.content())
        browser.close()
    if not ok:
        raise ScrapeError(t("login was not finished (window closed or timed out)",
                            "chưa đăng nhập xong (cửa sổ bị đóng hoặc hết thời gian)"))
    log(bold_green("  ✓ ") + green(t("Logged in", "Đã đăng nhập")) + (f" {bold(mask_name(name))}" if name else ""))
    log(gray(t("  Session saved to ", "  Đã lưu phiên vào ")) + blue(str(SESSION_FILE)))
    log(yellow(t("  Keep this file private: it works like your password. Delete it with --logout.",
                 "  Giữ kín file này: nó có giá trị như mật khẩu. Xoá bằng --logout.")))


# --------------------------------------------------------------------------- #
# Facebook data -> posts
# --------------------------------------------------------------------------- #

def apply_patch(root: dict, path: list, data) -> None:
    """Facebook streams parts of a GraphQL result as {"path": [...], "data": {...}} lines.
    Put each part back where it belongs so every story is complete."""
    if not path:
        if isinstance(root, dict) and isinstance(data, dict):
            deep_merge(root, data)
        return
    node = root
    for key, nxt in zip(path, path[1:]):
        empty = [] if isinstance(nxt, int) else {}
        if isinstance(key, int):
            if not isinstance(node, list):
                return
            while len(node) <= key:
                node.append({})
            if not isinstance(node[key], (dict, list)):
                node[key] = empty
            node = node[key]
        else:
            if not isinstance(node, dict):
                return
            if not isinstance(node.get(key), (dict, list)):
                node[key] = empty
            node = node[key]
    last = path[-1]
    if isinstance(last, int):
        if not isinstance(node, list):
            return
        while len(node) <= last:
            node.append({})
        if isinstance(node[last], dict) and isinstance(data, dict):
            deep_merge(node[last], data)
        else:
            node[last] = data
    elif isinstance(node, dict):
        if isinstance(node.get(last), dict) and isinstance(data, dict):
            deep_merge(node[last], data)
        else:
            node[last] = data


def deep_merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v


def parse_graphql(text: str) -> list[dict]:
    """GraphQL response body (one JSON object per line) -> list of complete `data` roots."""
    roots: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("for (;;);"):   # Facebook wraps responses in for(;;); to block JSON hijacking
            line = line[9:]
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if "path" in obj:
            if roots and "data" in obj:   # a patch for the last root (ignored if it came first)
                apply_patch(roots[-1], obj["path"], obj["data"])
        elif isinstance(obj.get("data"), dict):
            roots.append(obj["data"])
    return roots


def html_json(html: str) -> Iterator:
    """JSON blobs embedded in a Facebook page (<script type="application/json">)."""
    for m in re.finditer(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.S):
        try:
            yield json.loads(m.group(1))
        except ValueError:
            continue


def find_stories(obj) -> Iterator[dict]:
    """Top-level feed stories (not the shared post nested inside a story)."""
    return iter_dicts(obj, lambda d: d.get("__typename") == "Story" and bool(d.get("post_id"))
                      and "comet_sections" in d)


def feed_ended(obj) -> bool:
    """True when the timeline says there are no more posts."""
    feed = first(obj, "timeline_list_feed_units", lambda v: isinstance(v, dict) and "page_info" in v)
    return bool(feed and feed["page_info"].get("has_next_page") is False)


def all_dicts(obj) -> Iterator[dict]:
    """Every nested dict, including the ones inside other matches."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def grids(obj, want: Callable[[dict], bool]) -> Iterator[tuple[dict, list[dict]]]:
    """(connection, nodes) for every list of "edges" whose nodes match `want` (a photo grid, an album
    list). Only the grid itself is used: the profile header next to it (avatar, cover) and other lists
    on the page (comments...) are not."""
    for conn in all_dicts(obj):
        edges = conn.get("edges")
        if not isinstance(edges, list):
            continue
        nodes = []
        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            for cand in (node, (node or {}).get("node") if isinstance(node, dict) else None):
                if isinstance(cand, dict) and want(cand):
                    nodes.append(cand)
                    break
        if nodes:
            yield conn, nodes


def write_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write through a temporary file, so a stop in the middle never leaves half a file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding, newline="")
    os.replace(tmp, path)


def best_image(media: dict) -> tuple[Optional[str], int]:
    """(largest image URL, its longest side or 0 when unknown) of a Photo node."""
    best, size = None, -1
    for key in ("photo_image", "image", "viewer_image", "large_share_image", "massive_image", "blurred_image"):
        img = media.get(key)
        if not isinstance(img, dict) or not img.get("uri"):
            continue
        side = max(to_int(img.get("width")) or 0, to_int(img.get("height")) or 0)
        if side > size:
            best, size = img["uri"], side
    if best is None:
        return None, 0
    if size <= 0:   # size unknown: read it from the CDN "cstp=mx2048x1366" hint
        m = re.search(r"cstp=mx(\d+)x(\d+)", best)
        size = max(int(m.group(1)), int(m.group(2))) if m else 0
    return best, size


def collect_media(story: dict) -> tuple[list[dict], list[dict], int]:
    """Photos and videos of a story (own attachments, then the shared post's), plus the photo
    count Facebook says the post has (more than listed for big albums)."""
    photos: list[dict] = []
    videos: list[dict] = []
    seen: set[str] = set()
    declared = 0
    roots = [story.get("attachments"), dig(story, "comet_sections", "content", "story", "attachments"),
             dig(story, "attached_story", "attachments")]
    stack = [r for r in reversed(roots) if r]
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            stack.extend(reversed(cur))
            continue
        if not isinstance(cur, dict):
            continue
        sub = cur.get("all_subattachments")
        if isinstance(sub, dict):
            declared = max(declared, to_int(sub.get("count")) or 0)
        kind = cur.get("__typename")
        mid = str(cur.get("id") or "")
        if kind in ("Photo", "Video") and mid:
            if mid not in seen:
                seen.add(mid)
                if kind == "Photo":
                    url, side = best_image(cur)
                    photos.append({"id": mid, "url": url, "size": side, "page": cur.get("url"),
                                   "caption": cur.get("accessibility_caption")})
                else:
                    legacy = cur.get("videoDeliveryLegacyFields") or {}
                    hd = (cur.get("browser_native_hd_url") or legacy.get("browser_native_hd_url")
                          or cur.get("playable_url_quality_hd"))
                    sd = (cur.get("browser_native_sd_url") or legacy.get("browser_native_sd_url")
                          or cur.get("playable_url"))
                    ms = to_int(cur.get("playable_duration_in_ms")) or to_int(cur.get("length_in_second"))
                    # Some responses report milliseconds and others seconds: >10000 must be ms.
                    # Newer responses list progressive MP4s with a quality label (stories use these).
                    prog = dig(cur, "videoDeliveryResponseFragment", "videoDeliveryResponseResult",
                               "progressive_urls") or []
                    prog = [p for p in prog if isinstance(p, dict) and p.get("progressive_url")
                            and not p.get("failure_reason")]
                    prog_hd = [p["progressive_url"] for p in prog if dig(p, "metadata", "quality") == "HD"]
                    prog_rest = [p["progressive_url"] for p in prog if dig(p, "metadata", "quality") != "HD"]
                    videos.append({
                        "id": mid,
                        "page": cur.get("permalink_url") or cur.get("url") or f"{FB}/watch/?v={mid}",
                        "direct": uniq([*prog_hd, hd, sd, *prog_rest]),
                        "duration": (ms / 1000 if ms and ms > 10000 else ms) if ms else None,
                        "thumb": dig(cur, "preferred_thumbnail", "image", "uri") or dig(cur, "image", "uri"),
                    })
            continue   # do not look inside a photo / video node
        stack.extend(reversed(list(cur.values())))
    return photos, videos, declared


def story_text(story: dict) -> str:
    for path in (("comet_sections", "content", "story", "message", "text"),
                 ("comet_sections", "content", "story", "comet_sections", "message", "story", "message", "text"),
                 ("message", "text")):
        txt = dig(story, *path)
        if isinstance(txt, str):
            return txt
    msg = first(story, "message", lambda v: isinstance(v, dict) and isinstance(v.get("text"), str))
    return msg["text"] if msg else ""


def external_link(story: dict) -> Optional[str]:
    """Link shared in the post (an article etc.), not a Facebook URL."""
    for att in story.get("attachments") or []:
        for key in ("web_link", "url"):
            url = first(att, key, lambda v: isinstance(v, str) and v.startswith("http"))
            if not url:
                continue
            if "l.facebook.com/l.php" in url:
                url = parse_qs(urlparse(url).query).get("u", [url])[0]
            if "facebook.com" not in urlparse(url).netloc:
                return url
    return None


def parse_story(story: dict) -> dict:
    pid = str(story["post_id"])
    actor = dig(story, "actors", 0) or first(story, "actors", lambda v: isinstance(v, list) and v) or [{}]
    actor = actor[0] if isinstance(actor, list) else actor
    created = to_int(story.get("creation_time")) or to_int(first(story, "creation_time")) or 0
    url = story.get("permalink_url") or story.get("wwwURL") or first(story, "wwwURL") or f"{FB}/{pid}"
    photos, videos, declared = collect_media(story)
    for v in videos:
        # Reels: the video node often has no /reel/ link, but the post link is /reel/<video id>/.
        if f"/reel/{v['id']}" in url or "/reel/" in (v.get("page") or ""):
            v["reel"] = True
            if "/reel/" not in (v.get("page") or ""):
                v["page"] = f"{FB}/reel/{v['id']}/"
    reactions = first(story, "reaction_count", lambda v: isinstance(v, dict) and "count" in v)
    comments = first(story, "comment_rendering_instance", lambda v: isinstance(v, dict) and v.get("comments"))
    shares = first(story, "share_count", lambda v: isinstance(v, dict) and "count" in v)
    shared = story.get("attached_story") or {}
    shared_actor = dig(shared, "actors", 0) or {}
    return blank_post(**{
        "id": pid,
        "url": url,
        "created": created,
        "author": actor.get("name"),
        "author_id": actor.get("id"),
        "author_url": actor.get("url"),
        "text": story_text(story),
        "photos": photos,
        "videos": videos,
        "photo_count": max(declared, len(photos)),
        "reactions": to_int((reactions or {}).get("count")),
        "comments": to_int(dig(comments or {}, "comments", "total_count")),
        "shares": to_int((shares or {}).get("count")),
        "shared_from": shared.get("permalink_url") or shared.get("wwwURL"),
        "shared_author": shared_actor.get("name"),
        "shared_author_id": str(shared_actor.get("id") or "") or None,
        "shared_text": story_text(shared) if shared else "",
        "link": external_link(story),
        "sponsored": bool(story.get("sponsored_data")),
        "to_id": str((first(story, "to", lambda v: isinstance(v, dict) and v.get("id")) or {}).get("id") or "") or None,
        "related_ids": story_people(story),
    })


def story_people(story: dict) -> list[str]:
    """Ids linked to a post besides its author: whose timeline it is on, co-authors, and who is
    tagged or mentioned ("X is with Y", "@Y" in the text)."""
    ids = set()
    owner = dig(first(story, "owning_profile", lambda v: isinstance(v, dict)) or {}, "id")
    if owner:
        ids.add(str(owner))
    for section in (dig(story, "comet_sections", "title"), dig(story, "comet_sections", "context_layout"),
                    dig(story, "comet_sections", "content", "story", "comet_sections", "message"),
                    story.get("with_tags")):
        for ent in iter_dicts(section or {}, lambda d: isinstance(d.get("entity"), dict) or "sample_entities" in d):
            for e in [ent.get("entity")] + list(ent.get("sample_entities") or []):
                if isinstance(e, dict) and e.get("id"):
                    ids.add(str(e["id"]))
    # Co-authors of collaboration posts ("A and B" posts show on both timelines).
    for key in ("actors", "collaborators"):
        for actor in first(story, key, lambda v: isinstance(v, list)) or []:
            if isinstance(actor, dict) and actor.get("id"):
                ids.add(str(actor["id"]))
    for node in dig(story, "with_tags", "nodes") or []:
        if isinstance(node, dict) and node.get("id"):
            ids.add(str(node["id"]))
    return sorted(ids)


def is_own(post: dict, owner_id: Optional[str]) -> bool:
    """False for ads and for posts of other pages that Facebook mixes into a timeline.
    Kept: the owner's posts, collaboration posts, posts on the owner's wall, and posts the owner is
    tagged or mentioned in."""
    if post.get("sponsored"):
        return False
    if not owner_id or not post.get("author_id"):
        return True
    return owner_id in {str(post["author_id"]), str(post.get("to_id") or "")} | set(post.get("related_ids") or [])


def flat(post: dict, files: list[str]) -> dict:
    """One posts.csv row."""
    created = datetime.fromtimestamp(post["created"], tz=timezone.utc) if post["created"] else None
    return {
        "id": post["id"],
        "url": post["url"],
        "created": created.isoformat() if created else "",
        "author": post["author"],
        "author_id": post["author_id"],
        "text": post["text"],
        "photos": post["photo_count"] or len(post["photos"]),
        "videos": len(post["videos"]),
        "reactions": post["reactions"],
        "comments": post["comments"],
        "shares": post["shares"],
        "shared_from": post["shared_from"],
        "shared_author": post["shared_author"],
        "link": post["link"],
        "files": " | ".join(files),
    }


# --------------------------------------------------------------------------- #
# Timeline collector
# --------------------------------------------------------------------------- #

def media_count(item: dict) -> int:
    return len(item["photos"]) + len(item["videos"])


def better(new: dict, old: Optional[dict]) -> bool:
    """True when `new` should replace `old`: the same post / story can arrive more than once,
    sometimes with less data."""
    if not old:
        return True
    return media_count(new) > media_count(old) or bool(new.get("created") and not old.get("created"))


def profile_header(html: str) -> dict:
    """The profile / page shown on the page (profile_header_renderer.user): id, name, url,
    username_for_profile, profilePhoto, profilePicLarge, cover_photo, story_bucket.
    Everything about the owner is read from here, never from the page's top bar, which shows the
    logged-in account."""
    for blob in html_json(html):
        header = first(blob, "profile_header_renderer", lambda v: isinstance(v, dict))
        user = (header or {}).get("user")
        if isinstance(user, dict) and str(user.get("id") or "").isdigit():
            return user
    return {}


def find_owner_id(html: str, header: dict, not_ids: set[str]) -> Optional[str]:
    """Numeric id of the profile / page shown. The header is trusted even when it is your own
    profile; the fallbacks never return the logged-in account (`not_ids`)."""
    if header.get("id"):
        return str(header["id"])
    for pattern in (r'"pageID":"(\d+)"', r'"userID":"(\d+)"'):
        for m in re.finditer(pattern, html):
            if m.group(1) not in not_ids:
                return m.group(1)
    return None


class Timeline:
    """Scroll a profile / page (or open one post) in a headless browser and collect its posts.

    Callbacks (set before collect()):
      on_ready()      once the page is loaded and the owner is known, before any on_new()
      on_new(post)    once per new post, in timeline order
      on_update(post) when a post seen before comes again with more photos / videos
      should_stop()   checked after every scroll
    """

    def __init__(self, opts, cookies: list[dict], viewer_ids: set[str]):
        self.opts = opts
        self.cookies = cookies
        self.viewer_ids = viewer_ids
        self.posts: dict[str, dict] = {}
        self.html_ids: list[str] = []     # posts of the first page, in page order
        self.owner_id: Optional[str] = None
        self.header: dict = {}              # profile_header(): the owner's name, photos, stories
        self.html = ""
        self.final_url = ""
        self.stories: list[dict] = []
        # Photos / Albums tabs (_tabs()): photo id -> {"url", "size"}, and the albums with their photo ids.
        self.tab_photos: dict[str, dict] = {}
        self.albums: list[dict] = []
        self.ended = False
        self.on_ready: Callable[[], None] = lambda: None
        self.on_new: Callable[[dict], None] = lambda post: None
        self.on_update: Callable[[dict], None] = lambda post: None   # a post came again with more media
        self.on_scroll: Optional[Callable[[int, int], None]] = None   # (posts found, oldest time)
        self.on_tab: Optional[Callable[[str], None]] = None            # what the tab reader is doing
        self._ready = False
        self._errors = 0

    # -- responses -------------------------------------------------------- #

    def _on_response(self, resp) -> None:
        if "/api/graphql" not in resp.url:
            return
        try:
            body = resp.text()
        except Exception:
            return
        try:
            for root in parse_graphql(body):
                self._take(root)
                if feed_ended(root):
                    self.ended = True
        except Exception as e:   # never let one odd response stop the scroll
            self._errors += 1
            if self._errors <= 3:   # only the first few, so the screen is not flooded
                log(warn(t(f"could not read a Facebook response: {type(e).__name__}: {e}",
                           f"không đọc được một phản hồi của Facebook: {type(e).__name__}: {e}")))

    def _take(self, obj, from_html: bool = False) -> None:
        for story in find_stories(obj):
            pid = str(story["post_id"])
            try:
                post = parse_story(story)
            except Exception as e:
                log(warn(f"{pid}: {type(e).__name__}: {e}"))
                continue
            post["_raw"] = story
            old = self.posts.get(pid)
            if better(post, old):
                self.posts[pid] = post
                if old and self._ready:
                    self.on_update(post)
            if from_html and pid not in self.html_ids:
                self.html_ids.append(pid)
            if not old and self._ready:
                self.on_new(post)

    def _set_ready(self) -> None:
        """The owner is known: replay the posts that arrived while the page was loading."""
        self._ready = True
        self.on_ready()
        order = self.html_ids + [pid for pid in self.posts if pid not in self.html_ids]
        for pid in order:
            self.on_new(self.posts[pid])

    # -- browsing --------------------------------------------------------- #

    def collect(self, url: str, single: bool, should_stop: Callable[[], bool]) -> None:
        sync_playwright = import_playwright()
        opts = self.opts
        with sync_playwright() as pw:
            browser = launch_browser(pw, opts.browser, headless=not opts.show_browser)
            try:
                ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 1000},
                                          timezone_id="UTC")
                if self.cookies:
                    ctx.add_cookies(self.cookies)
                if not opts.show_browser:
                    # Images and videos are not needed to read the timeline: skip them to go faster.
                    ctx.route("**/*", lambda route: route.abort()
                              if route.request.resource_type in ("image", "media", "font")
                              else route.continue_())
                page = ctx.new_page()
                page.on("response", self._on_response)
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(3000)
                self._check_page(page)
                self.html = page.content()
                self.final_url = page.url
                if not single:
                    self.header = profile_header(self.html)
                    self.owner_id = find_owner_id(self.html, self.header, self.viewer_ids)
                for blob in html_json(self.html):
                    self._take(blob, from_html=True)
                self._set_ready()
                if single:
                    page.wait_for_timeout(2000)
                    return
                if opts.stories and self.owner_id:
                    self._stories(ctx)
                self._scroll(page, should_stop)
                if opts.all_photos and opts.photos and not opts.metadata_only and self.owner_id:
                    self._tabs(ctx)
            finally:
                browser.close()

    def main_post(self, url: str) -> Optional[dict]:
        """The post a post link points to (not the suggested posts shown under it)."""
        paths = {urlparse(u).path.rstrip("/") for u in (url, self.final_url) if u}
        for post in self.posts.values():
            if post["id"] in url or post["id"] in self.final_url \
                    or urlparse(post["url"] or "").path.rstrip("/") in paths:
                return post
        for pid in self.html_ids:
            return self.posts[pid]
        return next(iter(self.posts.values()), None)

    def _stories(self, ctx) -> None:
        """Active stories (last 24 h) of the profile / page itself.

        The story viewer page already holds every card of the owner's "bucket" in its HTML. It is only
        read: nothing is clicked (a click marks the story as seen), and the viewer is not moved on to
        the stories of other people in the logged-in account's tray."""
        node = dig(self.header, "story_bucket", "nodes", 0) or {}
        bucket, card = node.get("id"), dig(node, "first_story_to_show", "id")
        if not bucket:
            return
        page = ctx.new_page()
        try:
            page.goto(f"{FB}/stories/{bucket}/" + (f"{card}/" if card else ""),
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            html = page.content()
        except Exception as e:
            log(warn(t(f"could not open the stories: {e}", f"không mở được story: {e}")))
            return
        finally:
            page.close()
        cards: dict[str, dict] = {}
        for blob in html_json(html):
            # Only the owner's own bucket, never the other people in the stories tray.
            for bucket_node in iter_dicts(blob, lambda d: isinstance(d.get("story_bucket_owner"), dict)):
                if str(bucket_node["story_bucket_owner"].get("id")) != self.owner_id:
                    continue
                for c in iter_dicts(bucket_node, lambda d: "story_card_info" in d and "attachments" in d):
                    photos, videos, _ = collect_media(c)
                    item = {"id": str(c.get("id")), "post_id": c.get("post_id"),
                            "created": to_int(c.get("creation_time")) or 0,
                            "photos": [p for p in photos if p["url"]], "videos": videos}
                    if better(item, cards.get(item["id"])):
                        cards[item["id"]] = item
        self.stories = [c for c in cards.values() if media_count(c)]

    def _tab_url(self, tab: str) -> str:
        vanity = owner_vanity(self.header)
        return f"{FB}/{vanity}/{tab}" if vanity else f"{FB}/profile.php?id={self.owner_id}&sk={tab}"

    def _tabs(self, ctx) -> None:
        """The Photos and Albums tabs: every photo the profile uploaded and which album it is in.

        The Photos grid already holds each photo's full-size link, so no photo page has to be opened.
        Album grids only have small previews; Run.tabs() takes those photos from the Photos tab (or the
        posts) when it can. Each tab and album is read in its own page, so late data of one page is
        never mixed into another. Like the timeline, the pages are only read."""
        limit = self.opts.limit
        try:
            photos = self._read_tab(ctx, self._tab_url("photos_by"), TabReader("photos"), limit,
                                    lambda n: t(f"Reading the Photos tab · {n} photos", f"Đang đọc tab Ảnh · {n} ảnh"))
            self.tab_photos = photos.photos
            albums = self._read_tab(ctx, self._tab_url("photos_albums"), TabReader("albums"), None,
                                    lambda n: t(f"Reading the Albums tab · {n} albums", f"Đang đọc tab Album · {n} album"))
            for i, album in enumerate(albums.albums, 1):
                name = album["title"][:40] or "?"
                grid = self._read_tab(ctx, album["url"], TabReader("album"), limit,
                                      lambda n: t(f"Reading album {i}/{len(albums.albums)} \"{name}\" · {n} photos",
                                                  f"Đang đọc album {i}/{len(albums.albums)} \"{name}\" · {n} ảnh"))
                album["ids"], album["thumbs"] = list(grid.photos), grid.photos
                self.albums.append(album)
        except ScrapeError:
            raise
        except Exception as e:   # keep what was read so far
            log(warn(t(f"could not read the Photos / Albums tabs: {e}", f"không đọc được tab Ảnh / Album: {e}")))

    def _read_tab(self, ctx, url: str, reader: "TabReader", limit: Optional[int],
                  label: Callable[[int], str]) -> "TabReader":
        page = ctx.new_page()
        page.on("response", reader.on_response)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            self._check_page(page)
            for blob in html_json(page.content()):
                reader.take(blob)

            def report(n: int) -> None:
                if self.on_tab:
                    self.on_tab(label(n))
                else:
                    status(gray("  " + label(n)))

            self._scroll(page, lambda: bool(limit and reader.count() >= limit), count=reader.count,
                         report=report, ended=lambda: reader.ended, max_idle=max(6, self.opts.max_idle // 2))
        finally:
            page.close()
        return reader

    def _check_page(self, page) -> None:
        url = page.url
        if "/checkpoint" in url:
            raise ScrapeError(t("Facebook wants you to verify your account. Open facebook.com in your "
                                "browser, finish the check, then run --login again.",
                                "Facebook yêu cầu xác minh tài khoản. Mở facebook.com trên trình duyệt, "
                                "xác minh xong rồi chạy lại --login."))
        if re.search(r"facebook\.com/login", url):
            raise ScrapeError(t("Facebook sent you to the login page: the session expired. "
                                "Run: python fb-dl.py --login",
                                "Facebook chuyển về trang đăng nhập: phiên đã hết hạn. "
                                "Chạy: python fb-dl.py --login"))

    def _scroll(self, page, should_stop: Callable[[], bool], count: Optional[Callable[[], int]] = None,
                report: Optional[Callable[[int], None]] = None, ended: Optional[Callable[[], bool]] = None,
                max_idle: Optional[int] = None) -> None:
        """Scroll until the list ends (Facebook says so), nothing new comes for `max_idle` scrolls
        (default --max-idle), or should_stop(). By default it counts and reports timeline posts."""
        opts = self.opts
        count = count or (lambda: len(self.posts))
        ended = ended or (lambda: self.ended)
        max_idle = max_idle or opts.max_idle
        idle, last = 0, -1
        started = time.monotonic()
        while True:
            try:
                page.keyboard.press("Escape")   # closes the "log in to see more" popup when logged out
                page.mouse.wheel(0, 2500)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(int(opts.scroll_wait * 1000))
            if "/checkpoint" in page.url or "facebook.com/login" in page.url:
                self._check_page(page)
            n = count()
            if report:
                report(n)
            else:
                oldest = min((p["created"] for p in self.posts.values() if p["created"]), default=0)
                if self.on_scroll:
                    self.on_scroll(n, oldest)
                else:
                    when = datetime.fromtimestamp(oldest).strftime("%Y-%m-%d") if oldest else "?"
                    spent = fmt_eta(time.monotonic() - started)
                    status(gray(t(f"  Scrolling the timeline... {n} posts, oldest {when}  ({spent})",
                                  f"  Đang cuộn timeline... {n} bài, cũ nhất {when}  ({spent})")))
            if should_stop():
                return
            if ended():
                page.wait_for_timeout(1500)   # let the last responses arrive
                return
            idle = idle + 1 if n == last else 0
            last = n
            if idle >= max_idle:
                return
            if idle and idle % 4 == 0:
                # Facebook sometimes stops loading: scroll up a little and back down to wake it up.
                try:
                    page.mouse.wheel(0, -5000)
                    page.wait_for_timeout(800)
                    page.mouse.wheel(0, 5000)
                except Exception:
                    pass


class TabReader:
    """What one page of the Photos / Albums tabs holds. Each page gets its own reader, so data that
    arrives late from one page can never be filed under another.

    kind "photos" / "album": photo id -> {"url", "size"} in grid order; kind "albums": the album list."""

    def __init__(self, kind: str):
        self.kind = kind
        self.photos: dict[str, dict] = {}
        self.albums: list[dict] = []
        self.ended = False

    def count(self) -> int:
        return len(self.albums) if self.kind == "albums" else len(self.photos)

    def on_response(self, resp) -> None:
        if "/api/graphql" not in resp.url:
            return
        try:
            for root in parse_graphql(resp.text()):
                self.take(root)
        except Exception:   # an odd response: the scroll goes on
            pass

    def take(self, obj) -> None:
        if self.kind == "albums":
            want = (lambda d: isinstance(d.get("title"), dict) and "/media/set/" in str(d.get("url") or ""))
        else:
            want = (lambda d: d.get("__typename") == "Photo" and bool(d.get("id")))
        for conn, nodes in grids(obj, want):
            for node in nodes:
                if self.kind == "albums":
                    if all(a["url"] != node["url"] for a in self.albums):
                        self.albums.append({"title": node["title"].get("text") or "", "url": node["url"],
                                            "id": str(node.get("id") or ""), "ids": [], "thumbs": {}})
                    continue
                url, size = best_image(node)
                old = self.photos.get(str(node["id"]))
                if url and (not old or size > old["size"]):
                    self.photos[str(node["id"])] = {"url": url, "size": size}
            if dig(conn, "page_info", "has_next_page") is False:
                self.ended = True


# --------------------------------------------------------------------------- #
# Photo viewer (full-size photos, albums with more photos than the timeline shows)
# --------------------------------------------------------------------------- #

class PhotoViewer:
    """www.facebook.com/photo/?fbid=...&set=... pages, read with plain requests."""

    def __init__(self, session: requests.Session, wait: float):
        self.s = session
        self.wait = wait
        self._lock = threading.Lock()
        self._last = 0.0

    def _get(self, url: str) -> str:
        with self._lock:
            delay = self._last + self.wait - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=30)
                if r.ok:
                    return r.text
            except requests.RequestException:
                pass
            time.sleep(2 + 3 * attempt)
        return ""

    def photo(self, fbid: str, set_id: str = "") -> dict:
        """{"url": full-size image, "next": next photo id, "next_video": bool} ({} when blocked)."""
        page = self._get(f"{FB}/photo/?fbid={fbid}&set={set_id}")
        if not page or '{"__dr":"CometErrorRoot.react"}' in page:
            return {}
        m = re.search(r'"__isNode":"Photo","id":"' + re.escape(fbid) + r'"', page)
        start = m.start() if m else 0
        m = re.search(r',"image":\{"uri":"([^"]+)"', page[start:]) or re.search(r',"image":\{"uri":"([^"]+)"', page)
        nxt = re.search(r'"nextMediaAfterNodeId":\{"__typename":"(Photo|Video)","id":"(\d+)"', page) \
            or re.search(r'"nextMedia":\{"edges":\[\{"node":\{"__typename":"(Photo|Video)","id":"(\d+)"', page)
        return {"url": json_unescape(m.group(1)) if m else None, "next": nxt.group(2) if nxt else None,
                "next_video": bool(nxt and nxt.group(1) == "Video")}

    def album(self, set_id: str, first_id: str, limit: int) -> list[dict]:
        """Walk an album photo by photo (Facebook has no list of all photos in a post)."""
        out: list[dict] = []
        seen: set[str] = set()
        pid: Optional[str] = first_id
        while pid and pid not in seen and len(out) < limit:
            seen.add(pid)
            info = self.photo(pid, set_id)
            if not info:
                break
            if info.get("url"):
                out.append({"id": pid, "url": info["url"], "size": 0, "page": f"{FB}/photo/?fbid={pid}",
                            "caption": None})
            if info.get("next_video"):
                break   # videos inside an album are downloaded from the post itself
            pid = info.get("next")
        return out


# --------------------------------------------------------------------------- #
# Progress tracking (SQLite)
# --------------------------------------------------------------------------- #

class Progress:
    """posts(id, status, files, error, updated). status: done | partial | error.
    "partial" = saved with some file types turned off; a later full run completes it."""

    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, status TEXT, "
                        "files TEXT, error TEXT, updated TEXT)")
        # Where each photo was saved, so the Photos / Albums tabs can link it instead of downloading again.
        self.db.execute("CREATE TABLE IF NOT EXISTS photos (id TEXT PRIMARY KEY, file TEXT)")
        self.db.commit()

    def _row(self, post_id: str):
        with self.lock:
            return self.db.execute("SELECT status, files FROM posts WHERE id = ?", (post_id,)).fetchone()

    def done(self, post_id: str, folder: Path) -> bool:
        row = self._row(post_id)
        if not row or row[0] != "done":
            return False
        try:
            files = json.loads(row[1] or "[]")
        except ValueError:
            return False
        if any(f.startswith("posts/") and not f.endswith(".txt") for f in files):
            return False   # saved by an older build (everything in posts/): plan again so the files move out
        return all((folder / f).exists() for f in files)

    def known(self, post_id: str) -> bool:
        row = self._row(post_id)
        return bool(row and row[0] in ("done", "partial"))

    def mark(self, post_id: str, state: str, files: Optional[list[str]] = None, error: Optional[str] = None) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO posts VALUES (?, ?, ?, ?, ?)",
                            (post_id, state, json.dumps(files or [], ensure_ascii=False), error,
                             datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    def add_photo(self, photo_id: str, file: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO photos VALUES (?, ?)", (photo_id, file))
            self.db.commit()

    def photo_file(self, photo_id: str) -> Optional[str]:
        with self.lock:
            row = self.db.execute("SELECT file FROM photos WHERE id = ?", (photo_id,)).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        with self.lock:
            self.db.close()


# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #

def pmap(fn: Callable, items, workers: int) -> list:
    """fn over items in threads. On Ctrl+C the jobs not started yet are cancelled instead of waited for."""
    items = list(items)
    if not items:
        return []
    pool = ThreadPoolExecutor(max(1, min(workers, len(items))))
    try:
        futures = [pool.submit(fn, item) for item in items]
        # Short waits instead of one long one, so Ctrl+C is noticed at once (also on Windows).
        while wait(futures, timeout=0.5).not_done:
            pass
        return [f.result() for f in futures]
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        pool.shutdown(wait=False)


def is_valid_file(dest: Path) -> bool:
    """Reject "finished" downloads that are really HTML/JSON error pages."""
    try:
        if not dest.is_file() or dest.stat().st_size < 64 or Path(f"{dest}.aria2").exists():
            return False
        with open(dest, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return False
    if dest.suffix == ".txt":
        return True
    if not looks_like_media(head):
        return False
    if dest.suffix == ".mp4":
        return head[4:8] == b"ftyp"
    return True


def image_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    if "dst-jpg" in url or path.endswith((".jpg", ".jpeg")):
        return ".jpg"
    for ext in (".png", ".webp", ".gif"):
        if path.endswith(ext):
            return ext
    return ".jpg"


def fetch(url: str, dest: Path, bar: Optional[ProgressBar] = None,
          session: Optional[requests.Session] = None) -> Optional[str]:
    """Download one URL to dest (through dest.part). Returns an error message, or None when dest is valid.
    The bytes count on the progress bar only when the file is good."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    key = str(tmp)
    try:
        with (session or requests).get(url, headers={"User-Agent": UA, "Referer": f"{FB}/"},
                                       stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 16):
                    fh.write(chunk)
                    if bar:
                        bar.set_live(key, fh.tell())
        os.replace(tmp, dest)
    except (requests.RequestException, OSError) as e:
        tmp.unlink(missing_ok=True)
        return str(e)
    finally:
        if bar:
            bar.forget(key)
    if is_valid_file(dest):
        if bar:
            bar.add(dest.stat().st_size)
        return None
    dest.unlink(missing_ok=True)
    return t("the server sent an error page instead of the file", "máy chủ trả trang lỗi thay vì file")


def download_aria2(aria2: str, tasks: list[tuple[str, Path]], jobs: int, conns: int, work: Path) -> None:
    lines = []
    for url, dest in tasks:
        if is_valid_file(dest):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        for leftover in (dest, Path(f"{dest}.aria2")):
            leftover.unlink(missing_ok=True)
        lines += [url, f"  dir={dest.parent}", f"  out={dest.name}"]   # aria2 input format: URL, then options
    if not lines:
        return
    work.mkdir(parents=True, exist_ok=True)
    inp = work / "aria2-input.txt"
    inp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        aria2, f"--input-file={inp}", f"--max-concurrent-downloads={jobs}",
        f"--max-connection-per-server={conns}", f"--split={conns}", "--min-split-size=1M",
        "--continue=true", "--allow-overwrite=true", "--auto-file-renaming=false",
        "--file-allocation=none", "--max-tries=5", "--retry-wait=2", "--timeout=30",
        "--connect-timeout=15", "--quiet=true", f"--user-agent={UA}",
        "--referer=https://www.facebook.com/", "--header=Accept: */*",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        raise
    finally:
        inp.unlink(missing_ok=True)


def download_files(tasks: list[tuple[str, Path]], aria2: Optional[str], opts, work: Path, bar: ProgressBar) -> None:
    """Photos (and other plain files): aria2c, or requests when aria2c is missing."""
    tasks = [(u, d) for u, d in tasks if not is_valid_file(d)]
    if not tasks:
        return
    bar.watch([d for _, d in tasks])
    try:
        if aria2:
            download_aria2(aria2, tasks, opts.jobs, opts.connections, work)
        else:
            session = requests.Session()

            def one(task):
                url, dest = task
                for _ in range(3):
                    if fetch(url, dest, session=session) is None:
                        return
                    time.sleep(1)

            pmap(one, tasks, opts.jobs)
        for _, dest in tasks:
            if dest.exists() and not is_valid_file(dest):
                dest.unlink(missing_ok=True)
    finally:
        bar.unwatch()


def remove_ytdlp_leftovers(dest: Path) -> None:
    """yt-dlp leaves <name>.f137.mp4, .part and .ytdl files when it fails."""
    for f in dest.parent.glob(glob.escape(dest.stem) + ".*"):
        if f != dest:
            f.unlink(missing_ok=True)


def jar_cookie(c: dict):
    """A Playwright-style cookie dict as an http.cookiejar.Cookie (for yt-dlp's in-memory jar)."""
    from http.cookiejar import Cookie
    domain = c["domain"] if c["domain"].startswith(".") else "." + c["domain"]
    expires = int(c["expires"]) if c.get("expires", -1) and c["expires"] > 0 else None
    return Cookie(0, c["name"], c["value"], None, False, domain, True, True, c.get("path") or "/", True,
                  bool(c.get("secure")), expires, False, None, None, {})


def download_video(video: dict, dest: Path, opts, cookies: list[dict], ffmpeg: Optional[str],
                   bar: ProgressBar) -> Optional[str]:
    """Best quality with yt-dlp, else the direct MP4 links. Returns an error message or None.

    The cookies are put straight into yt-dlp's in-memory jar: no cookie file is written, and the
    video threads do not share one. aria2c is not used here because yt-dlp would write every cookie
    to a temporary file for it."""
    if is_valid_file(dest):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    err = None
    if video.get("page") and not opts.direct_video:
        try:
            import yt_dlp
        except ImportError:
            yt_dlp = None
            err = t("yt-dlp is not installed", "chưa cài yt-dlp")
        if yt_dlp:
            class Quiet:
                def debug(self, msg): pass
                def info(self, msg): pass
                def warning(self, msg): pass
                def error(self, msg): pass

            ydl_opts = {
                "outtmpl": str(dest.with_suffix("")).replace("%", "%%") + ".%(ext)s",
                "format": "bv*+ba/b" if ffmpeg else "b",
                "merge_output_format": "mp4",
                "logger": Quiet(), "quiet": True, "noprogress": True, "no_warnings": True,
                "retries": 5, "fragment_retries": 5, "noplaylist": True,
                "progress_hooks": [bar.ytdl_hook],
                "postprocessors": [{"key": "FFmpegMetadata"}] if ffmpeg else [],
            }
            if ffmpeg:
                ydl_opts["ffmpeg_location"] = ffmpeg
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    for c in cookies:
                        ydl.cookiejar.set_cookie(jar_cookie(c))
                    ydl.download([video["page"]])
                if is_valid_file(dest):
                    return None
                err = t("yt-dlp finished but no MP4 was saved", "yt-dlp chạy xong nhưng không có file MP4")
            except Exception as e:
                err = re.sub(r"^ERROR:\s*", "", str(e)).strip().splitlines()[0][:200] if str(e).strip() else repr(e)
            finally:
                # "base." matches the hook's tmp names (base.f137.mp4.part) but not a sibling "base_v1".
                bar.forget(str(dest.with_suffix("")) + ".")
            remove_ytdlp_leftovers(dest)
    for url in video.get("direct") or []:
        e = fetch(url, dest, bar)
        if e is None:
            return None
        err = err or e
    return err or t("no video link", "không có link video")


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #

FOLDERS = {"text": "posts", "image": "images", "video": "videos", "reel": "reels", "story": "stories"}


def blank_post(**fields) -> dict:
    """A post dict with every field parse_story() fills."""
    post = {"id": "", "url": "", "created": 0, "author": None, "author_id": None, "author_url": None,
            "text": "", "photos": [], "videos": [], "photo_count": 0, "reactions": None, "comments": None,
            "shares": None, "shared_from": None, "shared_author": None, "shared_author_id": None,
            "shared_text": "", "link": None,
            "sponsored": False, "to_id": None, "related_ids": [], "_raw": {}}
    post.update(fields)
    return post


def name_room(out_dir: Path) -> int:
    """How many UTF-16 units the text part of a file name may use so full paths stay under
    Windows' 260 limit: <out_dir>\\reels\\<date>_<post id>_<text>_v10.f999.mp4.part"""
    fixed = utf16_len(str(out_dir)) + len("\\reels\\") + 10 + 1 + 20 + 1 + len("_v10.f999.mp4.part")
    return max(0, min(50, 259 - fixed))


def post_base(post: dict, room: int = 50) -> str:
    when = datetime.fromtimestamp(post["created"]).strftime("%Y-%m-%d") if post["created"] else "0000-00-00"
    desc = sanitize(post["text"] or post["shared_text"] or "", room)
    return f"{when}_{post['id']}" + (f"_{desc}" if desc else "")


def post_text_file(post: dict, files: list[str]) -> str:
    when = datetime.fromtimestamp(post["created"]).strftime("%Y-%m-%d %H:%M") if post["created"] else "?"
    lines = [post["url"], f"{when} · {post['author'] or ''}",
             f"Reactions {fmt_int(post['reactions'])} · Comments {fmt_int(post['comments'])} · "
             f"Shares {fmt_int(post['shares'])}"]
    if post["link"]:
        lines.append(f"Link: {post['link']}")
    if files:
        lines.append("Files: " + " | ".join(f"../{f}" for f in files))
    lines += ["", post["text"] or ""]
    if post["shared_from"]:
        lines += ["", f"── Shared from {post['shared_author'] or ''}: {post['shared_from']}", post["shared_text"] or ""]
    return "\n".join(lines).rstrip() + "\n"


def save_url(session: requests.Session, url: Optional[str], dest: Path) -> bool:
    if not url:
        return False
    try:
        r = session.get(url, timeout=30)
    except requests.RequestException:
        return False
    if r.ok and looks_like_media(r.content):
        dest.write_bytes(r.content)
        return True
    return False


def owner_vanity(header: dict) -> Optional[str]:
    """The profile's username (facebook.com/<username>), from the header only."""
    name = header.get("username_for_profile")
    if isinstance(name, str) and name:
        return name
    parts = [x for x in urlparse(header.get("url") or "").path.split("/") if x]
    return parts[0] if parts and parts[0] != "profile.php" else None


def save_profile(header: dict, html: str, out_dir: Path, session: requests.Session, owner_id: Optional[str],
                 images: bool) -> dict:
    """profile.json, plus avatar.jpg and cover.jpg in full size when `images`.
    Everything comes from the profile header, never from the top bar (which shows your own account)."""
    name = header.get("name") or ""
    if not name:
        import html as htmllib
        # The page title is "<name> | Facebook" (logged in it can be just "Facebook").
        for title in re.findall(r"<title>([^<]*)</title>", html):
            title = re.sub(r"^\(\d+\)\s*", "", htmllib.unescape(title)).strip()
            title = re.sub(r"\s*\|\s*Facebook\s*$", "", title)
            if title and title.lower() not in ("facebook", "verified account", "shared with public"):
                name = title
                break
    followers = re.search(r'"text":"([0-9.,KMB]+ followers)"', html)
    info = {"name": name, "id": owner_id, "username": owner_vanity(header),
            "url": header.get("url"), "followers": followers.group(1) if followers else None,
            "saved": datetime.now().isoformat(timespec="seconds")}
    write_atomic(out_dir / "profile.json", json.dumps(info, ensure_ascii=False, indent=2))
    if images and header:
        viewer = PhotoViewer(session, 0)
        # Avatar and cover: the photo pages have the full size, the header only smaller copies.
        fbid = parse_qs(urlparse(dig(header, "profilePhoto", "url") or "").query).get("fbid", [None])[0]
        if not (fbid and save_url(session, viewer.photo(fbid).get("url"), out_dir / "avatar.jpg")):
            save_url(session, dig(header, "profilePicLarge", "uri"), out_dir / "avatar.jpg")
        cover = dig(header, "cover_photo", "photo") or {}
        if cover.get("id") and not save_url(session, viewer.photo(str(cover["id"])).get("url"), out_dir / "cover.jpg"):
            save_url(session, dig(cover, "image", "uri"), out_dir / "cover.jpg")
    return info


def write_csv(out_dir: Path) -> int:
    rows = []
    for f in sorted((out_dir / "metadata").glob("*.json")):
        try:
            rows.append(json.loads(f.read_text(encoding="utf-8"))["row"])
        except (ValueError, KeyError, OSError):
            continue
    rows.sort(key=lambda r: r.get("created") or "", reverse=True)
    if rows:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        # utf-8-sig: the BOM makes Excel show the Vietnamese text correctly.
        write_atomic(out_dir / "posts.csv", buf.getvalue(), encoding="utf-8-sig")
    return len(rows)


def folder_name(target: Target, header: dict, owner_id: Optional[str], posts: list[dict]) -> str:
    """downloads/<this>: the profile's username, else its numeric id."""
    if target.slug and not target.slug.isdigit():
        return sanitize(target.slug, 80) or "profile"
    if not target.is_post:
        return sanitize(owner_vanity(header) or "", 80) or target.slug or owner_id or "profile"
    for p in posts:   # a single post: use its author
        parts = [x for x in urlparse(p.get("author_url") or "").path.split("/") if x]
        if parts and parts[0] != "profile.php":
            return sanitize(parts[0], 80)
        if p.get("author_id"):
            return str(p["author_id"])
    return "single"


def hide_viewer(post: dict, viewer_ids: set[str]) -> dict:
    """Your own posts on someone's wall, or posts you are tagged in, can be part of a timeline.
    Keep the post but not your name / id."""
    if not viewer_ids:
        return post
    post = dict(post)
    if str(post.get("author_id")) in viewer_ids:
        post.update(author=t("(you)", "(bạn)"), author_id=None, author_url=None)
    if str(post.get("to_id")) in viewer_ids:
        post["to_id"] = None
    if str(post.get("shared_author_id")) in viewer_ids:   # a share of one of your own posts
        post.update(shared_author=t("(you)", "(bạn)"), shared_author_id=None)
    post["related_ids"] = [i for i in post.get("related_ids") or [] if i not in viewer_ids]
    return post


def is_reel(video: dict) -> bool:
    return bool(video.get("reel")) or "/reel/" in (video.get("page") or "")


def adopt_existing(dest: Path, out_dir: Path, *others: Optional[Path]) -> None:
    """Reuse a file saved under another name instead of downloading it again:
    older builds kept every file in posts/, and an album can change between 1 and several photos
    (<name>.jpg <-> <name>_01.jpg)."""
    if dest.exists():
        return
    for old in (out_dir / FOLDERS["text"] / dest.name, *others):
        if old and old != dest and old.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(old, dest)
                return
            except OSError:
                pass


def plan_post(post: dict, out_dir: Path, viewer: Optional[PhotoViewer], opts, room: int) -> dict:
    """{"photos": [(url, dest)], "videos": [(video, dest)], "files": media files relative to out_dir,
    "had": files already on disk before this run}.
    Photos go to images/, reels to reels/, other videos to videos/ (the text goes to posts/)."""
    base = post_base(post, room)
    photos = list(post["photos"]) if opts.photos else []
    if viewer and photos:
        # Big albums: the timeline only lists the first few photos.
        if post["photo_count"] > len(photos):
            more = viewer.album(f"pcb.{post['id']}", photos[0]["id"], post["photo_count"])
            if len(more) > len(photos):
                photos = more
        # Small previews -> full-size photo from the photo page.
        for ph in photos:
            if not ph["url"] or 0 < ph["size"] < 900:
                url = viewer.photo(ph["id"]).get("url")
                if url:
                    ph["url"] = url
    usable = [ph for ph in photos if ph["url"]]
    folder = out_dir / FOLDERS["image"]
    photo_tasks = []
    for i, ph in enumerate(usable, 1):
        ext = image_ext(ph["url"])
        single, first_of_many = folder / f"{base}{ext}", folder / f"{base}_01{ext}"
        dest = folder / f"{base}_{i:02d}{ext}" if len(usable) > 1 else single
        # Earlier runs may have saved this photo under the single- or multi-photo name.
        adopt_existing(dest, out_dir, single if dest == first_of_many else first_of_many if dest == single else None)
        photo_tasks.append((ph["url"], dest))
    vids = post["videos"] if opts.videos else []
    video_tasks = []
    for i, v in enumerate(vids, 1):
        vfolder = out_dir / (FOLDERS["reel"] if is_reel(v) else FOLDERS["video"])
        dest = vfolder / f"{base}{f'_v{i}' if len(vids) > 1 else ''}.mp4"
        adopt_existing(dest, out_dir)
        video_tasks.append((v, dest))
    files = [d.relative_to(out_dir).as_posix() for _, d in photo_tasks + video_tasks]
    return {"photos": photo_tasks, "photo_ids": [ph["id"] for ph in usable], "videos": video_tasks,
            "files": files, "had": {f for f in files if is_valid_file(out_dir / f)}}


def save_metadata(out_dir: Path, post: dict, files: list[str], raw=None) -> None:
    """metadata/<id>.json. Without new files or raw data, the ones saved before are kept
    (e.g. --metadata-only on a profile downloaded earlier)."""
    path = out_dir / "metadata" / f"{post['id']}.json"
    old = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    row = flat(post, files)
    if not files and dig(old, "row", "files"):
        row["files"] = old["row"]["files"]
    doc = {"row": row, "post": {k: v for k, v in post.items() if k != "_raw"}}
    if raw is not None:
        doc["raw"] = raw
    elif "raw" in old:
        doc["raw"] = old["raw"]
    write_atomic(path, json.dumps(doc, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# Main flow
# --------------------------------------------------------------------------- #

def video_id(url: str) -> Optional[str]:
    """Video id of a reel / video / watch link (fb.watch and /share/v/ links are first opened in the
    browser, which follows them to one of these)."""
    u = urlparse(url or "")
    m = re.search(r"/(?:reel|videos)/(?:[^/]+/)*?(\d{6,})", u.path)
    if m:
        return m.group(1)
    v = parse_qs(u.query).get("v", [""])[0]
    return v if v.isdigit() else None


def single_post(timeline: Timeline, target: Target) -> list[dict]:
    """The post a post / reel / video link points to (not the suggested posts shown under it)."""
    post = timeline.main_post(target.url)
    if post:
        return [post]
    vid = video_id(timeline.final_url) or video_id(target.url)
    if vid:
        # Reels / videos opened directly have no feed story: let yt-dlp take the link.
        page = timeline.final_url if video_id(timeline.final_url) else target.url
        return [blank_post(id=vid, url=page, videos=[{"id": vid, "page": page, "direct": [],
                                                      "reel": "/reel/" in page}])]
    return []


class Run:
    """Downloads of one profile / page: files, progress, and the tally for the summary."""

    def __init__(self, out_dir: Path, opts, aria2: Optional[str], ffmpeg: Optional[str], cookies: list[dict],
                 session: requests.Session):
        self.out_dir = out_dir
        self.opts = opts
        self.aria2 = aria2
        self.ffmpeg = ffmpeg
        self.cookies = cookies
        self.work = out_dir / ".parts"
        self.room = name_room(out_dir)
        self.viewer = PhotoViewer(session, opts.wait) if opts.full_photos else None
        # A post is "done" only when nothing was turned off; else "partial" so a full run completes it.
        self.complete = opts.photos and opts.videos and opts.text and opts.full_photos
        self.failures: list[tuple[str, str]] = []
        self.saved: set[str] = set()     # posts saved in this run (a post can be processed twice)
        self.processed: set[str] = set()
        self.stories_ok = 0
        self.tab_photos_ok = 0
        self.bytes = 0      # newly downloaded only
        self.stop = threading.Event()   # set on Ctrl+C: the download thread ends after its current files

    @property
    def posts_ok(self) -> int:
        return len(self.saved)

    def fail(self, progress: Optional[Progress], post: dict, reason: str, files: Optional[list[str]] = None,
             items: Optional[list[tuple[str, str, str]]] = None) -> None:
        """A post that is not fully saved. `items`: (kind, link, detail) of each photo / video that failed."""
        if progress:
            progress.mark(post["id"], "error", files, reason)
        self.failures.append(failure("post", post["url"] or post["id"], reason, items))
        lines = [f"  {bold_red('✗')} {link(post['url'] or post['id'])}", f"      {gray('└')} {yellow(reason)}"]
        lines += [f"        {gray('·')} {kind}: {link(url)}  {gray(detail)}" for kind, url, detail in items or []]
        log("\n".join(lines))

    def posts(self, pending: list[dict], progress: Progress) -> None:
        """Download a known list of posts (used for single post links)."""
        with ProgressBar(len(pending)) as bar:
            for bi in range(0, len(pending), self.opts.batch):
                self.process(pending[bi:bi + self.opts.batch], progress, bar)

    def consume(self, q: "queue.Queue", progress: Progress, bar: ProgressBar,
                latest: Callable[[str], dict]) -> None:
        """Download posts while the timeline is still being scrolled (runs in its own thread).
        Post ids are taken from `q` in batches (None means the scroll is over) and looked up with
        `latest`, so a post that came again with more photos is downloaded in its fullest version."""
        finished = False
        while not finished and not self.stop.is_set():
            item = q.get()
            if item is None:
                break
            batch = [item]
            deadline = time.monotonic() + 3   # gather what the next scrolls bring, up to --batch posts
            while len(batch) < self.opts.batch:
                try:
                    item = q.get(timeout=max(0.05, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if item is None:
                    finished = True
                    break
                batch.append(item)
            if self.stop.is_set():
                break
            try:
                self.process([latest(pid) for pid in dict.fromkeys(batch)], progress, bar)
            except Exception as e:   # keep going with the next batch
                log(warn(f"{type(e).__name__}: {e}"))

    def process(self, batch: list[dict], progress: Progress, bar: ProgressBar) -> None:
        """Plan, download and check one batch of posts."""
        opts = self.opts
        self.processed.update(p["id"] for p in batch)

        def plan(post):
            try:
                return plan_post(post, self.out_dir, self.viewer, opts, self.room)
            except Exception as e:   # never let one post stop the run
                return {"error": f"{type(e).__name__}: {e}"}

        plans = pmap(plan, batch, opts.workers)
        try:
            download_files([task for p in plans for task in p.get("photos", [])], self.aria2, opts, self.work, bar)
        except Exception as e:   # e.g. disk full: the posts of this batch are reported below
            log(warn(t(f"photo downloads failed: {type(e).__name__}: {e}",
                       f"tải ảnh bị lỗi: {type(e).__name__}: {e}")))
        video_errors: dict[Path, str] = {}

        def get_video(job):
            video, dest = job
            try:
                e = download_video(video, dest, opts, self.cookies, self.ffmpeg, bar)
            except Exception as ex:
                e = f"{type(ex).__name__}: {ex}"
            if e:
                video_errors[dest] = e

        pmap(get_video, [job for p in plans for job in p.get("videos", [])], opts.video_jobs)
        if self.stop.is_set():
            return   # stopped: leave the marks, a re-run checks these posts again
        for post, plan_ in zip(batch, plans):
            try:
                ok = self.finish(post, plan_, progress, video_errors)
            except Exception as e:
                self.fail(progress, post, f"{type(e).__name__}: {e}")
                ok = False
            bar.post_done(ok)

    def finish(self, post: dict, plan: dict, progress: Progress, video_errors: dict) -> bool:
        """Check the files of one post, write its .txt and metadata, mark it. True when complete."""
        if plan.get("error"):
            self.fail(progress, post, plan["error"])
            return False
        out_dir, opts = self.out_dir, self.opts
        # Every photo / video that failed, with a link to open it on Facebook.
        items = [(t("photo", "ảnh"), f"{FB}/photo/?fbid={pid}", d.relative_to(out_dir).as_posix())
                 for pid, (_, d) in zip(plan["photo_ids"], plan["photos"]) if not is_valid_file(d)]
        items += [("reel" if is_reel(v) else "video", v.get("page") or f"{FB}/watch/?v={v['id']}",
                   video_errors.get(d) or t("not downloaded", "không tải được"))
                  for v, d in plan["videos"] if not is_valid_file(d)]
        n_bad_photos = sum(1 for _, d in plan["photos"] if not is_valid_file(d))
        n_bad_videos = len(items) - n_bad_photos
        reasons = []
        if n_bad_photos:
            reasons.append(t(f"{n_bad_photos} of {len(plan['photos'])} photo{'s' if len(plan['photos']) != 1 else ''} not downloaded",
                             f"{n_bad_photos}/{len(plan['photos'])} ảnh không tải được"))
        if n_bad_videos:
            reasons.append(t(f"{n_bad_videos} of {len(plan['videos'])} video{'s' if len(plan['videos']) != 1 else ''} not downloaded",
                             f"{n_bad_videos}/{len(plan['videos'])} video không tải được"))
        files = [f for f in plan["files"] if is_valid_file(out_dir / f)]
        new_files = [f for f in files if f not in plan["had"]]
        if opts.text:
            txt = out_dir / FOLDERS["text"] / f"{post_base(post, self.room)}.txt"
            txt.parent.mkdir(exist_ok=True)
            write_atomic(txt, post_text_file(post, files))
            files.append(txt.relative_to(out_dir).as_posix())
        if post["created"]:
            for f in files:
                os.utime(out_dir / f, (post["created"], post["created"]))
        save_metadata(out_dir, post, files)
        for pid, (_, dest) in zip(plan["photo_ids"], plan["photos"]):
            if is_valid_file(dest):
                progress.add_photo(str(pid), dest.relative_to(out_dir).as_posix())
        if reasons:
            self.fail(progress, post, "; ".join(reasons), files, items)
            return False
        progress.mark(post["id"], "done" if self.complete else "partial", files)
        size = sum((out_dir / f).stat().st_size for f in files)
        self.saved.add(post["id"])
        self.bytes += sum((out_dir / f).stat().st_size for f in new_files)
        n_photos = len(plan["photos"])
        n_reels = sum(1 for v, _ in plan["videos"] if is_reel(v))
        n_videos = len(plan["videos"]) - n_reels
        kinds = ([f"{n_photos} {t('photos', 'ảnh')}" if n_photos > 1 else t("1 photo", "1 ảnh")] if n_photos else []) \
            + ([f"{n_videos} video"] if n_videos else []) + ([f"{n_reels} reel"] if n_reels else [])
        note = ""
        if opts.photos and post["photo_count"] > n_photos:
            # Not an error: the count can include videos, and --fast-photos skips big albums.
            note = "  " + yellow(t(f"({n_photos} of {post['photo_count']} photos found)",
                                   f"(tìm được {n_photos}/{post['photo_count']} ảnh)"))
        label = magenta(f"[{' + '.join(kinds) or t('text', 'chữ')}] ")
        log(f"  {bold_green('✓')} {label}{post_base(post, self.room)}  {gray(fmt_bytes(size))}{note}")
        return True

    def tabs(self, tab_photos: dict, albums: list[dict], progress: Progress) -> None:
        """Save the Photos tab to photos/<id>.jpg and each album to albums/<title>/<id>.jpg.

        A photo already on disk (from a post, the Photos tab or an earlier run) is hard-linked, not
        downloaded again. The rest is downloaded with aria2c in one go. Album grids only have small
        previews, so album photos not in the Photos tab are looked up on their photo page first."""
        out_dir, opts = self.out_dir, self.opts
        if not tab_photos and not albums:
            return
        limit = opts.limit

        def existing(pid: str) -> Optional[Path]:
            rel = progress.photo_file(pid)
            if rel and is_valid_file(out_dir / rel):
                return out_dir / rel
            for f in (out_dir / "photos").glob(f"{pid}.*"):
                if is_valid_file(f):
                    return f
            return None

        # Every (destination -> photo id) wanted, Photos tab first; each destination once.
        wanted: dict[Path, str] = {}
        for pid in list(tab_photos)[:limit or None]:
            wanted.setdefault(out_dir / "photos" / f"{pid}{image_ext(tab_photos[pid]['url'])}", pid)
        names = [sanitize(a["title"], 70) or "album" for a in albums]
        for album, name in zip(albums, names):
            if names.count(name) > 1:   # two albums with the same title get their own folders
                name = f"{name} ({album.get('id') or albums.index(album) + 1})"
            for pid in album["ids"][:limit or None]:
                url = (tab_photos.get(pid) or album["thumbs"].get(pid) or {}).get("url") or ""
                wanted.setdefault(out_dir / "albums" / name / f"{pid}{image_ext(url) if url else '.jpg'}", pid)
        todo = [(pid, dest) for dest, pid in wanted.items() if not is_valid_file(dest)]
        if not todo:
            return
        log("\n" + bold_cyan(t(f"  ── Photos / Albums tabs ({len(tab_photos)} photos, {len(albums)} albums)",
                                f"  ── Tab Ảnh / Album ({len(tab_photos)} ảnh, {len(albums)} album)")))
        linked = downloaded = failed = 0
        with ProgressBar(len(todo), unit=("photos", "ảnh")) as bar:
            # 1. Already on disk: link it.
            rest = []
            for pid, dest in todo:
                src = existing(pid)
                if src and src != dest and link_or_copy(src, dest):
                    linked += 1
                    bar.post_done(True)
                else:
                    rest.append((pid, dest))
            # 2. Full-size link: the Photos grid already has the original size (checked against the
            #    photo pages); only album-only photos need their photo page.
            def source(item):
                pid, dest = item
                info = tab_photos.get(pid)
                if info:
                    return pid, dest, info["url"]
                url = self.viewer.photo(pid).get("url") if self.viewer else None
                if not url:
                    for album in albums:
                        url = url or (album["thumbs"].get(pid) or {}).get("url")
                return pid, dest, url

            sources = pmap(source, rest, opts.workers)
            # 3. One download per photo; the same photo in several places is downloaded once.
            first_dest: dict[str, Path] = {}
            tasks = []
            for pid, dest, url in sources:
                if url and pid not in first_dest:
                    first_dest[pid] = dest
                    tasks.append((url, dest))
            try:
                download_files(tasks, self.aria2, opts, self.work, bar)
            except Exception as e:
                log(warn(f"{type(e).__name__}: {e}"))
            for pid, dest, url in sources:
                src = first_dest.get(pid)
                ok = is_valid_file(dest) or bool(src and src != dest and is_valid_file(src) and link_or_copy(src, dest))
                bar.post_done(ok)
                if ok and dest == src:
                    downloaded += 1
                    progress.add_photo(pid, dest.relative_to(out_dir).as_posix())
                    self.bytes += dest.stat().st_size
                elif ok:
                    linked += 1
                else:
                    failed += 1
                    self.failures.append(failure("tab", f"{FB}/photo/?fbid={pid}",
                                                 t(f"photo not downloaded: {dest.relative_to(out_dir).as_posix()}",
                                                   f"không tải được ảnh: {dest.relative_to(out_dir).as_posix()}")))
        self.tab_photos_ok = linked + downloaded
        log(f"  {bold_green('✓')} " + t(f"{downloaded} photos downloaded, {linked} reused from files already saved",
                                         f"{downloaded} ảnh tải mới, {linked} ảnh dùng lại từ file đã có")
            + (f"   {bold_red('✗')} {failed}" if failed else ""))

    def stories(self, stories: list[dict]) -> None:
        """Save active stories to stories/ and list them in stories.json (stories seen in earlier runs
        stay listed). Story videos have no page yt-dlp can open: only the direct links are used."""
        out_dir, opts = self.out_dir, self.opts
        folder = out_dir / FOLDERS["story"]
        index_path = out_dir / "stories.json"
        try:
            index = {s["id"]: s for s in json.loads(index_path.read_text(encoding="utf-8"))}
        except (OSError, ValueError, KeyError, TypeError):
            index = {}
        jobs = []   # (kind, source, dest, story)
        for st in stories:
            when = datetime.fromtimestamp(st["created"]).strftime("%Y-%m-%d_%H%M") if st["created"] else "0000-00-00"
            if opts.photos:
                jobs += [("photo", ph["url"], folder / f"{when}_{ph['id']}{image_ext(ph['url'])}", st)
                         for ph in st["photos"]]
            if opts.videos:
                jobs += [("video", {**v, "page": ""}, folder / f"{when}_{v['id']}.mp4", st) for v in st["videos"]]
        if not jobs:
            return
        log("\n" + bold_cyan(t("  ── Stories", "  ── Story")))
        had = {dest for _, _, dest, _ in jobs if is_valid_file(dest)}
        errors: dict[Path, str] = {}
        with ProgressBar(len(jobs), unit=("files", "file")) as bar:
            try:
                download_files([(src, dest) for kind, src, dest, _ in jobs if kind == "photo"],
                               self.aria2, opts, self.work, bar)
            except Exception as e:
                log(warn(f"{type(e).__name__}: {e}"))
            for kind, src, dest, _ in jobs:
                if kind == "video":
                    e = download_video(src, dest, opts, [], None, bar)
                    if e:
                        errors[dest] = e
            for _, _, dest, st in jobs:
                ok = is_valid_file(dest)
                bar.post_done(ok)
                if not ok:
                    reason = errors.get(dest) or t("not downloaded", "không tải được")
                    log(f"  {bold_red('✗')} {magenta('[story]')} {dest.name}  {yellow(reason)}")
                    self.failures.append(failure("story", f"{FB}/stories/{st.get('post_id') or st['id']}",
                                                 f"{dest.name}: {reason}"))
                    continue
                if st["created"]:
                    os.utime(dest, (st["created"], st["created"]))
                entry = index.setdefault(st["id"], {"id": st["id"], "post_id": st.get("post_id"),
                                                    "created": st["created"], "files": []})
                rel = dest.relative_to(out_dir).as_posix()
                if rel not in entry["files"]:
                    entry["files"].append(rel)
                self.stories_ok += 1
                if dest not in had:
                    self.bytes += dest.stat().st_size
                log(f"  {bold_green('✓')} {magenta('[story]')} {dest.name}")
        write_atomic(index_path, json.dumps(sorted(index.values(), key=lambda s: s["created"] or 0, reverse=True),
                                            ensure_ascii=False, indent=2))


def link_or_copy(src: Path, dest: Path) -> bool:
    """Put an existing file at dest too: a hard link (no extra disk space), or a copy."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dest)
    except OSError:
        try:
            shutil.copy2(src, dest)
        except OSError:
            return False
    return True


def failure(kind: str, url: str, reason: str, items: Optional[list[tuple[str, str, str]]] = None) -> dict:
    """One line of failed.txt. kind: post | story | tab. items: (kind, link, detail) of the photos /
    videos inside a post that failed."""
    return {"kind": kind, "url": url, "reason": reason, "items": items or []}


def write_failed(out_dir: Path, failures: list[dict]) -> Path:
    """failed.txt: what could not be downloaded, grouped, each with a link to open it on Facebook.
    Rewritten after every run; removed when nothing failed."""
    failed_file = out_dir / "failed.txt"
    if not failures:
        failed_file.unlink(missing_ok=True)
        return failed_file
    lines = [t(f"# {len(failures)} items could not be downloaded ({datetime.now():%Y-%m-%d %H:%M})",
               f"# {len(failures)} mục không tải được ({datetime.now():%Y-%m-%d %H:%M})"),
             t("# Run the same command again to retry: finished items are skipped.",
               "# Chạy lại đúng lệnh cũ để thử lại: những gì đã xong sẽ được bỏ qua."),
             t("# Open a link to see the post / photo / video on Facebook.",
               "# Mở link để xem bài / ảnh / video trên Facebook.")]
    groups = [("post", t("Posts", "Bài đăng")), ("story", t("Stories", "Story")),
              ("tab", t("Photos / Albums tabs", "Tab Ảnh / Album"))]
    for kind, title in groups:
        group = [f for f in failures if f["kind"] == kind]
        if not group:
            continue
        lines += ["", f"== {title} ({len(group)}) =="]
        for f in group:
            lines += [f["url"], f"    {f['reason']}"]
            lines += [f"    - {k}: {u}   ({d})" for k, u, d in f["items"]]
    write_atomic(failed_file, "\n".join(lines) + "\n")
    return failed_file


def report(run: Run, out_dir: Path, rows: int, failed_file: Path, secs: float, with_stories: bool,
           already: int = 0) -> None:
    """The summary at the end of a run: what was saved, how much, and where."""
    log("\n" + bold(f"  ━━ {t('Done ', 'Xong ')}") + gray("━" * 36))
    n_posts, n_stories, n_tabs = run.posts_ok, run.stories_ok, run.tab_photos_ok
    done = [t(f"{n_posts} post" + ("" if n_posts == 1 else "s"), f"{n_posts} bài")]
    if with_stories:
        done.append(t(f"{n_stories} story file" + ("" if n_stories == 1 else "s"), f"{n_stories} file story"))
    if n_tabs:
        done.append(t(f"{n_tabs} photos from the Photos / Albums tabs", f"{n_tabs} ảnh từ tab Ảnh / Album"))
    counts = (f"  {bold_green('✓ ' + ', '.join(done))}   "
              + (bold_red(f"✗ {len(run.failures)}") if run.failures else gray("✗ 0")) + f" {t('failed', 'lỗi')}")
    if already:
        counts += gray(t(f" · {already} already saved", f" · {already} bài đã có từ trước"))
    if run.bytes:
        counts += gray(" · ") + f"{bold(fmt_bytes(run.bytes))} {t('new in', 'mới trong')} {fmt_eta(secs)}"
    log(counts)
    log(gray(t("  Folder: ", "  Thư mục: ")) + blue(str(out_dir)) + gray(f"  (posts.csv: {rows})"))
    if run.failures:
        log(yellow(t("  Failed items with links: ", "  Danh sách lỗi kèm link: ")) + blue(str(failed_file)))
    log(gray(t("  Full log of this run: ", "  Nhật ký đầy đủ của lượt chạy: ")) + blue(str(out_dir / "fb-dl.log")))


def account_ids(cookies: list[dict]) -> set[str]:
    """Ids of the logged-in account: the user (c_user) and the Page it may be acting as (i_user)."""
    return {c["value"] for c in cookies if c["name"] in ("c_user", "i_user") and c["value"].isdigit()}


class Job:
    """One profile / page / post link.

    For a profile or page the timeline is read and downloaded at the same time: every post the scroll
    finds goes through the filters (owner, --since / --until / -n, already saved), its metadata is saved,
    and it is queued for Run.consume(), which downloads in its own thread. After the scroll the queue is
    finished, then the stories and the Photos / Albums tabs follow.
    A single post link is read first and downloaded after.
    """

    def __init__(self, target: Target, opts, cookies: list[dict], aria2: Optional[str], ffmpeg: Optional[str]):
        self.target, self.opts, self.cookies = target, opts, cookies
        self.aria2, self.ffmpeg = aria2, ffmpeg
        self.viewer_ids = account_ids(cookies)
        self.timeline = Timeline(opts, cookies, self.viewer_ids)
        self.session = http_session(cookies)
        self.me = ""
        self.out_dir: Optional[Path] = None
        self.progress: Optional[Progress] = None
        self.run: Optional[Run] = None
        self.bar: Optional[ProgressBar] = None
        self.queue: "queue.Queue" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.n = {"own": 0, "old": 0, "known": 0, "others": 0, "already": 0, "filtered": 0}
        self.latest: dict[str, dict] = {}   # queued posts by id, in their fullest version
        self.started = time.monotonic()

    # -- output ----------------------------------------------------------- #

    def open_output(self, folder: str) -> None:
        self.out_dir = Path(self.opts.output).resolve() / folder
        (self.out_dir / "metadata").mkdir(parents=True, exist_ok=True)
        open_log(self.out_dir / "fb-dl.log", self.target.slug or self.target.url)
        self.progress = Progress(self.out_dir / ".progress.db")
        self.run = Run(self.out_dir, self.opts, self.aria2, self.ffmpeg, self.cookies, self.session)

    def save_meta(self, post: dict) -> None:
        raw = scrub(post.get("_raw"), self.viewer_ids, self.me) if self.opts.raw else None
        save_metadata(self.out_dir, post, [], raw)

    def log_login(self) -> None:
        if not self.cookies:
            log(warn(t("Not logged in: Facebook only shows a few posts. Run --login first to get everything.",
                       "Chưa đăng nhập: Facebook chỉ hiện vài bài. Chạy --login trước để lấy đầy đủ.")))
        elif self.me:
            log(gray(t("  Logged in as ", "  Đăng nhập: ")) + mask_name(self.me))

    # -- callbacks from the timeline (browser thread) ---------------------- #

    def on_ready(self) -> None:
        tl, opts = self.timeline, self.opts
        uid, self.me = page_user(tl.html)
        if self.cookies and uid == "0":
            raise ScrapeError(t("the cookies are not logged in (expired or wrong). Run: python fb-dl.py --login",
                                "cookie không còn đăng nhập (hết hạn hoặc sai). Chạy: python fb-dl.py --login"))
        if uid != "0":
            self.viewer_ids.add(uid)
        if self.target.is_post:
            return   # a single post is handled once the page is read
        self.open_output(folder_name(self.target, tl.header, tl.owner_id, []))
        try:
            info = save_profile(tl.header, tl.html, self.out_dir, self.session, tl.owner_id,
                                images=opts.photos and not opts.metadata_only)
            dot = gray(" · ")
            log(f"  {bold(info['name'] or self.target.slug)}"
                + (f"{dot}{info['followers']}" if info.get("followers") else "")
                + (f"{dot}id {info['id']}" if info.get("id") else ""))
        except Exception as e:
            log(warn(t(f"could not save the profile info: {e}", f"không lưu được thông tin trang: {e}")))
        self.log_login()
        if opts.metadata_only:
            return
        log(gray(t("  Reading the timeline and downloading at the same time → ",
                   "  Vừa đọc timeline vừa tải → ")) + blue(str(self.out_dir)) + "\n")
        self.bar = ProgressBar(scrolling=True).__enter__()
        tl.on_scroll = lambda count, oldest: None   # the progress bar shows the scroll
        tl.on_tab = self.bar.set_note
        self.worker = threading.Thread(target=self.run.consume, name="downloads", daemon=True,
                                       args=(self.queue, self.progress, self.bar, self.latest.__getitem__))
        self.worker.start()

    def on_new(self, post: dict) -> None:
        if self.target.is_post:
            return
        try:
            self._on_new(post)
        except Exception as e:   # e.g. disk full: report this post, keep scrolling
            self.run.failures.append(failure("post", post.get("url") or post.get("id"), f"{type(e).__name__}: {e}"))
            log(f"  {bold_red('✗')} {link(post.get('url') or post.get('id'))}\n      {gray('└')} "
                + yellow(f"{type(e).__name__}: {e}"))

    def _on_new(self, post: dict) -> None:
        opts = self.opts
        if not (opts.include_others or is_own(post, self.timeline.owner_id)):
            self.n["others"] += 1
            return
        created = post["created"]
        if opts.until and created and created > opts.until:
            self.n["filtered"] += 1
            return
        if opts.since and created and created < opts.since:
            self.n["old"] += 1
            self.n["filtered"] += 1
            return
        self.n["old"] = 0
        if opts.limit and self.n["own"] >= opts.limit:
            return
        self.n["own"] += 1
        post = hide_viewer(post, self.viewer_ids)
        self.n["known"] = self.n["known"] + 1 if self.progress.known(post["id"]) else 0
        if not opts.metadata_only and self.progress.done(post["id"], self.out_dir):
            self.n["already"] += 1   # keep its metadata (with the file list) as it is
            return
        self.save_meta(post)
        if not opts.metadata_only:
            self.latest[post["id"]] = post
            self.queue.put(post["id"])
            self.bar.found(1, created)

    def on_update(self, post: dict) -> None:
        """A queued post came again with more photos / videos: use that version. If it was already
        downloaded, queue it once more (only the new files are downloaded)."""
        pid = post["id"]
        if self.target.is_post or self.opts.metadata_only or pid not in self.latest:
            return
        self.latest[pid] = hide_viewer(post, self.viewer_ids)
        if pid in self.run.processed:
            self.run.processed.discard(pid)
            self.queue.put(pid)

    def should_stop(self) -> bool:
        opts = self.opts
        if opts.limit and self.n["own"] >= opts.limit:
            return True
        if opts.since and self.n["old"] >= 5:      # 5 older posts in a row (a pinned post can be old)
            return True
        return bool(opts.update and self.n["known"] >= 10)

    # -- the whole job ---------------------------------------------------- #

    def finish_downloads(self) -> None:
        """Let the download thread empty the queue, then close the progress bar."""
        if self.worker:
            self.queue.put(None)
            while self.worker.is_alive():   # short joins so Ctrl+C still works
                self.worker.join(0.5)
            self.worker = None
        if self.bar:
            self.bar.__exit__(None, None, None)
            self.bar = None

    def execute(self) -> int:
        tl, opts, target = self.timeline, self.opts, self.target
        tl.on_ready, tl.on_new, tl.on_update = self.on_ready, self.on_new, self.on_update
        stories: list[dict] = []
        early: Optional[int] = None   # set when there is nothing to download / summarise
        stopped = False
        try:
            try:
                tl.collect(target.url, target.is_post, self.should_stop)
            finally:
                status("")
                if self.bar:
                    self.bar.scroll_done()
            if target.is_post:
                early = self.single()
            else:
                stories = tl.stories if opts.stories else []
                early = self.after_scroll(stories)
                if early is None:
                    self.finish_downloads()
                    if stories:
                        self.run.stories(stories)
                    if tl.tab_photos or tl.albums:
                        self.run.tabs(tl.tab_photos, tl.albums, self.progress)
        except KeyboardInterrupt:
            stopped = True
            raise
        finally:
            if stopped:
                # Let the download thread finish the file it is on (briefly), then stop.
                if self.run:
                    self.run.stop.set()
                if self.worker:
                    self.worker.join(2)
                if self.bar:
                    self.bar.__exit__(None, None, None)
            else:
                self.finish_downloads()   # also after an error: finish what was already queued
            if self.progress and not (self.worker and self.worker.is_alive()):
                self.progress.close()
            rows, failed_file = 0, None
            if self.run:
                if self.run.work.exists():
                    shutil.rmtree(self.run.work, ignore_errors=True)
                # Also when stopped or after an error: keep posts.csv / failed.txt in step with the files.
                rows = write_csv(self.out_dir)
                failed_file = write_failed(self.out_dir, self.run.failures)
        try:
            if early is not None:
                return early
            report(self.run, self.out_dir, rows, failed_file, max(1.0, time.monotonic() - self.started),
                   bool(stories), self.n["already"])
            return len(self.run.failures)
        finally:
            close_log()

    def after_scroll(self, stories: list[dict]) -> Optional[int]:
        """What the scroll found. Returns an exit code when there is nothing left to download."""
        opts = self.opts
        if self.out_dir is None:   # the page never loaded far enough to know the profile
            raise ScrapeError(t("could not read this profile / page", "không đọc được trang này"))
        if self.n["others"] and not opts.include_others:
            log(gray(t(f"  Skipped {self.n['others']} ads / posts of other pages that Facebook mixed "
                       "into the timeline (keep them with --include-others).",
                       f"  Bỏ qua {self.n['others']} bài quảng cáo / bài của trang khác Facebook chèn "
                       "vào timeline (giữ lại bằng --include-others).")))
        if opts.stories:
            log(gray(t(f"  Stories: {len(stories)} active." if stories else "  Stories: none active right now.",
                       f"  Story: {len(stories)} đang hoạt động." if stories else "  Story: hiện không có story nào.")))
        tabs = self.timeline.tab_photos or self.timeline.albums
        if not self.n["own"] and self.n["filtered"]:
            log(warn(t(f"No posts in the chosen dates ({self.n['filtered']} posts outside --since / --until).",
                       f"Không có bài nào trong khoảng ngày đã chọn ({self.n['filtered']} bài nằm ngoài --since / --until).")))
        elif not self.n["own"] and not stories and not tabs:
            log(warn(t("No posts found. The profile may be private, empty, or need login (--login).",
                       "Không tìm thấy bài nào. Profile có thể riêng tư, trống, hoặc cần đăng nhập (--login).")))
            return 1
        if not self.n["own"] and not stories and not tabs:
            return 0
        if opts.metadata_only:
            rows = write_csv(self.out_dir)
            log(green(t(f"  ✓ Metadata saved ({rows} posts in posts.csv) → ",
                        f"  ✓ Đã lưu metadata ({rows} bài trong posts.csv) → ")) + blue(str(self.out_dir)))
            return 0
        return None

    def single(self) -> Optional[int]:
        """A post / reel / video link: read it, then download it. Returns an exit code when there is
        nothing to download."""
        tl, opts = self.timeline, self.opts
        posts = [hide_viewer(p, self.viewer_ids) for p in single_post(tl, self.target)]
        self.open_output(folder_name(self.target, tl.header, tl.owner_id, posts))
        self.log_login()
        if not posts:
            log(warn(t("This link has no post that can be read (deleted, private, or needs --login).",
                       "Link này không có bài nào đọc được (đã xoá, riêng tư, hoặc cần --login).")))
            return 1
        for p in posts:
            self.save_meta(p)
        if opts.metadata_only:
            return 0
        pending = [p for p in posts if not self.progress.done(p["id"], self.out_dir)]
        self.n["already"] = len(posts) - len(pending)
        self.run.posts(pending, self.progress)
        return None


def scrape(target_text: str, opts, cookies: list[dict], aria2: Optional[str], ffmpeg: Optional[str]) -> int:
    """Everything for one profile / page / post link. Returns the number of failures."""
    target = Target(target_text)
    label = target.slug or target.url
    log("\n" + bold_cyan(f"━━ {label} ") + gray("━" * max(4, 40 - len(label))))
    return Job(target, opts, cookies, aria2, ffmpeg).execute()


def check_login(opts, cookies: list[dict]) -> int:
    if not cookies:
        log(bold_red(t("✗ No login. Run: python fb-dl.py --login", "✗ Chưa đăng nhập. Chạy: python fb-dl.py --login")))
        return 1
    sync_playwright = import_playwright()
    with sync_playwright() as pw:
        browser = launch_browser(pw, opts.browser, headless=True)
        try:
            ctx = browser.new_context(locale="en-US")
            ctx.add_cookies(cookies)
            page = ctx.new_page()
            page.goto(f"{FB}/me", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            uid, name = page_user(page.content())
            url = page.url
        finally:
            browser.close()
    if "/checkpoint" in url:
        log(bold_red(t("✗ Facebook wants you to verify the account (checkpoint). Open facebook.com in your browser.",
                       "✗ Facebook yêu cầu xác minh tài khoản (checkpoint). Mở facebook.com trên trình duyệt.")))
        return 1
    if uid == "0":
        log(bold_red(t("✗ The session is expired or invalid. Run: python fb-dl.py --login",
                       "✗ Phiên đăng nhập hết hạn hoặc sai. Chạy: python fb-dl.py --login")))
        return 1
    log(bold_green("✓ ") + green(t("Logged in as ", "Đang đăng nhập là ")) + bold(mask_name(name)))
    return 0


def logout() -> None:
    """Delete the saved session and say how to end it on Facebook's side too."""
    existed = SESSION_FILE.exists()
    SESSION_FILE.unlink(missing_ok=True)
    log(green(t("✓ Saved session deleted (fb-session.json)." if existed else "✓ No saved session.",
                "✓ Đã xoá phiên đã lưu (fb-session.json)." if existed else "✓ Không có phiên nào được lưu.")))
    if existed:
        log(yellow(t("  The session still works on Facebook until you log it out there:\n"
                     "  Facebook → Settings & privacy → Settings → Accounts Center → Password and security →\n"
                     "  Where you're logged in → log out the session (or change your password to log out everywhere).",
                     "  Phiên vẫn còn hiệu lực trên Facebook cho tới khi bạn đăng xuất nó ở đó:\n"
                     "  Facebook → Cài đặt & quyền riêng tư → Cài đặt → Trung tâm tài khoản → Mật khẩu và bảo mật →\n"
                     "  Nơi bạn đã đăng nhập → đăng xuất phiên đó (hoặc đổi mật khẩu để đăng xuất mọi nơi).")))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fb-dl",
        description=t("Download every post (text, photos, videos, reels, stories) of a Facebook profile or "
                      "page, from the first post to today, in the best quality.",
                      "Tải toàn bộ bài đăng (chữ, ảnh, video, reel, story) của một trang cá nhân hoặc fanpage "
                      "Facebook, từ bài đầu tiên tới hiện tại, chất lượng cao nhất."),
        epilog=t("Examples:", "Ví dụ:")
               + "\n  python fb-dl.py --login\n  python fb-dl.py nasa\n"
               "  python fb-dl.py https://www.facebook.com/profile.php?id=123456789012345\n"
               "  python fb-dl.py nasa -n 50 --since 2025-01-01\n"
               "  python fb-dl.py nasa --update\n"
               "  python fb-dl.py https://www.facebook.com/nasa/posts/pfbid0abc...\n"
               "  python fb-dl.py --logout\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    a = p.add_argument
    a("targets", nargs="*", metavar="profile",
      help=t("username, profile / page link, profile.php?id=..., numeric id or post link (several allowed)",
             "username, link trang / fanpage, profile.php?id=..., id số hoặc link bài (nhập được nhiều)"))
    a("-o", "--output", default="downloads", help=t("root folder (default: downloads)", "thư mục gốc (mặc định: downloads)"))

    g = p.add_argument_group(t("what to download (default: everything)", "tải những gì (mặc định: tất cả)"))
    g.add_argument("-n", "--limit", type=int,
                   help=t("only the N newest posts (and the first N photos of each Photos / Albums tab and album)",
                          "chỉ lấy N bài mới nhất (và N ảnh đầu của tab Ảnh và mỗi album)"))
    g.add_argument("--since", type=parse_date, metavar="YYYY-MM-DD",
                   help=t("only posts from this day on (scrolling stops there)", "chỉ lấy bài từ ngày này trở đi (dừng cuộn khi tới đó)"))
    g.add_argument("--until", type=lambda s: parse_date(s, end=True), metavar="YYYY-MM-DD",
                   help=t("only posts up to this day", "chỉ lấy bài tới hết ngày này"))
    g.add_argument("--update", action="store_true",
                   help=t("stop scrolling after 10 posts in a row that were already downloaded (fast re-runs)",
                          "dừng cuộn khi gặp 10 bài liên tiếp đã tải (chạy lại nhanh để lấy bài mới)"))
    g.add_argument("--no-photos", dest="photos", action="store_false", help=t("do not download photos", "không tải ảnh"))
    g.add_argument("--no-videos", dest="videos", action="store_false", help=t("do not download videos and reels", "không tải video và reel"))
    g.add_argument("--no-text", dest="text", action="store_false",
                   help=t("do not write a .txt file for each post", "không ghi file .txt cho mỗi bài"))
    g.add_argument("--no-stories", dest="stories", action="store_false",
                   help=t("do not save the active stories", "không tải story đang hoạt động"))
    g.add_argument("--no-all-photos", dest="all_photos", action="store_false",
                   help=t("do not save the Photos / Albums tabs",
                          "không tải tab Ảnh / Album"))
    g.add_argument("--metadata-only", action="store_true",
                   help=t("only save metadata (JSON + CSV), no files", "chỉ lưu metadata (JSON + CSV), không tải file"))
    g.add_argument("--include-others", action="store_true",
                   help=t("keep ads and posts of other pages that Facebook mixes into the timeline",
                          "giữ cả quảng cáo và bài của trang khác Facebook chèn vào timeline"))
    g.add_argument("--raw", action="store_true",
                   help=t("also keep Facebook's raw data in metadata/*.json (your account is removed from it)",
                          "lưu thêm dữ liệu gốc của Facebook vào metadata/*.json (đã xoá thông tin tài khoản của bạn)"))
    # Hidden: commands from earlier development builds used these flags; they are the default now.
    g.add_argument("--stories", dest="_legacy_stories", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--all-photos", dest="_legacy_all_photos", action="store_true", help=argparse.SUPPRESS)

    q = p.add_argument_group(t("quality and speed", "chất lượng và tốc độ"))
    q.add_argument("--fast-photos", dest="full_photos", action="store_false",
                   help=t("only the photos listed on the timeline (faster, but big albums are cut)",
                          "chỉ lấy ảnh có sẵn trên timeline (nhanh hơn, nhưng album lớn bị thiếu)"))
    q.add_argument("--direct-video", action="store_true",
                   help=t("use the timeline MP4 instead of yt-dlp (faster, often only 720p)",
                          "dùng link MP4 trên timeline thay vì yt-dlp (nhanh hơn, thường chỉ 720p)"))
    q.add_argument("-j", "--jobs", type=int, default=16, help=t("files aria2c downloads at once (default: 16)", "số file aria2c tải cùng lúc (mặc định: 16)"))
    q.add_argument("-x", "--connections", type=int, default=8, help=t("aria2c connections per file (default: 8)", "số kết nối aria2c mỗi file (mặc định: 8)"))
    q.add_argument("--video-jobs", type=int, default=3, help=t("videos downloaded at once (default: 3)", "số video tải cùng lúc (mặc định: 3)"))
    q.add_argument("-w", "--workers", type=int, default=4, help=t("threads reading photo pages (default: 4)", "số luồng đọc trang ảnh (mặc định: 4)"))
    q.add_argument("--wait", type=float, default=0.5, help=t("seconds between photo page requests (default: 0.5)", "giãn cách giữa các request trang ảnh, giây (mặc định: 0.5)"))
    q.add_argument("--batch", type=int, default=30, help=t("posts per download batch (default: 30)", "số bài mỗi lô tải (mặc định: 30)"))

    b = p.add_argument_group(t("browser and scrolling", "trình duyệt và cuộn trang"))
    b.add_argument("--browser", choices=("auto", "msedge", "chrome", "chromium"), default="auto",
                   help=t("browser used to read the timeline (default: auto = Edge, Chrome, then Chromium)",
                          "trình duyệt dùng để đọc timeline (mặc định: auto = Edge, Chrome, rồi Chromium)"))
    b.add_argument("--show-browser", action="store_true", help=t("show the browser window while scrolling", "hiện cửa sổ trình duyệt khi cuộn"))
    b.add_argument("--scroll-wait", type=float, default=1.5, help=t("seconds between scrolls (default: 1.5)", "số giây giữa mỗi lần cuộn (mặc định: 1.5)"))
    b.add_argument("--max-idle", type=int, default=25,
                   help=t("stop after this many scrolls with no new posts (default: 25)",
                          "dừng sau ngần này lần cuộn không có bài mới (mặc định: 25)"))

    s = p.add_argument_group(t("login", "đăng nhập"))
    s.add_argument("--login", action="store_true", help=t("open a browser window to log in and save the session", "mở cửa sổ trình duyệt để đăng nhập và lưu phiên"))
    s.add_argument("--logout", action="store_true", help=t("delete the saved session (fb-session.json)", "xoá phiên đã lưu (fb-session.json)"))
    s.add_argument("--check-login", action="store_true", help=t("only check the login, then exit", "chỉ kiểm tra đăng nhập rồi thoát"))
    s.add_argument("--cookies", metavar="FILE", help=t("use a cookies.txt / JSON export instead of the saved session", "dùng file cookies.txt / JSON xuất từ trình duyệt thay cho phiên đã lưu"))
    s.add_argument("--no-login", action="store_true", help=t("ignore the saved session (logged out)", "không dùng phiên đã lưu (chế độ chưa đăng nhập)"))

    o = p.add_argument_group(t("output", "hiển thị"))
    o.add_argument("--lang", choices=("en", "vi"), default=LANG, help=t("message language (default: auto)", "ngôn ngữ thông báo (mặc định: tự nhận)"))
    o.add_argument("--no-color", dest="color", action="store_false", help=t("plain text output", "in chữ trơn, không màu"))
    o.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main() -> None:
    global LANG
    LANG = detect_lang(sys.argv[1:])
    if LANG not in ("en", "vi"):
        LANG = "en"
    p = build_parser()
    opts = p.parse_args()
    LANG = opts.lang
    init_colors(opts.color)
    # Keep the concurrency and timing values within sane bounds for this machine.
    opts.jobs = max(1, min(32, opts.jobs))
    opts.connections = max(1, min(16, opts.connections))
    opts.video_jobs = max(1, min(8, opts.video_jobs))
    opts.workers = max(1, min(8, opts.workers))
    opts.batch = max(1, opts.batch)
    opts.max_idle = max(2, opts.max_idle)
    opts.scroll_wait = max(0.5, opts.scroll_wait)
    if opts.limit is not None and opts.limit < 1:
        p.error(t("-n/--limit must be 1 or more", "-n/--limit phải từ 1 trở lên"))

    try:
        if opts.logout:
            logout()
            if not opts.targets and not opts.login:
                sys.exit(0)
        if opts.login:
            do_login(opts)
            if not opts.targets:
                sys.exit(0)
        cookies = [] if opts.no_login else load_cookies(opts.cookies)
        if opts.check_login:
            sys.exit(check_login(opts, cookies))
        if not opts.targets:
            p.error(t("enter at least one profile, page or post link (or use --login first)",
                      "cần nhập ít nhất một profile, page hoặc link bài (hoặc chạy --login trước)"))

        aria2 = find_tool("aria2c")
        ffmpeg = find_ffmpeg()
        if not opts.metadata_only:
            log(gray(t("Downloader: ", "Bộ tải:     ")) + (green("aria2c") + gray(f"  {aria2}") if aria2 else
                yellow(t("requests (aria2c not found, slower)", "requests (không có aria2c, sẽ chậm hơn)"))))
            log(gray("ffmpeg:     ") + (green("ffmpeg") + gray(f"  {ffmpeg}") if ffmpeg else
                yellow(t("not found (videos may be lower quality)", "không có (video có thể chất lượng thấp hơn)"))))
        log(gray(t("Login:      ", "Đăng nhập:  ")) + (green(t("yes", "có")) + gray(f"  ({Path(opts.cookies).name if opts.cookies else SESSION_FILE.name})")
            if cookies else yellow(t("no (only a few posts are visible)", "không (chỉ thấy được vài bài)"))))

        failed = 0
        for target in opts.targets:
            try:
                failed += scrape(target, opts, cookies, aria2, ffmpeg)
            except ScrapeError as e:
                failed += 1
                status("")
                log(bold_red(t("Error: ", "Lỗi: ")) + red(str(e)), err=True)
            except Exception as e:   # an unexpected error: report it and go on with the next profile
                failed += 1
                status("")
                log(bold_red(t("Error: ", "Lỗi: ")) + red(f"{type(e).__name__}: {e}"), err=True)
    except ScrapeError as e:
        log(bold_red(t("Error: ", "Lỗi: ")) + red(str(e)), err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        status("")
        log("\n" + yellow(t("Stopped. Run the same command again to continue.",
                             "Đã dừng. Chạy lại đúng lệnh cũ để tải tiếp.")), err=True)
        sys.stdout.flush()
        os._exit(130)   # do not wait for downloads still running in other threads
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
