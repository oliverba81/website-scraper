#!/usr/bin/env python3
"""
Website Scraper → Markdown
Extrahiert komplette Webseiten als strukturierte Markdown-Dateien.
Bilder werden per Claude (Anthropic) detailliert beschrieben.
Unterstützt Einzel-URLs und XML-Sitemaps (inkl. Sitemap-Index, .gz).
"""

import sys
import os
import re
import json
import gzip
import base64
import email
import html as _html
import random
import threading
import subprocess
import importlib
import time
import tkinter as tk
from email import policy
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

# ─── Konstanten ──────────────────────────────────────────────────────────────

APP_NAME    = "website_scraper"
APP_VERSION = "1.0.19"
SETTINGS_FILE = Path.home() / f".{APP_NAME}_settings.json"

GITHUB_REPO     = "oliverba81/website-scraper"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}"

# Read-only Update-Token – in _token.py neben der .py-Datei ablegen (wird nicht ins Git-Repo committed)
# _token.py Inhalt:  GITHUB_UPDATE_TOKEN = "github_pat_..."
try:
    from _token import GITHUB_UPDATE_TOKEN  # type: ignore
except ImportError:
    GITHUB_UPDATE_TOKEN = ""

# ── Menschliche Zeitschätzung ────────────────────────────────────────────────
HUMAN_MIN_BASE          = 3.0   # Basis: Navigation + Datei anlegen + Überblick
HUMAN_MIN_PER_100_WORDS = 1.0   # Copy-Paste + Markdown-Formatierung (keine KI-Texte)
HUMAN_MIN_PER_IMAGE     = 2.5   # Snipping-Tool + Datei einfügen + kurze Beschreibung
HUMAN_MIN_MIN_PER_PAGE  = 2.0   # Minimum pro Seite
MAX_RUNS_HISTORY        = 1000  # Maximale Anzahl gespeicherter Läufe

# ── Ausgabeformate ────────────────────────────────────────────────────────────
DEFAULT_XML_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<page>\n'
    '  <title>{{title}}</title>\n'
    '  <url>{{url}}</url>\n'
    '  <content><![CDATA[{{content}}]]></content>\n'
    '</page>'
)
DEFAULT_CSV_FIELDS = ["title", "url", "content"]
ALL_FORMAT_FIELDS  = [
    "title", "url", "content", "text",
    "meta_description", "date", "images_count",
]

# Version der Builtin-Format-Defaults; erhöht eine einmalige Migration in
# get_formats() (z. B. CSV-Trennzeichen Komma → Semikolon für dt. Excel).
FORMATS_REV = 1

# C0-Steuerzeichen (außer \t \n \r) entfernen: brechen sonst Excel-Zellen bzw.
# machen XML nicht wohlgeformt (xml.sax.saxutils.escape entfernt sie NICHT).
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _strip_ctrl(s: str) -> str:
    return _CTRL_RE.sub("", str(s))

REQUIRED_PACKAGES = {
    "playwright": "playwright",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "anthropic": "anthropic",
    "keyring": "keyring",
    "keyrings.alt": "keyrings.alt",
    "customtkinter": "customtkinter",
}

SUPPORTED_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


# ─── Abhängigkeiten ──────────────────────────────────────────────────────────

def _check_missing():
    missing = []
    for mod_name, pkg_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append(pkg_name)
    return missing


def _playwright_browsers_ok():
    try:
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
        return bool(list(cache.glob("chromium-*")))
    except Exception:
        return False


def _refresh_sys_path():
    """Fügt user site-packages zu sys.path hinzu (nach pip install nötig)."""
    import site
    importlib.invalidate_caches()
    try:
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.insert(0, user_site)
    except Exception:
        pass
    try:
        import sysconfig
        purelib = sysconfig.get_paths().get("purelib", "")
        if purelib and purelib not in sys.path:
            sys.path.insert(0, purelib)
    except Exception:
        pass


def ensure_dependencies():
    """Prüft und installiert fehlende Pakete beim ersten Start."""
    settings = load_settings()

    if settings.get("setup_done") and settings.get("setup_version") == APP_VERSION:
        _refresh_sys_path()
        still_missing = _check_missing()
        if not still_missing:
            return
        settings.pop("setup_done", None)
        save_settings(settings)

    missing = _check_missing()
    browsers_needed = not _playwright_browsers_ok()

    if not missing and not browsers_needed:
        _mark_setup_done()
        return

    root = tk.Tk()
    root.title("Erstmaliges Setup – Website Scraper")
    root.geometry("500x240")
    root.resizable(False, False)
    root.lift()
    root.focus_force()

    frm = ttk.Frame(root, padding=20)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Installiere benötigte Pakete…",
              font=("Segoe UI", 11)).pack(anchor="w")

    prog = ttk.Progressbar(frm, length=460, mode="indeterminate")
    prog.pack(pady=10)
    prog.start(15)

    status_var = tk.StringVar(value="Vorbereitung…")
    ttk.Label(frm, textvariable=status_var, foreground="#555",
              wraplength=460).pack(anchor="w")

    note = ttk.Label(frm,
                     text="(Chromium-Download ca. 150 MB – nur einmalig)",
                     foreground="#888", font=("Segoe UI", 8))
    note.pack(anchor="w", pady=(4, 0))

    def _set(msg):
        root.after(0, lambda: status_var.set(msg))

    def _install():
        try:
            if missing:
                _set(f"pip install {' '.join(missing[:4])}{'…' if len(missing) > 4 else ''}")
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--quiet"] + missing,
                    timeout=300,
                )
            _refresh_sys_path()

            if browsers_needed:
                _set("Installiere Chromium Browser (einmalig ~150 MB)…")
                subprocess.check_call(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    timeout=600,
                )
            _mark_setup_done()
            root.after(0, root.destroy)
        except subprocess.CalledProcessError as exc:
            def _err():
                prog.stop()
                status_var.set(f"FEHLER: {exc}")
                messagebox.showerror(
                    "Setup-Fehler",
                    f"Installation fehlgeschlagen:\n{exc}\n\n"
                    "Manuell ausführen:\n"
                    "  pip install -r requirements.txt\n"
                    "  python -m playwright install chromium",
                    parent=root,
                )
            root.after(0, _err)

    threading.Thread(target=_install, daemon=True).start()
    root.mainloop()


def _mark_setup_done():
    s = load_settings()
    s["setup_done"] = True
    s["setup_version"] = APP_VERSION
    save_settings(s)


# ─── Einstellungen ────────────────────────────────────────────────────────────

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(data: dict):
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─── Sitemap-Queue (wiederaufnehmbare Abarbeitung) ────────────────────────────

QUEUE_FILENAME     = "_queue.json"
# Eigene Datei für den EML-Ordner-Modus: anderer Lebenszyklus als die Sitemap-
# Queue (wird NICHT bei Abschluss gelöscht, sondern dient dauerhaft dem
# inkrementellen „welche Dateien sind erledigt“). Getrennte Namen verhindern,
# dass ein abgeschlossener Lauf des einen Modus die Liste des anderen stört.
EML_QUEUE_FILENAME = "_eml_queue.json"
QUEUE_SCHEMA       = 1


def _queue_path(output_dir, filename: str = QUEUE_FILENAME) -> Path:
    return Path(output_dir) / filename


def _load_queue(output_dir, log_fn=None, filename: str = QUEUE_FILENAME) -> dict:
    """Lädt die Queue-/Ledger-Datei. Gibt None zurück bei Fehler/falschem Schema.

    all_urls wird order-preserving dedupliziert, done auf all_urls geschnitten –
    so sind die Werte für Resume-Dialog und Worker identisch und robust gegen
    geschrumpfte oder manuell editierte Listen. (Im EML-Modus tragen all_urls/done
    Dateinamen statt URLs – die Logik ist identisch.)
    """
    try:
        path = _queue_path(output_dir, filename)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != QUEUE_SCHEMA:
            return None
        all_urls = data.get("all_urls")
        done     = data.get("done")
        if not isinstance(all_urls, list) or not all_urls or not isinstance(done, list):
            return None
        data["all_urls"] = list(dict.fromkeys(all_urls))
        data["done"]     = [u for u in data["all_urls"] if u in set(done)]
        return data
    except Exception as exc:
        if log_fn:
            log_fn(f"Liste konnte nicht gelesen werden ({exc}) – starte neu.")
        return None


def _write_queue_atomic(output_dir, data: dict, log_fn=None,
                        filename: str = QUEUE_FILENAME):
    """Schreibt die Queue-/Ledger-Datei atomar (temp + os.replace). Nicht-fatal:

    Ein OneDrive-Lock / PermissionError / Disk-voll bricht den Lauf NICHT ab –
    die Seite ist bereits erfolgreich geschrieben; im schlimmsten Fall wird sie
    bei einer Wiederaufnahme erneut verarbeitet.
    """
    target = _queue_path(output_dir, filename)
    tmp    = target.with_suffix(target.suffix + ".tmp")   # *.json.tmp, selbes Verzeichnis
    for attempt in range(3):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, target)                       # os.replace im try (OneDrive lockt v.a. das Ziel)
            return
        except OSError:
            time.sleep(0.1 * (attempt + 1))               # Worker-Thread, blockiert die GUI nicht
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    if log_fn:
        log_fn("Listen-Stand konnte nicht gespeichert werden – "
               "bei Wiederaufnahme werden ggf. einige Dateien erneut verarbeitet.")


def _delete_queue(output_dir, filename: str = QUEUE_FILENAME):
    """Entfernt die Queue-/Ledger-Datei und eine evtl. übrig gebliebene *.tmp."""
    target = _queue_path(output_dir, filename)
    for p in (target, target.with_suffix(target.suffix + ".tmp")):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def _default_formats() -> list:
    """Gibt die 3 vorinstallierten Ausgabeformate zurück."""
    return [
        {"id": "builtin_md",  "name": "Jira-Markdown", "type": "markdown",
         "extension": ".md",  "template": "", "fields": [], "params": {},
         "builtin": True},
        {"id": "builtin_xml", "name": "XML",  "type": "xml",
         "extension": ".xml", "template": DEFAULT_XML_TEMPLATE,
         "fields": ["title", "url", "content"],
         "params": {"root_element": "page"},
         "builtin": False},
        {"id": "builtin_csv", "name": "CSV",  "type": "csv",
         "extension": ".csv", "template": "",
         "fields": list(DEFAULT_CSV_FIELDS),
         "params": {"delimiter": ";", "quotechar": '"', "include_header": True},
         "builtin": False},
    ]


def get_formats() -> list:
    """Lädt die konfigurierten Formate (mit Defaults wenn leer)."""
    s = load_settings()
    fmts = s.get("formats", [])
    if not fmts:
        fmts = _default_formats()
        s["formats"] = fmts
        s["formats_rev"] = FORMATS_REV
        save_settings(s)
        return fmts
    # Einmalige Migration (via Versionsflag, NICHT bei jeder Extraktion): das
    # alte Komma-Trennzeichen des Builtin-CSV-Formats ging in dt. Excel nicht als
    # Tabelle auf. Läuft genau einmal → spätere bewusste Editor-Wahl bleibt.
    if s.get("formats_rev", 0) < FORMATS_REV:
        for f in fmts:
            if f.get("id") == "builtin_csv" and f.get("params", {}).get("delimiter") == ",":
                f["params"]["delimiter"] = ";"
        s["formats"] = fmts
        s["formats_rev"] = FORMATS_REV
        save_settings(s)
    return fmts


def get_active_format() -> dict:
    """Gibt das aktuell aktive Ausgabeformat zurück."""
    s    = load_settings()
    fmts = get_formats()
    aid  = s.get("active_format", "builtin_md")
    for f in fmts:
        if f["id"] == aid:
            return f
    return fmts[0]


def _apply_template(template: str, data: dict) -> str:
    """Ersetzt {{key}}-Platzhalter im Template durch data[key]."""
    result = template
    for k, v in data.items():
        result = result.replace("{{" + k + "}}", str(v))
    return result


def _version_tuple(v: str) -> tuple:
    """Konvertiert '1.2.3' → (1, 2, 3) für korrekten Versionsvergleich."""
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _check_for_update(token: str = ""):
    """
    Prüft GitHub Releases auf eine neuere Version.
    Gibt (version_str, asset_url) zurück oder None.
    Token ist optional – bei öffentlichen Repos nicht nötig.
    """
    import urllib.request as _ureq
    headers = {
        "Accept":     "application/vnd.github.v3+json",
        "User-Agent": f"website-scraper/{APP_VERSION}",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    req = _ureq.Request(f"{GITHUB_API_BASE}/releases/latest", headers=headers)
    with _ureq.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    latest_tag = data.get("tag_name", "")
    latest_ver = latest_tag.lstrip("v")
    if _version_tuple(latest_ver) > _version_tuple(APP_VERSION):
        # browser_download_url ist bei public repos ohne Token zugänglich
        # (a["url"] = API-Endpunkt, der auch bei public repos 401 liefert)
        asset_url = next(
            (a["browser_download_url"] for a in data.get("assets", [])
             if a["name"] == "website_scraper.py"),
            None,
        )
        if asset_url is None:
            return None  # Release ohne Asset → kein automatisches Update möglich
        return latest_ver, asset_url
    return None


def _download_update(token: str, asset_url: str) -> bytes:
    """
    Lädt das Update-Asset von GitHub herunter.
    requests (in requirements.txt) entfernt den Authorization-Header beim
    Redirect zu S3 automatisch (cross-domain redirect stripping).
    """
    import requests as _req
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/octet-stream",
        "User-Agent":    f"website-scraper/{APP_VERSION}",
    }
    resp = _req.get(asset_url, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.content


# ─── API-Key-Verwaltung (keyring + Fallback) ──────────────────────────────────

_USE_KEYRING = None  # None = uninitialized, True/False = keyring available/not


def _init_keyring():
    global _USE_KEYRING
    if _USE_KEYRING is not None:
        return
    try:
        import keyring as kr
        kr.get_keyring()
        _USE_KEYRING = True
    except Exception:
        _USE_KEYRING = False


def get_api_key(provider: str) -> str:
    _init_keyring()
    if _USE_KEYRING:
        try:
            import keyring as kr
            val = kr.get_password(APP_NAME, provider)
            return val or ""
        except Exception:
            pass
    return load_settings().get(f"key_{provider}", "")


def set_api_key(provider: str, value: str):
    _init_keyring()
    if _USE_KEYRING:
        try:
            import keyring as kr
            kr.set_password(APP_NAME, provider, value)
            return
        except Exception:
            pass
    s = load_settings()
    s[f"key_{provider}"] = value
    save_settings(s)


# ─── Sitemap-Parser ───────────────────────────────────────────────────────────

def _fetch_sitemap_urls(sitemap_url: str, log_fn=None) -> list:
    """Lädt und parst eine XML-Sitemap (inkl. Sitemap-Index, .gz)."""
    import urllib.request as ureq

    if log_fn:
        log_fn(f"  Lade Sitemap: {sitemap_url}")

    try:
        req = ureq.Request(
            sitemap_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; WebScraper/1.0)"},
        )
        with ureq.urlopen(req, timeout=30) as resp:
            content = resp.read()

        # Gzip-Dekompression
        if sitemap_url.lower().endswith(".gz") or content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)

        root = ET.fromstring(content)

        # Namespace ermitteln
        ns_match = re.match(r"\{(.*?)\}", root.tag)
        ns = ns_match.group(1) if ns_match else ""

        def _tag(name):
            return f"{{{ns}}}{name}" if ns else name

        # Sitemap-Index? → Sub-Sitemaps rekursiv laden
        sub_sitemaps = root.findall(_tag("sitemap"))
        if sub_sitemaps:
            urls = []
            for sm in sub_sitemaps:
                loc = sm.find(_tag("loc"))
                if loc is not None and loc.text:
                    child_urls = _fetch_sitemap_urls(loc.text.strip(), log_fn)
                    urls.extend(child_urls)
                    if log_fn:
                        log_fn(f"  Sub-Sitemap: {len(child_urls)} URLs")
            return urls

        # Normale Sitemap
        urls = []
        for url_el in root.findall(_tag("url")):
            loc = url_el.find(_tag("loc"))
            if loc is not None and loc.text:
                urls.append(loc.text.strip())

        return urls

    except Exception as exc:
        if log_fn:
            log_fn(f"  Sitemap-Fehler: {exc}")
        return []


