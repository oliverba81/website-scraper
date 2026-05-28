# COPILOT_SPEC.md — Rebuild der Website-Scraper Desktop-App (Python, Windows)

## 1) Aufgabenstellung (Eröffnungs-Prompt an Copilot)

Du bist ein erfahrener Python-Entwickler mit Fokus auf robuste Desktop-Apps, Web-Automation und sauberer Architektur.

Deine Aufgabe ist es, eine bestehende Website-Scraper-Anwendung **vollständig neu** als **einzelnes Python-Skript** zu implementieren:

- Ziel-Datei: `website_scraper.py`
- Zielplattform: Windows 10/11
- Python-Version: 3.10+

Wichtige Vorgaben:

1. **Framework-Wahl triffst du selbst**: Wähle **genau eines** aus
   - PyQt6
   - PySide6
   - CustomTkinter

   Begründe die Wahl kurz (2–5 Sätze) und verwende danach ausschließlich dieses Framework konsistent.

2. **UI/UX-Design entwirfst du komplett selbst**:
   - Layout
   - Farbwelt
   - Icons/Symbole
   - Dark-/Light-Theme-Entscheidung

3. **Nicht kopieren / nicht übernehmen**:
   - Kein tkinter
   - Kein altes Layout
   - Keine 1:1-Übernahme alter UI-Strukturen

4. **Funktionsgleichheit ist Pflicht**:
   - Alle in dieser Spezifikation genannten Features vollständig umsetzen.

5. **Lieferform**:
   - Eine einzelne Datei `website_scraper.py`
   - Keine zusätzlichen Unterordner/Packages im Projekt

---

## 2) Funktionale Anforderungen (vollständig und verbindlich)

## 2.1 Betriebsmodi

### A) Einzelseite
- Input: eine URL
- Output: genau eine Markdown-Datei (`.md`)

### B) Sitemap-Modus
- Input: Sitemap-URL
- Output:
  - ein Ausgabeverzeichnis
  - pro Seite eine eigene `.md`
  - zusätzlich `_index.md` als Übersicht

### C) Simulationsmodus
- Zweck: UI-/Workflow-Test ohne echte Web- oder KI-Abhängigkeiten
- Regeln:
  - **kein Browser-Start**
  - **keine KI-API-Calls**
  - Erzeuge Dummy-Markdown
  - künstliche Seitenlaufzeit je Seite: **0,8 bis 2,5 Sekunden**
- Der Modus muss Fortschritt, ETA und Dateistruktur realistisch testen.

---

## 2.2 Browser-Automatisierung (Playwright, Sync API)

Verwende Playwright **Sync API** mit Chromium.

Pflichtverhalten:
- Headless konfigurierbar (UI-Option)
- Seitenaufruf mit:
  - `wait_until="domcontentloaded"`
  - danach zusätzlich **2 Sekunden Pause**
- Vollständiges Scrollen bis Seitenende:
  - wiederholt scrollen, bis `scrollHeight` stabil bleibt
  - maximal **40 Iterationen**, dann Abbruch der Scroll-Schleife

Bilddownload muss über Browser-Kontext laufen (für Auth/Cookies):
- **verwende `ctx.request.get()`**
- **nicht** `page.request.get()`

Lazy-Load-Bilder robust erkennen über:
- `img.complete`
- `currentSrc`
- `data-src`
- `data-lazy-src`
- `srcset`-Fallback

Bildfilter:
- Mindestgröße: **30 × 30 px**
- SVG überspringen
- erlaubte MIME-Typen:
  - `image/png`
  - `image/jpeg`
  - `image/webp`
  - `image/gif`

---

## 2.3 HTML → Markdown (BeautifulSoup + lxml)

Parser:
- BeautifulSoup mit `lxml`

Content-Root-Erkennung in folgender Priorität:
1. `<main>`
2. `<article>`
3. id/class per Regex auf typische Content-Muster
4. fallback: `<body>`

Zu konvertierende Elemente:
- Überschriften `h1`–`h6`
- `p`
- `ul`/`ol` inkl. Verschachtelung
- `table` → Markdown-Tabelle
- `blockquote`
- `pre`/`code` inkl. Sprachklasse
- `a` mit absoluten URLs
- Inline: `strong`, `em`, `del`, `code`
- `figure`/`figcaption`
- `details`/`summary`
- `hr`
- `iframe` → als Link darstellen

