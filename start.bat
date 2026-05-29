@echo off
cd /d "%~dp0"
py -c "import subprocess,sys,os; e=sys.executable; w=os.path.join(os.path.dirname(e),'pythonw.exe'); subprocess.Popen([w if os.path.exists(w) else e,'website_scraper.py'])"
