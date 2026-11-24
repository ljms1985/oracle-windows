# Oracle — Very Detailed Step-by-Step Windows Setup Guide

This guide gets the Oracle Python agent (the one built for Lorenza's
Windows PC, also called Friend Agent) from a folder of code to a
running program on your PC. Follow it in order. Do not skip the
environment-variable steps — Oracle will not start correctly without
an OpenAI key, and email/camera features will not work without theirs.

## 1. What you need before you start

- A Windows 10 or 11 PC.
- An internet connection for downloads and for Oracle's brain.
- An OpenAI account and an OpenAI API key. Keep that key private.
  Never paste it into a chat, an email, or a shared document. It is
  set only as a Windows environment variable on your own PC.
- Optional, only if you want those features:
  - A Gmail account, and a Gmail App Password (not your normal Gmail
    password) for email alerts and improvement proposals.
  - An EMEET PIXY Dual-Camera AI PTZ 4K camera, with EMEET Studio
    installed, for camera watch.
  - A microphone and speakers/headphones for voice.

## 2. Install Python

1. Go to python.org/downloads and download Python 3.10 or newer
   (3.11 or 3.12 is fine) for Windows.
2. Run the installer.
3. On the first installer screen, tick "Add python.exe to PATH".
   This is essential. Without it, `python` will not work in a terminal.
4. Click Install, then Finish.
5. Test it: press Windows key, type `cmd`, open Command Prompt, type:
   ```
   python --version
   ```
   You should see something like `Python 3.12.x`. If you see an error,
   reinstall and make sure the PATH box was ticked.

## 3. Create the folders

Oracle expects one main folder, with subfolders created automatically
on first run for some things, and a few you create by copying the code.

1. Create the main folder, for example:
   ```
   C:\friend-agent
   ```
2. Copy every code file listed in Section 4 into `C:\friend-agent`.
   Keep the exact filenames — the code imports by filename.
