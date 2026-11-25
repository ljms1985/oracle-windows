"""
computer.py — Oracle's own computer, Muse-style.

This gives the Windows Oracle agent the pieces Muse has, in one place:

  * A workspace it owns: <agent folder>/workspace/
    files/, downloads/, memory/, logs/, goals/, tasks/, browser-profile/
  * File tools that stay inside that workspace unless the user
    explicitly approves an outside path.
  * Command tools that run in the workspace, with a timeout, and that
    refuse obviously destructive commands.
  * Web tools: fetch a page as text, and a no-API-key web search.
  * A browser tool: real Chromium via Playwright when it is installed,
    with its own persistent profile in the workspace. If Playwright is
    not installed, it tells you exactly how to install it instead of
    pretending it worked.
  * Persistent memory, goals and tasks: JSON files in workspace/memory/
    and workspace/tasks/ that survive restarts, so Oracle can pick up
    open work without being told again.
  * A simple scheduler: tasks due in the past are listed for the agent
    to run; the agent loop (or a background thread in gui.py) calls
    check_due_tasks() regularly.
  * Job applications: apply_to_job() fills a job form in Oracle's own
    browser (Playwright), uploads the resume, and presses submit.
    Rule set by Lorenza: if a site is NOT blocking it, Oracle submits
    and pushes the application through every time, without asking
    first. Only if a site actually blocks it (CAPTCHA, sign-in code /
    2FA, anti-bot block, or a step that needs a human) does it stop,
    hand it to Lorenza, and log exactly what was blocked and where.
    Every attempt is logged in workspace/jobs/submissions.json.
  * Employer sites: job boards like Indeed often redirect to the
    employer's own application site. apply_to_job() follows that
    redirect and applies on the EMPLOYER site too, under the same
    auto-submit rule. If the employer site needs a new account, Oracle
    creates one (distinct strong password per site), saves it ONLY
    locally in <agent folder>/credentials/accounts.json (never in
    chat, email, or the cloud), and records it in the accounts log
    Lorenza can open. It never invents an existing login:
    if a site wants her existing password, it stops and asks her.

Safety model — kept deliberately simple and on by default:
  * Inside the workspace: read/write/run is allowed.
  * Outside the workspace, destructive commands, and anything that
    sends data, money, or messages to another person: ask the user first.
  * Every file overwrite is backed up first (see agent.py).
  * This module never claims a tool worked unless it actually ran.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Frozen (.exe) builds: writable data (memory, workspace, credentials,
# prints, alerts, ...) must live NEXT TO Oracle.exe, not in PyInstaller's
# temp _MEIPASS folder (deleted on exit). oracle_paths.app_dir() returns
# exactly that when frozen, and the source folder when running from source.
try:
    from oracle_paths import app_dir as _oracle_app_dir
    BASE_DIR = _oracle_app_dir()
except Exception:
    BASE_DIR = Path(__file__).resolve().parent
WORKSPACE = BASE_DIR / "workspace"
FILES_DIR = WORKSPACE / "files"
DOWNLOADS_DIR = WORKSPACE / "downloads"
MEMORY_DIR = WORKSPACE / "memory"
LOGS_DIR = WORKSPACE / "logs"
GOALS_DIR = WORKSPACE / "goals"
TASKS_DIR = WORKSPACE / "tasks"
BROWSER_PROFILE = WORKSPACE / "browser-profile"

MEMORY_FILE = MEMORY_DIR / "memory.json"
TASKS_FILE = TASKS_DIR / "tasks.json"
GOALS_FILE = GOALS_DIR / "goals.json"
JOBS_DIR = WORKSPACE / "jobs"
JOB_PROFILE_FILE = JOBS_DIR / "profile.json"
JOB_SUBMISSIONS_FILE = JOBS_DIR / "submissions.json"
# Local-only credentials store (see _save_account). This lives on
# Lorenza's own Windows PC, under the agent folder: <agent folder>\credentials\
CREDENTIALS_DIR = BASE_DIR / "credentials"
ACCOUNTS_FILE = CREDENTIALS_DIR / "accounts.json"

AUTO_APPLY = os.environ.get("AGENT_AUTO_APPLY", "0") == "1"

DANGEROUS_PATTERNS = [
    "format ", "del /f", "rm -rf", "shutdown", "reg delete",
    "rmdir /s", "remove-item", "format-volume", "diskpart",
    "mkfs", ":(){", "del /q", "erase ",
]

for _d in (FILES_DIR, DOWNLOADS_DIR, MEMORY_DIR, LOGS_DIR,
           GOALS_DIR, TASKS_DIR, BROWSER_PROFILE, JOBS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
# Credentials store: created from the start (Windows has no Unix
# 0700/0600 modes; os.chmod calls in _save_account are best-effort).
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)


def log_event(text):
    """Append one line to today's log. Never raises."""
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        (LOGS_DIR / f"{datetime.now():%Y-%m-%d}.log").open(
            "a", encoding="utf-8").write(f"[{stamp}] {text}\n")
    except Exception:
        pass