def _url_to_filename(url: str, ext: str = ".md") -> str:
    """Erstellt einen eindeutigen, sicheren Dateinamen aus einer URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        name = re.sub(r"[^\w\-]", "_", parsed.netloc)
    else:
        name = re.sub(r"[^\w\-]", "_", path.replace("/", "__"))
    name = re.sub(r"_+", "_", name).strip("_")[:100] or "index"
    return name + ext


def _eml_to_filename(path, ext: str = ".md") -> str:
    """Erstellt einen sicheren Ausgabe-Dateinamen aus einem .eml-Pfad.

    Auf oberster Verzeichnisebene sind .eml-Basisnamen eindeutig, daher genügt
    der (gesäuberte) Dateistamm.
    """
    name = re.sub(r"[^\w\-]", "_", Path(path).stem)
    name = re.sub(r"_+", "_", name).strip("_")[:100] or "eml"
    return name + ext


# ─── .eml-Parser ──────────────────────────────────────────────────────────────

def _parse_eml(path, max_images: int = None):
    """Parst eine .eml-Datei und liefert (html, img_data, subject, date, from_).

    - Wählt den HTML-Body (Fallback: text/plain in <pre> verpackt).
    - Sammelt inline-Bilder (Content-ID) als img_data{ "cid:<id>" / "<id>": (b64, mime) },
      genau so wie das HTML sie via src="cid:…" referenziert → der bestehende
      _img_block-Lookup (Stufe 1) trifft direkt.
    - Respektiert max_images (begrenzt die Anzahl beschriebener Bilder).
    """
    with open(path, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=policy.default)

    subject = (msg["subject"] or Path(path).stem).strip()
    date    = (msg["date"] or "").strip()
    from_   = (msg["from"] or "").strip()

    body = msg.get_body(preferencelist=("html", "plain"))
    if body is not None and body.get_content_type() == "text/html":
        html = body.get_content()
    elif body is not None:
        text = body.get_content()
        html = ("<html><head></head><body><pre>"
                + _html.escape(text) + "</pre></body></html>")
    else:
        html = "<html><head></head><body></body></html>"

    img_data: dict = {}
    count = 0
    for part in msg.walk():
        if part.get_content_type() not in SUPPORTED_MIMES:
            continue
        if max_images is not None and count >= max_images:
            break
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None
        if not payload:
            continue
        cid  = (part["Content-ID"] or "").strip().strip("<>")
        b64  = base64.b64encode(payload).decode()
        mime = part.get_content_type()
        if cid:
            img_data[f"cid:{cid}"] = (b64, mime)
            img_data[cid]          = (b64, mime)
            count += 1
    return html, img_data, subject, date, from_


# ─── Simulationsmodus ────────────────────────────────────────────────────────

def _sim_html(url: str) -> str:
    """Erzeugt eine realistische Dummy-HTML-Seite für den Simulationsmodus."""
    parsed = urlparse(url)
    title = parsed.path.strip("/").replace("/", " › ") or parsed.netloc
    title = title.capitalize() or "Startseite"
    return f"""<!DOCTYPE html>
<html lang="de">
<head><title>[SIM] {title}</title></head>
<body>
<main>
  <h1>{title}</h1>
  <p>Dies ist eine <strong>simulierte Seite</strong> für Testzwecke.
     Kein Browser wurde geöffnet, kein API-Key wurde verwendet.</p>
  <p>Quell-URL: <a href="{url}">{url}</a></p>

  <h2>Abschnitt 1 – Textinhalt</h2>
  <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.
     Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.</p>
  <blockquote>
    <p>💡 Hinweis: Dieser Inhalt wurde im Simulationsmodus generiert und
       entspricht nicht dem echten Seiteninhalt.</p>
  </blockquote>

  <h2>Abschnitt 2 – Liste</h2>
  <ul>
    <li>Simulierter Listenpunkt 1</li>
    <li>Simulierter Listenpunkt 2
      <ul>
        <li>Verschachtelter Punkt A</li>
        <li>Verschachtelter Punkt B</li>
      </ul>
    </li>
    <li>Simulierter Listenpunkt 3</li>
  </ul>

  <h2>Abschnitt 3 – Tabelle</h2>
  <table>
    <tr><th>Eigenschaft</th><th>Wert</th><th>Beschreibung</th></tr>
    <tr><td>URL</td><td><code>{url}</code></td><td>Gescrapte Seite</td></tr>
    <tr><td>Modus</td><td>Simulation</td><td>Kein echtes Scraping</td></tr>
    <tr><td>Bilder</td><td>0</td><td>Keine AI-Calls im Simulationsmodus</td></tr>
  </table>

  <h2>Abschnitt 4 – Code</h2>
  <pre><code class="language-python"># Beispiel-Code (simuliert)
def scrape(url):
    return "Markdown-Inhalt"
</code></pre>

  <h3>Details-Block</h3>
  <details>
    <summary>Mehr Informationen</summary>
    <p>Dieser aufklappbare Bereich enthält zusätzliche Informationen,
       die im Simulationsmodus als Beispiel für das Details-Element dienen.</p>
  </details>
