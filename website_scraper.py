#!/usr/bin/env python3
"""
website_scraper.py — Website-Scraper Desktop-App (PyQt6, Dark Mode)

Framework-Wahl: PyQt6
  PyQt6 bietet native Windows-Integration, exzellente Dark-Mode-Unterstützung
  via QSS-Stylesheets, einen robusten Signal/Slot-Mechanismus für vollständig
  thread-sichere UI-Updates und eine ausgereifte Widget-Bibliothek für
  professionelle Desktop-Apps. Im Gegensatz zu CustomTkinter (tkinter-basiert,
  gemäß Spec ausgeschlossen) und PySide6 liefert PyQt6 die stabilste,
  bestdokumentierte Basis für eine eigenständige Windows-Anwendung.
"""

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — BOOTSTRAP: Auto-Install fehlender Abhängigkeiten
# ══════════════════════════════════════════════════════════════════════════════

import sys
import subprocess
import importlib
import site
import os
import json
from pathlib import Path

SETUP_VERSION = "1.1"
SETTINGS_FILE = Path.home() / ".website_scraper_settings.json"

REQUIRED_PACKAGES: dict[str, str] = {
    "PyQt6":        "PyQt6",
    "bs4":          "beautifulsoup4",
    "lxml":         "lxml",
    "playwright":   "playwright",
    "openai":       "openai",
    "google":       "google-genai",
    "keyring":      "keyring",
    "keyrings":     "keyrings.alt",
}


def _refresh_sys_path() -> None:
    try:
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            sys.path.append(user_site)
    except Exception:
        pass
    try:
        for p in site.getsitepackages():
            if p and p not in sys.path:
                sys.path.append(p)
    except Exception:
        pass


def _missing_packages() -> list[str]:
    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def _pip_install(packages: list[str]) -> None:
    for pkg in packages:
        print(f"[Setup] pip install {pkg} …", flush=True)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", pkg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    _refresh_sys_path()


