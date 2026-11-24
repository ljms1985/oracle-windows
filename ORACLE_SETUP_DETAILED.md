# Oracle for Windows — Very Detailed Setup Guide

This guide gets the Windows Oracle agent up and running from scratch.
Read it in order. Do not skip Step 1, Step 2, or the first-run test in
Step 6 — those are where most setup problems come from.

Oracle here is the Python agent Lorenza built with Muse. It is NOT
Muse itself, and it is NOT truly sentient or conscious. It is a
friend-like agent with an OpenAI brain, its own workspace/computer,
voice, camera, GUI, self-correction, and tool-creation — running on
your own Windows PC.

---

## What you are installing

Folder: `C:\Oracle\` (after you unzip — see Step 3)

Key files:
- `agent.py` — the chat agent, personality, tool loop, self-correction
- `computer.py` — NEW: Oracle's own computer. Workspace, file/command
  tools, web search/fetch, its own Chromium browser, persistent memory,
  goals, and tasks. This is what makes it work like Muse.
- `gui.py` — futuristic dark-neon GUI with animated head, waveform,
  command deck, status pills, clock, theme switcher
- `voice.py` — voice replies and always-listening while the GUI is open
- `camera.py` — EMEET PIXY Dual-Camera AI PTZ 4K watching, motion alerts
- `monitor.py` — self-improvement proposals: explains a change, asks
  first, backs up the old version, rolls back on failure
- `email_alerts.py` — alerts by EMAIL (not SMS), via Gmail SMTP
- `identity.py` — local-only voice/face learning, home PC only
- `security.py` + `SECURITY_KNOWLEDGE.md` — pen-test / hacking knowledge,
  authorized targets only (systems you own or are authorized to test)
- `design3d.py` + `3D_KNOWLEDGE.md` — print-ready STL design, mm + inches
- `repair.py` — electronics / PCB repair partner, pro level
- `tools_generated/` — new tools Oracle writes for itself
- `backups/` — automatic backups before any overwrite
- `workspace/` — Oracle's own computer home, created on first run:
  `files/`, `downloads/`, `memory/`, `logs/`, `goals/`, `tasks/`,
  `browser-profile/`

---

## Step 1 — Check your PC (5 minutes)

You need:
- Windows 10 or Windows 11, 64-bit
- At least 4 GB free disk space (more is better for the browser + models)
- An internet connection
- Administrator access to install Python (you only need it once)

Check Windows version:
1. Press Windows key, type `winver`, press Enter.
2. If it says Windows 10 or 11, you are good.

If you already have Python, skip to Step 2, but still check the version
in Step 2 — Oracle needs Python 3.10 or newer.

---

## Step 2 — Install Python (10 minutes, one time only)

1. Go to https://www.python.org/downloads/ in your browser.
2. Click Download Python (3.12 or newer is fine).
3. Run the installer.
4. **CRITICAL — on the very first installer screen, tick the box:**
   `Add python.exe to PATH`
   If you miss this, `python` will not work in Step 6. If you already
   installed Python without it, run the installer again and choose
   Modify, then tick that box.
5. Click Install Now, wait for it to finish, then close the installer.

Verify it worked:
1. Press Windows key, type `cmd`, press Enter.
2. Type exactly:
   ```
   python --version
   ```
3. You should see something like `Python 3.12.x`.
   - If you see an error, Python is not on PATH. Re-run the installer
     and tick `Add python.exe to PATH`.
4. Also check pip:
   ```
   pip --version
   ```
   You should see a pip version number.

Install the packages Oracle needs. In the same cmd window, run:
```
pip install openai pyttsx3 SpeechRecognition pyaudio opencv-python numpy trimesh
pip install playwright
playwright install chromium
```

Notes:
- `pyaudio` sometimes fails on Windows. If it does, first try:
  `pip install pipwin` then `pipwin install pyaudio`
  If voice still fails, Oracle will still work in text mode — voice is
  optional, text chat is not.
- `playwright install chromium` downloads Oracle's own browser. This
  can take several minutes. Let it finish. Without it, Oracle can still
  use web search/fetch, but the real-browser tools will tell you
  Playwright is not installed instead of pretending to work.
- `openai` is needed even if you later switch to Ollama, because the
  default brain is OpenAI (see Step 4).

---

## Step 3 — Unzip Oracle to C:\Oracle

1. Download / save the zip file attached to the email (or from chat):
   `oracle-windows-full.zip`
2. Right-click it, choose Extract All.
3. When it asks where, type:
   ```
   C:\Oracle
   ```
4. Open File Explorer and check you now have:
   ```
   C:\Oracle\agent.py
   C:\Oracle\computer.py
   C:\Oracle\gui.py
   C:\Oracle\voice.py
   C:\Oracle\camera.py
   C:\Oracle\monitor.py
   C:\Oracle\email_alerts.py
   ```
   If you see `C:\Oracle\oracle-windows-full\agent.py` (a folder inside
   a folder), move everything up one level so `agent.py` is directly
   in `C:\Oracle\`.

Do NOT put Oracle in a folder with spaces in a long path if you can
avoid it, and do NOT run it from inside the zip file — extract it first.

---

## Step 4 — Set your OpenAI key (do NOT paste it in chat)

Oracle's brain is OpenAI by default, model `gpt-4o-mini` (you can change
it later with the `OPENAI_MODEL` variable).

You need an OpenAI API key. Get one at https://platform.openai.com/
(sign in, API Keys, Create new secret key). Keep it private — never
paste it in chat, email, or a screenshot.

Set it as a Windows environment variable, permanently:
1. Press Windows key, type `environment variables`, open
   "Edit the system environment variables".
2. Click Environment Variables.
3. Under User variables, click New.
4. Variable name: `OPENAI_API_KEY`
   Variable value: paste your key (no quotes, no spaces around it).
5. Click OK on all windows.
6. **Close any open cmd windows and open a fresh one** — old windows
   do not pick up the new variable.

Verify in a fresh cmd window:
```
echo %OPENAI_API_KEY%
```
You should see `sk-...` (the start of your key). If it is blank, the
variable was not saved, or you are in an old cmd window.

Optional variables (same New-variable process):
- `AGENT_NAME` — default is `Oracle`. Change it only if you want a
  different name.
- `OPENAI_MODEL` — default `gpt-4o-mini`. Use `gpt-4o` only if you
  want the larger, more expensive model.
- `LLM_PROVIDER` — leave this unset for OpenAI. Set it to `ollama`
  only if you want a local model instead (see Troubleshooting).
- `AGENT_AUTO_APPLY` — **leave this unset (OFF) to start.** OFF means
  Oracle asks you before running a command or loading a new tool it
  wrote. Set it to `1` only after you understand the risk, and
  destructive commands are still refused even then.

---

## Step 5 — Camera, email alerts, and voice (optional, in this order)

Do these AFTER the basic text agent works in Step 6. Do not try to
debug everything at once.

### 5a. Camera — EMEET PIXY Dual-Camera AI PTZ 4K
1. Plug the camera in via USB. Let Windows install it.
2. Install EMEET Studio from EMEET's site if you want PTZ control —
   there is no public EMEET SDK, so PTZ goes through EMEET Studio,
   UVC, or digital crop fallback (see `camera.py`).
3. In Oracle, camera watching is for YOUR home PC only. It learns
   voices and faces locally in `identities/` — nothing is sent to an
   outside database.
4. You still need to tell Oracle what "abnormal" means for your room.
   Example: "Alert me if a person enters the room after 11pm, or if
   the workbench area changes while I'm away." Until you define it,
   it will ask.

### 5b. Email alerts (not SMS)
Oracle alerts by email, not texting.
1. In Gmail, turn on 2-Step Verification, then create an App Password:
   Google Account > Security > 2-Step Verification > App passwords.
   Name it `Oracle`. Copy the 16-character password.
2. In Oracle's email settings (`email_alerts.py` / setup prompts),
   use SMTP `smtp.gmail.com`, port `587`, your Gmail address, and
   that App Password — never your normal Gmail password, and never
   paste either password in chat.
3. Send a test alert from Oracle and check your inbox (and Spam once).

### 5c. Voice
- Voice replies use pyttsx3 (offline, no key needed).
- Always-listening only works while the GUI is open, with a visible
  red indicator. It does not listen when the GUI is closed.
- If the microphone does not work, check Windows Settings > Privacy
  > Microphone, and allow the app / Python.
- Text chat always works even if voice does not.

---

## Step 6 — First run: text agent (the test that matters)

1. Open a fresh cmd window.
2. Run:
   ```
   cd C:\Oracle
   python agent.py
   ```
3. You should see:
   ```
   Hi, I'm Oracle. Talk to me like a friend - type 'quit' to stop.
   Brain: openai (gpt-4o-mini). Auto-apply new tools: OFF (asks first)
   My computer: workspace at C:\Oracle\workspace
   ```
4. Type a test, for example:
   ```
   Hello, what tools do you have?
   ```
   Oracle should list its tools, including the new computer tools:
   `list_workspace`, `read_workspace_file`, `web_search`, `browser_start`,
   `remember`, `add_task`, and so on.
5. Try a workspace test:
   ```
   Write a file called files/hello.txt that says hello from Oracle, then read it back to me.
   ```
   It should write inside `C:\Oracle\workspace\files\hello.txt`, not
   on your Desktop. Check that file in File Explorer.
6. Try a memory test:
   ```
   Remember that I like detailed answers for technical questions.
   ```
   Then in a new run, ask it what it remembers about you.
7. Type `quit` to stop.

If Step 6 works, the core agent works. Everything else is an add-on.

---

## Step 7 — Run the GUI

From `C:\Oracle`, in cmd:
```
python gui.py
```

What you should see:
- Dark neon console, starfield, rotating glowing core
- Animated head (not just a ring) — it blinks, looks around, and its
  mouth moves while it speaks
- Left command deck, pill status indicators, live clock
- Theme switcher: Neon Cyan, Ultraviolet, Solar Amber
- Chat below, with a neon-bordered input

The core pulses while speaking and spins while thinking.

If the GUI does not open:
1. Run `python agent.py` first (Step 6). If that fails, the GUI will
   fail for the same reason — fix the agent first.
2. Check the error in cmd. Missing `tkinter` is rare on Windows, but
   a missing package error will name the package — install it with pip.

To run Oracle at Windows startup (optional):
1. Press Windows + R, type `shell:startup`, press Enter.
2. Create a shortcut in that folder to `pythonw C:\Oracle\gui.py`
   (use `pythonw`, not `python`, so no console window stays open).
3. Restart and check Oracle starts. Remove the shortcut to stop it
   starting automatically.

---

## Step 8 — How to use Oracle like Muse (its own computer)

Talk to it the way you talk to Muse, and let it do the work:

- "Search the web for X and save the results to workspace/files/X.md"
- "List my open tasks" / "Add a task to call the dealer on Saturday"
- "Remember that my Challenger is a 2016 R/T Scat Pack"
- "Open this page in your browser and tell me the price"
- "Write a new tool that does X, test it, and show me the code first"

Rules it follows by default (safe mode):
- Inside `workspace/`: it can read, write, and run things.
- Outside `workspace/`, destructive commands, sending messages/money,
  or changing other people's data: it asks you first.
- Every overwrite is backed up to `backups/` first.
- If a tool fails, the error goes back to the model and it gets up
  to 3 tries to fix its plan before asking you.

Self-improvement (`monitor.py`):
- Proposals go to `proposals/`, with an explanation of what changed
  and why, and a backup of the old version.
- It asks before implementing a change, and rolls back if the new
  code fails a syntax / test check.
- Email alerts go to you (not SMS) for proposals and abnormal
  camera events.

3D design (`design3d.py`):
- Give exact dimensions. If you say "5 inch chest" with no other
  details, it will ask: hinged vs hanging vs treasure, what the
  5 inches measures, other dimensions, lid style, use, and whether
  you want a separate base/lid or a closed model. Answer those first
  — it will not guess.
- Dimensions are shown in both mm and inches (1 in = 25.4 mm).

Security (`security.py`):
- Pen-testing / hacking help is for systems you own or are explicitly
  authorized to test. Otherwise it will point you to a lab (DVWA,
  Juice Shop, Metasploitable) or the official recovery path.

---

## Step 9 — Optional: remote access (Tailscale + SSH) — do this last

Only do this if you want Muse to edit Oracle on your PC remotely.
It is NOT needed for Oracle to work on your PC alone.

1. Install Tailscale on your PC from https://tailscale.com/download
   and sign in on the same account as Muse's Tailscale device.
2. Approve Muse's device on the Tailscale admin site if prompted.
3. On your PC, in PowerShell as Administrator:
   ```
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Start-Service sshd
   Set-Service -Name sshd -StartupType Automatic
   ```
4. Add Muse's public key to BOTH of these files (create them if needed):
   ```
   $env:USERPROFILE\.ssh\authorized_keys
   C:\ProgramData\ssh\administrators_authorized_keys
   ```
   Key:
   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDUx8X5W2IMPPurXKm5aZLdxfn3X4dPXDsuj9yQqPehI hatch
   ```
