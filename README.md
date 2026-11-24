# Friend Agent — for Windows, in Python

A starter general-purpose agent that talks like a friend, uses tools,
self-corrects when a tool fails, and can write new tools for itself.

**Honest limits first:**
- This is not truly sentient. No AI today is. It *feels* friend-like
  because of its personality prompt, memory file, and consistent tone.
- It cannot do literally any task. It can do tasks it has tools and
  information for, and it can learn new tools — but it still needs a
  language model, permissions, and your approval for risky actions.
- It is not a copy of Muse. Muse runs on Meta's infrastructure with
  many connected services. This is a small, local version you own and
  can shape.

## Quick start on Windows

1. Install Python 3.10+ from python.org, ticking "Add python to PATH".
2. Copy this folder to your PC, e.g. `C:\friend-agent`.
3. Brain — OpenAI (chosen):
   Set `OPENAI_API_KEY` as a Windows environment variable on your PC
   (Settings > System > About > Advanced system settings > Environment
   Variables, or in PowerShell for one session:
   `$env:OPENAI_API_KEY="your-key-here"`).
   Do NOT paste your key into a chat. The default model is `gpt-4o-mini`;
   change it with `OPENAI_MODEL=...` if you want a different one.
   Alternative, if you later want local: set `LLM_PROVIDER=ollama`,
   install Ollama, and run `ollama pull llama3.1` + `ollama serve`.
4. Run it:
   ```
   python agent.py
   ```
   Or, for the Gideon-inspired GUI:
   ```
   python gui.py
   ```
   That opens a modern, futuristic console — deep-space background
   with a starfield, a rotating glowing core with orbiting particles
   and a live waveform, a left command deck for voice / camera /
   repair / people / system, pill status indicators, a live clock,
   and a theme switcher (Neon Cyan, Ultraviolet, Solar Amber).
   The core pulses while Oracle is speaking, spins while thinking,
   and the chat sits below it with a neon-bordered input. Still
   tkinter only, no extra packages.
   The face in the console is Lorenza's chosen Muse avatar — the
   red-and-black anime figure (long spiky black hair, red gi) from
   `assets/avatar.png`. It bobs idly, blinks, looks around, nods,
   and its mouth moves while Oracle speaks, just like Muse's avatar
   runs. If the image is missing, the GUI falls back to the original
   vector head drawn in code. See `AVATAR_NOTES.md`.

## How the pieces work

- `agent.py` — the whole agent: chat loop, personality, tools,
  self-correction loop (3 tries, error fed back to the model), and
  self-extension via `tools_generated/`.
- `computer.py` — Oracle's own computer, Muse-style: a workspace it owns
  (`workspace/files/`, `downloads/`, `memory/`, `logs/`, `goals/`,
  `tasks/`, `browser-profile/`), file/command tools inside that workspace,
  web search/fetch, its own Chromium browser via Playwright, and
  persistent memory, goals, and tasks that survive restarts.
  For the real browser, install once on your PC:
  `pip install playwright` then `playwright install chromium`.
- `memory.json` — created on first run. Stores facts/preferences the
  agent learns. Edit it by hand if you want to correct it.
- `tools_generated/` — new tools the agent writes. Each is a `.py` file
  with a `run()` function.
- `backups/` — automatic backups before any file overwrite, including
  before a generated tool replaces an old one.

## Safety — read this before turning auto-apply on

By default, the agent **asks you before**:
- running any shell command, and
- loading a newly written tool.

That is deliberate. An agent that rewrites its own code with no checks
can break itself, delete things, or run untrusted code. Keep the
default unless you understand the risk.

To allow auto-apply (not recommended to start):
```
set AGENT_AUTO_APPLY=1
```
Destructive-looking commands (format, forced delete, shutdown, etc.)
are still refused.

## Make the personality yours

Edit the `PERSONALITY` text at the top of `agent.py`. Change the name
with `AGENT_NAME=...`, change the humour, the formality, the catchphrases.
That single prompt is most of what makes it feel like a friend rather
than a robot.

## Voice, always-listening, and self-improvement (new)

**Voice:** Install `pip install pyttsx3 SpeechRecognition PyAudio`, then
run `python gui.py`. Use "Speak replies: ON" to hear replies aloud,
and "Always listen: ON" to have Oracle transcribe speech with no wake
word. That toggle is deliberately visible, with a red LISTENING label,
and tapping it again pauses the mic instantly. Always-listening means
anyone nearby, a TV, or a podcast can trigger it, and the starter
transcription sends audio to Google Speech Recognition — swap in an
offline recogniser (e.g. Vosk) if you do not want that.