</main>
</body>
</html>"""


# ─── Zeitersparnis-Hilfsfunktionen ───────────────────────────────────────────

def _estimate_human_time(md_paths: list):
    """Schätzt Menschenzeit anhand Wort- und Bildanzahl der Markdown-Ausgaben.
    Gibt (gesamt_min, wörter, bilder) zurück."""
    total_min, total_words, total_images = 0.0, 0, 0
    for path in md_paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception:
            text = ""
        # Nur Seiteninhalt zählen – KI-Bildbeschreibungen (Blockquotes) ausschließen
        content = " ".join(l for l in text.splitlines() if not l.startswith(">"))
        words = len(content.split())
        images = text.count("> 📷")
        page_min = max(
            HUMAN_MIN_MIN_PER_PAGE,
            HUMAN_MIN_BASE
            + (words / 100) * HUMAN_MIN_PER_100_WORDS
            + images * HUMAN_MIN_PER_IMAGE,
        )
        total_min += page_min
        total_words += words
        total_images += images
    return total_min, total_words, total_images


def _fmt_min(minutes: float) -> str:
    """Formatiert Minuten als '2 Std 05 Min' / '14 Min 32 Sek' / '45 Sek'."""
    total_secs = int(minutes * 60)
    h, rem = divmod(total_secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} Std {m:02d} Min"
    if m:
        return f"{m} Min {s:02d} Sek"
    return f"{s} Sek"


def _save_run(url: str, mode: str, pages: int,
              tool_min: float, human_min: float):
    """Fügt einen Lauf zur persistenten Historie in settings.json hinzu."""
    saved_min = max(0.0, human_min - tool_min)
    pct = int(saved_min / max(human_min, 0.01) * 100)
    entry = {
        "date": time.strftime("%d.%m.%Y %H:%M"),
        "mode": mode, "url": url, "pages": pages,
        "tool_min": round(tool_min, 2),
        "human_min": round(human_min, 2),
        "saved_min": round(saved_min, 2),
        "pct": pct,
    }
    s = load_settings()
    runs = s.get("runs", [])
    runs.append(entry)
    s["runs"] = runs[-MAX_RUNS_HISTORY:]
    save_settings(s)


# ─── Scraper-Kern ─────────────────────────────────────────────────────────────

class Scraper:
    def __init__(self, settings: dict,
                 log_fn=None, progress_fn=None, stop_event=None):
        self.settings = settings
        self._log = log_fn or print
        self._progress = progress_fn or (lambda v: None)
        self._stop = stop_event or threading.Event()
        self.base_url = ""
        self._img_cache: dict = {}
        self._img_data: dict = {}
        self._img_pos_map: dict = {}
        self._img_counter = [0]
        self._img_total = [0]
        # Zusätzliche Format-Variablen, die _extract_page_vars überschreiben
        # (für .eml: date/from). Beim Web-Pfad leer → keine Auswirkung.
        self._meta: dict = {}

    def run(self, url: str, output_path: str, output_format: dict = None):
        self.base_url = url
        self._log(f"Öffne Seite: {url}")
        self._progress(5)

        html, img_data = self._browse(url)
        if self._stop.is_set():
            return

        self._progress(42)
        self._convert_and_write(html, img_data, output_path, output_format)

    def run_eml(self, eml_path: str, output_path: str, output_format: dict = None):
        """Wandelt eine einzelne .eml-Datei um (ohne Browser).

        Erzeugt aus der Mail dasselbe (html, img_data)-Paar wie der Browser-Pfad
        und nutzt danach dieselbe Konvertierung/Render-Logik.
        """
        self.base_url = eml_path
        self._log(f"Lese E-Mail: {Path(eml_path).name}")
        self._progress(10)

        # describe_images respektieren (wie der Browser-Pfad): ist die
        # Beschreibung aus, werden keine Bilder eingesammelt (max_images=0 →
        # img_data leer) und _img_block zeigt den Alt-/Quelle-Fallback.
        describe = self.settings.get("describe_images", True)
        max_imgs = int(self.settings.get("max_images", 30)) if describe else 0
        html, img_data, subject, date, from_ = _parse_eml(eml_path, max_imgs)

        # Betreff als einzige Titelquelle: <title> einsetzen, falls keiner da ist.
        # _to_markdown nutzt ihn für die # H1, _extract_page_vars für das title-Feld.
        if subject:
            from bs4 import BeautifulSoup
            if BeautifulSoup(html, "lxml").find("title") is None:
                title_tag = f"<title>{_html.escape(subject)}</title>"
                if re.search(r"(?i)<head[^>]*>", html):
                    html = re.sub(r"(?i)(<head[^>]*>)", r"\1" + title_tag, html, count=1)
                else:
                    html = title_tag + html

        # Layout-Icons (z. B. 24×24) nicht an die AI schicken: <img> mit gesetzten
        # width/height < 30 vor der Konvertierung entfernen. (Greift nur bei
        # vorhandenen Attributen – attributlose Kleinbilder bleiben erhalten.)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        removed = False
        for img in soup.find_all("img"):
            try:
                w = int(img.get("width", "0") or 0)
                h = int(img.get("height", "0") or 0)
            except ValueError:
                continue
            if 0 < w < 30 and 0 < h < 30:
                img.decompose()
                removed = True
        if removed:
            html = str(soup)

        # url kommt aus base_url; title aus <title>. Nur date/from ergänzen.
        self._meta = {"date": date, "meta_description": from_}

        self._progress(42)
        self._convert_and_write(html, img_data, output_path, output_format)

    def _convert_and_write(self, html: str, img_data: dict,
                           output_path: str, output_format: dict = None):
        """Geteilter Render-/Schreib-Tail von run() und run_eml()."""
        fmt      = output_format or {"type": "markdown", "extension": ".md"}
        fmt_type = fmt.get("type", "markdown")
        _label   = {"xml": "XML", "csv": "CSV"}.get(fmt_type, "Markdown")
        self._log(f"Konvertiere Inhalt zu {_label}…")

        md = self._to_markdown(html, img_data)
        if self._stop.is_set():
            return

        self._progress(95)
        if fmt_type == "xml":
            content = self._render_xml(md, html, fmt)
        elif fmt_type == "csv":
            content = self._render_csv(md, html, fmt)
        else:
            template = fmt.get("template", "")
            if template:
                vars_ = self._extract_page_vars(md, html)
                content = _apply_template(template, vars_)
            else:
                content = md
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if fmt_type == "csv":
            # utf-8-sig (BOM, genau 1×) → Excel erkennt UTF-8; newline="" → die
            # \r\n von csv.writer werden nicht erneut übersetzt (sonst \r\r\n,
            # was Excels Quote-Parsing bricht).
            with open(out, "w", encoding="utf-8-sig", newline="") as f:
                f.write(content)
        else:
            out.write_text(content, encoding="utf-8")
        self._log(f"Gespeichert: {output_path}")
        self._progress(100)

    # ── Seiten-Variablen / Format-Konverter ───────────────────────────────────

    def _extract_page_vars(self, md: str, html: str) -> dict:
        """Extrahiert Seitendaten als Dict für Template-Platzhalter."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text().strip() if soup.title else ""
        if not title:
            h1 = soup.find("h1")
            title = h1.get_text().strip() if h1 else ""
        meta_tag  = soup.find("meta", attrs={"name": "description"})
        meta_desc = meta_tag.get("content", "").strip() if meta_tag else ""
        body       = soup.body or soup
        plain_text = body.get_text(separator=" ", strip=True)
        result = {
            "title":            title,
            "url":              self.base_url,
            "content":          md,
            "text":             plain_text,
            "meta_description": meta_desc,
            "date":             time.strftime("%d.%m.%Y"),
            "images_count":     str(len(self._img_data)),
        }
        # .eml-Metadaten (date/from) überschreiben die Defaults; Web-Pfad: _meta leer.
        result.update({k: v for k, v in self._meta.items() if v})
        return result

    def _render_xml(self, md: str, html: str, fmt: dict) -> str:
        """Rendert die Seite als wohlgeformtes XML gemäß Format-Template.

        Steuerzeichen werden gefiltert, Feldwerte XML-escaped. Steht
        {{content}} in einem CDATA-Block, wird der Content NICHT escaped,
        sondern nur ]]> CDATA-sicher gemacht.
        """
        from xml.sax.saxutils import escape
        data     = self._extract_page_vars(md, html)
        template = fmt.get("template", "") or DEFAULT_XML_TEMPLATE
        content_in_cdata = bool(
            re.search(r"<!\[CDATA\[(?:(?!\]\]>).)*\{\{content\}\}", template, re.S)
        )
        out = {}
        for k, v in data.items():
            s = _strip_ctrl(v)
            if k == "content" and content_in_cdata:
                out[k] = s.replace("]]>", "]]]]><![CDATA[>")
            else:
                out[k] = escape(s, {'"': "&quot;", "'": "&apos;"})
        # Einmalige Ersetzung → keine Platzhalter-Injection durch Feldinhalte.
        return re.sub(r"\{\{(\w+)\}\}",
                      lambda m: out.get(m.group(1), m.group(0)), template)

    def _render_csv(self, md: str, html: str, fmt: dict) -> str:
        """Rendert die Seite als CSV-Zeile gemäß Format-Konfiguration."""
        import csv as _csv
        import io

        def _csv_safe(v) -> str:
            v = _strip_ctrl(v)
            # CSV-Formula-Injection: Excel wertet =,+,-,@ am Zellanfang als Formel
            # aus (QUOTE_ALL schützt davor NICHT). Führendes ' macht die Zelle Text.
            if v[:1] in ("=", "+", "-", "@", "\t", "\r"):
                v = "'" + v
            return v

        data   = self._extract_page_vars(md, html)
        params = fmt.get("params", {})
        fields = fmt.get("fields", DEFAULT_CSV_FIELDS) or DEFAULT_CSV_FIELDS
        buf    = io.StringIO()
        writer = _csv.writer(
            buf,
            delimiter=params.get("delimiter") or ";",
            quotechar=params.get("quotechar", '"'),
            quoting=_csv.QUOTE_ALL,
        )
        if params.get("include_header", True):
            writer.writerow(fields)
        writer.writerow([_csv_safe(data.get(f, "")) for f in fields])
        return buf.getvalue()

    # ── Browser ──────────────────────────────────────────────────────────────

    def _browse(self, url: str):
        # ── Simulationsmodus ──────────────────────────────────────────────────
        if self.settings.get("simulate"):
            delay = random.uniform(0.8, 2.5)
            self._log(f"  [SIM] Simuliere Seitenlade ({delay:.1f} s)…")
            # Fortschritt schrittweise von 5 % → 38 % während der simulierten Ladezeit
            steps = 12
            for i in range(steps):
                if self._stop.is_set():
                    return "", {}
                time.sleep(delay / steps)
                self._progress(5 + int(33 * (i + 1) / steps))
            self._log("  [SIM] Erzeuge Dummy-Inhalt…")
            return _sim_html(url), {}
        # ─────────────────────────────────────────────────────────────────────

        from playwright.sync_api import sync_playwright

        headless = self.settings.get("headless", True)
        max_imgs = int(self.settings.get("max_images", 30))
        describe = self.settings.get("describe_images", True)

        img_data: dict = {}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            try:
                ctx = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = ctx.new_page()

                self._log("Lade Seite…")
                self._progress(10)
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                page.wait_for_timeout(2000)
                self._progress(20)

                self._log("Scrolle Seite (lade Lazy-Content)…")
                self._full_scroll(page)
                self._progress(32)

                if describe and not self._stop.is_set():
                    # Warten bis alle Bilder geladen sind (max. 5 Sek.)
                    try:
                        page.wait_for_function(
                            "() => Array.from(document.images).every(img => img.complete)",
                            timeout=5000,
                        )
                    except Exception:
                        pass  # Nicht alle geladen – trotzdem fortfahren

                    # Index-Attribut injizieren + Bild-Infos auslesen (VOR page.content(),
                    # damit data-scraper-idx im HTML-Snapshot enthalten ist).
                    # Für noch nicht geladene Bilder: offsetWidth/offsetHeight als Fallback.
                    img_infos = page.evaluate("""() => {
                        const imgs = Array.from(document.querySelectorAll('img'));
                        imgs.forEach((img, idx) => img.setAttribute('data-scraper-idx', String(idx)));
                        return imgs.map((img, idx) => {
                            const w = img.complete ? img.naturalWidth
                                      : Math.max(img.offsetWidth,
                                                 parseInt(img.getAttribute('width') || '0'));
                            const h = img.complete ? img.naturalHeight
                                      : Math.max(img.offsetHeight,
                                                 parseInt(img.getAttribute('height') || '0'));
                            const src = (img.complete ? img.currentSrc : '') || img.src ||
                                        img.getAttribute('data-src') ||
                                        img.getAttribute('data-lazy-src') || '';
                            return {
                                idx: idx,
                                src: src,
                                originalSrc: img.getAttribute('src') || '',
                                alt: img.alt || '',
                                width: w,
                                height: h,
                                complete: img.complete
                            };
                        });
                    }""")

                    candidates = [
                        info for info in img_infos
                        if info["src"]
                        and info["width"] >= 30
                        and info["height"] >= 30
                        and not info["src"].lower().endswith(".svg")
                        and "image/svg" not in info["src"]
                    ][:max_imgs]

                    total = len(candidates)
                    incomplete = sum(1 for i in img_infos if not i.get("complete", True) and i["src"])
                    skip_info = f" · {incomplete} noch nicht fertig geladen" if incomplete else ""
                    self._log(f"Lade {total} Bilder… (von {len(img_infos)} img-Elementen{skip_info})")

                    for i, info in enumerate(candidates):
                        if self._stop.is_set():
                            break
                        self._download_image(ctx, info, img_data)
                        self._progress(32 + int(10 * (i + 1) / max(total, 1)))

                else:
                    img_infos = []

                # HTML-Snapshot NACH Attribut-Injektion aufnehmen
                html = page.content()

            finally:
                browser.close()

        return html, img_data

    def _full_scroll(self, page):
        prev = -1
        iterations = 0
        while iterations < 40:
            page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            page.wait_for_timeout(400)
            h = page.evaluate("document.body.scrollHeight")
            if h == prev:
                break
            prev = h
            iterations += 1
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)

    def _download_image(self, ctx, info: dict, img_data: dict):
        abs_src = info["src"]
        orig_src = info["originalSrc"]
        idx = info.get("idx", -1)
        try:
            response = ctx.request.get(abs_src)
            if not response.ok:
                self._log(f"  [Bild] HTTP {response.status}: {abs_src[:90]}")
                return
            ct = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if ct not in SUPPORTED_MIMES:
                self._log(f"  [Bild] Übersprungen ({ct}): {abs_src[:90]}")
                return
            b64 = base64.b64encode(response.body()).decode()
            img_data[abs_src] = (b64, ct)
            # Auch relative Variante speichern (Pfad ohne Domain)
            try:
                parsed = urlparse(abs_src)
                rel = parsed.path + ("?" + parsed.query if parsed.query else "")
                if rel and rel != abs_src:
                    img_data[rel] = (b64, ct)
            except Exception:
                pass
            if orig_src:
                img_data[orig_src] = (b64, ct)
            # Positions-Index als primärer Fallback (data-scraper-idx im HTML-Snapshot)
            if idx >= 0:
                img_data[f"__pos_{idx}"] = (b64, ct)
        except Exception as e:
            self._log(f"  [Bild] Fehler: {e} – {abs_src[:90]}")

    # ── HTML → Markdown ───────────────────────────────────────────────────────

    # Content-Container-Tokens nach Aussagekraft gestaffelt (durch -, _, Leerzeichen
    # getrennt). "content" ist das verlässlichste Signal und wird zuerst geprüft;
    # erst danach "main/article/entry/post". So gewinnt z. B. "article--content"
    # gegen "article-count" oder "article--teaser".
    _CONTENT_TIERS = [
        re.compile(r"(?:^|[-_ ])content(?:[-_ ]|$)", re.I),
        re.compile(r"(?:^|[-_ ])(main|article|entry|post)(?:[-_ ]|$)", re.I),
    ]
    # Navigations-/Rahmen-Elemente, die NIE als Content-Wurzel taugen.
    # Schützt vor Klassen wie "gh-g-navigation--main-panel" (enthält "main").
    _NAVISH_RE = re.compile(
        r"\b(nav|navigation|menu|header|footer|breadcrumb|sidebar)\b", re.I
    )

    def _is_navish(self, el) -> bool:
        """True, wenn das Element zur Navigation/Rahmenstruktur gehört."""
        if (el.name or "").lower() in ("nav", "header", "footer"):
            return True
        haystack = " ".join(el.get("class") or []) + " " + (el.get("id") or "")
        return bool(self._NAVISH_RE.search(haystack))

    def _find_content_root(self, soup):
        """Findet den Haupt-Inhaltscontainer und überspringt Navigations-Elemente.

        Frühere Heuristik (\\b(content|main|article)\\b) matchte fälschlich
        Navigations-IDs wie 'gh-g-navigation--main', weil Bindestriche als
        Wortgrenzen zählen – die <nav> wurde als Wurzel gewählt und in _node
        sofort verworfen → leere Ausgabe.
        """
        for tag in ("main", "article"):
            el = soup.find(tag)
            if el is not None:
                return el
        # Pro Stufe alle nicht-navigationsartigen Treffer sammeln und den
        # textreichsten wählen (robust gegen kleine Teaser-/Zähler-Container).
        for pattern in self._CONTENT_TIERS:
            matches = []
            seen = set()
            for el in soup.find_all(class_=pattern) + soup.find_all(id=pattern):
                if id(el) in seen or self._is_navish(el):
                    continue
                seen.add(id(el))
                matches.append(el)
            if matches:
                return max(matches, key=lambda e: len(e.get_text(strip=True)))
        return soup.body or soup

    def _to_markdown(self, html: str, img_data: dict) -> str:
        try:
            from bs4 import BeautifulSoup
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                soup = BeautifulSoup(html, "html.parser")
        except ImportError:
            return "# Fehler\n\nBeautifulSoup nicht verfügbar.\n"

        title_tag = soup.find("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""

        for dead in soup.find_all(["script", "style", "noscript", "svg",
                                   "iframe", "template"]):
            dead.decompose()

        # Globale Positions-Map: BeautifulSoup-Element-ID → DOM-Index aus JS-Evaluation
        # Beide traversieren in document order ohne noscript/template → Indizes stimmen überein
        _body = soup.body or soup
        self._img_pos_map = {id(el): i for i, el in enumerate(_body.find_all("img"))}

        root = self._find_content_root(soup)

        self._img_data = img_data
        self._img_counter = [0]
        self._img_total = [len(list(root.find_all("img")))]

        lines: list = []
        if page_title:
            lines += ["", f"# {page_title}", ""]

        self._node(root, lines)

        md = "\n".join(lines)
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md.strip() + "\n"

    def _node(self, el, out: list):
        from bs4 import NavigableString, Tag

        if isinstance(el, NavigableString):
            t = str(el).strip()
            if t:
                out.append(t)
            return

        if not isinstance(el, Tag):
            return

        tag = (el.name or "").lower()

        if tag in ("script", "style", "noscript", "svg", "template", "nav", "footer"):
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            n = int(tag[1])
            txt = self._inline(el).strip()
            if txt:
                out += ["", f"{'#' * n} {txt}", ""]
            return

        if tag == "p":
            # Absätze mit Bildern (z. B. <p><img></p>) getrennt ausgeben:
            # Bilder als Bild-Block, Text als normalen Absatz.
            if el.find("img"):
                buf = ""
                for ch in el.children:
                    if isinstance(ch, Tag) and ch.name == "img":
                        if buf.strip():
                            out += ["", buf.strip(), ""]
                        buf = ""
                        self._img_block(ch, out)
                    elif isinstance(ch, Tag) and ch.find("img"):
                        if buf.strip():
                            out += ["", buf.strip(), ""]
                        buf = ""
                        self._node(ch, out)
                    else:
                        buf += self._inline(ch)
                if buf.strip():
                    out += ["", buf.strip(), ""]
                return
            txt = self._inline(el).strip()
            if txt:
                out += ["", txt, ""]
            return

        if tag == "blockquote":
            inner: list = []
            for ch in el.children:
                self._node(ch, inner)
            for line in "\n".join(inner).splitlines():
                out.append(f"> {line}" if line.strip() else ">")
            out.append("")
            return

        if tag == "pre":
            code = el.find("code")
            text = (code or el).get_text()
            lang = ""
            if code:
                for cls in (code.get("class") or []):
                    if cls.startswith("language-"):
                        lang = cls[9:]
                        break
            out += ["", f"```{lang}", text.rstrip(), "```", ""]
            return

        if tag == "img":
            self._img_block(el, out)
            return

        if tag == "figure":
            # <figure> umschließt nicht nur Bilder: WordPress & Co. verpacken
            # auch Tabellen (figure.wp-block-table), Code (wp-block-code), Listen
            # usw. in <figure>. Nur eine echte Bild-Figur als Bild-Block rendern;
            # enthält die Figur Block-Inhalt (z. B. eine Tabelle), als Container
            # rekursiv verarbeiten – sonst ginge der gesamte Inhalt verloren.
            block_child = el.find(["table", "pre", "blockquote", "ul", "ol", "iframe"])
            img = el.find("img")
            cap = el.find("figcaption")
            if img is not None and block_child is None:
                self._img_block(img, out, caption=self._inline(cap).strip() if cap else "")
            else:
                for ch in el.children:
                    self._node(ch, out)
            return

        if tag == "table":
            # Tabelle mit Bildern → als Container rekursiv verarbeiten (Bilder nicht verwerfen)
            if el.find("img"):
                for ch in el.children:
                    self._node(ch, out)
            else:
                self._table(el, out)
            return

        if tag == "ul":
            out.append("")
            for li in el.find_all("li", recursive=False):
                self._list_item(li, out, indent=0, ordered=False, num=None)
            out.append("")
            return

        if tag == "ol":
            out.append("")
            for i, li in enumerate(el.find_all("li", recursive=False), 1):
                self._list_item(li, out, indent=0, ordered=True, num=i)
            out.append("")
            return

        if tag == "details":
            summ = el.find("summary")
            if summ:
                out += ["", f"**{self._inline(summ).strip()}**", ""]
            for ch in el.children:
                if not (isinstance(ch, Tag) and ch.name == "summary"):
                    self._node(ch, out)
            return

        if tag == "hr":
            out += ["", "---", ""]
            return

        if tag == "iframe":
            src = el.get("src", "")
            if src:
                out += ["", f"[Eingebetteter Inhalt]({src})", ""]
            return

        if tag in ("div", "section", "aside", "article", "main", "header"):
            classes = " ".join(el.get("class") or []).lower()
            if re.search(
                r"\b(note|tip|warning|caution|danger|info|hint|alert|callout|admonition|notice)\b",
                classes,
            ):
                inner: list = []
                for ch in el.children:
                    self._node(ch, inner)
                for line in "\n".join(inner).splitlines():
                    out.append(f"> {line}" if line.strip() else ">")
                out.append("")
                return

        for ch in el.children:
            self._node(ch, out)

    # ── Inline-Konverter ──────────────────────────────────────────────────────

    def _inline(self, el) -> str:
        from bs4 import NavigableString, Tag

        if isinstance(el, NavigableString):
            return str(el)
        if not isinstance(el, Tag):
            return ""

        tag = (el.name or "").lower()

        if tag in ("script", "style"):
            return ""

        if tag in ("strong", "b"):
            inner = self._inline_children(el)
            return f"**{inner}**" if inner.strip() else inner

        if tag in ("em", "i"):
            inner = self._inline_children(el)
            return f"*{inner}*" if inner.strip() else inner

        if tag in ("del", "s", "strike"):
            inner = self._inline_children(el)
            return f"~~{inner}~~" if inner.strip() else inner

        if tag == "code":
            return f"`{el.get_text()}`"

        if tag == "a":
            href = el.get("href", "")
            if href and not href.startswith("#"):
                if not href.startswith("http"):
                    href = urljoin(self.base_url, href)
            inner = self._inline_children(el).strip()
            if href and inner:
                return f"[{inner}]({href})"
            return inner

        if tag == "br":
            return "\n"

        if tag == "img":
            alt = el.get("alt", "")
            return f"[Bild: {alt}]" if alt else ""

        return self._inline_children(el)

    def _inline_children(self, el) -> str:
        return "".join(self._inline(ch) for ch in el.children)

    # ── Bild-Block ────────────────────────────────────────────────────────────

    def _img_block(self, el, out: list, caption: str = ""):
        src = (
            el.get("src")
            or el.get("data-src")
            or el.get("data-lazy-src")
            or el.get("data-original")
            or (el.get("data-srcset", "").split() or [""])[0]
            or (el.get("srcset", "").split(",")[0].strip().split() or [""])[0]
            or ""
        )
        # Daten-URIs und Blob-URLs sind keine echten Bild-URLs
        if src.startswith(("data:", "blob:")):
            src = ""

        alt = el.get("alt", "")
        title_attr = el.get("title", "")
        label = caption or title_attr or alt or "Screenshot"

        out.append("")
        out.append(f"> 📷 **Screenshot: {label}**")
        out.append(">")

        # ── Bild-Lookup: 6 Stufen ─────────────────────────────────────────────
        entry = None

        # Stufe 1+2: exakt / absolut via src & data-*-Attribute
        if src:
            entry = self._img_data.get(src)
            if entry is None and self.base_url:
                entry = self._img_data.get(urljoin(self.base_url, src))
            if entry is None:
                for attr in ("data-src", "data-lazy-src", "data-original"):
                    val = el.get(attr, "")
                    if val:
                        entry = self._img_data.get(val)
                        if entry is None and self.base_url:
                            entry = self._img_data.get(urljoin(self.base_url, val))
                        if entry:
                            break

        # Stufe 3: srcset-Attribute direkt am <img>
        if entry is None:
            for srcset_attr in ("srcset", "data-srcset"):
                srcset_val = el.get(srcset_attr, "")
                if srcset_val:
                    for part in srcset_val.split(","):
                        part_url = part.strip().split()[0] if part.strip() else ""
                        if part_url and not part_url.startswith(("data:", "blob:")):
                            entry = self._img_data.get(part_url)
                            if entry is None and self.base_url:
                                entry = self._img_data.get(urljoin(self.base_url, part_url))
                            if entry:
                                break
                if entry:
                    break

        # Stufe 4: übergeordnetes <picture>-Element → <source srcset="…">
        if entry is None and el.parent and el.parent.name == "picture":
            for source in el.parent.find_all("source"):
                for src_attr in ("srcset", "src"):
                    sv = source.get(src_attr, "")
                    for part in sv.split(","):
                        part_url = part.strip().split()[0] if part.strip() else ""
                        if part_url and not part_url.startswith(("data:", "blob:")):
                            entry = self._img_data.get(part_url)
                            if entry is None and self.base_url:
                                entry = self._img_data.get(urljoin(self.base_url, part_url))
                            if entry:
                                break
                    if entry:
                        break
                if entry:
                    break

        # Stufe 5: data-scraper-idx – vom JS injiziertes Attribut (100 % zuverlässig)
        if entry is None:
            scraper_idx = el.get("data-scraper-idx")
            if scraper_idx is not None:
                try:
                    entry = self._img_data.get(f"__pos_{int(scraper_idx)}")
                except (ValueError, TypeError):
                    pass

        if entry:
            b64, mime_type = entry
            self._img_counter[0] += 1
            n = self._img_counter[0]
            total = self._img_total[0]
            self._log(f"  Beschreibe Bild {n}/{total}: {label[:60]}…")
            desc = self._describe_image(b64, mime_type, alt)
            for line in desc.splitlines():
                out.append(f"> {line}" if line else ">")
        else:
            sidx = el.get("data-scraper-idx", "?")
            reason = (f"scraper-idx={sidx} nicht in img_data"
                      if sidx != "?" else "kein data-scraper-idx")
            self._log(f"  [Bild übersprungen] {reason} · src='{(src or '')[:60]}'")
            if alt:
                out.append(f"> Alt-Text: {alt}")
            elif src:
                out.append(f"> Bild-URL: {src}")
            else:
                out.append("> [Bild ohne Quelle]")

        out.append("")

    # ── KI-Bildbeschreibung ───────────────────────────────────────────────────

    def _describe_image(self, b64: str, mime_type: str, alt: str) -> str:
        api_key = get_api_key("claude")

        if not api_key:
            return f"[Kein API-Key – Alt-Text: {alt}]" if alt else "[Kein API-Key konfiguriert]"

        cache_key = b64[:64]
        if cache_key in self._img_cache:
            return self._img_cache[cache_key]

        prompt = (
            "Beschreibe dieses Bild/Screenshot sehr detailliert auf Deutsch. "
            "Nenne alle sichtbaren UI-Elemente, Texte, Feldbezeichnungen, Buttons, "
            "Dropdown-Optionen, Einstellungen, Werte, Symbole und deren Bedeutung. "
            "Beschreibe auch Layout und Struktur. Beginne direkt ohne Einleitung."
            + (f" Alt-Text: {alt}" if alt else "")
        )

        try:
            time.sleep(0.5)
            result = self._describe_claude(b64, mime_type, prompt)
            self._img_cache[cache_key] = result
            return result
        except Exception as exc:
            self._log(f"  Bildbeschreibungs-Fehler: {exc}")
            return f"[Bildbeschreibung fehlgeschlagen: {exc}]"

    def _describe_claude(self, b64: str, mime_type: str, prompt: str) -> str:
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=get_api_key("claude"))
        model = self.settings.get("claude_model", "claude-haiku-4-5")
        resp = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.content[0].text.strip()

    # ── Listeneinträge ────────────────────────────────────────────────────────

    def _list_item(self, li, out: list, indent: int, ordered: bool, num):
        from bs4 import Tag
        prefix = "  " * indent
        bullet = f"{num}." if ordered else "-"

        inline_parts: list = []
        nested: list = []
        block_els: list = []  # img / figure direkt im <li>

        for ch in li.children:
            if isinstance(ch, Tag) and ch.name in ("ul", "ol"):
                nested.append(ch)
            elif isinstance(ch, Tag) and ch.name in ("img", "figure"):
                block_els.append(ch)
            else:
                inline_parts.append(self._inline(ch))

        text = "".join(inline_parts).strip()
        if text:
            out.append(f"{prefix}{bullet} {text}")

        # Bilder im Listeneintrag als Block unterhalb des Textes ausgeben
        for bel in block_els:
            if bel.name == "img":
                self._img_block(bel, out)
            else:  # figure
                img = bel.find("img")
                cap = bel.find("figcaption")
                if img:
                    self._img_block(img, out,
                                    caption=self._inline(cap).strip() if cap else "")

        for sub in nested:
            is_ord = sub.name == "ol"
            for j, sub_li in enumerate(sub.find_all("li", recursive=False), 1):
                self._list_item(sub_li, out, indent + 1, ordered=is_ord, num=j)

    # ── Tabellen ──────────────────────────────────────────────────────────────

    def _table(self, table, out: list):
        rows: list = []
        for tr in table.find_all("tr"):
            cells = []
            for cell in tr.find_all(["th", "td"]):
                t = cell.get_text(" ", strip=True).replace("|", "\\|").replace("\n", " ")
                cells.append(t)
            if cells:
                rows.append(cells)

        if not rows:
            return

        ncols = max(len(r) for r in rows)
        for r in rows:
            while len(r) < ncols:
                r.append("")

        out.append("")
        for i, row in enumerate(rows):
            out.append("| " + " | ".join(row) + " |")
            if i == 0:
                out.append("| " + " | ".join(["---"] * ncols) + " |")
        out.append("")


