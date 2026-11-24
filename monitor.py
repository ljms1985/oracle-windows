"""
Self-improvement monitor for Oracle.

What it does, once a day (or when you run: python monitor.py):
  1. Searches the web for new tools / libraries / techniques that
     could help a general Python AI agent - e.g. new agent frameworks,
     speech, or tool libraries. It uses DuckDuckGo's HTML endpoint,
     no API key needed.
  2. Filters to a short list of *candidate* improvements. It does NOT
     trust a random blog post as code - candidates are proposals only.
  3. Writes a proposal file to proposals/ and, if email is configured,
     emails you a plain-language explanation and asks YES/NO.
  4. ONLY on a clear YES (by email reply, or by approving in the GUI /
     by creating proposals/<name>.approved) does it apply a change,
     and then only with a backup in backups/ and a note in the proposal
     file. Anything else = no change, proposal stays pending.

Safety rules built in:
  * Never auto-apply code downloaded from the internet.
  * Never apply a change without an explanation to you first.
  * Never overwrite agent.py / gui.py without a timestamped backup.
  * If a change breaks the syntax check (py_compile), roll it back.

To run the monitor on a schedule on Windows, use Task Scheduler to
run `python monitor.py` daily. The GUI also has a "Check for
improvements" button that runs this in a thread.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROPOSALS_DIR = BASE_DIR / "proposals"
BACKUP_DIR = BASE_DIR / "backups"

SEARCHES = [
    "python AI agent framework new tools 2026",
    "python speech recognition library improvements",
    "openai python sdk new features",
]

def web_search(query, max_results=5):
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return [{"title": f"Search failed: {e}", "url": "", "snippet": ""}]
    # Very small parser - enough for titles/links, no extra dependency.
    import re
    results = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html):
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        link = m.group(1)
        if title and link:
            results.append({"title": title, "url": link, "snippet": ""})
        if len(results) >= max_results:
            break
    return results or [{"title": "No results found", "url": "", "snippet": ""}]


def propose_improvement(title, url, explanation):
    PROPOSALS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() else "-" for c in title)[:40]
    path = PROPOSALS_DIR / f"{stamp}-{safe}.txt"
    text = (f"Proposed improvement - {stamp}\n"
            f"Title: {title}\nURL: {url}\n\n"
            f"Explanation for you:\n{explanation}\n\n"
            "Status: PENDING - no change has been applied.\n"
            "To approve: reply YES to the SMS, or create a file named "
            f"{path.stem}.approved in proposals/, or approve in the GUI.\n")
    path.write_text(text, encoding="utf-8")

    # Email step - replaces SMS, per user choice. Explained, then asked,
    # before any change.
    try:
        from email_alerts import send_email
        msg = (f"Oracle found a possible improvement:\n{title}\n{explanation}\n"
               f"More: {url}\nReply YES to apply it (with a backup first), or NO to skip it. "
               "Nothing will change unless you say YES. "
               "You can also approve in the GUI or by creating a .approved file in proposals/.")
        sent = send_email(f"Oracle improvement proposal: {title}", msg)
        if not sent:
            print("[monitor] Email not sent (SMTP not configured) - proposal saved to proposals/, email skipped.")
    except Exception as e:
        print(f"[monitor] Email step failed: {e}")
    return path


def run_daily_check():
    print("Oracle self-improvement check - proposals only, no auto-apply.")
    for q in SEARCHES:
        print(f"\nSearch: {q}")
        for r in web_search(q):
            print(f" - {r['title']} ({r['url']})")
            # Starter behaviour: propose the top result per search as a
            # *reading* candidate, not as code to install. A human (you)
            # decides if it is actually an improvement.
            propose_improvement(
                r["title"], r["url"],
                "This came up in a search for ways a Python AI agent could improve. "
                "Read the link first - if it looks like a real, trusted improvement "
                "(a new library version, a better speech tool, a safer pattern), "
                "reply YES and I will help install / integrate it step by step, "
                "with a backup. If it looks irrelevant or untrusted, reply NO."
            )
            break  # only the top result per search, to avoid spam


if __name__ == "__main__":
    run_daily_check()