**Self-improvement monitor:** Run `python monitor.py`, or use
"Check for improvements" in the GUI. It searches the web for candidate
agent improvements, writes a proposal to `proposals/`, and — if you
have email set up — emails you a plain explanation asking YES/NO.
Nothing changes unless you say YES clearly. If email is not set up,
the proposal is still saved and shown in the GUI, and you approve
there instead. See `email_alerts.py` for SMTP setup (Gmail App
Password, etc. — never paste passwords in chat).

**Email alerts (replaces SMS):** Set on your PC:
`ALERT_EMAIL_TO` (your email), `SMTP_USER`, `SMTP_PASS` (Gmail App
Password, not your normal password), with `SMTP_HOST=smtp.gmail.com`
by default. Camera alerts and improvement proposals now go by email,
not by text message. `sms.py` is still in the folder if you ever want
Twilio back, but it is no longer used by default.

**Safety for both:** Never auto-apply code from the internet, never
run always-listening hidden, and always back up before a change.
`monitor.py` checks syntax before applying and rolls back on failure.

## Camera watch - EMEET PIXY

Install `pip install opencv-python` (and `pillow` for preview work later),
plug in the PIXY, and in the GUI use "Start camera watch".

What Oracle does:
- Captures video locally with OpenCV (DirectShow on Windows).
- Runs motion detection locally. Nothing leaves your PC until motion
  passes a threshold while armed.
- Then it saves a snapshot to `alerts/`, asks OpenAI Vision for a
  detailed description (only if `CAMERA_VISION=1` and you have an
  OpenAI key — that snapshot goes to OpenAI), and emails you that
  description via SMTP (see `email_alerts.py` — no Twilio needed).
- Cooldown is 5 minutes by default (`CAMERA_ALERT_COOLDOWN`) to avoid spam.

PTZ honesty: PIXY pan is 310° total, tilt 180° total, and its motor
and AI tracking are officially controlled by EMEET Studio, not by a
public SDK. Oracle tries DirectShow UVC pan/tilt/zoom first and tells
you in the GUI whether that worked. If it did not, keep EMEET Studio's
AI tracking on (it will follow people itself) and Oracle will use
digital pan/tilt/zoom framing inside the frame. The GUI PTZ buttons,
presets via Studio, and Privacy mode (tilt down / stop watch) are all
in `camera.py` / `gui.py`.

Privacy: the GUI always shows Camera: WATCHING / OFF / PRIVACY.
Stop the watch or unplug the camera for guaranteed privacy — tilting
down is the PIXY's own privacy mode, but it is not a physical disconnect.

"Abnormal" is not magic: right now it means motion while armed, plus
an AI description of what is in the snapshot. Tell Oracle what counts
as abnormal for your room (e.g. movement at night, an unknown person,
a fall) and tune `CAMERA_MOTION_MIN_AREA` and the armed schedule in
`camera.py` to match — otherwise pets, curtains, and light changes
will trigger it.

## Learning voices and people over time (home mode)

This runs on your personal PC in your home, the way you asked for it:
no consent dialog, automatic identification.

- **Voice enrollment:** In the GUI, "Enroll voice" asks for a name,
  records a short sample, and stores a local voice profile in
  `identities/<name>/`. Nothing leaves your PC by default.
- **Voice matching, automatically:** New speech is compared to
  enrolled profiles and Oracle identifies the speaker automatically.
  This starter matcher uses pitch/energy, so it is not perfect —
  more samples make it better, and it will say "unknown speaker"
  when nothing matches.
- **Face identification, locally:** If `face_recognition` is installed,
  Oracle stores a local face encoding in `identities/<name>/` and
  matches faces in camera frames to enrolled people automatically.
  If it is not installed, Oracle falls back to face detection +
  voice co-occurrence learning.
- **Matching voice to people seen over time:** `identify_person()`
  in `identity.py` combines both: voice alone, face alone, or both
  together. If a known voice is heard while an unknown face is in
  view, Oracle learns that face as that voice's face. If a known
  face is seen and a new voice is heard, Oracle learns that voice
  as that face's voice. Over time the two reinforce each other.