def _playwright_install_chromium() -> None:
    print("[Setup] playwright install chromium …", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _load_raw_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_raw_settings(data: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Determine whether setup is needed ───────────────────────────────────────
_raw_cfg = _load_raw_settings()
_setup_done = (
    _raw_cfg.get("setup_done") is True
    and _raw_cfg.get("setup_version") == SETUP_VERSION
)

_missing = _missing_packages()
if _missing:
    _setup_done = False

if not _setup_done:
    # Phase 1: install Python packages (console-based, no Qt yet)
    if _missing:
        print(f"[Setup] Installiere fehlende Pakete: {_missing}", flush=True)
        _pip_install(_missing)
        _refresh_sys_path()

    # Phase 2: install playwright chromium
    # Use Qt dialog if PyQt6 is now available
    try:
        from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar
        from PyQt6.QtCore import Qt as _Qt

        _app_setup = QApplication.instance() or QApplication(sys.argv)
        _setup_style = (
            "QWidget{background:#1e1e2e;color:#cdd6f4;font-family:'Segoe UI';font-size:13px;}"
            "QProgressBar{border:1px solid #45475a;border-radius:5px;background:#313244;min-height:20px;}"
            "QProgressBar::chunk{background:#89b4fa;border-radius:4px;}"
        )

        class _SetupDlg(QDialog):
            def __init__(self) -> None:
                super().__init__()
                self.setWindowTitle("Website Scraper — Ersteinrichtung")
                self.setFixedSize(480, 140)
                self.setStyleSheet(_setup_style)
                lay = QVBoxLayout(self)
                self._lbl = QLabel("Installiere Playwright Chromium …")
                self._lbl.setAlignment(_Qt.AlignmentFlag.AlignCenter)
                self._bar = QProgressBar()
                self._bar.setRange(0, 100)
                self._bar.setValue(0)
                lay.addWidget(self._lbl)
                lay.addWidget(self._bar)

            def tick(self, msg: str, pct: int) -> None:
                self._lbl.setText(msg)
                self._bar.setValue(pct)
                _app_setup.processEvents()

        _dlg = _SetupDlg()
        _dlg.show()
        _dlg.tick("Installiere Playwright Chromium …", 20)
        _playwright_install_chromium()
        _dlg.tick("Einrichtung abgeschlossen!", 100)
        import time as _t; _t.sleep(1)
        _dlg.close()

    except Exception:
        _playwright_install_chromium()

    _raw_cfg["setup_done"] = True
    _raw_cfg["setup_version"] = SETUP_VERSION
    _save_raw_settings(_raw_cfg)

else:
    # Always verify playwright chromium still works
    try:
        from playwright.sync_api import sync_playwright as _spw
        with _spw() as _pw:
            _b = _pw.chromium.launch(headless=True)
            _b.close()
    except Exception:
        _playwright_install_chromium()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

import gzip
import base64
import threading
import random
import re
import time
import urllib.request
import urllib.parse
from xml.etree import ElementTree as ET
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox,
    QProgressBar, QTextEdit, QFileDialog, QTabWidget, QFrame,
    QSizePolicy, QGroupBox, QSpinBox, QDialog, QDialogButtonBox,
    QFormLayout, QMessageBox, QScrollArea, QStyle,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QTextCursor

from bs4 import BeautifulSoup, NavigableString, Tag
from playwright.sync_api import sync_playwright

try:
    import keyring
    _KEYRING_OK = True
except ImportError:
    _KEYRING_OK = False

try:
    import keyrings.alt  # noqa: F401 — ensure fallback backend is registered
except ImportError:
    pass


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — SETTINGS & CONFIG
# ══════════════════════════════════════════════════════════════════════════════

KEYRING_SERVICE = "website_scraper"

DEFAULT_SETTINGS: dict = {
    "ai_provider": "openai",
    "openai_model": "gpt-4o",
    "gemini_model": "gemini-2.0-flash",
    "ai_describe_images": False,
    "browser_headless": True,
    "max_images_per_page": 30,
    "last_mode": "single",
    "single_url": "",
    "single_output_path": str(Path.home() / "Desktop"),
    "sitemap_url": "",
    "sitemap_output_path": str(Path.home() / "Desktop"),
    "setup_done": True,
    "setup_version": SETUP_VERSION,
}


class Settings:
    def __init__(self) -> None:
        self._data: dict = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        try:
            stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self._data.update(stored)
        except Exception:
            pass

    def save(self) -> None:
        try:
            SETTINGS_FILE.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get(self, key: str, default=None):
        fallback = default if default is not None else DEFAULT_SETTINGS.get(key)
        return self._data.get(key, fallback)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def get_api_key(self, provider: str) -> str:
        if _KEYRING_OK:
            try:
                return keyring.get_password(KEYRING_SERVICE, provider) or ""
            except Exception:
                pass
        return self._data.get(f"{provider}_api_key", "")

    def set_api_key(self, provider: str, key: str) -> None:
        if _KEYRING_OK:
            try:
                keyring.set_password(KEYRING_SERVICE, provider, key)
                return
            except Exception:
                pass
        self._data[f"{provider}_api_key"] = key
        self.save()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — SITEMAP PARSER
# ══════════════════════════════════════════════════════════════════════════════

_NS_STRIP = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_STRIP.sub("", tag)


def _fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "WebsiteScraper/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    if url.endswith(".gz") or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def parse_sitemap(url: str) -> list[str]:
    """Recursively resolve sitemap(index) and return all page URLs."""
    urls: list[str] = []
    try:
        data = _fetch_bytes(url)
        root = ET.fromstring(data)
        root_tag = _strip_ns(root.tag)
        if root_tag == "sitemapindex":
            for elem in root.iter():
                if _strip_ns(elem.tag) == "loc":
                    child = (elem.text or "").strip()
                    if child:
                        urls.extend(parse_sitemap(child))
        elif root_tag == "urlset":
            for elem in root.iter():
                if _strip_ns(elem.tag) == "loc":
                    loc = (elem.text or "").strip()
                    if loc:
                        urls.append(loc)
    except Exception as exc:
        print(f"[Sitemap] Fehler bei {url}: {exc}")
    return urls


def url_to_filename(url: str) -> str:
    """Convert a URL to a safe .md filename (max 100 chars)."""
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.query:
        parts.append(parsed.query)
    name = "__".join(parts) if parts else (parsed.netloc or "index")
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if len(name) > 96:
        name = name[:96]
    return (name or "index") + ".md"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — HTML → MARKDOWN CONVERTER
# ══════════════════════════════════════════════════════════════════════════════

_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "nav", "footer"}
_ADMONITION_CLASSES = {
    "note", "tip", "warning", "caution", "danger",
    "info", "hint", "alert", "callout",
}
_CONTENT_RE = re.compile(
    r"content|main|article|post|entry|body|text|story", re.IGNORECASE
)


def _find_content_root(soup: BeautifulSoup) -> Tag:
    main = soup.find("main")
    if main:
        return main
    article = soup.find("article")
    if article:
        return article
    for tag in soup.find_all(True):
        tag_id = tag.get("id", "") or ""
        tag_cls = " ".join(tag.get("class", []))
        if _CONTENT_RE.search(tag_id) or _CONTENT_RE.search(tag_cls):
            return tag
    return soup.find("body") or soup


def _abs_url(href: str, base: str) -> str:
    if not href:
        return ""
    return urllib.parse.urljoin(base, href)


def _inline(node: Tag | NavigableString) -> str:
    """Render a node as inline Markdown text."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    name = node.name
    if name in ("strong", "b"):
        inner = "".join(_inline(c) for c in node.children)
        return f"**{inner.strip()}**"
    if name in ("em", "i"):
        inner = "".join(_inline(c) for c in node.children)
        return f"*{inner.strip()}*"
    if name in ("del", "s", "strike"):
        inner = "".join(_inline(c) for c in node.children)
        return f"~~{inner.strip()}~~"
    if name == "code":
        return f"`{node.get_text()}`"
    if name == "a":
        href = node.get("href", "") or ""
        text = "".join(_inline(c) for c in node.children).strip()
        return f"[{text}]({href})" if href else text
    return "".join(_inline(c) for c in node.children)


def _convert_list(tag: Tag, depth: int = 0) -> str:
    lines: list[str] = []
    ordered = tag.name == "ol"
    counter = 1
    for item in tag.find_all("li", recursive=False):
        indent = "  " * depth
        prefix = f"{counter}. " if ordered else "- "
        text_parts: list[str] = []
        nested_lists: list[Tag] = []
        for child in item.children:
            if isinstance(child, NavigableString):
                text_parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name in ("ul", "ol"):
                    nested_lists.append(child)
                else:
                    text_parts.append(_inline(child))
        line_text = "".join(text_parts).strip()
        lines.append(f"{indent}{prefix}{line_text}")
        for nl in nested_lists:
            lines.append(_convert_list(nl, depth + 1))
        if ordered:
            counter += 1
    return "\n".join(lines)


def _convert_table(table: Tag) -> str:
    rows = table.find_all("tr")
    if not rows:
        return ""
    out: list[str] = []
    for i, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        out.append("| " + " | ".join(_inline(c) for c in cells) + " |")
        if i == 0:
            out.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(out)


class HtmlToMarkdown:
    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url
        self.images: list[tuple[str, str]] = []  # (url, label)

    def convert(self, html: str) -> tuple[str, list[tuple[str, str]]]:
        """Return (markdown, [(img_url, label), ...])."""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(_SKIP_TAGS):
            tag.decompose()
        root = _find_content_root(soup)
        self.images = []
        md = self._node(root)
        md = re.sub(r"\n{3,}", "\n\n", md).strip()
        return md, self.images

    def _node(self, tag: Tag | NavigableString, depth: int = 0) -> str:
        if isinstance(tag, NavigableString):
            text = str(tag)
            return text if text.strip() else ""
        if not isinstance(tag, Tag):
            return ""

        name = tag.name
        if name in _SKIP_TAGS:
            return ""

        # ── Headings ──────────────────────────────────────────────────────
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return f"\n{'#' * int(name[1])} {_inline(tag)}\n"

        # ── Paragraph ─────────────────────────────────────────────────────
        if name == "p":
            text = _inline(tag)
            return f"\n{text}\n" if text.strip() else ""

        # ── Lists ─────────────────────────────────────────────────────────
        if name in ("ul", "ol"):
            return "\n" + _convert_list(tag) + "\n"

        # ── Table ─────────────────────────────────────────────────────────
        if name == "table":
            return "\n" + _convert_table(tag) + "\n"

        # ── Blockquote ────────────────────────────────────────────────────
        if name == "blockquote":
            inner = self._children(tag)
            lines = [f"> {line}" for line in inner.strip().splitlines()]
            return "\n" + "\n".join(lines) + "\n"

        # ── Code blocks ───────────────────────────────────────────────────
        if name == "pre":
            code_tag = tag.find("code")
            if code_tag:
                lang = next(
                    (c[9:] for c in code_tag.get("class", []) if c.startswith("language-")),
                    "",
                )
                code = code_tag.get_text()
            else:
                lang, code = "", tag.get_text()
            return f"\n```{lang}\n{code}\n```\n"

        # ── Inline code (outside pre) ─────────────────────────────────────
        if name == "code" and (not tag.parent or tag.parent.name != "pre"):
            return f"`{tag.get_text()}`"

        # ── Link ──────────────────────────────────────────────────────────
        if name == "a":
            href = _abs_url(tag.get("href", "") or "", self.base_url)
            text = _inline(tag)
            return f"[{text}]({href})" if href else text

        # ── Image ─────────────────────────────────────────────────────────
        if name == "img":
            src = (
                tag.get("src")
                or tag.get("data-src")
                or tag.get("data-lazy-src")
                or ""
            )
            if not src:
                for entry in (tag.get("srcset") or "").split(","):
                    part = entry.strip().split()[0]
                    if part:
                        src = part
                        break
            src = _abs_url(src, self.base_url)
            if src and not src.lower().endswith(".svg"):
                alt = tag.get("alt", "") or src.split("/")[-1] or "Bild"
                self.images.append((src, alt))
                return f"\n> 📷 **Screenshot: {alt}**\n> _(Bildbeschreibung folgt)_\n"
            return ""

        # ── Figure ────────────────────────────────────────────────────────
        if name == "figure":
            figcap = tag.find("figcaption")
            cap_text = figcap.get_text().strip() if figcap else ""
            if figcap:
                figcap.decompose()
            inner = self._children(tag)
            if cap_text:
                inner = inner.replace("_(Bildbeschreibung folgt)_", f"_{cap_text}_")
            return inner

        # ── Details / Summary ─────────────────────────────────────────────
        if name == "details":
            summary = tag.find("summary")
            summary_text = summary.get_text().strip() if summary else "Details"
            if summary:
                summary.decompose()
            inner = self._children(tag)
            return f"\n**{summary_text}**\n{inner}\n"

        # ── Horizontal rule ───────────────────────────────────────────────
        if name == "hr":
            return "\n---\n"

        # ── Inline formatting ─────────────────────────────────────────────
        if name in ("strong", "b"):
            return f"**{_inline(tag)}**"
        if name in ("em", "i"):
            return f"*{_inline(tag)}*"
        if name in ("del", "s", "strike"):
            return f"~~{_inline(tag)}~~"

        # ── iFrame ────────────────────────────────────────────────────────
        if name == "iframe":
            src = tag.get("src", "") or ""
            title = tag.get("title", "Eingebetteter Inhalt")
            return f"\n[🔗 {title}]({src})\n" if src else ""

        # ── Admonition divs ───────────────────────────────────────────────
        if name in ("div", "section", "aside"):
            cls_str = " ".join(tag.get("class", [])).lower()
            for adm in _ADMONITION_CLASSES:
                if adm in cls_str:
                    inner = self._children(tag)
                    lines = [f"> **{adm.upper()}**"] + [
                        f"> {line}" for line in inner.strip().splitlines()
                    ]
                    return "\n" + "\n".join(lines) + "\n"

        # ── Default: recurse ──────────────────────────────────────────────
        return self._children(tag)

    def _children(self, tag: Tag) -> str:
        return "".join(self._node(c) for c in tag.children)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — AI IMAGE DESCRIBER
# ══════════════════════════════════════════════════════════════════════════════

_AI_PROMPT = (
    "Beschreibe dieses Bild auf Deutsch präzise und vollständig. "
    "Nenne alle UI-Elemente, sichtbaren Texte, Buttons, Werte und Zustände. "
    "Sei so konkret und detailliert wie möglich."
)
_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_IMG_CACHE: dict[str, str] = {}


class AIDescriber:
    def __init__(self, settings: "Settings") -> None:
        self.settings = settings

    def describe(self, img_bytes: bytes, mime: str, url: str) -> str:
        if url in _IMG_CACHE:
            return _IMG_CACHE[url]
        provider = self.settings.get("ai_provider", "openai")
        try:
            if provider == "openai":
                result = self._call_openai(img_bytes, mime)
            else:
                result = self._call_gemini(img_bytes, mime)
        except Exception as exc:
            result = f"[KI-Fehler: {exc}]"
        _IMG_CACHE[url] = result
        time.sleep(0.5)
        return result

    def _call_openai(self, img_bytes: bytes, mime: str) -> str:
        from openai import OpenAI
        api_key = self.settings.get_api_key("openai")
        if not api_key:
            return "[Kein OpenAI API-Key gesetzt]"
        client = OpenAI(api_key=api_key)
        b64 = base64.b64encode(img_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        model = self.settings.get("openai_model", "gpt-4o")
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _AI_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()

    def _call_gemini(self, img_bytes: bytes, mime: str) -> str:
        from google import genai
        from google.genai import types
        api_key = self.settings.get_api_key("gemini")
        if not api_key:
            return "[Kein Gemini API-Key gesetzt]"
        client = genai.Client(api_key=api_key)
        model = self.settings.get("gemini_model", "gemini-2.0-flash")
        img_part = types.Part.from_bytes(data=img_bytes, mime_type=mime)
        resp = client.models.generate_content(
            model=model,
            contents=[_AI_PROMPT, img_part],
        )
        return (getattr(resp, "text", "") or "").strip()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — PLAYWRIGHT SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

_MIN_IMG_DIM = 30


def _scroll_to_bottom(page, max_iter: int = 40) -> None:
    prev_height = 0
    for _ in range(max_iter):
        height = page.evaluate("document.documentElement.scrollHeight")
        if height == prev_height:
            break
        prev_height = height
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(400)


def _collect_page_images(page, ctx) -> list[tuple[str, bytes, str]]:
    """Download images from the page via browser context (preserves auth/cookies)."""
    img_infos = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('img')).map(img => ({
            src: img.src || img.currentSrc || '',
            data_src: img.getAttribute('data-src') || '',
            data_lazy: img.getAttribute('data-lazy-src') || '',
            srcset: img.srcset || img.getAttribute('srcset') || '',
            complete: img.complete,
            w: img.naturalWidth || 0,
            h: img.naturalHeight || 0,
        }))
    }""")
    result: list[tuple[str, bytes, str]] = []
    seen: set[str] = set()

    for info in img_infos:
        src = (
            info.get("src")
            or info.get("data_src")
            or info.get("data_lazy")
            or ""
        )
        if not src:
            for entry in (info.get("srcset") or "").split(","):
                part = entry.strip().split()[0]
                if part:
                    src = part
                    break
        if not src or src.lower().endswith(".svg") or src in seen:
            continue
        w, h = info.get("w", 0) or 0, info.get("h", 0) or 0
        if w < _MIN_IMG_DIM or h < _MIN_IMG_DIM:
            continue
        seen.add(src)
        try:
            r = ctx.request.get(src, timeout=20000)
            if not r.ok:
                continue
            body = r.body()
            ct = r.headers.get("content-type", "").split(";")[0].strip()
            if ct not in _ALLOWED_MIME:
                continue
            result.append((src, body, ct))
        except Exception:
            continue

    return result