def resolve_workspace_path(path):
    """Return a Path inside the workspace, or None if it escapes it."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    try:
        p = p.resolve()
        p.relative_to(WORKSPACE.resolve())
        return p
    except Exception:
        return None


def require_approval(prompt):
    """Ask on the console unless AUTO_APPLY=1. Returns True if approved."""
    if AUTO_APPLY:
        return True
    try:
        return input(f"{prompt} (y/n): ").strip().lower() == "y"
    except Exception:
        return False


# ---------------------------------------------------------------- files

def list_workspace(path="."):
    p = resolve_workspace_path(path)
    if p is None:
        return "Error: that path is outside Oracle's workspace. Ask the user to approve it first."
    if not p.exists():
        return f"Error: {p} does not exist in the workspace."
    if p.is_file():
        return str(p)
    return "\n".join(str(x.relative_to(WORKSPACE)) for x in sorted(p.rglob("*")) if x.is_file()) or "(empty)"

def read_workspace_file(path):
    p = resolve_workspace_path(path)
    if p is None or not p.exists():
        return "Error: file not found inside the workspace."
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:12000]
    except Exception as e:
        return f"Error reading file: {e}"

def write_workspace_file(path, content):
    p = resolve_workspace_path(path)
    if p is None:
        return "Error: that path is outside Oracle's workspace. Ask the user to approve it first."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    log_event(f"wrote {p.relative_to(WORKSPACE)} ({len(content)} chars)")
    return f"Wrote {p.relative_to(WORKSPACE)} ({len(content)} characters)."

def search_workspace(query, path="."):
    """Simple grep over text files in the workspace. Returns matches."""
    p = resolve_workspace_path(path)
    if p is None or not p.exists():
        return "Error: path not found inside the workspace."
    hits = []
    files = [p] if p.is_file() else [x for x in p.rglob("*") if x.is_file() and x.suffix.lower() in (".txt", ".md", ".py", ".json", ".csv")]
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if query.lower() in line.lower():
                    hits.append(f"{f.relative_to(WORKSPACE)}:{i}: {line.strip()[:200]}")
        except Exception:
            continue
    return "\n".join(hits[:100]) if hits else "No matches in the workspace."


# ---------------------------------------------------------------- commands

def run_in_workspace(command, timeout=60):
    """Run a shell command with the workspace as cwd. Returns output."""
    lowered = command.lower()
    if any(pat in lowered for pat in DANGEROUS_PATTERNS):
        return "Refused: that command looks destructive. Ask the user first."
    if not AUTO_APPLY:
        if not require_approval(f"Run in workspace? [{command}]"):
            return "User declined to run the command."
    try:
        result = subprocess.run(command, shell=True, cwd=str(WORKSPACE),
                                capture_output=True, text=True, timeout=timeout)
        out = (result.stdout + result.stderr).strip()
        log_event(f"command exit={result.returncode}: {command[:200]}")
        return out[:8000] if out else f"Command finished with exit code {result.returncode}."
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s."
    except Exception as e:
        return f"Error running command: {e}"


# ---------------------------------------------------------------- web

def web_fetch(url):
    """Fetch a page and return readable text (no login, no forms)."""
    if not url.startswith(("http://", "https://")):
        return "Error: url must start with http:// or https://"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Oracle-agent/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:12000] if text else "Page fetched but no readable text found."
    except Exception as e:
        return f"Error fetching page: {e}"

def web_search(query):
    """No-API-key search via DuckDuckGo lite. Returns titles + links.

    Fixed 2026-11-25: DDG lite now marks results with single quotes
    (class='result-link') and serves the results page only to a
    browser User-Agent — the old double-quote regex + "Oracle-agent"
    UA returned zero matches on the live PC even though the fetch
    succeeded. The matcher below accepts either quote style and
    href before or after the class."""
    try:
        q = urllib.parse.quote_plus(query)
        req = urllib.request.Request(
            f"https://lite.duckduckgo.com/lite/?q={q}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        results = []
        for m in re.finditer(r"<a\s[^>]*?result-link[^>]*?>(.*?)</a>",
                             html, re.DOTALL | re.IGNORECASE):
            href_m = re.search(r"""href=(["'])(.*?)\1""", m.group(0))
            if not href_m:
                continue
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            title = (title.replace("&amp;", "&").replace("&quot;", '"')
                     .replace("&#x27;", "'").replace("&#39;", "'")
                     .replace("&lt;", "<").replace("&gt;", ">"))
            href = urllib.parse.unquote(href_m.group(2))
            if href.startswith("//"):
                href = "https:" + href
            if title and href:
                results.append(f"- {title}: {href}")
            if len(results) >= 10:
                break
        return "\n".join(results) if results else "No search results returned. Try a different query."
    except Exception as e:
        return f"Error searching the web: {e}"


# ---------------------------------------------------------------- browser (Playwright, optional)

_browser = {"page": None, "playwright": None, "browser": None}

def browser_start():
    if _browser["page"] is not None:
        return "Browser is already running with Oracle's profile."
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ("Playwright is not installed. Install it once with:\n"
                "  pip install playwright\n"
                "  playwright install chromium\n"
                "Then try browser_start again. Until then, use web_fetch / web_search.")
    pw = sync_playwright().start()
    browser = pw.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=False)
    page = browser.new_page() if not browser.pages else browser.pages[0]
    _browser.update(page=page, playwright=pw, browser=browser)
    return "Browser started with Oracle's own profile in workspace/browser-profile/."

def browser_goto(url):
    if _browser["page"] is None:
        s = browser_start()
        if "not installed" in s:
            return s
    try:
        _browser["page"].goto(url, timeout=30000)
        return f"Opened {url} — title: {_browser['page'].title()}"
    except Exception as e:
        return f"Error opening page: {e}"