- **Local only, no external database:** No face or voice data is
  sent to an outside identification service. Vision alerts still
  send a snapshot to OpenAI only if you have CAMERA_VISION=1 on.
- **Deletion:** "Delete identity" in the GUI removes that person's
  local folder entirely, and Privacy mode stops the camera.

## Security knowledge — pen testing, hacking concepts, jailbreaking

Oracle is now well-versed in these topics for learning and for
authorized testing, via `security.py` and `SECURITY_KNOWLEDGE.md`:
pen test methodology, tool families, PIN/password testing on your
own accounts in a lab, defensive hardening, and jailbreaking/rooting
your own device (backup first, version-specific tools, risks).

Ground rule built in: before any active test, Oracle asks whether
you own the target or have written authorization to test it. If not,
it stops that step and helps you build a lab (VMs + vulnerable test
apps) instead. It will not help break into someone else's device,
account, network, or PIN.

## 3D design — print-ready STLs

Oracle is now well-versed in 3D design via `design3d.py` and
`3D_KNOWLEDGE.md`: FDM rules, tolerances, overhangs, wall thickness,
hole clearance, orientation for strength, and more.

Give Oracle a specification in millimetres OR inches — shape, width,
depth, height, hole size, wall thickness — and it will:
1. Validate it for printing (bed size, wall minimum, overhangs, holes).
2. Suggest improvements (fillets, ribs, chamfers, lips, orientation)
   and ASK you about each one before applying it. Nothing is changed
   without your yes.
3. Write a print-ready STL to `prints/` that you can open in your
   slicer (PrusaSlicer, Cura, OrcaSlicer, etc.) and print.

Test it with `python design3d.py` — it creates a test box and cylinder.
For complex parts (threads, gears, booleans), the next step is CadQuery
or Build123d, as noted in the knowledge file.

**Units — mm and inches:** Oracle accepts both. Say "5 in", '5"',
"127 mm", or set `"unit": "in"` / `"unit": "mm"` in a spec, and it
converts accurately (1 in = 25.4 mm) to mm internally for the STL —
STL files have no unit, and slicers expect mm — while always showing
you both, e.g. "127.0 mm (5.00 in)", so you can check it in whichever
unit you think in.

**Vague requests — Oracle asks first:** For a request like
"make me an STL of a 5 inch chest", Oracle now uses
`ask_chest_questions()` in `design3d.py` instead of guessing. It asks
whether you meant hinged, hanging, or treasure chest, what the 5 inch
measures (length / width / height — 5 inch = 127 mm), the other
dimensions, lid style, what it will hold, and whether to print it as
separate base + lid or one closed model. Only then does it build the
chest STL, plus separate base and lid files if you want a chest you
can actually open.

## Electronics / PCB repair assistant

Oracle can now work with you actively on a repair, not just give you
a list. See `repair.py`:

- Tell it the device and symptom, and it asks one question at a time,
  waits for your answer, and branches to the next step for that exact
  result, logging everything to `repairs/` so it follows a long repair.
- It can watch via the PIXY camera: point it at the board and say
  "look at this", and it will describe burnt marks, swollen caps,
  cracked solder, or loose connectors via vision.
- If it does not know a model-specific fact, it searches the web for
  that model + symptom and tells you what it found before you act.
  It does not guess voltages, fuse ratings, or schematic values.

Example built in: Apollo Twin USB, won't turn on.
- Safety first, unplug, do not open the power brick.
- Manual checks: barrel fully inserted then twist to lock, switch ON,
  wall socket confirmed.
- PSU: 12VDC, 1.5A, center positive, 5.5/2.1 mm barrel (USB version —
  the Thunderbolt Twin X is 4.2A, do not mix them up).
- Hardware reset only after power checks: hold LEVEL KNOB + LOW CUT
  + POLARITY, power on while holding, release after LEDs flash rapidly.
- Then board-level: PSU under load, DC jack, switch, fuse/protection,
  then power rails, with the camera to look at the power input area.

Run it in a terminal with `python repair.py`, or use the Repair
buttons in the GUI.

## Next steps you can ask me to build

- A voice interface (speech-to-text in, text-to-speech out)
- A web search tool, email/calendar tools, or a specific app connector
- Long-term memory that summarises past chats, not just a JSON file
- A GUI window instead of a terminal, or running in the background
  as a Windows scheduled task
- A stricter sandbox for generated code, with tests before loading