def scrape_page(
    url: str,
    headless: bool,
    max_images: int,
    ai_describe: bool,
    settings: "Settings",
    stop_event: threading.Event,
    progress_cb=None,
) -> tuple[str, str]:
    """
    Scrape *url* and return (markdown_text, page_title).
    progress_cb(msg: str, pct: int | None) is called for UI updates.
    """

    def _log(msg: str, pct: int | None = None) -> None:
        if progress_cb:
            progress_cb(msg, pct)

    converter = HtmlToMarkdown(base_url=url)
    describer = AIDescriber(settings) if ai_describe else None
    title = ""

    browser = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            try:
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 WebsiteScraper/1.0"
                    )
                )
                page = ctx.new_page()

                _log("Lade Seite …", 10)
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2_000)

                if stop_event.is_set():
                    return "", ""

                _log("Scrolle bis Ende …", 20)
                _scroll_to_bottom(page)

                if stop_event.is_set():
                    return "", ""

                title = page.title()
                html = page.content()

                _log("Konvertiere HTML → Markdown …", 40)
                md, image_list = converter.convert(html)

                if stop_event.is_set():
                    return "", ""

                if ai_describe and describer and image_list:
                    _log("Lade Bilder für KI …", 50)
                    img_data = _collect_page_images(page, ctx)
                    url_to_data = {u: (b, m) for u, b, m in img_data}

                    for idx, (img_url, label) in enumerate(image_list[:max_images]):
                        if stop_event.is_set():
                            break
                        pct = 50 + int(idx / max(len(image_list), 1) * 45)
                        _log(f"KI beschreibt: {label[:40]} …", pct)
                        if img_url in url_to_data:
                            img_bytes, mime = url_to_data[img_url]
                            desc = describer.describe(img_bytes, mime, img_url)
                            md = md.replace("_(Bildbeschreibung folgt)_", desc, 1)
            finally:
                if browser is not None:
                    browser.close()
                    browser = None
    except Exception:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        raise

    header = (
        f"# {title}\n\n"
        f"**URL:** {url}  \n"
        f"**Erstellt:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        "---\n\n"
    )
    _log("Fertig!", 100)
    return header + md, title


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — WORKER THREADS
# ══════════════════════════════════════════════════════════════════════════════