Admonition-ähnliche Divs (z. B. Klassen mit):
- `note`, `tip`, `warning`, `caution`, `danger`, `info`, `hint`, `alert`, `callout`

müssen als Blockquote in Markdown erscheinen.

Zu ignorieren/überspringen:
- `script`
- `style`
- `noscript`
- `svg`
- `template`
- `nav`
- `footer`

Bildblöcke im Markdown-Output:
- Format:
  - `> 📷 **Screenshot: [Label]**`
  - darunter die KI-Beschreibung als Quote-Text

---

## 2.4 KI-Bildbeschreibung

Unterstützte Provider:
- OpenAI (GPT-4o)
- Google Gemini (`google-genai` SDK, `genai.Client`)

Auswahl des Providers in den Einstellungen.

### OpenAI-Anforderung
- API-Aufruf über `client.chat.completions.create`
- Bild im `image_url`-Block als Data-URL mit Base64:
  - `data:{mime};base64,{...}`

### Gemini-Anforderung
- `types.Part.from_bytes(data=..., mime_type=...)`
- Aufruf über `client.models.generate_content`

Prompt-Sprache: **Deutsch**.

Prompt-Inhalt:
- UI-Elemente exakt beschreiben
- sichtbare Texte
- Buttons
- Werte/Zustände
- möglichst präzise und vollständig

Weitere Regeln:
- Session-Cache für Bildbeschreibungen (gleiche Bild-URL => kein Doppel-Call)
- Zwischen KI-Calls: `time.sleep(0.5)`
- Max. Bilder pro Seite konfigurierbar (Default: **30**)

---

## 2.5 Sitemap-Parser

Technik:
- `urllib.request` (kein `requests` notwendig)
- XML namespace-tolerant parsen
- `<sitemapindex>` rekursiv auflösen
- `.gz`-Sitemaps via `gzip` dekomprimieren

Dateinamen aus URL erzeugen:
- Pfadsegmente mit `__` verbinden
- Sonderzeichen zu `_`
- maximal 100 Zeichen
- Endung `.md`

---

## 2.6 Fortschritt, ETA und Durchsatz

### Einzelseite
- ein Fortschrittsbalken (0–100 %)

### Sitemap-Modus
- Gesamt-Fortschrittsbalken
- Seitenzähler: `Seite X von Y (Z %)`

ETA:
- Berechnung aus dem Durchschnitt bereits gemessener Seitenlaufzeiten
- Anzeigeformat:
  - `Noch ca. X min Y sek`
  - wenn > 60 min: Stundenformat
- Zusätzlich anzeigen:
  - `Ø N Sek / Seite`

---

## 2.7 Einstellungen (persistent)

Speicherort:
- `~/.website_scraper_settings.json`

Zu speichern:
- AI-Provider (`openai` / `gemini`)
- OpenAI-Modell:
  - `gpt-4o`
  - `gpt-4o-mini`
- Gemini-Modelle:
  - `gemini-2.0-flash`
  - `gemini-2.0-flash-lite`
  - `gemini-1.5-flash`
  - `gemini-1.5-pro`
- Bilder mit AI beschreiben (bool)
- Browser headless (bool)
- Max. Bilder pro Seite (int)
- letzter Modus
- letzte URL
- letzter Ausgabepfad
- letzter Zustand **pro Modus getrennt**

API-Key-Speicherung:
- primär `keyring` (Windows Credential Manager)
- Fallback: `keyrings.alt`, falls nativer Keystore nicht verfügbar

---

## 2.8 Abbruch-Funktion

- Verwende `threading.Event` als Stop-Signal
- Prüfe das Stop-Signal an kritischen Stellen:
  - nach Seitenladevorgang
  - nach jedem Bild
  - nach jeder Sitemap-Seite
- Thread-sichere UI-Updates:
  - bei Tk-basiert: `after(0, ...)`
  - bei Qt-basiert: Signal/Slot-Mechanismus

---

## 2.9 Auto-Setup beim Erststart

Beim Start fehlende Abhängigkeiten automatisch installieren:
- über `subprocess.check_call([sys.executable, '-m', 'pip', 'install', ...])`

Wenn Playwright-Browser fehlt:
- `playwright install chromium`

Setup-Status in Settings cachen:
- `setup_done`
- `setup_version`

Wichtig:
- Trotz Cache bei jedem Start verifizieren, ob Imports wirklich funktionieren
- Wenn nicht: Cache-Reset und Setup erneut ausführen