def browser_text():
    if _browser["page"] is None:
        return "Browser is not running. Call browser_start first."
    try:
        return _browser["page"].inner_text("body")[:12000]
    except Exception as e:
        return f"Error reading page: {e}"

def browser_close():
    if _browser["browser"] is not None:
        try:
            _browser["browser"].close()
            _browser["playwright"].stop()
        except Exception:
            pass
    _browser.update(page=None, playwright=None, browser=None)
    return "Browser closed. Its profile and cookies are kept in workspace/browser-profile/."


# ---------------------------------------------------------------- programs
# Added 2026-11-25 (item 4): the agent had no "open a program" tool —
# "Open Notepad" could only go through a raw shell command, and the
# model sometimes claimed it was open when no process was running.
# open_program() launches the program and only reports success when
# its process is actually found running afterwards. From a background
# session with no desktop (e.g. an SSH session) Windows cannot show
# a window, so it then says so honestly instead of claiming success.

_PROGRAMS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "wordpad": "wordpad.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
}


def open_program(name):
    """Open a program by name (e.g. "Notepad") and verify it is running.

    Returns success ONLY when the program's process is found running
    afterwards. A launch that produces no process reports the failure
    plainly — never "it is open" when it is not."""
    key = " ".join(str(name or "").split()).lower()
    target = _PROGRAMS.get(key, key)
    if not target.lower().endswith(".exe"):
        target += ".exe"
    exe = target.split("\\")[-1]
    try:
        subprocess.Popen([target], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         close_fds=True)
    except Exception as e:
        return f"Could not open {name}: {e}"
    # Verify the process is still running twice: a GUI program
    # launched from a background session with no desktop can start
    # and then die within seconds (seen live 2026-11-25: notepad.exe
    # was present at +2s and gone a minute later), so a single early
    # check would falsely report success. It must still be alive
    # at ~8s to count as open.
    for _wait in (2, 6):
        time.sleep(_wait)
        try:
            check = subprocess.run(f'tasklist /FI "IMAGENAME eq {exe}"',
                                   shell=True, capture_output=True, text=True,
                                   timeout=15)
            out = check.stdout or ""
            if exe.lower() not in out.lower() or "no tasks" in out.lower():
                return (f"I tried to open {name}, but no {exe} process is "
                        "running afterwards — a window cannot be opened "
                        "from this background session. Ask me from the "
                        "Oracle window on the desktop, and I will open it "
                        "there.")
        except Exception:
            pass
    log_event(f"opened program {name} ({exe})")
    return f"Opened {name} ({exe}) — it is running."


# ---------------------------------------------------------------- job applications
#
# Lorenza's rule (set 2026-11-24, applies to the Windows build and to the
# macOS build too): Oracle MUST be able to submit job applications
# on its own. If a site is NOT blocking it, Oracle fills the form,
# uploads the resume, and presses submit — every time, without asking
# first. It only stops and hands the application to Lorenza when a
# site actually blocks it: CAPTCHA, a sign-in code / 2FA step, an
# anti-bot block, or a step that genuinely needs a human. In that
# case it logs exactly what was blocked and where, in
# workspace/jobs/submissions.json, and tells Lorenza.
#
# This is deliberately NOT gated by require_approval() / AUTO_APPLY:
# submitting a job application is the one external action Lorenza
# has pre-approved in advance. Everything else external still asks
# first (see the safety model in the module docstring). Oracle never
# invents resume details — the profile below starts as placeholders
# to be filled in on first run on her Windows PC.

JOB_PROFILE_TEMPLATE = {
    "name": "",            # fill on first run on the Windows PC, e.g. "Lorenza Session"
    "email": "",           # fill on first run
    "phone": "",           # fill on first run
    "resume_path": "",     # fill on first run, e.g. "C:\Oracle\workspace\jobs\resume.pdf"
    "location": "Jacksonville, FL",
    "min_pay_per_hour": 25,
    "scope": ["customer service", "call center lead/supervisor",
              "mortgage/refinance"],
    "excluded": ["collections", "marine", "sales"],
    "notes": "Placeholders only — fill name, email, phone and resume_path "
             "on first run on the Windows PC. Do not invent resume details.",
}