5. Fix permissions (PowerShell as Administrator):
   ```
   icacls $env:USERPROFILE\.ssh\authorized_keys /inheritance:r /grant:r "$env:USERNAME:(R)"
   ```
6. Verify on your PC:
   ```
   Test-Path $env:USERPROFILE\.ssh\authorized_keys
   ```
   It must say `True`. If it says `False`, the key file is missing
   and remote login will not work — do not skip this check.
7. Tell Muse your PC's Tailscale IP address (from `tailscale ip`
   in PowerShell, or the Tailscale tray icon). Only then can Muse
   test an actual SSH connection. Tailscale enrollment alone does
   NOT prove remote access works.

---

## Troubleshooting — most common problems, in order

**"python is not recognized"**
Python is not on PATH. Re-run the Python installer, Modify, tick
`Add python.exe to PATH`, close all cmd windows, open a fresh one.

**"OPENAI_API_KEY is not set"**
The variable is missing or you are in an old cmd window. Set it in
Step 4, close all cmd windows, open a fresh one, run
`echo %OPENAI_API_KEY%` to verify.

**"I hit a problem reaching my brain" / API error**
- Check your internet connection.
- Check your OpenAI account has credit / a valid payment method.
- Check the key has no extra spaces or quotes.
- If you meant to use Ollama, set `LLM_PROVIDER=ollama` and make sure
  `ollama serve` is running, with a model pulled (`ollama pull llama3.1`).