def _format_eta(remaining_secs: float, avg_secs: float) -> str:
    avg_str = f"Ø {avg_secs:.1f} Sek / Seite"
    if remaining_secs >= 3600:
        h = int(remaining_secs // 3600)
        m = int((remaining_secs % 3600) // 60)
        return f"Noch ca. {h} h {m} min  |  {avg_str}"
    m = int(remaining_secs // 60)
    s = int(remaining_secs % 60)
    return f"Noch ca. {m} min {s} sek  |  {avg_str}"


class SinglePageWorker(QThread):
    progress = pyqtSignal(str, int)
    log      = pyqtSignal(str)
    done     = pyqtSignal(str, str)   # (filepath, title)
    finished_work = pyqtSignal(bool, str)

    def __init__(
        self, url: str, out_dir: str, settings: Settings,
        stop_event: threading.Event,
    ) -> None:
        super().__init__()
        self.url = url
        self.out_dir = out_dir
        self.settings = settings
        self.stop_event = stop_event

    def run(self) -> None:
        try:
            def _cb(msg: str, pct: int | None = None) -> None:
                self.progress.emit(msg, pct or 0)
                self.log.emit(msg)

            md, title = scrape_page(
                self.url,
                self.settings.get("browser_headless", True),
                self.settings.get("max_images_per_page", 30),
                self.settings.get("ai_describe_images", False),
                self.settings,
                self.stop_event,
                _cb,
            )
            if self.stop_event.is_set():
                self.finished_work.emit(False, "Abgebrochen.")
                return

            out = Path(self.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            fpath = out / url_to_filename(self.url)
            fpath.write_text(md, encoding="utf-8")
            self.done.emit(str(fpath), title)
            self.finished_work.emit(True, f"Gespeichert: {fpath}")
        except Exception as exc:
            self.finished_work.emit(False, f"Fehler: {exc}")


class SitemapWorker(QThread):
    progress     = pyqtSignal(str, int)
    eta_update   = pyqtSignal(str)
    log          = pyqtSignal(str)
    done         = pyqtSignal(str, str)
    finished_work = pyqtSignal(bool, str)

    def __init__(
        self, sitemap_url: str, out_dir: str, settings: Settings,
        stop_event: threading.Event,
    ) -> None:
        super().__init__()
        self.sitemap_url = sitemap_url
        self.out_dir = out_dir
        self.settings = settings
        self.stop_event = stop_event

    def run(self) -> None:
        try:
            self.log.emit("Lese Sitemap …")
            self.progress.emit("Lese Sitemap …", 0)
            urls = parse_sitemap(self.sitemap_url)
            if not urls:
                self.finished_work.emit(False, "Keine URLs in Sitemap gefunden.")
                return

            total = len(urls)
            self.log.emit(f"{total} URLs gefunden.")
            out = Path(self.out_dir)
            out.mkdir(parents=True, exist_ok=True)

            headless   = self.settings.get("browser_headless", True)
            ai_imgs    = self.settings.get("ai_describe_images", False)
            max_imgs   = self.settings.get("max_images_per_page", 30)
            page_times: list[float] = []
            index_entries: list[tuple[str, str, str]] = []

            for i, url in enumerate(urls):
                if self.stop_event.is_set():
                    break

                pct = int(i / total * 100)
                self.progress.emit(f"Seite {i + 1} von {total} ({pct} %)", pct)

                if page_times:
                    avg = sum(page_times) / len(page_times)
                    self.eta_update.emit(_format_eta(avg * (total - i), avg))

                t0 = time.time()

                def _cb(msg: str, _p: int | None = None, _i: int = i) -> None:
                    self.log.emit(f"[{_i + 1}/{total}] {msg}")

                try:
                    md, title = scrape_page(
                        url, headless, max_imgs, ai_imgs,
                        self.settings, self.stop_event, _cb,
                    )
                except Exception as exc:
                    self.log.emit(f"Fehler bei {url}: {exc}")
                    page_times.append(time.time() - t0)
                    continue

                if self.stop_event.is_set():
                    break

                fname = url_to_filename(url)
                fpath = out / fname
                try:
                    fpath.write_text(md, encoding="utf-8")
                    index_entries.append((url, title or url, fname))
                    self.done.emit(str(fpath), title or url)
                except Exception as exc:
                    self.log.emit(f"Schreibfehler: {exc}")

                page_times.append(time.time() - t0)

            if index_entries:
                self._write_index(out, index_entries)

            if self.stop_event.is_set():
                self.finished_work.emit(
                    False, f"Abgebrochen nach {len(index_entries)} Seiten."
                )
            else:
                self.finished_work.emit(
                    True,
                    f"{len(index_entries)} Seiten gespeichert in {out}",
                )
        except Exception as exc:
            self.finished_work.emit(False, f"Fehler: {exc}")

    def _write_index(self, out: Path, entries: list[tuple[str, str, str]]) -> None:
        lines = [
            "# Sitemap-Übersicht\n",
            f"**Sitemap:** {self.sitemap_url}  ",
            f"**Erstellt:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
            f"**Seiten:** {len(entries)}\n",
            "---\n",
        ]
        for url, title, fname in entries:
            lines.append(f"- [{title}]({fname}) — {url}")
        (out / "_index.md").write_text("\n".join(lines), encoding="utf-8")


class SimulationWorker(QThread):
    progress     = pyqtSignal(str, int)
    eta_update   = pyqtSignal(str)
    log          = pyqtSignal(str)
    done         = pyqtSignal(str, str)
    finished_work = pyqtSignal(bool, str)

    def __init__(
        self, mode: str, url: str, out_dir: str,
        stop_event: threading.Event,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.url = url
        self.out_dir = out_dir
        self.stop_event = stop_event

    def run(self) -> None:
        if self.mode == "single":
            self._sim_single()
        else:
            self._sim_sitemap()

    def _sim_single(self) -> None:
        self.log.emit("[SIM] Einzelseiten-Simulation gestartet")
        steps = [
            ("Browser starten (simuliert) …", 5),
            ("Seite laden …", 15),
            ("Scrollen …", 30),
            ("HTML verarbeiten …", 50),
            ("Markdown konvertieren …", 75),
            ("Datei schreiben …", 90),
        ]
        for msg, pct in steps:
            if self.stop_event.is_set():
                self.finished_work.emit(False, "Abgebrochen.")
                return
            self.progress.emit(msg, pct)
            self.log.emit(f"[SIM] {msg}")
            time.sleep(random.uniform(0.3, 0.7))

        out = Path(self.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        url = self.url or "https://beispiel.de/seite"
        fname = url_to_filename(url)
        fpath = out / fname
        fpath.write_text(_dummy_md(url, "Simulierte Einzelseite"), encoding="utf-8")
        self.done.emit(str(fpath), "Simulierte Einzelseite")
        self.progress.emit("Fertig!", 100)
        self.finished_work.emit(True, f"Simulation abgeschlossen: {fpath}")

    def _sim_sitemap(self) -> None:
        sim_urls = [f"https://beispiel.de/seite-{i}" for i in range(1, 9)]
        total = len(sim_urls)
        self.log.emit(f"[SIM] Sitemap-Simulation: {total} Seiten")
        out = Path(self.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        page_times: list[float] = []
        index_entries: list[tuple[str, str, str]] = []

        for i, url in enumerate(sim_urls):
            if self.stop_event.is_set():
                break

            pct = int(i / total * 100)
            self.progress.emit(f"Seite {i + 1} von {total} ({pct} %)", pct)

            if page_times:
                avg = sum(page_times) / len(page_times)
                self.eta_update.emit(_format_eta(avg * (total - i), avg))

            t0 = time.time()
            delay = random.uniform(0.8, 2.5)
            sub_steps = ["Starte …", "Lade …", "Scrolle …", "HTML …", "Markdown …", "Speichere …"]
            for step_msg in sub_steps:
                if self.stop_event.is_set():
                    break
                self.log.emit(f"[SIM] [{i + 1}/{total}] {step_msg}")
                time.sleep(delay / len(sub_steps))

            if self.stop_event.is_set():
                break

            fname = url_to_filename(url)
            fpath = out / fname
            title = f"Simulierte Seite {i + 1}"
            fpath.write_text(_dummy_md(url, title), encoding="utf-8")
            index_entries.append((url, title, fname))
            self.done.emit(str(fpath), title)
            page_times.append(time.time() - t0)

        if index_entries:
            lines = ["# Sitemap-Übersicht (Simulation)\n"]
            for url, title, fname in index_entries:
                lines.append(f"- [{title}]({fname}) — {url}")
            (out / "_index.md").write_text("\n".join(lines), encoding="utf-8")

        if self.stop_event.is_set():
            self.finished_work.emit(
                False, f"Abgebrochen nach {len(index_entries)} Seiten."
            )
        else:
            self.progress.emit("Fertig!", 100)
            self.finished_work.emit(
                True,
                f"Simulation: {len(index_entries)} Seiten in {out}",
            )


def _dummy_md(url: str, title: str) -> str:
    return (
        f"# {title}\n\n"
        f"**URL:** {url}  \n"
        f"**Erstellt:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  \n"
        f"**Modus:** Simulation\n\n"
        "---\n\n"
        "## Einleitung\n\n"
        "Dies ist ein simulierter Inhalt für Test- und UI-Entwicklungszwecke.\n\n"
        "## Abschnitt 1\n\n"
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n\n"
        "## Abschnitt 2\n\n"
        "- Punkt 1: Erster Listeneintrag\n"
        "- Punkt 2: Zweiter Listeneintrag\n"
        "- Punkt 3: Dritter Listeneintrag\n\n"
        "## Tabelle\n\n"
        "| Spalte A | Spalte B | Spalte C |\n"
        "| --- | --- | --- |\n"
        "| Wert 1 | Wert 2 | Wert 3 |\n"
        "| Wert 4 | Wert 5 | Wert 6 |\n\n"
        "## Code-Beispiel\n\n"
        "```python\n"
        "def hello():\n"
        "    print('Hello, Website Scraper!')\n"
        "```\n\n"
        "> **NOTE**\n"
        "> Dies ist eine simulierte Admonition-Box.\n\n"
        "> 📷 **Screenshot: Beispielbild**\n"
        "> _(Simulierte KI-Bildbeschreibung: Ein Screenshot der Webseite mit "
        "Navigationselementen und Hauptinhalt.)_\n"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — UI  (PyQt6, Dark Theme)
# ══════════════════════════════════════════════════════════════════════════════

_QSS = """
/* ── Base ───────────────────────────────────────────────────────────────── */
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 13px;
}
QMainWindow { background-color: #181825; }

/* ── Tabs ────────────────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #313244;
    background: #1e1e2e;
    border-radius: 6px;
}
QTabBar::tab {
    background: #313244;
    color: #a6adc8;
    padding: 8px 22px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
}
QTabBar::tab:hover:!selected { background: #45475a; color: #cdd6f4; }

/* ── Buttons ─────────────────────────────────────────────────────────────── */
QPushButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: bold;
    min-height: 32px;
}
QPushButton:hover   { background-color: #b4befe; }
QPushButton:pressed { background-color: #74c7ec; }
QPushButton:disabled { background-color: #45475a; color: #6c7086; }
QPushButton#danger   { background-color: #f38ba8; color: #1e1e2e; }
QPushButton#danger:hover { background-color: #fab387; }
QPushButton#secondary    { background-color: #45475a; color: #cdd6f4; }
QPushButton#secondary:hover { background-color: #585b70; }

/* ── Inputs ──────────────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #89b4fa;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #313244;
    border: 1px solid #45475a;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QSpinBox::up-button, QSpinBox::down-button {
    background: #45475a;
    border: none;
    border-radius: 3px;
    width: 18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #585b70; }

/* ── Progress bar ────────────────────────────────────────────────────────── */
QProgressBar {
    border: 1px solid #45475a;
    border-radius: 6px;
    background: #313244;
    text-align: center;
    color: #cdd6f4;
    font-weight: bold;
    min-height: 22px;
}
QProgressBar::chunk { background: #89b4fa; border-radius: 5px; }

/* ── Checkbox ────────────────────────────────────────────────────────────── */
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 18px; height: 18px;
    border: 2px solid #45475a;
    border-radius: 4px;
    background: #313244;
}
QCheckBox::indicator:checked { background: #89b4fa; border-color: #89b4fa; }

/* ── Group box ───────────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 14px;
    padding: 8px 10px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

/* ── Scrollbar ───────────────────────────────────────────────────────────── */
QScrollBar:vertical { background: #1e1e2e; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ── Custom labels ───────────────────────────────────────────────────────── */
QLabel#status_lbl { color: #a6e3a1; font-size: 12px; }
QLabel#eta_lbl    { color: #f9e2af; font-size: 12px; }
QLabel#app_title  { font-size: 22px; font-weight: bold; color: #89b4fa; }
QLabel#app_sub    { font-size: 12px; color: #6c7086; }

/* ── Separator ───────────────────────────────────────────────────────────── */
QFrame#separator { background: #313244; max-height: 1px; min-height: 1px; }

/* ── Dialog ──────────────────────────────────────────────────────────────── */
QDialog { background: #1e1e2e; }
QDialogButtonBox QPushButton { min-width: 90px; }
"""


# ─────────────────────────────────────────────────────────────────────────────
# Reusable widgets
# ─────────────────────────────────────────────────────────────────────────────

class PathInputRow(QWidget):
    """QLineEdit + optional folder-browse button."""

    def __init__(
        self, placeholder: str = "", browse: bool = False, parent=None
    ) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        lay.addWidget(self.edit)
        if browse:
            btn = QPushButton()
            btn.setObjectName("secondary")
            btn.setFixedSize(QSize(38, 34))
            btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
            btn.setIconSize(QSize(18, 18))
            btn.setToolTip("Verzeichnis wählen")
            btn.clicked.connect(self._browse)
            lay.addWidget(btn)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Ausgabeverzeichnis wählen")
        if path:
            self.edit.setText(path)

    @property
    def text(self) -> str:
        return self.edit.text().strip()

    @text.setter
    def text(self, v: str) -> None:
        self.edit.setText(v)


class ProgressPanel(QWidget):
    """Status label + progress bar + ETA label + log view."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.setContentsMargins(0, 0, 0, 0)

        self._status = QLabel("Bereit.")
        self._status.setObjectName("status_lbl")

        self._bar = QProgressBar()
        self._bar.setValue(0)

        self._eta = QLabel("")
        self._eta.setObjectName("eta_lbl")

        log_lbl = QLabel("📋 Protokoll:")
        log_lbl.setStyleSheet("color:#6c7086;font-size:11px;")

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 10))
        self._log.setMinimumHeight(140)
        self._log.setMaximumHeight(200)
        self._log.setStyleSheet(
            "background:#11111b;border:1px solid #313244;border-radius:6px;color:#a6adc8;"
        )

        lay.addWidget(self._status)
        lay.addWidget(self._bar)
        lay.addWidget(self._eta)
        lay.addWidget(log_lbl)
        lay.addWidget(self._log)

    def update_progress(self, msg: str, pct: int) -> None:
        self._status.setText(msg)
        self._bar.setValue(max(0, min(100, pct)))

    def update_eta(self, text: str) -> None:
        self._eta.setText(text)

    def append_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(f"<span style='color:#6c7086'>[{ts}]</span> {msg}")
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def reset(self) -> None:
        self._status.setText("Bereit.")
        self._bar.setValue(0)
        self._eta.setText("")
        self._log.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Settings dialog
# ─────────────────────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("⚙  Einstellungen")
        self.setMinimumSize(540, 560)
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(14)

        # ── AI ────────────────────────────────────────────────────────────
        ai_grp = QGroupBox("🤖 KI-Einstellungen")
        ai_form = QFormLayout(ai_grp)
        ai_form.setSpacing(10)

        self._provider = QComboBox()
        self._provider.addItems(["openai", "gemini"])
        self._provider.setCurrentText(self.settings.get("ai_provider", "openai"))
        self._provider.currentTextChanged.connect(self._toggle_models)
        ai_form.addRow("Provider:", self._provider)

        self._openai_mdl = QComboBox()
        self._openai_mdl.addItems(["gpt-4o", "gpt-4o-mini"])
        self._openai_mdl.setCurrentText(self.settings.get("openai_model", "gpt-4o"))
        ai_form.addRow("OpenAI-Modell:", self._openai_mdl)

        self._gemini_mdl = QComboBox()
        self._gemini_mdl.addItems([
            "gemini-2.0-flash", "gemini-2.0-flash-lite",
            "gemini-1.5-flash", "gemini-1.5-pro",
        ])
        self._gemini_mdl.setCurrentText(
            self.settings.get("gemini_model", "gemini-2.0-flash")
        )
        ai_form.addRow("Gemini-Modell:", self._gemini_mdl)

        self._oai_key = QLineEdit()
        self._oai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._oai_key.setPlaceholderText("sk-…")
        self._oai_key.setText(self.settings.get_api_key("openai"))
        ai_form.addRow("OpenAI API-Key:", self._oai_key)

        self._gem_key = QLineEdit()
        self._gem_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._gem_key.setPlaceholderText("AIza…")
        self._gem_key.setText(self.settings.get_api_key("gemini"))
        ai_form.addRow("Gemini API-Key:", self._gem_key)

        lay.addWidget(ai_grp)

        # ── Scraper ───────────────────────────────────────────────────────
        sc_grp = QGroupBox("🌐 Scraper-Einstellungen")
        sc_form = QFormLayout(sc_grp)
        sc_form.setSpacing(10)

        self._headless = QCheckBox()
        self._headless.setChecked(self.settings.get("browser_headless", True))
        sc_form.addRow("Browser headless:", self._headless)

        self._ai_imgs = QCheckBox()
        self._ai_imgs.setChecked(self.settings.get("ai_describe_images", False))
        sc_form.addRow("Bilder mit KI beschreiben:", self._ai_imgs)

        self._max_imgs = QSpinBox()
        self._max_imgs.setRange(1, 500)
        self._max_imgs.setValue(self.settings.get("max_images_per_page", 30))
        sc_form.addRow("Max. Bilder / Seite:", self._max_imgs)

        lay.addWidget(sc_grp)

        # ── Buttons ───────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._toggle_models(self._provider.currentText())

    def _toggle_models(self, provider: str) -> None:
        self._openai_mdl.setEnabled(provider == "openai")
        self._gemini_mdl.setEnabled(provider == "gemini")

    def _save(self) -> None:
        s = self.settings
        s.set("ai_provider",        self._provider.currentText())
        s.set("openai_model",       self._openai_mdl.currentText())
        s.set("gemini_model",       self._gemini_mdl.currentText())
        s.set("browser_headless",   self._headless.isChecked())
        s.set("ai_describe_images", self._ai_imgs.isChecked())
        s.set("max_images_per_page", self._max_imgs.value())
        s.set_api_key("openai", self._oai_key.text().strip())
        s.set_api_key("gemini", self._gem_key.text().strip())
        s.save()
        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Tab: Einzelseite
# ─────────────────────────────────────────────────────────────────────────────

class SinglePageTab(QWidget):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._worker: SinglePageWorker | SimulationWorker | None = None
        self._stop = threading.Event()
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(14, 14, 14, 14)

        url_grp = QGroupBox("🔗 Ziel-URL")
        url_lay = QVBoxLayout(url_grp)
        self._url = PathInputRow("https://example.com/seite")
        self._url.text = self.settings.get("single_url", "")
        url_lay.addWidget(self._url)
        lay.addWidget(url_grp)

        out_grp = QGroupBox("📁 Ausgabeverzeichnis")
        out_lay = QVBoxLayout(out_grp)
        self._out = PathInputRow("C:\\Users\\…\\Desktop", browse=True)
        self._out.text = self.settings.get(
            "single_output_path", str(Path.home() / "Desktop")
        )
        out_lay.addWidget(self._out)
        lay.addWidget(out_grp)

        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("▶  Starten")
        self._btn_start.clicked.connect(self._start)
        self._btn_stop = QPushButton("⏹  Abbrechen")
        self._btn_stop.setObjectName("danger")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._cancel)
        self._btn_sim = QPushButton("🔬  Simulation")
        self._btn_sim.setObjectName("secondary")
        self._btn_sim.clicked.connect(self._simulate)
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_stop)
        btn_row.addWidget(self._btn_sim)
        lay.addLayout(btn_row)

        self._prog = ProgressPanel()
        lay.addWidget(self._prog)
        lay.addStretch()

    def _save_state(self) -> None:
        self.settings.set("single_url", self._url.text)
        self.settings.set("single_output_path", self._out.text)
        self.settings.set("last_mode", "single")
        self.settings.save()

    def _lock(self) -> None:
        self._btn_start.setEnabled(False)
        self._btn_sim.setEnabled(False)
        self._btn_stop.setEnabled(True)

    def _unlock(self) -> None:
        self._btn_start.setEnabled(True)
        self._btn_sim.setEnabled(True)
        self._btn_stop.setEnabled(False)

    def _start(self) -> None:
        url, out = self._url.text, self._out.text
        if not url:
            QMessageBox.warning(self, "Fehler", "Bitte eine URL eingeben.")
            return
        if not out:
            QMessageBox.warning(self, "Fehler", "Bitte ein Ausgabeverzeichnis angeben.")
            return
        self._save_state()
        self._stop = threading.Event()
        self._prog.reset()
        self._lock()

        self._worker = SinglePageWorker(url, out, self.settings, self._stop)
        self._worker.progress.connect(self._prog.update_progress)
        self._worker.log.connect(self._prog.append_log)
        self._worker.done.connect(
            lambda fp, _t: self._prog.append_log(f"✅ Gespeichert: {fp}")
        )
        self._worker.finished_work.connect(self._on_finish)
        self._worker.start()

    def _simulate(self) -> None:
        url = self._url.text or "https://beispiel.de/seite"
        out = self._out.text or str(Path.home() / "Desktop")
        self._save_state()
        self._stop = threading.Event()
        self._prog.reset()
        self._lock()

        self._worker = SimulationWorker("single", url, out, self._stop)
        self._worker.progress.connect(self._prog.update_progress)
        self._worker.log.connect(self._prog.append_log)
        self._worker.done.connect(
            lambda fp, _t: self._prog.append_log(f"✅ Gespeichert: {fp}")
        )
        self._worker.finished_work.connect(self._on_finish)
        self._worker.start()

    def _cancel(self) -> None:
        self._stop.set()
        self._prog.append_log("⚠ Abbruch angefordert …")

    def _on_finish(self, ok: bool, msg: str) -> None:
        self._unlock()
        icon = "✅" if ok else "⚠"
        self._prog.update_progress(f"{icon} {msg}", 100 if ok else 0)
        self._prog.append_log(f"{icon} {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Tab: Sitemap
# ─────────────────────────────────────────────────────────────────────────────

class SitemapTab(QWidget):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._worker: SitemapWorker | SimulationWorker | None = None
        self._stop = threading.Event()
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(14, 14, 14, 14)

        url_grp = QGroupBox("🗺  Sitemap-URL")
        url_lay = QVBoxLayout(url_grp)
        self._url = PathInputRow("https://example.com/sitemap.xml")
        self._url.text = self.settings.get("sitemap_url", "")
        url_lay.addWidget(self._url)
        lay.addWidget(url_grp)

        out_grp = QGroupBox("📁 Ausgabeverzeichnis")
        out_lay = QVBoxLayout(out_grp)
        self._out = PathInputRow("C:\\Users\\…\\Desktop", browse=True)
        self._out.text = self.settings.get(
            "sitemap_output_path", str(Path.home() / "Desktop")
        )
        out_lay.addWidget(self._out)
        lay.addWidget(out_grp)

        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("▶  Starten")
        self._btn_start.clicked.connect(self._start)
        self._btn_stop = QPushButton("⏹  Abbrechen")
        self._btn_stop.setObjectName("danger")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._cancel)
        self._btn_sim = QPushButton("🔬  Simulation")
        self._btn_sim.setObjectName("secondary")
        self._btn_sim.clicked.connect(self._simulate)
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_stop)
        btn_row.addWidget(self._btn_sim)
        lay.addLayout(btn_row)

        self._prog = ProgressPanel()
        lay.addWidget(self._prog)
        lay.addStretch()

    def _save_state(self) -> None:
        self.settings.set("sitemap_url", self._url.text)
        self.settings.set("sitemap_output_path", self._out.text)
        self.settings.set("last_mode", "sitemap")
        self.settings.save()

    def _lock(self) -> None:
        self._btn_start.setEnabled(False)
        self._btn_sim.setEnabled(False)
        self._btn_stop.setEnabled(True)

    def _unlock(self) -> None:
        self._btn_start.setEnabled(True)
        self._btn_sim.setEnabled(True)
        self._btn_stop.setEnabled(False)

    def _start(self) -> None:
        url, out = self._url.text, self._out.text
        if not url:
            QMessageBox.warning(self, "Fehler", "Bitte eine Sitemap-URL eingeben.")
            return
        if not out:
            QMessageBox.warning(self, "Fehler", "Bitte ein Ausgabeverzeichnis angeben.")
            return
        self._save_state()
        self._stop = threading.Event()
        self._prog.reset()
        self._lock()

        self._worker = SitemapWorker(url, out, self.settings, self._stop)
        self._worker.progress.connect(self._prog.update_progress)
        self._worker.eta_update.connect(self._prog.update_eta)
        self._worker.log.connect(self._prog.append_log)
        self._worker.done.connect(
            lambda fp, title: self._prog.append_log(f"✅ {title}")
        )
        self._worker.finished_work.connect(self._on_finish)
        self._worker.start()

    def _simulate(self) -> None:
        url = self._url.text or "https://beispiel.de/sitemap.xml"
        out = self._out.text or str(Path.home() / "Desktop")
        self._save_state()
        self._stop = threading.Event()
        self._prog.reset()
        self._lock()

        self._worker = SimulationWorker("sitemap", url, out, self._stop)
        self._worker.progress.connect(self._prog.update_progress)
        self._worker.eta_update.connect(self._prog.update_eta)
        self._worker.log.connect(self._prog.append_log)
        self._worker.done.connect(
            lambda fp, title: self._prog.append_log(f"✅ {title}")
        )
        self._worker.finished_work.connect(self._on_finish)
        self._worker.start()

    def _cancel(self) -> None:
        self._stop.set()
        self._prog.append_log("⚠ Abbruch angefordert …")

    def _on_finish(self, ok: bool, msg: str) -> None:
        self._unlock()
        icon = "✅" if ok else "⚠"
        self._prog.update_progress(f"{icon} {msg}", 100 if ok else 0)
        self._prog.append_log(f"{icon} {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("🌐 Website Scraper")
        self.setMinimumSize(740, 680)
        self.resize(880, 760)
        self._build()
        self._restore_tab()

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setSpacing(0)
        root_lay.setContentsMargins(0, 0, 0, 0)

        # ── Header ────────────────────────────────────────────────────────
        header = QWidget()
        header.setStyleSheet("background:#181825;")
        header.setFixedHeight(68)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 10, 20, 10)

        title = QLabel("🌐  Website Scraper")
        title.setObjectName("app_title")
        sub = QLabel("HTML → Markdown Konverter  •  PyQt6  •  Dark Mode")
        sub.setObjectName("app_sub")

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(title)
        col.addWidget(sub)
        h_lay.addLayout(col)
        h_lay.addStretch()

        cfg_btn = QPushButton("⚙  Einstellungen")
        cfg_btn.setObjectName("secondary")
        cfg_btn.setFixedWidth(150)
        cfg_btn.clicked.connect(self._open_settings)
        h_lay.addWidget(cfg_btn)

        root_lay.addWidget(header)

        sep = QFrame()
        sep.setObjectName("separator")
        root_lay.addWidget(sep)

        # ── Content ───────────────────────────────────────────────────────
        content = QWidget()
        c_lay = QVBoxLayout(content)
        c_lay.setContentsMargins(16, 16, 16, 16)

        self.tabs = QTabWidget()
        self._tab_single = SinglePageTab(self.settings)
        self._tab_sitemap = SitemapTab(self.settings)
        self.tabs.addTab(self._tab_single, "📄  Einzelseite")
        self.tabs.addTab(self._tab_sitemap, "🗺  Sitemap")
        c_lay.addWidget(self.tabs)
        root_lay.addWidget(content)

        # ── Status bar ────────────────────────────────────────────────────
        sb = self.statusBar()
        sb.showMessage("Bereit — Website Scraper v1.0  |  PyQt6")
        sb.setStyleSheet("background:#181825;color:#6c7086;font-size:11px;")

    def _restore_tab(self) -> None:
        if self.settings.get("last_mode") == "sitemap":
            self.tabs.setCurrentIndex(1)
        else:
            self.tabs.setCurrentIndex(0)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.statusBar().showMessage("Einstellungen gespeichert.")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    settings = Settings()

    app: QApplication = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Website Scraper")
    app.setStyleSheet(_QSS)

    # Enable high-DPI icons
    try:
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    except AttributeError:
        pass

    window = MainWindow(settings)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