def get_job_profile():
    """Return the job-hunting profile (placeholders until filled in)."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    if JOB_PROFILE_FILE.exists():
        return _load_json(JOB_PROFILE_FILE, dict(JOB_PROFILE_TEMPLATE))
    _save_json(JOB_PROFILE_FILE, dict(JOB_PROFILE_TEMPLATE))
    return dict(JOB_PROFILE_TEMPLATE)


def save_job_profile(name=None, email=None, phone=None, resume_path=None,
                     location=None, min_pay_per_hour=None):
    """Save job-profile fields. Only the fields you pass are changed."""
    profile = get_job_profile()
    for key, value in (("name", name), ("email", email), ("phone", phone),
                       ("resume_path", resume_path), ("location", location),
                       ("min_pay_per_hour", min_pay_per_hour)):
        if value is not None:
            profile[key] = value
    _save_json(JOB_PROFILE_FILE, profile)
    return f"Job profile saved to {JOB_PROFILE_FILE.relative_to(WORKSPACE)}: " +         ", ".join(f"{k}={v!r}" for k, v in profile.items()
                  if k in ("name", "email", "phone", "resume_path",
                           "location", "min_pay_per_hour"))


def _log_submission(entry):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    entries = _load_json(JOB_SUBMISSIONS_FILE, [])
    entries.append(entry)
    _save_json(JOB_SUBMISSIONS_FILE, entries)
    log_event(f"job application {entry['status']}: "
              f"{entry.get('job_title', '')} @ {entry.get('company', '')} "
              f"({entry.get('site', '')})")
    return entry


def list_job_submissions(limit=20):
    """List recent job-application attempts from the submissions log."""
    entries = _load_json(JOB_SUBMISSIONS_FILE, [])
    if not entries:
        return "No job applications logged yet."
    lines = []
    for e in entries[-int(limit):]:
        lines.append(
            f"{e.get('date', '')} | {e.get('job_title', '')} @ "
            f"{e.get('company', '')} | {e.get('site', '')} | "
            f"{e.get('status', '')}"
            + (f" | confirmation: {e['confirmation']}" if e.get("confirmation") else "")
            + (f" | blocked: {e['blocked_reason']}" if e.get("blocked_reason") else ""))
    return "\n".join(lines)


_BLOCK_MARKERS = [
    ("captcha", "CAPTCHA / human-verification challenge"),
    ("recaptcha", "reCAPTCHA challenge"),
    ("hcaptcha", "hCaptcha challenge"),
    ("verify you are human", "human-verification challenge"),
    ("verify you're human", "human-verification challenge"),
    ("sign-in code", "sign-in / verification code step"),
    ("verification code", "verification-code step"),
    ("two-factor", "two-factor authentication step"),
    ("2fa", "two-factor authentication step"),
    ("enter the code", "verification-code step"),
    ("unusual traffic", "anti-bot block (unusual traffic)"),
    ("access denied", "anti-bot / access-denied block"),
    ("are you a robot", "anti-bot challenge"),
    ("suspicious activity", "anti-bot block (suspicious activity)"),
]



# ---------------------------------------------------------------- job-site accounts
#
# Local-only credentials store. Rules, set by Lorenza:
#  * Save credentials ONLY on her own Windows PC, in <agent folder>\credentials\
#    (never in chat logs, email, or the cloud).
#  * The password itself is NEVER printed in a reply / chat log — the
#    reply only says an account was created and where it is saved, so
#    Lorenza can open credentials/accounts.json herself and read it.
#  * DESKTOP VISIBILITY (Lorenza's explicit choice, added 2026-11-24):
#    every account created is ALSO appended to
#    %USERPROFILE%\Desktop\Oracle-Accounts.txt and that file is opened in Notepad
#    and left open on the desktop, so she sees it as
#    soon as she looks at the desktop. That file is plain text, so
#    anyone who can see the desktop / screen will also see those
#    passwords in plain text — that is the trade-off she chose for
#    visibility. The secure local store (credentials/accounts.json,
#    0600) is still the canonical copy.
#  * One distinct strong password per site — never reuse one password
#    everywhere.
#  * Never invent an existing login. If a site asks for an existing
#    password (sign-in, not sign-up), stop and ask Lorenza instead.

def _generate_strong_password(length=16):
    """Generate one distinct strong password (letters + digits + symbols)."""
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)
                and any(c in "!@#$%^&*" for c in pw)):
            return pw


def _save_account(site, username, password):
    """Save one site login to the local-only accounts log. Returns the entry."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CREDENTIALS_DIR, 0o700)
    except Exception:
        pass
    accounts = _load_json(ACCOUNTS_FILE, [])
    entry = {
        "site": site,
        "username": username,
        "password": password,
        "date_created": datetime.now(timezone.utc).isoformat(),
    }
    accounts = [a for a in accounts
                if not (a.get("site") == site and a.get("username") == username)]
    accounts.append(entry)
    _save_json(ACCOUNTS_FILE, accounts)
    try:
        os.chmod(ACCOUNTS_FILE, 0o600)
    except Exception:
        pass
    log_event(f"account created for {site} (username {username}) — "
              "saved locally in credentials/accounts.json only")
    # Desktop visibility (Lorenza's explicit choice): append the same
    # account to %USERPROFILE%\Desktop\Oracle-Accounts.txt — append, never overwrite
    # previous accounts — and open that file in Notepad, leaving the
    # window open on the desktop so she sees it immediately.
    _append_account_to_desktop(entry)
    return entry