# ─── Einstiegspunkt ───────────────────────────────────────────────────────────
# SettingsDialog und App werden erst nach ensure_dependencies() definiert,
# damit customtkinter beim ersten Start automatisch installiert werden kann.

if __name__ == "__main__":
    ensure_dependencies()

    import customtkinter as ctk
    ctk.set_appearance_mode(load_settings().get("appearance", "dark"))
    ctk.set_default_color_theme("blue")

    # ── Einstellungs-Dialog ───────────────────────────────────────────────────

    # ── Zentrierter Nachrichten-Dialog ────────────────────────────────────────

    class _MsgBox(ctk.CTkToplevel):
        """Ersatz für tkinter.messagebox – erscheint immer mittig zum Elternfenster."""

        def __init__(self, parent, title: str, message: str, kind: str = "ok"):
            super().__init__(parent)
            # None = Dialog geschlossen (Fenster-X/Escape) → sichere Variante,
            # False = explizit "Nein", True = explizit "Ja".
            self.result = None
            self.title(title)
            self.resizable(False, False)
            self.transient(parent)
            self.grab_set()
            self.lift()
            self.focus_force()
            self._build(message, kind)
            self._center(parent)
            self.wait_window()

        def _build(self, message: str, kind: str):
            self.columnconfigure(0, weight=1)
            ctk.CTkLabel(
                self, text=message, wraplength=380, justify="left",
                font=ctk.CTkFont(size=13), anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 14))
            btn = ctk.CTkFrame(self, fg_color="transparent")
            btn.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="e")
            if kind == "yesno":
                ctk.CTkButton(
                    btn, text="Nein", width=92, height=32,
                    fg_color="transparent", border_width=1,
                    text_color=("gray10", "gray90"),
                    command=self._no,
                ).pack(side="left", padx=(0, 8))
                ctk.CTkButton(
                    btn, text="Ja", width=92, height=32,
                    command=self._yes,
                ).pack(side="left")
            else:
                ctk.CTkButton(
                    btn, text="OK", width=92, height=32,
                    command=self.destroy,
                ).pack(side="left")

        def _yes(self):
            self.result = True
            self.destroy()

        def _no(self):
            self.result = False
            self.destroy()

        def _center(self, parent):
            self.update_idletasks()
            dw = self.winfo_reqwidth()
            dh = self.winfo_reqheight()
            px = parent.winfo_x() + (parent.winfo_width()  - dw) // 2
            py = parent.winfo_y() + (parent.winfo_height() - dh) // 2
            self.geometry(f"+{px}+{py}")

    def _askyn(parent, title: str, msg: str) -> bool:
        return _MsgBox(parent, title, msg, "yesno").result

    def _showmsg(parent, title: str, msg: str):
        _MsgBox(parent, title, msg, "ok")

    # ── FormatEditorDialog ────────────────────────────────────────────────────

    class FormatEditorDialog(ctk.CTkToplevel):
        """Dialog zum Anlegen und Bearbeiten eines Ausgabeformats."""

        def __init__(self, parent, fmt: dict):
            super().__init__(parent)
            self._fmt   = dict(fmt)
            self.result = None
            title_txt   = "Format bearbeiten" if fmt.get("id") else "Neues Format"
            self.title(title_txt)
            self.geometry("600x580")
            self.minsize(560, 420)
            self.transient(parent)
            self.grab_set()
            self.lift()
            self.focus_force()
            self._build_ui()
            self._load_values()
            self.wait_window()

        def _build_ui(self):
            self.columnconfigure(0, weight=1)
            self.rowconfigure(1, weight=1)

            ctk.CTkLabel(
                self,
                text=("✏️  Format bearbeiten" if self._fmt.get("id")
                      else "➕  Neues Format anlegen"),
                font=ctk.CTkFont(size=16, weight="bold"), anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 8))

            scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
            scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=0)
            scroll.columnconfigure(1, weight=1)

            r = 0

            # ── Name ──
            ctk.CTkLabel(scroll, text="Name", anchor="w").grid(
                row=r, column=0, sticky="w", padx=8, pady=(8, 4))
            self._name_var = tk.StringVar()
            ctk.CTkEntry(scroll, textvariable=self._name_var,
                         placeholder_text="z. B. Jira-Markdown").grid(
                row=r, column=1, sticky="ew", padx=(8, 4), pady=(8, 4))
            r += 1

            # ── Typ + Dateiendung ──
            ctk.CTkLabel(scroll, text="Typ", anchor="w").grid(
                row=r, column=0, sticky="w", padx=8, pady=4)
            type_row = ctk.CTkFrame(scroll, fg_color="transparent")
            type_row.grid(row=r, column=1, sticky="ew", padx=(8, 4), pady=4)
            self._type_var = tk.StringVar()
            ctk.CTkComboBox(
                type_row, variable=self._type_var,
                values=["Markdown", "XML", "CSV"],
                width=150, state="readonly",
                command=self._on_type_change,
            ).pack(side="left")
            ctk.CTkLabel(type_row, text="  Dateiendung:", anchor="w").pack(
                side="left", padx=(14, 4))
            self._ext_var = tk.StringVar()
            ctk.CTkEntry(type_row, textvariable=self._ext_var, width=72).pack(
                side="left")
            r += 1

            ctk.CTkFrame(scroll, height=1, fg_color="gray35").grid(
                row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
            r += 1

            # ── Template (Markdown/XML) ──
            self._tpl_frame = ctk.CTkFrame(scroll, fg_color="transparent")
            self._tpl_frame.grid(row=r, column=0, columnspan=2, sticky="ew")
            self._tpl_frame.columnconfigure(0, weight=1)
            ctk.CTkLabel(
                self._tpl_frame,
                text="📝  Template  (leer = Standard-Ausgabe)",
                font=ctk.CTkFont(weight="bold"), anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=(0, 2))
            ctk.CTkLabel(
                self._tpl_frame,
                text="Platzhalter:  {{title}}  {{url}}  {{content}}"
                     "  {{text}}  {{meta_description}}  {{date}}",
                font=ctk.CTkFont(size=10), text_color="gray55", anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
            self._tpl_box = ctk.CTkTextbox(
                self._tpl_frame,
                font=ctk.CTkFont(family="Consolas", size=10),
                height=120, corner_radius=6,
            )
            self._tpl_box.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
            r += 1

            # ── Felder (XML/CSV) ──
            self._fld_frame = ctk.CTkFrame(scroll, fg_color="transparent")
            self._fld_frame.grid(row=r, column=0, columnspan=2, sticky="ew")
            ctk.CTkLabel(
                self._fld_frame,
                text="📋  Felder",
                font=ctk.CTkFont(weight="bold"), anchor="w",
            ).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 4))
            self._field_vars: dict = {}
            _field_labels = {
                "title": "Titel",
                "url": "URL",
                "content": "Inhalt (Markdown)",
                "text": "Text (Plain)",
                "meta_description": "Meta-Beschreibung",
                "date": "Datum",
                "images_count": "Bilder-Anzahl",
            }
            for idx, fld in enumerate(ALL_FORMAT_FIELDS):
                v = tk.BooleanVar(value=False)
                self._field_vars[fld] = v
                ctk.CTkCheckBox(
                    self._fld_frame,
                    text=_field_labels.get(fld, fld),
                    variable=v,
                ).grid(row=1 + idx // 2, column=idx % 2, sticky="w",
                       padx=(8, 24), pady=2)
            r += 1

            # ── CSV-Parameter ──
            self._csv_frame = ctk.CTkFrame(scroll, fg_color="transparent")
            self._csv_frame.grid(row=r, column=0, columnspan=2, sticky="ew")
            ctk.CTkLabel(
                self._csv_frame,
                text="⚙  CSV-Parameter",
                font=ctk.CTkFont(weight="bold"), anchor="w",
            ).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))
            ctk.CTkLabel(
                self._csv_frame, text="Trennzeichen:", anchor="w",
            ).grid(row=1, column=0, sticky="w", padx=8, pady=2)
            self._delim_var = tk.StringVar(value=";")
            ctk.CTkEntry(
                self._csv_frame, textvariable=self._delim_var, width=48,
            ).grid(row=1, column=1, sticky="w", padx=4, pady=2)
            ctk.CTkLabel(
                self._csv_frame, text="Anführungszeichen:", anchor="w",
            ).grid(row=1, column=2, sticky="w", padx=(16, 4), pady=2)
            self._quote_var = tk.StringVar(value='"')
            ctk.CTkEntry(
                self._csv_frame, textvariable=self._quote_var, width=48,
            ).grid(row=1, column=3, sticky="w", padx=4, pady=2)
            self._header_var = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(
                self._csv_frame, text="Kopfzeile einschließen",
                variable=self._header_var,
            ).grid(row=2, column=0, columnspan=4, sticky="w", padx=8, pady=4)
            r += 1

            # ── XML-Parameter ──
            self._xml_frame = ctk.CTkFrame(scroll, fg_color="transparent")
            self._xml_frame.grid(row=r, column=0, columnspan=2, sticky="ew")
            ctk.CTkLabel(
                self._xml_frame,
                text="⚙  XML-Parameter",
                font=ctk.CTkFont(weight="bold"), anchor="w",
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
            ctk.CTkLabel(
                self._xml_frame, text="Wurzelelement:", anchor="w",
            ).grid(row=1, column=0, sticky="w", padx=8, pady=2)
            self._root_var = tk.StringVar(value="page")
            ctk.CTkEntry(
                self._xml_frame, textvariable=self._root_var, width=120,
            ).grid(row=1, column=1, sticky="w", padx=4, pady=2)

            # ── Buttons ──
            btn_row = ctk.CTkFrame(self, fg_color="transparent")
            btn_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 16))
            ctk.CTkButton(
                btn_row, text="Speichern", command=self._save,
                width=120, height=34,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                btn_row, text="Abbrechen", command=self.destroy,
                width=110, height=34,
                fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"),
            ).pack(side="left")

        def _on_type_change(self, val=None):
            if val is None:
                val = self._type_var.get()
            t = {"Markdown": "markdown", "XML": "xml", "CSV": "csv"}.get(
                val, "markdown")
            for widget, show in [
                (self._tpl_frame, t in ("markdown", "xml")),
                (self._fld_frame, t in ("xml", "csv")),
                (self._csv_frame, t == "csv"),
                (self._xml_frame, t == "xml"),
            ]:
                if show:
                    widget.grid()
                else:
                    widget.grid_remove()
            if not self._ext_var.get().strip():
                self._ext_var.set(
                    {"markdown": ".md", "xml": ".xml", "csv": ".csv"}[t])

        def _load_values(self):
            fmt = self._fmt
            self._name_var.set(fmt.get("name", ""))
            _type_map = {"markdown": "Markdown", "xml": "XML", "csv": "CSV"}
            self._type_var.set(
                _type_map.get(fmt.get("type", "markdown"), "Markdown"))
            self._ext_var.set(fmt.get("extension", ""))
            tpl = fmt.get("template", "")
            self._tpl_box.delete("1.0", tk.END)
            if tpl:
                self._tpl_box.insert("1.0", tpl)
            for fld, var in self._field_vars.items():
                var.set(fld in fmt.get("fields", []))
            params = fmt.get("params", {})
            self._delim_var.set(params.get("delimiter", ";"))
            self._quote_var.set(params.get("quotechar", '"'))
            self._header_var.set(params.get("include_header", True))
            self._root_var.set(params.get("root_element", "page"))
            self._on_type_change()

        def _save(self):
            name = self._name_var.get().strip()
            if not name:
                _showmsg(self, "Hinweis", "Bitte einen Namen eingeben.")
                return
            self.result = self._collect()
            self.destroy()

        def _collect(self) -> dict:
            _type_map = {"Markdown": "markdown", "XML": "xml", "CSV": "csv"}
            t      = _type_map.get(self._type_var.get(), "markdown")
            fields = [f for f, v in self._field_vars.items() if v.get()]
            params: dict = {}
            if t == "csv":
                params = {
                    "delimiter":      self._delim_var.get() or ";",
                    "quotechar":      self._quote_var.get() or '"',
                    "include_header": self._header_var.get(),
                }
            elif t == "xml":
                params = {"root_element": self._root_var.get() or "page"}
            ext    = self._ext_var.get().strip() or f".{t}"
            tpl    = (self._tpl_box.get("1.0", tk.END).strip()
                      if t != "csv" else "")
            fmt_id = self._fmt.get("id") or f"fmt_{int(time.time())}"
            return {
                "id":        fmt_id,
                "name":      self._name_var.get().strip(),
                "type":      t,
                "extension": ext,
                "template":  tpl,
                "fields":    fields,
                "params":    params,
                "builtin":   self._fmt.get("builtin", False),
            }

    # ── SettingsDialog ────────────────────────────────────────────────────────

    class SettingsDialog(ctk.CTkToplevel):
        def __init__(self, parent):
            super().__init__(parent)
            self.title("Einstellungen")
            self.geometry("640x600")
            self.resizable(False, False)
            self.transient(parent)
            self.grab_set()
            self.lift()
            self.focus_force()
            self._build_ui()
            self._load_values()
            self.wait_window()

        def _build_ui(self):
            ctk.CTkLabel(
                self, text="⚙  Einstellungen",
                font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
            ).pack(padx=20, pady=(18, 8), fill="x")

            tabs = ctk.CTkTabview(self, height=350)
            tabs.pack(fill="both", expand=True, padx=16, pady=(0, 8))

            ai       = tabs.add("🤖  KI & API")
            sc       = tabs.add("🔧  Scraper")
            fmt_tab  = tabs.add("📋  Formate")
            clog_tab = tabs.add("📰  Changelog")

            # ── KI-Tab ────────────────────────────────────────────────────────
            ai.columnconfigure(1, weight=1)

            row = 0
            ctk.CTkLabel(ai, text="Anthropic API-Key",
                         font=ctk.CTkFont(weight="bold"), anchor="w").grid(
                row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(12, 2))
            row += 1
            self._claude_var = tk.StringVar()
            claude_e = ctk.CTkEntry(ai, textvariable=self._claude_var, show="*", width=390)
            claude_e.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8)
            row += 1
            self._claude_show = tk.BooleanVar()
            ctk.CTkCheckBox(
                ai, text="Key anzeigen", variable=self._claude_show,
                command=lambda: claude_e.configure(show="" if self._claude_show.get() else "*"),
            ).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            row += 1

            ctk.CTkLabel(ai, text="Modell", anchor="w").grid(
                row=row, column=0, sticky="w", padx=8, pady=6)
            self._claude_model_var = tk.StringVar()
            ctk.CTkComboBox(ai, variable=self._claude_model_var,
                            values=["claude-haiku-4-5", "claude-sonnet-4-6",
                                    "claude-opus-4-8"], width=200).grid(
                row=row, column=1, sticky="w", padx=8, pady=6)
            # ── Scraper-Tab ───────────────────────────────────────────────────
            self._desc_var = tk.BooleanVar()
            ctk.CTkCheckBox(sc, text="Bilder mit AI beschreiben",
                            variable=self._desc_var).pack(anchor="w", padx=8, pady=(16, 8))

            self._headless_var = tk.BooleanVar()
            ctk.CTkCheckBox(sc, text="Browser unsichtbar (Headless-Modus)",
                            variable=self._headless_var).pack(anchor="w", padx=8, pady=8)

            max_row = ctk.CTkFrame(sc, fg_color="transparent")
            max_row.pack(anchor="w", padx=8, pady=(16, 8))
            ctk.CTkLabel(max_row, text="Max. Bilder pro Seite:").pack(side="left")
            self._max_var = tk.IntVar(value=30)
            ctk.CTkEntry(max_row, textvariable=self._max_var, width=72).pack(
                side="left", padx=(10, 8))
            ctk.CTkLabel(max_row, text="(je Bild ca. 1–3 API-Calls)",
                         text_color="gray55",
                         font=ctk.CTkFont(size=11)).pack(side="left")

            ctk.CTkFrame(sc, height=1, fg_color="gray35").pack(
                fill="x", padx=8, pady=(18, 14))

            appear_row = ctk.CTkFrame(sc, fg_color="transparent")
            appear_row.pack(anchor="w", padx=8, pady=(0, 8))
            ctk.CTkLabel(appear_row, text="Erscheinungsbild:").pack(side="left", padx=(0, 14))
            self._appear_var = tk.StringVar(value="dark")
            ctk.CTkSegmentedButton(
                appear_row,
                values=["🌙  Dark", "☀️  Light", "🖥  System"],
                variable=self._appear_var,
                width=280,
            ).pack(side="left")

            self._build_formats_tab(fmt_tab)
            self._build_changelog_tab(clog_tab)

            # ── Buttons ───────────────────────────────────────────────────────
            btn_row = ctk.CTkFrame(self, fg_color="transparent")
            btn_row.pack(padx=16, pady=(0, 18), fill="x")
            ctk.CTkButton(btn_row, text="Speichern", command=self._save,
                          width=130, height=34).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                btn_row, text="Abbrechen", command=self.destroy,
                width=110, height=34,
                fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"),
            ).pack(side="left")

        def _load_values(self):
            s = load_settings()
            self._claude_model_var.set(s.get("claude_model", "claude-haiku-4-5"))
            self._desc_var.set(s.get("describe_images", True))
            self._headless_var.set(s.get("headless", True))
            self._max_var.set(s.get("max_images", 30))
            # Erscheinungsbild: intern "dark"/"light"/"system" → Label mit Emoji
            _mode_to_label = {"dark": "🌙  Dark", "light": "☀️  Light", "system": "🖥  System"}
            self._appear_var.set(_mode_to_label.get(s.get("appearance", "dark"), "🌙  Dark"))
            self._claude_var.set(get_api_key("claude"))

        def _save(self):
            s = load_settings()
            s["claude_model"] = self._claude_model_var.get()
            s["describe_images"] = self._desc_var.get()
            s["headless"] = self._headless_var.get()
            try:
                s["max_images"] = int(self._max_var.get())
            except (ValueError, tk.TclError):
                s["max_images"] = 30
            # Erscheinungsbild: Label → interner Schlüssel
            _label_to_mode = {"🌙  Dark": "dark", "☀️  Light": "light", "🖥  System": "system"}
            appearance = _label_to_mode.get(self._appear_var.get(), "dark")
            s["appearance"] = appearance
            save_settings(s)
            claude = self._claude_var.get().strip()
            if claude:
                set_api_key("claude", claude)
            # Modus sofort anwenden (kein Neustart nötig)
            ctk.set_appearance_mode(appearance)
            _showmsg(self, "Einstellungen", "Gespeichert.")
            self.destroy()

        # ── Formate-Tab ───────────────────────────────────────────────────────

        def _build_formats_tab(self, frame):
            """Baut den Inhalt des Formate-Tabs (wird auch beim Reload aufgerufen)."""
            self._fmt_tab_frame = frame
            for w in frame.winfo_children():
                w.destroy()
            frame.columnconfigure(0, weight=1)

            ctk.CTkLabel(
                frame,
                text="Ausgabeformat für Extraktionen:",
                font=ctk.CTkFont(weight="bold"), anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=(12, 6))

            fmts     = get_formats()
            s        = load_settings()
            active_id = s.get("active_format", "builtin_md")
            self._fmt_radio_var = tk.StringVar(value=active_id)

            for i, fmt in enumerate(fmts):
                row_frame = ctk.CTkFrame(frame, fg_color="transparent")
                row_frame.grid(row=i + 1, column=0, sticky="ew", padx=4, pady=2)
                row_frame.columnconfigure(0, weight=1)

                ctk.CTkRadioButton(
                    row_frame,
                    text=f"{fmt['name']}   ({fmt.get('extension', '')})",
                    variable=self._fmt_radio_var,
                    value=fmt["id"],
                    command=lambda fid=fmt["id"]: self._set_active_format(fid),
                ).pack(side="left", padx=(4, 0))

                ctk.CTkButton(
                    row_frame, text="Bearbeiten",
                    width=90, height=28,
                    command=lambda f=fmt: self._edit_format(f),
                ).pack(side="right", padx=(4, 0))

                if not fmt.get("builtin", False):
                    ctk.CTkButton(
                        row_frame, text="🗑",
                        width=34, height=28,
                        fg_color=("gray72", "gray28"),
                        hover_color=("#c0392b", "#922b21"),
                        text_color=("gray10", "gray90"),
                        command=lambda f=fmt: self._delete_format(f),
                    ).pack(side="right", padx=(0, 2))

            ctk.CTkButton(
                frame,
                text="➕  Format hinzufügen",
                command=self._new_format,
                width=180, height=30,
                fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"),
            ).grid(row=len(fmts) + 1, column=0, sticky="w",
                   padx=8, pady=(10, 8))

        def _reload_formats_tab(self):
            if hasattr(self, "_fmt_tab_frame"):
                self._build_formats_tab(self._fmt_tab_frame)

        def _set_active_format(self, fmt_id: str):
            s = load_settings()
            s["active_format"] = fmt_id
            save_settings(s)

        def _new_format(self):
            dlg = FormatEditorDialog(self, {})
            if dlg.result:
                s    = load_settings()
                fmts = s.get("formats", [])
                fmts.append(dlg.result)
                s["formats"] = fmts
                save_settings(s)
                self._reload_formats_tab()

        def _edit_format(self, fmt: dict):
            dlg = FormatEditorDialog(self, dict(fmt))
            if dlg.result:
                s = load_settings()
                s["formats"] = [
                    dlg.result if f["id"] == fmt["id"] else f
                    for f in s.get("formats", [])
                ]
                save_settings(s)
                self._reload_formats_tab()

        def _delete_format(self, fmt: dict):
            if _askyn(self, "Format löschen",
                      f"Format '{fmt['name']}' wirklich löschen?"):
                s         = load_settings()
                s["formats"] = [f for f in s.get("formats", [])
                                 if f["id"] != fmt["id"]]
                if s.get("active_format") == fmt["id"]:
                    s["active_format"] = "builtin_md"
                save_settings(s)
                self._reload_formats_tab()

        # ── Changelog-Tab ─────────────────────────────────────────────────────

        def _build_changelog_tab(self, frame):
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)

            # Header-Zeile mit Status + Aktualisieren-Button
            hdr = ctk.CTkFrame(frame, fg_color="transparent")
            hdr.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 4))
            hdr.columnconfigure(0, weight=1)
            self._clog_status = tk.StringVar(value="Lade Changelog…")
            ctk.CTkLabel(
                hdr, textvariable=self._clog_status,
                font=ctk.CTkFont(size=11), text_color="gray55", anchor="w",
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkButton(
                hdr, text="↻  Aktualisieren",
                width=120, height=26,
                fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"),
                command=lambda: threading.Thread(
                    target=self._fetch_changelog, daemon=True).start(),
            ).grid(row=0, column=1, sticky="e")

            # Textbox für Release-Notes
            self._clog_box = ctk.CTkTextbox(
                frame,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                fg_color=("gray96", "#141420"),
                text_color=("gray10", "#d4d4d4"),
                corner_radius=6,
                state="disabled",
            )
            self._clog_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

            # Sofort laden
            threading.Thread(target=self._fetch_changelog, daemon=True).start()

        def _fetch_changelog(self):
            """Lädt die letzten 10 Releases von GitHub (Hintergrund-Thread)."""
            import urllib.request as _ureq
            try:
                self.after(0, self._clog_status.set, "Lade Changelog…")
                headers = {
                    "Accept":     "application/vnd.github.v3+json",
                    "User-Agent": f"website-scraper/{APP_VERSION}",
                }
                token = get_api_key("github") or GITHUB_UPDATE_TOKEN
                if token:
                    headers["Authorization"] = f"token {token}"
                req = _ureq.Request(
                    f"{GITHUB_API_BASE}/releases?per_page=10",
                    headers=headers,
                )
                with _ureq.urlopen(req, timeout=10) as resp:
                    releases = json.loads(resp.read())
                self.after(0, self._render_changelog, releases)
            except Exception as exc:
                self.after(0, self._clog_status.set, f"Fehler: {exc}")

        def _render_changelog(self, releases: list):
            _SKIP = {"## What's Changed", "## New Contributors"}
            lines = []
            for r in releases:
                tag  = r.get("tag_name", "")
                name = r.get("name", tag)
                body = (r.get("body") or "").strip()
                pub  = r.get("published_at", "")[:10]
                try:
                    from datetime import datetime
                    pub = datetime.strptime(pub, "%Y-%m-%d").strftime("%d.%m.%Y")
                except Exception:
                    pass
                if lines:
                    lines.append("")
                lines.append(f"  {name}  ·  {pub}")
                lines.append("  " + "─" * 28)
                if body:
                    for line in body.splitlines():
                        if line.strip() in _SKIP:
                            continue
                        if line.startswith("**Full Changelog**"):
                            continue
                        lines.append(f"  {line}")
                else:
                    lines.append("  (keine Beschreibung)")

            text = "\n".join(lines)
            self._clog_box.configure(state="normal")
            self._clog_box.delete("1.0", tk.END)
            self._clog_box.insert("1.0", text)
            self._clog_box.configure(state="disabled")
            self._clog_status.set(
                f"{len(releases)} Releases  ·  aktuellste: "
                f"{releases[0].get('tag_name','') if releases else '–'}"
            )

    # ── Statistik-Dialog ──────────────────────────────────────────────────────

    class StatsDialog(ctk.CTkToplevel):
        def __init__(self, parent):
            super().__init__(parent)
            self.title("Statistik – Zeitersparnis")
            self.geometry("820x500")
            self.minsize(640, 380)
            self.transient(parent)
            self.grab_set()
            self.lift()
            self.focus_force()
            self._build_ui()
            self._load()
            self.wait_window()

        def _build_ui(self):
            self.columnconfigure(0, weight=1)
            self.rowconfigure(2, weight=1)

            ctk.CTkLabel(
                self, text="📊  Zeitersparnis-Statistik",
                font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 8))

            banner = ctk.CTkFrame(self, corner_radius=8,
                                   fg_color=("#d4f5e2", "#0d2b1a"))
            banner.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
            self._total_var = tk.StringVar()
            ctk.CTkLabel(
                banner, textvariable=self._total_var,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=("#1a7a42", "#2ecc86"), anchor="w",
            ).pack(padx=14, pady=10, fill="x")

            self._log_box = ctk.CTkTextbox(
                self,
                font=ctk.CTkFont(family="Consolas", size=10),
                fg_color=("gray96", "#141420"),
                text_color=("gray10", "#d4d4d4"),
                corner_radius=6,
                state="disabled",
            )
            self._log_box.grid(row=2, column=0, sticky="nsew",
                                padx=16, pady=(0, 10))

            btn_row = ctk.CTkFrame(self, fg_color="transparent")
            btn_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
            ctk.CTkButton(
                btn_row, text="🗑  Statistik zurücksetzen",
                command=self._reset,
                fg_color=("gray72", "gray28"),
                hover_color=("#c0392b", "#922b21"),
                text_color=("gray10", "gray90"),
                text_color_disabled=("gray35", "gray65"),
                width=200, height=32,
            ).pack(side="left")
            ctk.CTkButton(
                btn_row, text="Schließen", command=self.destroy,
                width=110, height=32,
                fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"),
            ).pack(side="right")

        def _load(self):
            runs = load_settings().get("runs", [])
            total_saved = sum(r.get("saved_min", 0) for r in runs)
            total_human = sum(r.get("human_min", 0) for r in runs)
            n = len(runs)
            if n:
                self._total_var.set(
                    f"⚡  Gesamt gespart: {_fmt_min(total_saved)}"
                    f"   ·   Manuell wäre es ~{_fmt_min(total_human)} gewesen"
                    f"   ·   {n} {'Lauf' if n == 1 else 'Läufe'}"
                )
            else:
                self._total_var.set("Noch keine Läufe gespeichert.")

            header = (
                f"{'Datum':<18}{'Modus':<10}{'Seiten':>7}  "
                f"{'Manuell':<14}{'Tool':<12}Gespart\n"
                + "─" * 78 + "\n"
            )
            lines = [header]
            for run in reversed(runs):
                mode_lbl = "Sitemap" if run.get("mode") == "sitemap" else "Einzeln"
                line = (
                    f"{run.get('date', ''):<18}{mode_lbl:<10}"
                    f"{run.get('pages', 1):>7}  "
                    f"~{_fmt_min(run.get('human_min', 0)):<13}"
                    f"{_fmt_min(run.get('tool_min', 0)):<12}"
                    f"{_fmt_min(run.get('saved_min', 0))}  "
                    f"({run.get('pct', 0)} %)\n"
                )
                lines.append(line)

            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", tk.END)
            self._log_box.insert("1.0", "".join(lines))
            self._log_box.configure(state="disabled")

        def _reset(self):
            if _askyn(self, "Statistik zurücksetzen",
                      "Alle gespeicherten Läufe löschen?"):
                s = load_settings()
                s["runs"] = []
                save_settings(s)
                self._load()

    # ── Haupt-App ─────────────────────────────────────────────────────────────

    class App(ctk.CTk):
        def __init__(self):
            super().__init__()
            self.title(f"Website Scraper → Markdown  v{APP_VERSION}")
            self.geometry("920x720")
            self.update_idletasks()
            x = (self.winfo_screenwidth()  - 920) // 2
            y = (self.winfo_screenheight() - 720) // 2
            self.geometry(f"920x720+{x}+{y}")
            self.minsize(660, 560)
            self._stop_event = threading.Event()
            self._running = False
            self._build_ui()
            self._load_session()
            # Update-Check nach 3 Sek. (nach vollständigem Fensteraufbau)
            self.after(3000, self._check_update)

        def _build_ui(self):
            self.columnconfigure(0, weight=1)
            self.rowconfigure(1, weight=1)

            # ── Header ────────────────────────────────────────────────────────
            hdr = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray88", "gray14"))
            hdr.grid(row=0, column=0, sticky="ew")
            hdr.columnconfigure(0, weight=1)

            ctk.CTkLabel(
                hdr, text="🌐  Website Scraper → Markdown",
                font=ctk.CTkFont(size=20, weight="bold"), anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=22, pady=(14, 2))
            ctk.CTkLabel(
                hdr,
                text="Extrahiert Webseiten vollständig als strukturierte Markdown-Dateien",
                font=ctk.CTkFont(size=12), text_color="gray55", anchor="w",
            ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 14))
            ctk.CTkButton(
                hdr, text="⚙  Einstellungen", command=self._open_settings,
                width=148, height=34,
            ).grid(row=0, column=1, rowspan=2, padx=(0, 8))
            ctk.CTkButton(
                hdr, text="📊  Statistik", command=self._open_stats,
                width=130, height=34,
            ).grid(row=0, column=2, rowspan=2, padx=(0, 20))

            # ── Content ───────────────────────────────────────────────────────
            cnt = ctk.CTkFrame(self, fg_color="transparent")
            cnt.grid(row=1, column=0, sticky="nsew", padx=18, pady=14)
            cnt.columnconfigure(1, weight=1)

            r = 0

            # Modus-Zeile
            mode_row = ctk.CTkFrame(cnt, fg_color="transparent")
            mode_row.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(0, 6))
            mode_row.columnconfigure(2, weight=1)
            ctk.CTkLabel(mode_row, text="Modus",
                         font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 14))
            self._mode_var = tk.StringVar(value="single")
            ctk.CTkRadioButton(mode_row, text="Einzelne Seite",
                               variable=self._mode_var, value="single",
                               command=self._mode_changed).pack(side="left", padx=(0, 20))
            ctk.CTkRadioButton(mode_row, text="Sitemap  (alle Seiten)",
                               variable=self._mode_var, value="sitemap",
                               command=self._mode_changed).pack(side="left", padx=(0, 20))
            ctk.CTkRadioButton(mode_row, text="EML-Ordner",
                               variable=self._mode_var, value="eml",
                               command=self._mode_changed).pack(side="left")
            self._sim_var = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(mode_row, text="🧪  Simulationsmodus",
                            variable=self._sim_var,
                            command=self._sim_changed).pack(side="right")
            r += 1

            # Simulation-Banner
            self._sim_banner = ctk.CTkLabel(
                cnt,
                text="⚠   SIMULATIONSMODUS AKTIV  –  kein Browser · keine AI-Calls · kein Datenverbrauch",
                fg_color=("#fff3cd", "#3a2c00"),
                text_color=("#7a5c00", "#fbbf24"),
                corner_radius=6,
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w",
            )
            # Nicht initial ins Grid – erst bei Aktivierung einsetzen,
            # da grid()+grid_remove() auf manchen Systemen kurz sichtbar bleibt
            self._sim_banner_row = r
            r += 1

            # URL / EML-Ordner
            self._url_label = ctk.CTkLabel(cnt, text="URL",
                                           font=ctk.CTkFont(weight="bold"), anchor="w")
            self._url_label.grid(row=r, column=0, sticky="w", pady=6)
            self._url_var = tk.StringVar()
            self._url_entry = ctk.CTkEntry(
                cnt, textvariable=self._url_var, height=36,
                placeholder_text="https://example.com/page  oder  https://example.com/sitemap.xml",
            )
            # Entry in Spalte 1 (weight=1, dehnt sich). Spalte 2 bleibt leer und
            # damit 0px breit, solange der Quell-Picker nicht eingeblendet ist –
            # kein columnspan-Wechsel zur Laufzeit nötig (vermeidet Flackern).
            self._url_entry.grid(row=r, column=1, sticky="ew", padx=(10, 6), pady=6)
            # Ordner-Picker für die Quelle – nur im EML-Modus eingeblendet.
            self._url_browse_btn = ctk.CTkButton(cnt, text="…", width=36, height=36,
                                                 command=self._browse_source)
            self._url_row = r
            r += 1

            # Ausgabe
            self._out_label = ctk.CTkLabel(cnt, text="Ausgabedatei",
                                            font=ctk.CTkFont(weight="bold"), anchor="w")
            self._out_label.grid(row=r, column=0, sticky="w", pady=6)
            self._out_var = tk.StringVar()
            ctk.CTkEntry(cnt, textvariable=self._out_var, height=36,
                         placeholder_text="Ausgabepfad (leer = automatisch)").grid(
                row=r, column=1, sticky="ew", padx=(10, 6), pady=6)
            ctk.CTkButton(cnt, text="…", width=36, height=36,
                          command=self._browse_output).grid(row=r, column=2, sticky="w")
            r += 1

            # Buttons
            btn_row = ctk.CTkFrame(cnt, fg_color="transparent")
            btn_row.grid(row=r, column=0, columnspan=3, sticky="w", pady=(2, 10))

            self._start_btn = ctk.CTkButton(
                btn_row, text="▶  Extrahieren", command=self._start,
                width=154, height=38, font=ctk.CTkFont(size=13, weight="bold"),
            )
            self._start_btn.pack(side="left", padx=(0, 8))

            self._stop_btn = ctk.CTkButton(
                btn_row, text="⏹  Abbrechen", command=self._cancel,
                state="disabled", width=134, height=38,
                fg_color=("gray72", "gray28"), hover_color=("gray62", "gray38"),
                text_color=("gray10", "gray90"),
                text_color_disabled=("gray35", "gray65"),
            )
            self._stop_btn.pack(side="left", padx=(0, 8))

            self._open_btn = ctk.CTkButton(
                btn_row, text="📄  Öffnen", command=self._open_file,
                width=110, height=38,
                fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"),
            )
            self._open_btn.pack(side="left")

            # Nur im Sitemap-Modus sichtbar (durch _mode_changed ein-/ausgeblendet);
            # öffnet die _queue.json (offene Restliste) im Ausgabeordner.
            self._queue_btn = ctk.CTkButton(
                btn_row, text="📋  Liste", command=self._open_queue,
                width=104, height=38,
                fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"),
            )
            # Verwirft den gespeicherten Wiederaufnahme-Stand (_queue.json) des Ordners.
            self._discard_btn = ctk.CTkButton(
                btn_row, text="🗑  Verwerfen", command=self._discard_queue,
                width=120, height=38,
                fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"),
            )
            r += 1

            # Fortschritts-Karte
            prog_card = ctk.CTkFrame(cnt, corner_radius=10)
            prog_card.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(0, 10))
            prog_card.columnconfigure(0, weight=1)

            self._prog_bar = ctk.CTkProgressBar(prog_card, height=14, corner_radius=6)
            self._prog_bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
            self._prog_bar.set(0)

            self._status_var = tk.StringVar(value="Bereit.")
            ctk.CTkLabel(
                prog_card, textvariable=self._status_var,
                font=ctk.CTkFont(size=11), text_color="gray55", anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

            # Sitemap-Unterbereich (versteckt bis Sitemap-Modus aktiv)
            self._sep = ctk.CTkFrame(prog_card, height=1, fg_color="gray35")
            self._sep.grid(row=2, column=0, sticky="ew", padx=14)
            self._sep.grid_remove()

            self._sitemap_sub = ctk.CTkFrame(prog_card, fg_color="transparent")
            self._sitemap_sub.grid(row=3, column=0, sticky="ew", padx=14, pady=(6, 12))
            self._sitemap_sub.grid_remove()
            self._sitemap_sub.columnconfigure(0, weight=1)

            sm_info = ctk.CTkFrame(self._sitemap_sub, fg_color="transparent")
            sm_info.grid(row=0, column=0, sticky="ew", pady=(0, 6))
            self._pages_var = tk.StringVar(value="")
            ctk.CTkLabel(sm_info, textvariable=self._pages_var,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            self._avg_var = tk.StringVar(value="")
            ctk.CTkLabel(sm_info, textvariable=self._avg_var,
                         font=ctk.CTkFont(size=11), text_color="gray55").pack(
                side="left", padx=(18, 0))

            self._sitemap_bar = ctk.CTkProgressBar(
                self._sitemap_sub, height=10, corner_radius=4,
                progress_color=("#1a9e5c", "#2ecc86"),
            )
            self._sitemap_bar.grid(row=1, column=0, sticky="ew", pady=(0, 4))
            self._sitemap_bar.set(0)

            self._eta_var = tk.StringVar(value="")
            ctk.CTkLabel(self._sitemap_sub, textvariable=self._eta_var,
                         font=ctk.CTkFont(size=11), text_color="gray55",
                         anchor="w").grid(row=2, column=0, sticky="ew")
            r += 1

            # Savings-Banner (anfangs versteckt, erscheint nach Abschluss)
            self._savings_frame = ctk.CTkFrame(cnt, corner_radius=8,
                                                fg_color=("#d4f5e2", "#0d2b1a"))
            self._savings_frame.grid(row=r, column=0, columnspan=3,
                                      sticky="ew", pady=(0, 8))
            self._savings_frame.grid_remove()
            self._savings_var = tk.StringVar(value="")
            ctk.CTkLabel(
                self._savings_frame, textvariable=self._savings_var,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("#1a7a42", "#2ecc86"), anchor="w",
            ).pack(padx=14, pady=8, fill="x")
            r += 1

            # Log-Karte
            log_card = ctk.CTkFrame(cnt, corner_radius=10)
            log_card.grid(row=r, column=0, columnspan=3, sticky="nsew")
            log_card.columnconfigure(0, weight=1)
            log_card.rowconfigure(1, weight=1)
            cnt.rowconfigure(r, weight=1)

            ctk.CTkLabel(
                log_card, text="Protokoll",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray50", anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))

            self._log_box = ctk.CTkTextbox(
                log_card,
                font=ctk.CTkFont(family="Consolas", size=10),
                fg_color=("gray96", "#141420"),
                text_color=("gray10", "#d4d4d4"),
                corner_radius=6,
            )
            self._log_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))

        # ── Simulationsmodus ──────────────────────────────────────────────────

        def _sim_changed(self):
            if self._sim_var.get():
                self._sim_banner.grid(
                    row=self._sim_banner_row, column=0, columnspan=3,
                    sticky="ew", pady=(0, 8),
                )
            else:
                self._sim_banner.grid_remove()

        # ── Modus-Wechsel ─────────────────────────────────────────────────────

        def _mode_changed(self):
            mode = self._mode_var.get()
            prev = getattr(self, "_prev_mode", "single")
            if mode in ("sitemap", "eml"):
                self._out_label.configure(text="Ausgabeordner")
                self._open_btn.configure(text="📁  Öffnen")
                self._sep.grid()
                self._sitemap_sub.grid()
                self._queue_btn.pack(side="left", padx=(8, 0))
                self._discard_btn.pack(side="left", padx=(8, 0))
            else:
                self._out_label.configure(text="Ausgabedatei")
                self._open_btn.configure(text="📄  Öffnen")
                self._sep.grid_remove()
                self._sitemap_sub.grid_remove()
                self._queue_btn.pack_forget()
                self._discard_btn.pack_forget()

            # Eingabe-Zeile: EML-Modus = Quellordner mit Picker, sonst URL.
            if mode == "eml":
                self._url_label.configure(text="EML-Ordner")
                self._url_entry.configure(placeholder_text="Ordner mit .eml-Dateien")
                self._url_browse_btn.grid(row=self._url_row, column=2, sticky="w")
            else:
                self._url_label.configure(text="URL")
                self._url_entry.configure(
                    placeholder_text="https://example.com/page  oder  https://example.com/sitemap.xml")
                self._url_browse_btn.grid_remove()

            # Eingabewert nur beim Wechsel über die Web↔EML-Grenze tauschen
            # (single↔sitemap teilen sich die Web-URL und bleiben unverändert).
            if mode == "eml" and prev != "eml":
                self._url_web_cache = self._url_var.get()
                self._url_var.set(load_settings().get("last_source_eml", ""))
            elif mode != "eml" and prev == "eml":
                self._url_var.set(getattr(self, "_url_web_cache",
                                          load_settings().get("last_url", "")))
            self._prev_mode = mode

            # Zuletzt genutzten Ausgabepfad pro Modus wiederherstellen.
            self._out_var.set(load_settings().get(f"last_output_{mode}", ""))

        # ── UI-Helfer ─────────────────────────────────────────────────────────

        def _browse_output(self):
            if self._mode_var.get() in ("sitemap", "eml"):
                f = filedialog.askdirectory(title="Ausgabeordner wählen")
            else:
                fmt  = get_active_format()
                ext  = fmt.get("extension", ".md")
                name = fmt.get("name", "Markdown")
                f = filedialog.asksaveasfilename(
                    defaultextension=ext,
                    filetypes=[(name, f"*{ext}"), ("Alle Dateien", "*.*")],
                    title="Ausgabedatei wählen",
                )
            if f:
                self._out_var.set(f)

        def _browse_source(self):
            """Quellordner mit .eml-Dateien wählen (nur EML-Modus)."""
            f = filedialog.askdirectory(title="Ordner mit .eml-Dateien wählen")
            if f:
                self._url_var.set(f)

        def _open_file(self):
            p = self._out_var.get()
            if not p:
                _showmsg(self, "Hinweis", "Kein Ausgabepfad angegeben.")
                return
            path = Path(p)
            if path.exists():
                self._open_or_reveal(str(path))
            else:
                _showmsg(self, "Hinweis", "Datei/Ordner nicht gefunden.")

        @staticmethod
        def _open_or_reveal(p: str):
            path = str(Path(p))
            try:
                os.startfile(path)
            except OSError:
                subprocess.Popen(["explorer", "/select,", path])

        def _queue_filename(self) -> str:
            """Listen-Dateiname je nach Modus (EML hat ein eigenes, dauerhaftes)."""
            return EML_QUEUE_FILENAME if self._mode_var.get() == "eml" else QUEUE_FILENAME

        def _open_queue(self):
            out = self._out_var.get().strip()
            if not out:
                _showmsg(self, "Hinweis", "Kein Ausgabeordner angegeben.")
                return
            qp = _queue_path(out, self._queue_filename())
            if not qp.exists():
                _showmsg(self, "Hinweis", "Keine offene Liste vorhanden.")
                return
            self._open_or_reveal(str(qp))

        def _discard_queue(self):
            if self._running:
                _showmsg(self, "Hinweis",
                         "Während eines laufenden Vorgangs nicht möglich.")
                return
            out = self._out_var.get().strip()
            if not out:
                _showmsg(self, "Hinweis", "Kein Ausgabeordner angegeben.")
                return
            qp = _queue_path(out, self._queue_filename())
            if not qp.exists():
                _showmsg(self, "Hinweis", "Keine offene Liste vorhanden.")
                return
            if _askyn(
                self, "Lauf verwerfen",
                "Den gespeicherten Wiederaufnahme-Stand für diesen Ordner verwerfen?\n\n"
                "Bereits erzeugte Dateien bleiben erhalten – nur die Restliste "
                "wird gelöscht.",
            ):
                _delete_queue(out, self._queue_filename())
                self._log_ui("Wiederaufnahme-Stand verworfen.")
                _showmsg(self, "Verworfen", "Die offene Liste wurde gelöscht.")

        def _open_settings(self):
            SettingsDialog(self)

        def _open_stats(self):
            StatsDialog(self)

        # ── Update-Check ──────────────────────────────────────────────────────

        def _check_update(self):
            """Startet den Update-Check im Hintergrund (kein UI-Block)."""
            # Token optional – bei public Repo nicht nötig; private Repo braucht ihn
            token = get_api_key("github") or GITHUB_UPDATE_TOKEN
            threading.Thread(target=self._check_update_bg,
                             args=(token,), daemon=True).start()

        def _check_update_bg(self, token: str):
            try:
                result = _check_for_update(token)
                if result:
                    self.after(0, self._offer_update, *result)
            except Exception:
                pass  # Kein Netz, kein Token, kein Release → still ignorieren

        def _offer_update(self, new_ver: str, asset_url: str):
            if self._running:
                return  # Kein Update während einer laufenden Extraktion
            if _askyn(
                self, "Update verfügbar",
                f"Version {new_ver} ist verfügbar  (aktuell: {APP_VERSION})\n\n"
                "Die App wird aktualisiert, kurz neu gestartet und ist dann\n"
                "sofort einsatzbereit. Jetzt aktualisieren?",
            ):
                self._run_update(new_ver, asset_url)

        def _run_update(self, new_ver: str, asset_url: str):
            token = get_api_key("github") or GITHUB_UPDATE_TOKEN
            try:
                self._status_var.set(f"Lade Version {new_ver} herunter…")
                self.update_idletasks()
                data    = _download_update(token, asset_url)
                script  = Path(__file__).resolve()
                tmp     = script.with_name("website_scraper.new.py")
                updater = script.with_name("_ws_updater.py")
                tmp.write_bytes(data)
                # repr(str(...)) macht Pfade mit Leerzeichen + Sonderzeichen sicher
                updater.write_text(
                    "import time, sys, subprocess\n"
                    "from pathlib import Path\n"
                    "time.sleep(2)\n"
                    f"Path({repr(str(tmp))}).replace(Path({repr(str(script))}))\n"
                    f"subprocess.Popen([sys.executable, {repr(str(script))}])\n"
                    f"Path({repr(str(updater))}).unlink(missing_ok=True)\n",
                    encoding="utf-8",
                )
                # pythonw.exe → kein Konsolenfenster; DETACHED → unabhängig vom Parent
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                interp  = str(pythonw) if pythonw.exists() else sys.executable
                flags   = (getattr(subprocess, "DETACHED_PROCESS", 0) |
                           getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                subprocess.Popen([interp, str(updater)], creationflags=flags)
                self.destroy()
            except Exception as exc:
                _showmsg(self, "Update fehlgeschlagen", str(exc))

        def _show_savings(self, human_min: float, tool_secs: float):
            tool_min = tool_secs / 60
            saved_min = max(0.0, human_min - tool_min)
            pct = int(saved_min / max(human_min, 0.01) * 100)
            self._savings_var.set(
                f"⚡  Ein Mensch hätte ~{_fmt_min(human_min)} benötigt  ·  "
                f"Tool-Laufzeit: {_fmt_min(tool_min)}  ·  "
                f"Zeitersparnis: {pct} %"
            )
            self._savings_frame.grid()

        def _load_session(self):
            s = load_settings()
            self._url_var.set(s.get("last_url", ""))
            mode = s.get("last_mode", "single")
            self._mode_var.set(mode)
            self._mode_changed()   # stellt _out_var aus last_output_{mode} wieder her
            # Simulationsmodus immer deaktiviert starten (nie persistieren)
            self._sim_var.set(False)

        def _save_session(self):
            s = load_settings()
            mode = self._mode_var.get()
            s["last_mode"] = mode
            s[f"last_output_{mode}"] = self._out_var.get()
            if mode == "eml":
                # Quellordner separat – die Web-URL (last_url) nicht mit einem
                # Dateipfad überschreiben.
                s["last_source_eml"] = self._url_var.get()
            else:
                s["last_url"] = self._url_var.get()
            save_settings(s)

        # ── Logging / Fortschritt (thread-sicher) ─────────────────────────────

        def _log(self, msg: str):
            self.after(0, self._log_ui, msg)

        def _log_ui(self, msg: str):
            self._log_box.insert(tk.END, msg + "\n")
            self._log_box.see(tk.END)
            self._status_var.set(msg[:120])

        def _set_progress(self, v: float):
            def _do():
                self._prog_bar.set(v / 100.0)
                self._prog_bar.update_idletasks()
            self.after(0, _do)

        # ── Sitemap-Fortschritt (thread-sicher) ───────────────────────────────

        def _update_sitemap_progress(self, done: int, total: int, page_times: list,
                                     unit: str = "Seite"):
            pct = done / max(total, 1)
            self._sitemap_bar.set(pct)
            self._pages_var.set(f"{unit} {done} von {total}   ({pct * 100:.0f} %)")
            if page_times:
                avg = sum(page_times) / len(page_times)
                remaining_secs = (total - done) * avg
                h, rem = divmod(int(remaining_secs), 3600)
                m, s = divmod(rem, 60)
                if h:
                    eta_txt = f"Noch ca. {h} Std {m:02d} min {s:02d} sek"
                elif m:
                    eta_txt = f"Noch ca. {m} min {s:02d} sek"
                else:
                    eta_txt = f"Noch ca. {s} sek"
                self._eta_var.set(eta_txt)
                self._avg_var.set(f"  ·  Ø {avg:.0f} Sek / {unit}")
            else:
                self._eta_var.set("Berechne geschätzte Restzeit…")
                self._avg_var.set("")

        # ── Extraktion starten / abbrechen ────────────────────────────────────

        def _start(self):
            if self._running:
                return
            url = self._url_var.get().strip()
            mode = self._mode_var.get()
            if not url:
                _showmsg(self, "Hinweis",
                         "Bitte einen Ordner mit .eml-Dateien wählen." if mode == "eml"
                         else "Bitte URL eingeben.")
                return
            # Web-Modi: fehlendes Schema ergänzen. EML-Modus: url ist ein
            # Ordnerpfad → NICHT mit https:// präfixen.
            if mode != "eml" and not url.startswith("http"):
                url = "https://" + url
                self._url_var.set(url)

            output = self._out_var.get().strip()
            settings = load_settings()
            settings["simulate"] = self._sim_var.get()
            describe = settings.get("describe_images", True)
            active_fmt = get_active_format()

            if describe and not settings["simulate"] and not get_api_key("claude"):
                if not _askyn(
                    self, "Kein API-Key",
                    "Kein Anthropic API-Key konfiguriert.\n"
                    "Bilder werden ohne AI-Beschreibung dokumentiert.\n\n"
                    "Trotzdem fortfahren?",
                ):
                    return

            resume = False
            if mode == "eml":
                if not Path(url).is_dir():
                    _showmsg(self, "Fehler",
                             "Der angegebene Quellordner existiert nicht:\n" + url)
                    return
                if not output:
                    stem = re.sub(r"[^\w\-]", "_", Path(url).name) or "eml"
                    output = str(Path.home() / "Documents" / f"{stem}_eml")
                    self._out_var.set(output)
                try:
                    Path(output).mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    _showmsg(self, "Fehler",
                             f"Ausgabeordner konnte nicht angelegt werden:\n{exc}")
                    return
                # Kein Resume-Dialog: das dauerhafte Ledger setzt inkrementell fort.
            elif mode == "sitemap":
                if not output:
                    parsed = urlparse(url)
                    stem = re.sub(r"[^\w\-]", "_", parsed.netloc)
                    output = str(Path.home() / "Documents" / stem)
                    self._out_var.set(output)
                try:
                    Path(output).mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    _showmsg(self, "Fehler",
                             f"Ausgabeordner konnte nicht angelegt werden:\n{exc}")
                    return

                # Unterbrochenen Lauf erkennen und ggf. fortsetzen (vor jeder
                # State-Mutation – ein versehentliches Schließen darf nichts ändern).
                q = _load_queue(output, self._log_ui)
                if (q and q.get("sitemap_url") == url
                        and q.get("format_ext") == active_fmt.get("extension", ".md")
                        and 0 < len(q["done"]) < len(q["all_urls"])):
                    ans = _MsgBox(
                        self, "Unterbrochener Lauf",
                        f"{len(q['done'])} von {len(q['all_urls'])} Seiten in diesem "
                        f"Ordner sind bereits erledigt.\n\n"
                        f"Lauf fortsetzen?\n(Nein = neu starten)",
                        "yesno",
                    ).result
                    if ans is None:
                        return            # Dialog geschlossen → Start abbrechen, nichts verändern
                    resume = bool(ans)    # True = fortsetzen, False = neu starten
            else:
                if not output:
                    parsed = urlparse(url)
                    stem = re.sub(r"[^\w\-.]", "_", parsed.netloc + parsed.path).strip("_")
                    ext = active_fmt.get("extension", ".md")
                    output = str(Path.home() / "Documents" / f"{stem[:80]}{ext}")
                    self._out_var.set(output)

            self._save_session()
            self._run_start = time.time()
            self._last_url  = url
            self._last_fmt  = active_fmt
            self._savings_frame.grid_remove()
            self._savings_var.set("")
            self._stop_event.clear()
            self._running = True
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._prog_bar.set(0)
            self._log_box.delete("1.0", tk.END)

            if mode == "sitemap":
                self._pages_var.set("Lade Sitemap…")
                self._eta_var.set("")
                self._avg_var.set("")
                self._sitemap_bar.set(0)
                threading.Thread(target=self._worker_sitemap,
                                 args=(url, output, settings, resume), daemon=True).start()
            elif mode == "eml":
                self._pages_var.set("Lese Ordner…")
                self._eta_var.set("")
                self._avg_var.set("")
                self._sitemap_bar.set(0)
                threading.Thread(target=self._worker_eml,
                                 args=(url, output, settings), daemon=True).start()
            else:
                threading.Thread(target=self._worker,
                                 args=(url, output, settings), daemon=True).start()

        def _cancel(self):
            if self._running:
                self._stop_event.set()
                self._log_ui("Abbruch angefordert…")

        # ── Worker: Einzelseite ───────────────────────────────────────────────

        def _worker(self, url: str, output: str, settings: dict):
            try:
                fmt = get_active_format()
                scraper = Scraper(settings=settings, log_fn=self._log,
                                  progress_fn=self._set_progress,
                                  stop_event=self._stop_event)
                scraper.run(url, output, output_format=fmt)
                if not self._stop_event.is_set():
                    self.after(0, self._done, output)
                else:
                    self.after(0, self._cancelled)
            except Exception as exc:
                import traceback
                self._log(f"FEHLER: {exc}\n{traceback.format_exc()}")
                self.after(0, self._on_error, str(exc))

        # ── Worker: Sitemap ───────────────────────────────────────────────────

        def _worker_sitemap(self, sitemap_url: str, output_dir: str,
                            settings: dict, resume: bool = False):
            try:
                out_path = Path(output_dir)
                fmt      = get_active_format()
                fmt_ext  = fmt.get("extension", ".md")

                self._log(f"Verarbeite Sitemap: {sitemap_url}")
                try:
                    urls = list(dict.fromkeys(_fetch_sitemap_urls(sitemap_url, self._log)))
                except Exception as exc:
                    self._log(f"Sitemap konnte nicht geladen werden: {exc}")
                    urls = []

                # Offline-Fallback: bei Wiederaufnahme die gespeicherte Liste nutzen,
                # falls der frische Fetch leer/fehlerhaft war.
                q = _load_queue(output_dir, self._log) if resume else None
                if not urls and q:
                    urls = q["all_urls"]
                    self._log("Verwende gespeicherte Liste aus der Wiederaufnahme.")

                if self._stop_event.is_set():
                    self.after(0, self._cancelled)
                    return
                total = len(urls)
                if total == 0:
                    self.after(0, self._on_error,
                        "Keine URLs in der Sitemap gefunden.\n\n"
                        "Tipps:\n• URL direkt zur sitemap.xml angeben\n"
                        "• Manche Seiten haben /sitemap_index.xml")
                    return

                done = set(q["done"]) & set(urls) if q else set()
                self._log(f"Sitemap geladen: {total} Seiten gefunden"
                          + (f" · {len(done)} bereits erledigt (Wiederaufnahme)" if done else ""))

                def _save_state():
                    _write_queue_atomic(output_dir, {
                        "schema_version": QUEUE_SCHEMA,
                        "sitemap_url": sitemap_url,
                        "format_ext": fmt_ext,
                        "created": time.strftime("%Y-%m-%d %H:%M"),
                        "all_urls": urls,
                        "done": [u for u in urls if u in done],
                    }, self._log)

                # "Im Hintergrund aufrufbare Liste" sofort persistieren.
                _save_state()

                page_times: list = []
                # Einmaliger Initial-Push (erledigte als Startoffset); Skips lösen
                # danach keine weiteren UI-Updates aus (verhindert GUI-Fluten).
                self.after(0, self._update_sitemap_progress, len(done), total, page_times)

                for i, url in enumerate(urls):
                    if self._stop_event.is_set():
                        break
                    if url in done:
                        continue
                    self._log(f"\n[{i + 1}/{total}] {url}")
                    self._set_progress(0)
                    file_path = str(out_path / _url_to_filename(url, fmt_ext))
                    t0 = time.time()
                    try:
                        scraper = Scraper(settings=settings, log_fn=self._log,
                                          progress_fn=self._set_progress,
                                          stop_event=self._stop_event)
                        scraper.run(url, file_path, output_format=fmt)
                    except Exception as exc:
                        self._log(f"  FEHLER: {exc}")
                        continue   # bleibt pending → Retry bei Wiederaufnahme
                    # Scraper.run bricht bei Stop still ab (kein write_text, keine
                    # Exception) → erst NACH dem Stop-Check als erledigt markieren.
                    if self._stop_event.is_set():
                        break
                    done.add(url)
                    page_times.append(time.time() - t0)
                    self.after(0, self._update_sitemap_progress, len(done), total, page_times)
                    _save_state()

                self.after(0, self._update_sitemap_progress, len(done), total, page_times)
                if not self._stop_event.is_set():
                    failed = [u for u in urls if u not in done]
                    md_paths = [str(out_path / _url_to_filename(u, fmt_ext))
                                for u in urls if u in done]
                    try:
                        self._write_index(out_path, sitemap_url, urls, failed,
                                          page_times, ext=fmt_ext)
                    except Exception as exc:
                        self._log(f"Index-Fehler (ignoriert): {exc}")
                    _delete_queue(output_dir)   # durchgelaufen → fertig
                    self.after(0, self._done_sitemap,
                               output_dir, total, failed, page_times, md_paths)
                else:
                    self.after(0, self._cancelled)   # Queue bleibt erhalten → Wiederaufnahme
            except Exception as exc:
                import traceback
                self._log(f"FEHLER: {exc}\n{traceback.format_exc()}")
                self.after(0, self._on_error, str(exc))

        def _write_index(self, out_path: Path, sitemap_url: str,
                         urls: list, failed: list, page_times: list,
                         ext: str = ".md"):
            avg = sum(page_times) / len(page_times) if page_times else 0
            total_min = sum(page_times) / 60 if page_times else 0
            ok = len(urls) - len(failed)
            failed_set = set(failed)
            lines = [
                "# Sitemap-Extraktion", "",
                f"**Quelle:** {sitemap_url}  ",
                f"**Datum:** {time.strftime('%d.%m.%Y %H:%M')}  ",
                f"**Ergebnis:** {ok} von {len(urls)} Seiten erfolgreich  ",
                f"**Dauer:** {total_min:.1f} min  ·  Ø {avg:.0f} Sek/Seite",
                "", "## Seiten", "",
            ]
            for url in urls:
                fn = _url_to_filename(url, ext)
                if url in failed_set:
                    lines.append(f"- ~~[{url}]({fn})~~ *(fehlgeschlagen)*")
                else:
                    lines.append(f"- [{url}]({fn})")
            # Zeitersparnis-Tabelle
            try:
                md_paths = [str(out_path / _url_to_filename(u, ext))
                            for u in urls if u not in failed_set]
                human_min, total_words, total_images = _estimate_human_time(md_paths)
                saved_min = max(0.0, human_min - total_min)
                pct = int(saved_min / max(human_min, 0.01) * 100)
                lines += [
                    "", "---", "", "## ⚡ Zeitersparnis", "",
                    "| | Zeit |",
                    "|---|---|",
                    f"| 👤 Menschliche Bearbeitungszeit (geschätzt) | ~{_fmt_min(human_min)} |",
                    f"| 🤖 Tool-Laufzeit | {_fmt_min(total_min)} |",
                    f"| ⚡ Gespart | ~{_fmt_min(saved_min)} **(−{pct} %)** |",
                    "",
                    f"_Basis: {total_words:,} Inhaltswörter · {total_images} Bilder · "
                    f"3 Min Basis + 1 Min/100 Wörter + 2,5 Min/Bild_",
                ]
            except Exception:
                pass
            try:
                idx = out_path / "_index.md"
                idx.write_text("\n".join(lines), encoding="utf-8")
                self._log(f"\nIndex erstellt: {idx}")
            except Exception as exc:
                self._log(f"Index-Fehler: {exc}")

        # ── Worker: EML-Ordner ────────────────────────────────────────────────

        def _worker_eml(self, source_dir: str, output_dir: str, settings: dict):
            try:
                out_path = Path(output_dir)
                fmt      = get_active_format()
                fmt_ext  = fmt.get("extension", ".md")

                self._log(f"Verarbeite EML-Ordner: {source_dir}")
                files = sorted(Path(source_dir).glob("*.eml"))
                names = [f.name for f in files]
                total = len(names)
                if total == 0:
                    self.after(0, self._on_error,
                               "Keine .eml-Dateien im gewählten Ordner gefunden.")
                    return

                # Dauerhaftes Ledger laden (nur bei passendem Ordner + Format).
                q = _load_queue(output_dir, self._log, filename=EML_QUEUE_FILENAME)
                done = set()
                if q and q.get("source_dir") == source_dir and q.get("format_ext") == fmt_ext:
                    done = set(q["done"]) & set(names)
                # Ergänzung: bereits vorhandene Ausgabedateien gelten als erledigt
                # (robust, falls das Ledger verloren ging/gelöscht wurde).
                for f in files:
                    if (out_path / _eml_to_filename(f, fmt_ext)).exists():
                        done.add(f.name)
                initial_done = len(done)

                def _save_state():
                    _write_queue_atomic(output_dir, {
                        "schema_version": QUEUE_SCHEMA,
                        "source_dir": source_dir,
                        "format_ext": fmt_ext,
                        "created": (q or {}).get("created", time.strftime("%Y-%m-%d %H:%M")),
                        "updated": time.strftime("%Y-%m-%d %H:%M"),
                        # all_urls/done tragen hier Dateinamen (siehe _load_queue-Doku).
                        "all_urls": names,
                        "done": [n for n in names if n in done],
                    }, self._log, filename=EML_QUEUE_FILENAME)

                _save_state()
                self._log(f"{total} .eml gefunden"
                          + (f" · {initial_done} bereits erledigt" if initial_done else ""))

                page_times: list = []
                self.after(0, self._update_sitemap_progress,
                           len(done), total, page_times, "Datei")

                for i, f in enumerate(files):
                    if self._stop_event.is_set():
                        break
                    if f.name in done:
                        continue
                    self._log(f"\n[{i + 1}/{total}] {f.name}")
                    self._set_progress(0)
                    file_path = str(out_path / _eml_to_filename(f, fmt_ext))
                    t0 = time.time()
                    try:
                        scraper = Scraper(settings=settings, log_fn=self._log,
                                          progress_fn=self._set_progress,
                                          stop_event=self._stop_event)
                        scraper.run_eml(str(f), file_path, output_format=fmt)
                    except Exception as exc:
                        self._log(f"  FEHLER: {exc}")
                        continue   # bleibt pending → Retry beim nächsten Lauf
                    if self._stop_event.is_set():
                        break
                    done.add(f.name)
                    page_times.append(time.time() - t0)
                    self.after(0, self._update_sitemap_progress,
                               len(done), total, page_times, "Datei")
                    _save_state()

                self.after(0, self._update_sitemap_progress,
                           len(done), total, page_times, "Datei")
                if not self._stop_event.is_set():
                    failed = [n for n in names if n not in done]
                    md_paths = [str(out_path / _eml_to_filename(f, fmt_ext))
                                for f in files if f.name in done]
                    _save_state()   # finalen Stand sichern – Ledger NICHT löschen (dauerhaft)
                    self.after(0, self._done_eml, output_dir, total, initial_done,
                               failed, page_times, md_paths)
                else:
                    self.after(0, self._cancelled)   # Ledger bleibt → Wiederaufnahme
            except Exception as exc:
                import traceback
                self._log(f"FEHLER: {exc}\n{traceback.format_exc()}")
                self.after(0, self._on_error, str(exc))

        # ── Fertig-Handler ────────────────────────────────────────────────────

        def _done(self, output: str):
            self._running = False
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._prog_bar.set(1.0)
            human_min, nwords, nimages = _estimate_human_time([output])
            self._log(f"[Zeitschätzung] {nwords} Inhaltswörter · {nimages} Bilder → {human_min:.1f} Min")
            tool_secs = time.time() - getattr(self, "_run_start", time.time())
            tool_min = tool_secs / 60
            saved_min = max(0.0, human_min - tool_min)
            pct = int(saved_min / max(human_min, 0.01) * 100)
            self._show_savings(human_min, tool_secs)
            _save_run(getattr(self, "_last_url", ""), "single", 1,
                      tool_min, human_min)
            fmt_name = getattr(self, "_last_fmt", {}).get("name", "Markdown")
            if _askyn(
                self, "Fertig!",
                f"{fmt_name}-Datei gespeichert:\n{output}\n\n"
                f"⚡  Zeitersparnis: ~{_fmt_min(saved_min)} ({pct} %)\n"
                f"   Manuell: ~{_fmt_min(human_min)}  ·  Tool: {_fmt_min(tool_min)}\n\n"
                f"Jetzt öffnen?",
            ):
                self._open_or_reveal(output)

        def _done_sitemap(self, output_dir: str, total: int,
                          failed_urls: list, page_times: list, md_paths: list):
            self._running = False
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._prog_bar.set(1.0)
            self._sitemap_bar.set(1.0)
            failed = len(failed_urls)
            ok = total - failed
            avg = sum(page_times) / len(page_times) if page_times else 0
            tool_min_total = sum(page_times) / 60 if page_times else 0
            human_min, _, _ = _estimate_human_time(md_paths)
            tool_secs = sum(page_times)
            saved_min = max(0.0, human_min - tool_min_total)
            pct = int(saved_min / max(human_min, 0.01) * 100)
            self._pages_var.set(f"Seite {total} von {total}   (100 %)")
            self._eta_var.set(f"Fertig!  {ok} von {total} Seiten erfolgreich.")
            self._avg_var.set(f"  ·  Ø {avg:.0f} Sek / Seite")
            self._show_savings(human_min, tool_secs)
            _save_run(getattr(self, "_last_url", ""), "sitemap", ok,
                      tool_min_total, human_min)
            summary = (
                f"Sitemap-Extraktion abgeschlossen!\n\n"
                f"✅  {ok} Seiten erfolgreich\n"
                + (f"❌  {failed} Fehler\n" if failed else "")
                + f"\n⏱  Gesamt: {tool_min_total:.1f} min  ·  Ø {avg:.0f} Sek/Seite\n"
                f"\n⚡  Zeitersparnis: ~{_fmt_min(saved_min)} ({pct} %)\n"
                f"   Manuell: ~{_fmt_min(human_min)}  ·  Tool: {_fmt_min(tool_min_total)}\n"
                f"\n📁  {output_dir}"
            )
            if _askyn(self, "Fertig!", summary + "\n\nOrdner öffnen?"):
                self._open_or_reveal(output_dir)

        def _done_eml(self, output_dir: str, total: int, skipped: int,
                      failed_names: list, page_times: list, md_paths: list):
            self._running = False
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._prog_bar.set(1.0)
            self._sitemap_bar.set(1.0)
            failed = len(failed_names)
            new = max(0, total - skipped - failed)
            avg = sum(page_times) / len(page_times) if page_times else 0
            tool_min_total = sum(page_times) / 60 if page_times else 0
            human_min, _, _ = _estimate_human_time(md_paths)
            tool_secs = sum(page_times)
            saved_min = max(0.0, human_min - tool_min_total)
            pct = int(saved_min / max(human_min, 0.01) * 100)
            self._pages_var.set(f"Datei {total - failed} von {total}")
            self._eta_var.set(
                f"Fertig!  {new} neu · {skipped} übersprungen"
                + (f" · {failed} fehlgeschlagen" if failed else ""))
            self._avg_var.set(f"  ·  Ø {avg:.0f} Sek / Datei" if page_times else "")
            if page_times:
                self._show_savings(human_min, tool_secs)
            _save_run(getattr(self, "_last_url", ""), "eml", new,
                      tool_min_total, human_min)
            summary = (
                f"EML-Umwandlung abgeschlossen!\n\n"
                f"✅  {new} neu umgewandelt\n"
                f"⏭  {skipped} bereits erledigt (übersprungen)\n"
                + (f"❌  {failed} fehlgeschlagen – werden beim nächsten Lauf "
                   f"erneut versucht\n" if failed else "")
                + f"\n📁  {output_dir}"
            )
            if _askyn(self, "Fertig!", summary + "\n\nOrdner öffnen?"):
                self._open_or_reveal(output_dir)

        def _cancelled(self):
            self._running = False
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._status_var.set("Abgebrochen.")

        def _on_error(self, msg: str):
            self._running = False
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            _showmsg(self, "Fehler", f"Extraktion fehlgeschlagen:\n\n{msg}")

    App().mainloop()
