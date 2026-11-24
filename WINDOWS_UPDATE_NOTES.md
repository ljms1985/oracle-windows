# Windows Oracle — Job-Hunting Update (v2), 2026-11-24

Parity update: the Windows agent now has the SAME new job-hunting
capabilities as the Mac version (`~/workspace/oracle-mac/computer.py`).
Everything the Mac version can do, the Windows version can do.
Only `computer.py` changed; voice, camera, GUI, repair, 3D, security,
monitor, email alerts and SMS are untouched.

## What changed (all in `computer.py`)

1. **Browser form-fill + submit tool** — new `apply_to_job(url,
   job_title, company, field_values, resume_path)` using Playwright:
   fills fields (by label / placeholder / name / id), uploads the
   resume via `input[type='file']`, and clicks Submit / Apply /
   Apply Now. The old tools (`browser_start`, `browser_goto`,
   `browser_text`) could only open and read pages; they could not
   fill or submit a form.
2. **Auto-submit rule (Lorenza, 2026-11-24)** — if a site is NOT
   blocking it, Oracle fills the form and presses submit every time,
   without asking first. `apply_to_job()` is deliberately NOT gated
   by `require_approval()` / `AUTO_APPLY`; submitting a job
   application is the one external action Lorenza pre-approved.
   Only if a site actually blocks it (CAPTCHA / reCAPTCHA / hCaptcha,
   sign-in code / 2FA, anti-bot / access-denied, human-verification)
   does it stop, hand the application to Lorenza, and log exactly
   what was blocked and where.
3. **Follow redirects to employer sites** — `_follow_external_apply()`
   clicks "Apply on company site" / "Apply externally" / similar, so
   an Indeed listing that redirects to the employer's own site is
   filled and submitted on the EMPLOYER site too, under the same
   auto-submit rule. The final (employer) URL is what gets logged.
4. **Account creation** — `_handle_account_creation()` handles a
   sign-up gate: if the site offers sign-up, Oracle creates an
   account with the profile email as username and a distinct strong
   16-character password per site (`_generate_strong_password()`).
   If the site only offers sign-in with an EXISTING account, Oracle
   stops and asks Lorenza — it never invents an existing password.
5. **Local-only credentials store** — accounts are saved only on her
   own Windows PC in `<agent folder>\credentials\accounts.json`
   (`CREDENTIALS_DIR`, created at import; `os.chmod` 0700/0600 calls
   are best-effort on Windows, which has no Unix file modes).
   Never in chat, email, or the cloud. Passwords are never printed
   in a reply — `list_job_accounts()` shows site / username / date
   only.
6. **Desktop visibility (Lorenza's explicit choice)** — every account
   created is ALSO appended (never overwritten) to
   `%USERPROFILE%\Desktop\Oracle-Accounts.txt` and that file is opened
   in **Notepad** (`notepad.exe`) and left open on the desktop, so she
   sees it as soon as she looks at the desktop. That file is plain
   text, so anyone who can see the desktop / screen will also see
   those passwords in plain text — that is the trade-off she chose
   for visibility. The secure local store is still the canonical copy.
7. **Submissions log + job profile** — `workspace/jobs/submissions.json`
   logs every attempt (job, company, site, date/time, status
   `submitted` / `submitted_unconfirmed` / `blocked`, confirmation
   text if shown, blocked reason, fields filled/unfilled, resume
   note, account created). `list_job_submissions()` reads it.
   `workspace/jobs/profile.json` (`get_job_profile()` /
   `save_job_profile()`) holds the job-hunting profile: name, email,
   phone, resume_path, location Jacksonville, FL, min $25/hour,
   scope customer service / call-center lead/supervisor and
   mortgage/refinance, excluded collections / marine / sales.
   **All personal fields are placeholders — fill them on first run
   on the Windows PC. No resume details and no existing Indeed
   password were invented.**
8. **Tool registry + system prompt** — `apply_to_job`,
   `get_job_profile`, `save_job_profile`, `list_job_submissions`,
   `list_job_accounts` are registered in `COMPUTER_TOOLS` (which
   `agent.py` imports dynamically, so they are available to the agent
   with no `agent.py` change), and the job-applications rule is in
   `COMPUTER_SYSTEM_PROMPT`.

## Testing done (2026-11-24, Linux, Python 3.12.3)

- `python3 -W error::SyntaxWarning -m py_compile` on **all 12**
  `.py` files in `~/workspace/friend-agent/`: **all pass, no
  warnings** (one invalid-escape warning in a docstring was found
  and fixed; the Mac file's `open`/TextEdit calls were replaced
  with `notepad.exe`; no "Mac"/"TextEdit" references remain in
  `computer.py`).
- Runtime smoke test in a temp copy (`/tmp/win-smoke`): importing
  `computer` registers all 5 new tools; `get_job_profile()` returns
  the placeholder profile (Jacksonville, $25/hr, scope/excluded as
  above); `_generate_strong_password()` returns a 16-char password
  meeting the strength rules; `_log_submission()` +
  `list_job_submissions()` round-trip correctly;
  `list_job_accounts()` reports no accounts yet; the system prompt
  contains the auto-submit rule and the Notepad instruction;
  `apply_to_job` is not gated by `require_approval`.

## Still needs testing on a real Windows PC (not tested here)

- Playwright + Chromium install (`pip install playwright`,
  `playwright install chromium`) and a live `apply_to_job()` run
  against a real job board / employer site (form filling, resume
  upload, submit click, redirect following, CAPTCHA detection).
- Account creation end-to-end: Notepad opening
  `%USERPROFILE%\Desktop\Oracle-Accounts.txt` and leaving it open.
- GUI (`gui.py`) and voice/camera on Windows — untouched by this
  update, but not re-tested here.
- Fill in the job profile on first run (name, email, phone,
  `resume_path` to a real resume file) before any real application.