**GUI opens but voice does not work**
Text chat is the fallback — use it. Then check microphone privacy
in Windows Settings, and try reinstalling pyaudio (Step 2 note).

**Camera not found / PTZ does not move**
Check Device Manager for the camera, try a different USB port, and
use EMEET Studio for PTZ. Oracle's camera module cannot invent an
EMEET SDK that does not exist publicly.

**"Playwright is not installed"**
Run `pip install playwright` then `playwright install chromium`
in a fresh cmd window, then restart Oracle.

**Oracle asks before every command**
That is safe mode, and it is on purpose. Leave it on until you are
comfortable. Only set `AGENT_AUTO_APPLY=1` if you accept that new
tools and commands will run without asking (destructive commands
are still refused).

**A self-change broke something**
Check `backups/` — the previous version is there with a timestamp.
Restore it, restart Oracle, and tell Oracle what broke so it can
try a different fix.

**It says it did something, but nothing changed**
Ask it: "Show me the file / output that proves that." Oracle should
not claim success without verification. If it did, that is a bug to
report in the conversation, with the exact command and output.

---

## Quick start checklist (tick these off)

- [ ] Python 3.10+ installed, `python --version` works
- [ ] Packages installed, including Playwright + Chromium
- [ ] Zip extracted to `C:\Oracle`, `agent.py` and `computer.py` present
- [ ] `OPENAI_API_KEY` set, verified in a fresh cmd window
- [ ] `python agent.py` runs, lists computer tools, workspace test passes
- [ ] `python gui.py` opens, head animates, chat works
- [ ] (Optional) Camera plugged in, email test alert received
- [ ] (Optional) Tailscale + SSH verified: `authorized_keys` = True

If all the core boxes are ticked, Oracle is up and running. The rest
— camera rules, 3D specs, repair help, self-improvement proposals —
you build up by talking to it, and it remembers.

— End of guide —