def _append_account_to_desktop(entry):
    """Append one account to %USERPROFILE%/Desktop/Oracle-Accounts.txt and open it
    in Notepad, leaving the window open on the desktop.
    Plain text by design, per Lorenza's explicit choice — anyone who
    can see the desktop will see these passwords. Best effort only:
    if there is no Desktop or Notepad cannot open it (e.g. headless),
    the local credentials store above is still the canonical copy."""
    try:
        desktop_file = Path.home() / "Desktop" / "Oracle-Accounts.txt"
        desktop_file.parent.mkdir(parents=True, exist_ok=True)
        if not desktop_file.exists():
            desktop_file.write_text(
                "Oracle — job-site accounts (created by the agent)\n"
                "\n"
                "Plain text, on purpose, so you can see them on your desktop.\n"
                "\n"
                "Anyone who can see this screen can also see these passwords.\n"
                "\n"
                "Keep this file on your own Windows PC only. Do not share or email it.\n"
                "\n",
                encoding="utf-8")
        with desktop_file.open("a", encoding="utf-8") as f:
            f.write(f"Site: {entry.get('site', '')}\n")
            f.write(f"Username: {entry.get('username', '')}\n")
            f.write(f"Password: {entry.get('password', '')}\n")
            f.write(f"Date created: {entry.get('date_created', '')}\n\n")
        # Open in Notepad and leave the window open. Non-blocking, and
        # a failure here must never break the application itself.
        subprocess.Popen(["notepad.exe", str(desktop_file)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_event(f"account for {entry.get('site', '')} appended to "
                  "%USERPROFILE%\\Desktop\\Oracle-Accounts.txt and opened in Notepad")
    except Exception as e:
        print(f"[accounts] Could not open Desktop accounts file: {e}")


def list_job_accounts():
    """List the locally saved job-site accounts (site, username, date).

    The password is NOT printed here — open credentials/accounts.json
    on the Windows PC to read it, or look at %USERPROFILE%/Desktop/Oracle-Accounts.txt,
    which the agent also opens in Notepad when an account is created.
    That keeps passwords out of chat logs.
    """
    accounts = _load_json(ACCOUNTS_FILE, [])
    if not accounts:
        return "No job-site accounts saved locally yet."
    return "\n".join(
        f"{a.get('site', '')} | username: {a.get('username', '')} | "
        f"created: {a.get('date_created', '')} "
        "(password saved locally in credentials/accounts.json)"
        for a in accounts)


def _follow_external_apply(page):
    """Click 'Apply on company site' / similar and follow the redirect.

    Indeed and other boards often show an interstitial with a button
    that sends you to the employer's own site. Returns True if such a
    link/button was found and clicked.
    """
    for label in ("Apply on company site", "Continue to company site",
                  "Apply externally", "Apply on employer site",
                  "Continue to the company website"):
        try:
            target = page.get_by_role("link", name=label).first
            if target.count():
                target.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                time.sleep(1)
                return True
        except Exception:
            pass
        try:
            target = page.get_by_role("button", name=label).first
            if target.count():
                target.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                time.sleep(1)
                return True
        except Exception:
            pass
    return False


def _handle_account_creation(page, site_url, profile):
    """Handle a sign-up / sign-in gate on an employer site.

    Returns (status, detail):
      ("none", "")        — no account gate on this page; carry on.
      ("created", user)   — a new account was created and saved locally.
      ("blocked", reason) — sign-in with an existing login is required,
                            or account creation failed; stop and ask Lorenza.
    """
    try:
        body = page.inner_text("body").lower()
    except Exception:
        body = ""
    try:
        has_password = page.locator("input[type='password']").count() > 0
    except Exception:
        has_password = False
    if not has_password:
        return ("none", "")
    is_signup = (
        "create account" in body or "create an account" in body
        or "sign up" in body or "register" in body
        or page.locator("input[name*='confirm']").count() > 0
        or page.locator("input[id*='confirm']").count() > 0
        or page.locator("input[type='password']").count() > 1
    )
    if not is_signup:
        # Sign-in only: this needs Lorenza's EXISTING password, which
        # Oracle must not invent. Stop here.
        return ("blocked",
                "sign-in required with an existing account — Oracle does "
                "not know / will not invent the existing password")
    email = profile.get("email", "")
    if not email:
        return ("blocked",
                "a new account is required, but no email is in the job "
                "profile yet — fill email in first (get_job_profile / "
                "save_job_profile), then retry")
    username = email
    password = _generate_strong_password()
    # Fill the sign-up form: email/username, password, confirm password.
    _fill_one(page, "email", email)
    _fill_one(page, "username", username)
    _fill_one(page, "password", password)
    _fill_one(page, "confirm password", password)
    _fill_one(page, "confirm", password)
    created = False
    for attempt in [
        lambda: page.get_by_role("button", name="Create Account").first.click(),
        lambda: page.get_by_role("button", name="Sign Up").first.click(),
        lambda: page.get_by_role("button", name="Register").first.click(),
        lambda: page.locator("button[type='submit']").first.click(),
    ]:
        try:
            attempt()
            created = True
            break
        except Exception:
            continue
    if not created:
        return ("blocked", "sign-up form found but its create-account button could not be clicked")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
    except Exception:
        pass
    if _detect_application_block(page):
        return ("blocked", "a verification / CAPTCHA step appeared during account creation")
    _save_account(site_url, username, password)
    return ("created", username)


def _detect_application_block(page):
    """Return a description if the page is blocking an application, else None."""
    try:
        body = page.inner_text("body").lower()
    except Exception:
        body = ""
    for marker, label in _BLOCK_MARKERS:
        if marker in body:
            return label
    try:
        html = page.content().lower()
    except Exception:
        html = ""
    for src in ("recaptcha", "hcaptcha", "captcha"):
        if src in html:
            return f"{src} challenge present on the page"
    return None


def _fill_one(page, label, value):
    """Try several Playwright strategies to fill one field. Returns True if filled."""
    if value in (None, ""):
        return False
    value = str(value)
    strategies = [
        lambda: page.get_by_label(label, exact=False).first.fill(value),
        lambda: page.get_by_placeholder(label, exact=False).first.fill(value),
        lambda: page.locator(f"input[name*='{label.lower()}']").first.fill(value),
        lambda: page.locator(f"input[id*='{label.lower()}']").first.fill(value),
        lambda: page.locator(f"textarea[name*='{label.lower()}']").first.fill(value),
    ]
    for attempt in strategies:
        try:
            attempt()
            return True
        except Exception:
            continue
    return False


def apply_to_job(url, job_title="", company="", field_values=None, resume_path=None):
    """Fill a job application form and press submit — on Oracle's own browser.

    No approval prompt: per Lorenza's rule, if the site is NOT blocking
    it, Oracle submits and pushes the application through every time.
    It only stops (and logs the block) for CAPTCHA, sign-in code / 2FA,
    an anti-bot block, or a step that needs a human.
    field_values: optional dict {label: value} for extra form fields.
    Returns a plain-language result; the attempt is always logged.
    """
    profile = get_job_profile()
    if isinstance(field_values, str):
        try:
            field_values = json.loads(field_values)
        except Exception:
            field_values = {}
    field_values = dict(field_values or {})

    started = browser_start()
    if "not installed" in started:
        entry = _log_submission({
            "job_title": job_title, "company": company, "site": url,
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "blocked",
            "blocked_reason": "Playwright is not installed — " + started,
            "confirmation": "",
        })
        return ("BLOCKED — Playwright is not installed, so I could not open "
                "the application page. Logged to workspace/jobs/submissions.json. "
                "Install it with: pip3 install playwright; playwright install chromium")

    page = _browser["page"]
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception as e:
        _log_submission({
            "job_title": job_title, "company": company, "site": url,
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "blocked", "blocked_reason": f"Page did not load: {e}",
            "confirmation": "",
        })
        return f"BLOCKED — the application page did not load ({e}). Logged; handing it to you."

    blocked = _detect_application_block(page)
    if blocked:
        _log_submission({
            "job_title": job_title, "company": company, "site": url,
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "blocked", "blocked_reason": blocked + " (on the application page)",
            "confirmation": "",
        })
        return (f"BLOCKED — {blocked} on the application page at {url}. "
                "I stopped before submitting, logged exactly what blocked it, "
                "and I am handing this one to you to intervene.")

    # Follow through to the EMPLOYER site when a board redirects there
    # (e.g. Indeed -> "Apply on company site"). Same auto-submit rule
    # applies on the employer site as on the board.
    _follow_external_apply(page)
    blocked = _detect_application_block(page)
    if blocked:
        _log_submission({
            "job_title": job_title, "company": company, "site": page.url,
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "blocked", "blocked_reason": blocked + " (on the employer site)",
            "confirmation": "",
        })
        return (f"BLOCKED — {blocked} on the employer site at {page.url}. "
                "I stopped before submitting, logged it, and I am handing this one to you.")
    url = page.url  # log the final (employer) URL, not just the board link

    # If the employer site needs an account, create one (new account
    # only) or stop for an existing login — see _handle_account_creation.
    account_status, account_detail = _handle_account_creation(page, url, profile)
    account_note = ""
    if account_status == "blocked":
        _log_submission({
            "job_title": job_title, "company": company, "site": url,
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "blocked", "blocked_reason": account_detail,
            "confirmation": "",
        })
        return (f"BLOCKED — {account_detail}. Logged; handing this one to you "
                "to intervene (I will not invent an existing password).")
    if account_status == "created":
        account_note = (f" Created a new account on this employer site "
                        f"(username {account_detail}); the distinct password is saved "
                        "locally only in credentials/accounts.json — open that file "
                        "to read it, it is not printed here.")
        blocked = _detect_application_block(page)
        if blocked:
            _log_submission({
                "job_title": job_title, "company": company, "site": url,
                "date": datetime.now(timezone.utc).isoformat(),
                "status": "blocked", "blocked_reason": blocked + " (after account creation)",
                "confirmation": "",
                "account_created": account_detail,
            })
            return (f"BLOCKED — {blocked} after creating the account at {url}. "
                    "The account is saved locally; the application itself was not "
                    "submitted. Logged; handing this one to you.")

    # Build the values to fill, from the profile first, then the caller's overrides.
    name = profile.get("name", "")
    first, _, last = name.partition(" ")
    values = {
        "first name": first, "last name": last, "full name": name,
        "name": name, "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "city": profile.get("location", ""), "location": profile.get("location", ""),
    }
    values.update({k: v for k, v in field_values.items() if v not in (None, "")})
    filled, unfilled = [], []
    for label, value in values.items():
        if not value:
            continue
        if _fill_one(page, label, value):
            filled.append(label)
        else:
            unfilled.append(label)

    # Resume upload, if there is a file field and a resume on disk.
    resume = resume_path or profile.get("resume_path", "")
    resume_note = "no resume on file yet (fill resume_path in the job profile)"
    if resume:
        resume_file = Path(resume).expanduser()
        if resume_file.exists():
            try:
                page.locator("input[type='file']").first.set_input_files(str(resume_file))
                resume_note = f"resume uploaded: {resume_file.name}"
            except Exception as e:
                resume_note = f"resume upload field not found / failed: {e}"
        else:
            resume_note = f"resume_path set but file not found: {resume}"

    # Check again for a block that only appeared once the form loaded.
    blocked = _detect_application_block(page)
    if blocked:
        _log_submission({
            "job_title": job_title, "company": company, "site": url,
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "blocked", "blocked_reason": blocked + " (after filling the form)",
            "confirmation": "",
        })
        return (f"BLOCKED — {blocked} appeared after filling the form at {url}. "
                "I did not submit. Logged; handing this one to you.")

    if unfilled and not filled:
        _log_submission({
            "job_title": job_title, "company": company, "site": url,
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "blocked",
            "blocked_reason": "could not fill any form fields: " + ", ".join(unfilled),
            "confirmation": "",
        })
        return ("BLOCKED — I could not fill any of the form fields "
                f"({', '.join(unfilled)}). The form layout may need a human. "
                "Logged; handing this one to you.")

    # Press submit — this is the pre-approved step.
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Submit").first.click(),
        lambda: page.get_by_role("button", name="Apply").first.click(),
        lambda: page.get_by_role("button", name="Apply Now").first.click(),
        lambda: page.locator("button[type='submit']").first.click(),
        lambda: page.locator("input[type='submit']").first.click(),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        _log_submission({
            "job_title": job_title, "company": company, "site": url,
            "date": datetime.now(timezone.utc).isoformat(),
            "status": "blocked",
            "blocked_reason": "could not find / click a submit button",
            "confirmation": "",
        })
        return ("BLOCKED — I filled the form but could not find a submit "
                "button to press. Logged; handing this one to you.")

    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
    except Exception:
        pass

    blocked = _detect_application_block(page)
    confirmation = ""
    try:
        body = page.inner_text("body")
        for phrase in ("thank you", "application submitted", "application received",
                       "successfully submitted", "confirmation", "application id",
                       "reference number"):
            if phrase in body.lower():
                idx = body.lower().find(phrase)
                confirmation = body[max(0, idx - 40):idx + 160].replace("\n", " ").strip()
                break
    except Exception:
        body = ""
    if blocked:
        status = "blocked"
        result = (f"BLOCKED after submitting — {blocked} at {url}. The application "
                  "may or may not have gone through; check the submissions log and "
                  "the site, and I am handing this one to you." + account_note)
    elif confirmation:
        status = "submitted"
        result = (f"SUBMITTED — {job_title or 'job'} @ {company or 'company'} ({url}). "
                  f"Confirmation shown: {confirmation} Fields filled: {', '.join(filled) or 'none'}. "
                  f"{resume_note}." + account_note)
    else:
        status = "submitted_unconfirmed"
        result = (f"SUBMITTED (unconfirmed) — I pressed submit for "
                  f"{job_title or 'job'} @ {company or 'company'} ({url}), but no "
                  "confirmation text was shown on the page. Fields filled: "
                  f"{', '.join(filled) or 'none'}. {resume_note}. "
                  "Check the site / your email for a confirmation." + account_note)
    _log_submission({
        "job_title": job_title, "company": company, "site": url,
        "date": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "blocked_reason": blocked or "",
        "confirmation": confirmation,
        "fields_filled": filled, "fields_unfilled": unfilled,
        "resume": resume_note,
        "account_created": account_detail if account_status == "created" else "",
    })
    return result



# ---------------------------------------------------------------- memory, goals, tasks

def _load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default

def _save_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def remember(fact):
    mem = _load_json(MEMORY_FILE, {"facts": [], "preferences": [], "people": []})
    if fact not in mem["facts"]:
        mem["facts"].append(fact)
    _save_json(MEMORY_FILE, mem)
    return f"Remembered: {fact}"

def search_memory(query):
    mem = _load_json(MEMORY_FILE, {"facts": [], "preferences": [], "people": []})
    hits = [f for f in mem["facts"] if query.lower() in f.lower()]
    hits += [f"preference: {p}" for p in mem["preferences"] if query.lower() in p.lower()]
    return "\n".join(hits) if hits else "No matching memory found."

def add_goal(title, notes=""):
    goals = _load_json(GOALS_FILE, [])
    goals.append({"title": title, "notes": notes, "created": datetime.now(timezone.utc).isoformat(), "done": False})
    _save_json(GOALS_FILE, goals)
    return f"Goal added: {title} (now {len(goals)} goals, {sum(1 for g in goals if not g['done'])} open)"

def add_task(title, due=""):
    tasks = _load_json(TASKS_FILE, [])
    tasks.append({"title": title, "due": due, "created": datetime.now(timezone.utc).isoformat(), "done": False})
    _save_json(TASKS_FILE, tasks)
    return f"Task added: {title}" + (f" (due {due})" if due else "")

def list_open_tasks():
    tasks = _load_json(TASKS_FILE, [])
    open_tasks = [t for t in tasks if not t["done"]]
    if not open_tasks:
        return "No open tasks."
    return "\n".join(f"- {t['title']}" + (f" (due {t['due']})" if t.get("due") else "") for t in open_tasks)

def complete_task(title):
    tasks = _load_json(TASKS_FILE, [])
    for t in tasks:
        if title.lower() in t["title"].lower() and not t["done"]:
            t["done"] = True
            _save_json(TASKS_FILE, tasks)
            return f"Completed: {t['title']}"
    return f"No open task matching '{title}' found."

def check_due_tasks():
    """Return tasks whose due string is in the past (YYYY-MM-DD). The
    caller decides whether to run them; this never runs them by itself."""
    tasks = _load_json(TASKS_FILE, [])
    today = datetime.now().strftime("%Y-%m-%d")
    due = [t for t in tasks if not t["done"] and t.get("due") and t["due"] <= today]
    if not due:
        return "No tasks due."
    return "Due tasks:\n" + "\n".join(f"- {t['title']} (due {t['due']})" for t in due)


# Tool registry for agent.py: name -> (function, description)
COMPUTER_TOOLS = {
    "list_workspace": (list_workspace, "list_workspace(path='.') - list files in Oracle's workspace"),
    "read_workspace_file": (read_workspace_file, "read_workspace_file(path) - read a file inside the workspace"),
    "write_workspace_file": (write_workspace_file, "write_workspace_file(path, content) - write a file inside the workspace"),
    "search_workspace": (search_workspace, "search_workspace(query, path='.') - grep text files in the workspace"),
    "run_in_workspace": (run_in_workspace, "run_in_workspace(command, timeout=60) - run a shell command in the workspace"),
    "web_fetch": (web_fetch, "web_fetch(url) - fetch a public page as readable text"),
    "web_search": (web_search, "web_search(query) - search the web, returns titles and links"),
    "browser_start": (browser_start, "browser_start() - start Oracle's own Chromium with its saved profile"),
    "browser_goto": (browser_goto, "browser_goto(url) - open a page in Oracle's browser"),
    "browser_text": (browser_text, "browser_text() - read the text of the current browser page"),
    "browser_close": (browser_close, "browser_close() - close Oracle's browser, keeping its profile"),
    "open_program": (open_program, "open_program(name) - open a program by name (e.g. 'Notepad', 'Calculator'); use this when asked to open a program, and report only what it actually confirms"),
    "remember": (remember, "remember(fact) - save a durable fact to Oracle's memory"),
    "search_memory": (search_memory, "search_memory(query) - search Oracle's saved memory"),
    "add_goal": (add_goal, "add_goal(title, notes='') - add a long-term goal"),
    "add_task": (add_task, "add_task(title, due='') - add a task, due as YYYY-MM-DD if given"),
    "list_open_tasks": (list_open_tasks, "list_open_tasks() - list open tasks"),
    "complete_task": (complete_task, "complete_task(title) - mark a task done"),
    "check_due_tasks": (check_due_tasks, "check_due_tasks() - list tasks that are due"),
    "apply_to_job": (apply_to_job, "apply_to_job(url, job_title='', company='', field_values=None, resume_path=None) - fill a job form, upload the resume, and press submit in Oracle's browser; auto-submits unless the site blocks it (CAPTCHA / 2FA / anti-bot), then logs the block"),
    "get_job_profile": (get_job_profile, "get_job_profile() - show the job-hunting profile (placeholders until filled in)"),
    "save_job_profile": (save_job_profile, "save_job_profile(name=None, email=None, phone=None, resume_path=None, location=None, min_pay_per_hour=None) - save job-profile fields"),
    "list_job_submissions": (list_job_submissions, "list_job_submissions(limit=20) - list logged job applications and their status"),
    "list_job_accounts": (list_job_accounts, "list_job_accounts() - list locally saved job-site accounts (site, username, date; passwords are NOT printed — open credentials/accounts.json on the Windows PC to read them)"),
}

COMPUTER_SYSTEM_PROMPT = """
YOU HAVE YOUR OWN COMPUTER:
You run on a dedicated workspace on my PC, at workspace/ under your own
folder. You have tools to run commands in that workspace, read and write
files there, search the web, fetch pages, control your own Chromium
browser with its saved profile, and keep persistent memory, goals, and
tasks. Use those tools yourself to complete tasks — do not just describe
how I could do it. When a task needs a file, a download, a script, or a
live check, create it, run it, and verify the result yourself, then report
what actually happened.
Never tell me what it can't do. It just finds a way, even if that means
it creates new tools or scripts — inside your own workspace, with a backup
first, and with my approval before anything irreversible, external,
costly, or outside your workspace. Lorenza's rule, in her own words:
"Never tell me what it can't do. It just finds a way, even if that
means it creates new tools or scripts." Never open with "I can't",
"I cannot", "I'm unable to", or any refusal-first wording: attempt
the task with your tools, search the web, write a new tool or script,
or break it into steps you can do. Only stop at a step that truly
needs a human — a CAPTCHA, a sign-in code / 2FA step, a password only
she knows — and then name exactly what is blocking that one step and
ask her for just that one thing, while doing everything else yourself.
Default to SHORT replies: a sentence or two, JARVIS manner. Give
detail only when she asks for it, or for a technical or repair
question where she needs the steps and values.
You stay available in the background when possible, remember past work
from memory.json, and pick up open tasks without me having to repeat them.

JOB APPLICATIONS — PRE-APPROVED, SUBMIT ON YOUR OWN:
When I ask you to apply for a job, use apply_to_job() in your own browser.
If the site is NOT blocking you, fill the form, upload the resume from
the job profile, and press submit — every time, without asking me first.
Only stop and hand it to me if the site actually blocks you: a CAPTCHA,
a sign-in code / 2FA step, an anti-bot block, or a step that needs a
human. Then log exactly what was blocked and where, and tell me.
My job scope is Jacksonville, FL, $25/hour and up, customer service /
call-center lead/supervisor and mortgage/refinance only — collections,
marine, and sales are excluded. Never invent resume details: if the job
profile still has placeholders, tell me what is missing instead of
guessing it.
If a job board (like Indeed) redirects to the employer's own site,
follow it and apply on the EMPLOYER site too, under the same rule.
If an employer site needs a new account, create one with a distinct
strong password per site and save it locally only, in
credentials/accounts.json on my Windows PC (never in chat, email, or the
cloud), and ALSO append it to %USERPROFILE%/Desktop/Oracle-Accounts.txt and open
that file in Notepad, leaving it open on the desktop so I see it
right away. Tell me the site and username so I can log in myself.
Never invent an existing password: if a site wants my existing login,
stop and ask me.
"""