Benötigte Pakete:
- `playwright`
- `beautifulsoup4`
- `lxml`
- `openai`
- `google-genai`
- `keyring`
- `keyrings.alt`

`requests` wird **nicht** benötigt.

---

## 3) Nicht-funktionale Anforderungen

- Exakt **eine** Python-Datei: `website_scraper.py`
- Startbar über bereits vorhandene `start.bat` (ruft nur `py website_scraper.py` auf)
- Kompatibel mit Windows 10/11 und Python 3.10+
- Keine Syntax verwenden, die <3.10 bricht
- Keine Paketstruktur, keine zusätzlichen Module

---

## 4) Hinweise zur Design-Freiheit

Du sollst aktiv UX-Verbesserungen einbringen, solange alle Features erhalten bleiben.

Erwartungen:
- Begründe aktiv die Framework-Wahl
- Moderne, klare Desktop-UI
- Dark Mode ist bevorzugt, aber du entscheidest final
- Icons/Symbole sind erwünscht
- Bessere Nutzerführung als bei älteren Implementierungen ist explizit erlaubt

---

## 5) Kritische Code-Snippets (verbindliche Referenzmuster)

### 5.1 OpenAI: `image_url` korrekt als Data-URL

```python
import base64
from openai import OpenAI

client = OpenAI(api_key=api_key)

b64 = base64.b64encode(image_bytes).decode("ascii")
image_data_url = f"data:{mime_type};base64,{b64}"

resp = client.chat.completions.create(
    model=openai_model,
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_de},
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_url},
                },
            ],
        }
    ],
    temperature=0.2,
)
text = (resp.choices[0].message.content or "").strip()
```

### 5.2 Gemini: `types.Part.from_bytes(...)`

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

img_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
resp = client.models.generate_content(
    model=gemini_model,
    contents=[prompt_de, img_part],
)
text = (getattr(resp, "text", "") or "").strip()
```

### 5.3 Bilddownload über Browser-Kontext

```python
# Wichtig: Kontext-Request verwenden (Cookies/Auth)
r = ctx.request.get(img_url, timeout=20000)
if r.ok:
    body = r.body()
    headers = r.headers
```

### 5.4 Nach `pip install` den Importpfad aktualisieren

```python
import site
import sys

def _refresh_sys_path():
    # Nutzer- und globale Site-Packages sicher nachladen
    try:
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            sys.path.append(user_site)
    except Exception:
        pass

    for p in site.getsitepackages():
        if p and p not in sys.path:
            sys.path.append(p)
```

### 5.5 Browser immer sauber schließen

```python
browser = None
try:
    browser = pw.chromium.launch(headless=headless)
    # ... scraping logic ...
finally:
    if browser is not None:
        browser.close()
```

---

## 6) Implementierungsleitplanken

- Verwende klare Schichten innerhalb der Einzeldatei:
  - Settings/Config
  - Setup/Dependency-Check
  - UI
  - Scraper/Parser
  - AI-Describer
  - Worker/Threading
- Fehler robust behandeln und im UI verständlich melden
- Log-Ausgaben für Diagnose (Statusbereich in UI + optional Konsole)
- Bei Abbruch: keine hängenden Threads/Browser-Prozesse
- Dateischreibvorgänge atomar/sicher, soweit praktikabel

---

## 7) Verifikationsschritte (nach Implementierung zwingend selbst prüfen)

1. `start.bat` ausführen → Setup-Fenster erscheint, Pakete werden bei Bedarf installiert.
2. Simulationsmodus + Einzelseite → `.md`-Datei wird erzeugt, Inhalt plausibel.
3. Simulationsmodus + Sitemap → Ordner mit vielen `.md` + `_index.md`, ETA sichtbar.
4. Abbrechen-Button während Sitemap-Lauf testen → Prozess stoppt sauber.
5. Einstellungen ändern, App neu starten → Werte sind persistent.
6. API-Key eingeben → Speicherung über Keyring (Windows Credential Manager bzw. Fallback).

---

## 8) Wichtig: Kein Bezug auf alte Datei

Diese Implementierung ist ein vollständiger Neuaufbau.

- Keine Verweise auf alte Code-Strukturen
- Keine implizite Abhängigkeit auf vorherige `website_scraper.py`
- Ergebnis muss standalone und eigenständig wartbar sein