3. These subfolders are created automatically when Oracle runs, but
   you can also create them now so you can see where things go:
   ```
   C:\friend-agent\tools_generated
   C:\friend-agent\backups
   C:\friend-agent\identities
   C:\friend-agent\proposals
   C:\friend-agent\alerts
   C:\friend-agent\repairs
   C:\friend-agent\prints
   ```
   What each folder is for:
   - `tools_generated\` — new tools Oracle writes for itself, each a
     `.py` file with a `run()` function. Only loaded after approval
     unless auto-apply is on.
   - `backups\` — automatic copies made before any file is overwritten.
   - `identities\` — local voice/face profiles, one subfolder per person.
     Local only, never sent to an outside identification service.
   - `proposals\` — internet self-improvement proposals, awaiting YES.
   - `alerts\` — camera snapshots saved when motion triggers an alert.
   - `repairs\` — repair session logs, one markdown file per repair.
   - `prints\` — STL files Oracle creates for 3D printing.

## 4. The full file list — what goes where

All of these files go directly in `C:\friend-agent\` (not in subfolders),
unless a subfolder is named:

Main program and interface:
- `agent.py` — chat loop, personality, tools, self-correction,
  self-extension. Run this for terminal Oracle.
- `gui.py` — Gideon-inspired GUI: dark console, glowing cyan ring /
  waveform, transcript, voice buttons, camera buttons, repair buttons.
  Run this for visual Oracle. Requires only tkinter, which ships with
  Python on Windows, plus Pillow for the avatar image
  (`assets/avatar.png` — Lorenza's chosen red-and-black anime avatar;
  see `AVATAR_NOTES.md`). If Pillow or the image is missing, the GUI
  falls back to the drawn vector head and still runs.
- `voice.py` — text-to-speech and speech-to-text helpers used by GUI.

Knowledge and specialty modules:
- `design3d.py` — 3D design and STL writer, mm and inches, chest
  questions, print validation, improvement suggestions.
- `3D_KNOWLEDGE.md` — 3D printing rules Oracle uses.
- `repair.py` — repair assistant, generic repair flow plus the
  Apollo Twin USB won't-turn-on example.
- `security.py` — pen testing / hacking concepts / jailbreaking
  knowledge, with an authorization gate.
- `SECURITY_KNOWLEDGE.md` — security methodology and tool notes.
- `camera.py` — PIXY camera watch, motion detection, PTZ attempts,
  snapshot and email alert logic.
- `identity.py` — voice/face learning and matching, local only.
- `monitor.py` — internet self-improvement monitor, proposals only,
  never auto-applies without a clear YES.
- `email_alerts.py` — SMTP email sending and IMAP reply checking.
- `sms.py` — retained Twilio SMS code. Not used by default anymore;
  email replaced it. Keep it only if you ever want SMS back.
- `README.md` — project overview, quick start, and feature notes.
- `SETUP_GUIDE.md` — this file.

Files created on first run (do not copy these, they are made for you):
- `memory.json` — facts and preferences Oracle learns.
- `__pycache__\` — Python bytecode cache, ignore it.

## 5. Install the Python packages

Open Command Prompt, go to the folder, and install in groups so you
can see which group fails if one does:

```
cd C:\friend-agent
pip install pyttsx3 SpeechRecognition PyAudio
pip install opencv-python pillow
```

Notes:
- `PyAudio` can be awkward on Windows. If `pip install PyAudio`
  fails, download the matching `.whl` for your Python version from
  a trusted wheel source and install that file with
  `pip install <filename>.whl`, then retry.
- Voice, camera, and face features need their packages. The core
  chat in `agent.py` and the STL writer in `design3d.py` need no
  extra packages beyond Python itself.
- Optional face recognition: `pip install face_recognition` — this
  can be hard on Windows because it needs dlib. If it fails, Oracle
  still works with voice + face detection + co-occurrence learning,
  it just will not have 128-d face encodings.

## 6. Set the OpenAI key (the brain)

Oracle uses OpenAI by default, model `gpt-4o-mini` unless you change it.

For one terminal session only (good for testing):
```
set OPENAI_API_KEY=your-key-here
```
In PowerShell for one session:
```
$env:OPENAI_API_KEY="your-key-here"
```

Permanently, so every terminal and the GUI see it:
1. Settings > System > About > Advanced system settings >
   Environment Variables.
2. Under User variables, New: Name `OPENAI_API_KEY`, Value your key.
3. OK out of all dialogs, then open a NEW Command Prompt.

Optional model change:
- Environment variable `OPENAI_MODEL`, e.g. `gpt-4o-mini` (default).
- Agent name: `AGENT_NAME` (default `Oracle`).
- Local alternative, only if you later want it: set
  `LLM_PROVIDER=ollama`, install Ollama, run
  `ollama pull llama3.1` and `ollama serve`. You do not need this
  if you are using OpenAI.

Test the brain:
```
cd C:\friend-agent
python agent.py
```
Type a question, for example "Explain what a power rail is in
electronics repair, in detail." Oracle should give a detailed answer.
Type `quit` to stop. If it says the API key is not set, your
environment variable is not visible in that terminal — open a new
terminal after setting it permanently.

## 7. Run the GUI

```
cd C:\friend-agent
python gui.py
```

You should see a dark window, a glowing cyan ring, status ONLINE,
a transcript area, and an input row. While it thinks, the ring spins.
In the centre is Lorenza's chosen Muse avatar (red-and-black anime
figure, long spiky black hair, red gi) — it bobs, blinks, looks
around, nods, and its mouth moves while Oracle speaks. If the avatar
image is missing you will see the original drawn head instead; see
`AVATAR_NOTES.md`.
While it speaks, the waveform animates and text types out.

GUI buttons to try, in order:
- Speak replies ON/OFF — hear replies aloud.
- Always listen ON/OFF — mic on, no wake word, red LISTENING label.
  Tap again to pause instantly. Note: any nearby speech or TV can
  trigger it, and starter transcription sends audio to Google.
- Check for improvements — runs the monitor, saves a proposal.
- Start camera watch — see Section 9.
- Start Apollo Twin repair / Look at board — see Section 10.
- Enroll voice / List enrolled / Delete identity — see Section 11.

## 8. Set up email alerts and improvement approvals (optional, recommended)

Email replaced SMS for Oracle. Set these on your PC, never in chat:

- `ALERT_EMAIL_TO` — the email Oracle should send alerts to.
- `ALERT_EMAIL_FROM` — the sender address, usually your Gmail.
- `SMTP_USER` — your Gmail address.
- `SMTP_PASS` — a Gmail App Password, NOT your normal Gmail password.
  Get it at: Google Account > Security > 2-Step Verification >
  App passwords. If you do not see App passwords, turn on 2-Step
  Verification first.
- `SMTP_HOST` — default `smtp.gmail.com`.
- `SMTP_PORT` — default `587`.

Optional reply checking (so Oracle can read a YES reply by email):
- `IMAP_HOST`, `IMAP_USER`, `IMAP_PASS` — same Gmail App Password
  approach, IMAP host usually `imap.gmail.com`.

How approval works:
- An improvement proposal is explained by email, and Oracle changes
  NOTHING unless you reply with a clear YES, approve in the GUI, or
  create a `proposals\<name>.approved` file.
- Camera alerts are emailed with a detailed description, only after
  motion passes the threshold while armed.

## 9. Set up the camera — EMEET PIXY (optional)

1. Plug in the PIXY, install EMEET Studio from EMEET, and confirm
   the camera works in Studio first.
2. Keep EMEET Studio AI tracking ON if you want the camera itself
   to pan and tilt to follow people. There is no public EMEET SDK,
   so Oracle cannot drive the motor directly through an official API.
3. In Oracle's GUI, use Start camera watch.
4. Oracle will try DirectShow UVC pan/tilt/zoom and will tell you
   honestly in the GUI whether that worked. If it did not, it uses
   digital framing inside the frame, and Studio tracking does the
   physical movement.
5. Motion settings in `camera.py`: `MOTION_MIN_AREA` default 5000,
   alert cooldown default 300 seconds (5 minutes).
6. Vision descriptions: set `CAMERA_VISION=1` only if you want a
   snapshot sent to OpenAI Vision for a detailed description. If
   this is off, alerts are motion-only and no snapshot leaves your PC.
7. Privacy: use Privacy mode in the GUI to stop the watch and tilt
   down if PTZ works. For guaranteed privacy, unplug the camera.

## 10. Use the repair assistant

Terminal:
```
python repair.py
```
Or use the Repair buttons in the GUI.

The flow for any device is the same:
1. Safety: unplug from mains before opening. Do not open a mains
   power brick itself — test it from outside, replace it if faulty.
2. Tell Oracle the device and symptom.
3. Answer one question at a time. Oracle branches on your answer.
4. Point the PIXY at the board and say "look at this" for a visual
   description: burnt marks, swollen caps, cracked solder, loose
   connectors — then confirm if it matches what you see.
5. Oracle searches the web for that model + symptom when it does
   not already know a verified value, and tells you the source
   before you act. It does not guess voltages or fuse ratings.
6. Everything is logged to `repairs\<device>-<date>.md`.

Apollo Twin USB example already built in:
- Barrel fully inserted, then twist to lock, switch ON, wall socket
  confirmed with another device.
- PSU: 12VDC, 1.5A, center positive, 5.5 mm outside / 2.1 mm inside.
  Do not use the Thunderbolt Twin X 4.2A supply.
- Hardware reset, only after power checks: hold LEVEL KNOB + LOW CUT
  + POLARITY, power on while holding, release after front LEDs
  flash rapidly for several seconds.

## 11. Voice and person learning (home mode)

This runs on your personal PC in your home, as you asked:
- Enroll voice in the GUI: give a name, record a short sample.
  That name + sample is enrollment, stored in
  `identities\<name>\` locally.
- Oracle then matches new speech automatically, and matches faces
  in camera frames automatically if face recognition is installed.
- If a known voice is heard with an unknown face in view, Oracle
  learns that face for that voice. If a known face is seen with a
  new voice, it learns that voice for that face. Over time they
  reinforce each other.
- Delete identity in the GUI removes that person's folder entirely.

## 12. 3D design and STL files

Terminal test:
```
python design3d.py
```
This creates test files in `prints\`.

Ask Oracle for a part in mm or inches — it converts 1 in = 25.4 mm
exactly, builds the STL in mm (slicers expect mm), and shows you both
units, e.g. "127.0 mm (5.00 in)".

For vague requests, Oracle asks first instead of guessing. Example,
a "5 inch chest": hinged, hanging, or treasure? What does 5 inch
measure — length, width, or height? Other dimensions? Lid style?
What will it hold? Separate base + lid, or one closed model?
Only then does it write the STL(s) to `prints\`, ready for
PrusaSlicer, Cura, or OrcaSlicer.

Oracle also suggests improvements (fillets, ribs, chamfers, lips,
orientation) and applies each one only after you say yes.

## 13. Security knowledge — authorized testing only

Oracle knows pen testing methodology, tools, PIN/password testing
for your own accounts in a lab, hardening, and jailbreaking/rooting
your own device. Before any active test it asks: do you own the
target or have written authorization? If not, it stops that step
and helps you build a lab instead (VMs, DVWA, Juice Shop,
Metasploitable). It will not help break into someone else's device,
account, network, or PIN.

## 14. Troubleshooting

- `python` not recognized: reinstall Python with "Add python to PATH".
- API key not set: set it permanently, then open a NEW terminal.
- GUI does not open: run `python agent.py` first to test the brain
  without the GUI, then check for a tkinter error in the terminal.
- Voice does not hear you: check Windows microphone permission for
  the terminal/Python, and that the correct mic is default.
- PyAudio install fails: use a matching wheel file, see Section 5.
- Camera not found: confirm it works in EMEET Studio first, then
  try Oracle's camera watch. DirectShow camera index may differ.
- Email not sending: check the App Password (not normal password),
  SMTP host/port, and that 2-Step Verification is on.
- Oracle gives a short answer: ask it to go into detail — its
  instruction is to give detailed answers to questions, especially
  technical ones.

## 15. Safety defaults — do not change these lightly

- `AGENT_AUTO_APPLY=1` turns OFF the ask-before-running and
  ask-before-loading-new-tools safety. Keep it off to start.
- Destructive commands are refused even in auto-apply mode.
- Internet code is never auto-applied. A proposal needs a clear YES.
- Always-listening is visible, with a red LISTENING label, and can
  be paused instantly. Do not run it hidden.

End of guide. You now have Oracle running on Windows, with chat,
GUI, voice, camera, repair, 3D, and security help in one folder.
