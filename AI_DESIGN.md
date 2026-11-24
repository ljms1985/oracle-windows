# Oracle for Windows — AI Design (v1.0.6)

Concise design doc: how Oracle is supposed to behave, and where each
behaviour lives in the code. Practical, not theory. If code and this doc
disagree, the code is what runs — fix the doc, or fix the code, and say
which you did.

## 0. One plain fact

**Muse's own source code is NOT available and was NOT copied.**
The benchmark in §8 is Muse's *observable behaviour in conversation*
only — what a user can see it do. Oracle is an independent
implementation built to match that behaviour, not a copy of Muse.

## 1. The brain: LLM + tools

- The intelligence is the LLM, not the Python code. Swap the model and
  Oracle gets smarter. Default brain is OpenAI (`OPENAI_MODEL`,
  default `gpt-4o-mini`); Ollama local (`LLM_PROVIDER=ollama`,
  `OLLAMA_MODEL`, default `llama3.1`) is the offline alternative.
  (`agent.py`: `call_llm`, `PROVIDER`.)
- The model answers in one of two ways: plain friendly text, or a JSON
  action `{"thought": ..., "tool": ..., "args": [...]}`. Tools are plain
  Python functions in `agent.py` (`TOOLS`) plus the computer tools in
  `computer.py` (workspace files, browser, web search/fetch, memory,
  goals, tasks). New tools the model writes itself go to
  `tools_generated/` and are only loaded if they define `run()`.
- **Self-correction: up to 3 tries per user request** (`agent.py`
  main loop, `for attempt in range(3)`). If a tool call fails, or the
  model picks a tool that does not exist, the error goes back to the
  model as a new message ("That tool call failed: ... Fix your plan
  and try again. Attempt N/3.") and it retries. After 3 failed
  attempts Oracle stops and asks the user what they expected — it
  does not loop forever and does not pretend it succeeded.
- Destructive commands are refused by pattern (`DANGEROUS_PATTERNS`:
  format, `del /f`, `rm -rf`, shutdown, `reg delete`, ...). Anything
  else run through `run_command` asks first unless
  `AGENT_AUTO_APPLY=1`. A refusal is also fed back to the model, so
  it can re-plan instead of dying silently.

## 2. Multi-turn context

- Each conversation keeps a `history` list of `{"role", "content"}`
  turns (GUI: `self.history`; CLI: the `messages` list). The system
  prompt (personality + computer prompt + MEMORY) plus the full
  history is sent to the model on every turn, so Oracle can refer
  back to what was said earlier in the session.
- **Rule: summarise older context, don't just grow the list.**
  History grows without a cap in the current code — that is a known
  gap, not a feature. The v1.0.6 rule is: keep the most recent turns
  verbatim; when the history passes a sensible size, summarise the
  oldest turns into a short running summary (facts, decisions, open
  items) and keep only the summary plus recent turns in the prompt.
  Never silently drop a fact the user stated — if it matters, it goes
  into persistent memory (§3) first, then out of the live history.
- The model is instructed to remember what the user likes from MEMORY
  and build on it (see `PERSONALITY` in `agent.py`).

## 3. Persistent memory (local only)

- Two layers, both plain JSON files on the user's own machine:
  - `memory.json` next to the program (`agent.py`: `MEMORY_FILE`,
    `load_memory` / `save_memory`) — durable facts and preferences.
  - **Muse memory import (v1.0.7, `memory_import.py`, `gui.py`,
    `MEMORY_SHARING.md`):** on 2026-11-24 Lorenza authorized Muse
    to share any/all information with Oracle via the private
    Tailscale/SSH tunnel only, so Oracle can inherit Muse
    conversations and memory and handle those threads. Muse chat
    exports (`.md` / `.json` / `.txt`) go in the `memory_import/`
    folder next to Oracle (Windows: next to `Oracle.exe`; Mac: next
    to `Oracle.app`) or are picked with Memory > Import Muse
    memory…; Oracle auto-imports them at startup, dedupes them
    against what it already knows, and stores them in `memory.json`
    under `"imported"` with `"imported_files"` tracking what was
    already imported — existing facts are never overwritten. The
    GUI feeds the stored memory into every reply's system prompt
    (`_ask`) and shows it in the MEMORY card and "What do you
    remember?". Scope is Muse-to-Oracle only, local on her PC —
    never GitHub, email to others, or public places; the import log
    records file, count and date only, never keys or credentials.
    Browser history is never mined for this.
  - The computer workspace: `workspace/memory/memory.json`,
    `workspace/goals/goals.json`, `workspace/tasks/tasks.json`
    (`computer.py`: `MEMORY_DIR`, `GOALS_DIR`, `TASKS_DIR`) with
    tools `remember(fact)`, `search_memory(query)`, `add_goal`,
    `add_task`, `list_open_tasks`, `check_due_tasks`. These survive
    restarts; Oracle picks up where it left off.
- Memory is *durable facts, preferences, goals and tasks* — not a
  transcript dump. Save the conclusion ("user prefers X", "Sonata
  needs a bearing test"), not every sentence.
- **Voice and face learning are local-only** (`identity.py`):
  enrolled voices are matched automatically; faces seen on camera are
  matched against face encodings stored locally; if a known voice is
  heard while a face is in view (or vice versa) the two profiles are
  linked automatically and reinforce each other over time. All voice
  samples, face encodings and profiles stay on the user's own PC —
  they are never uploaded, never sent to a cloud service, and never
  shared. Face matching needs `face_recognition` (dlib); without it
  Oracle falls back to OpenCV face detection + voice matching and
  co-occurrence linking. This is for Lorenza's own home PC, by her
  choice — no consent dialog is wanted there. Do not extend it to
  other people's devices or to outside databases.

## 4. Speech: always listening, natural voice

- **Always listening, no wake word** — by Lorenza's choice, for her
  own home PC. While the GUI is open and listening is ON, the mic is
  active and any intelligible speech is transcribed (`voice.py`:
  `listen_once`). Trade-off, stated plainly in the code: a TV or
  podcast nearby can trigger it. There is always a visible LISTENING
  indicator and a button to pause instantly. Never run it hidden, and
  never run it in a shared/public space without telling people nearby.
- Listening is a background thread; it never blocks the UI.
  Transcription currently uses Google Speech Recognition over the
  internet (`recognize_google`) — audio snippets go to Google. The
  standing TODO is to swap in an offline recogniser (e.g. Vosk) if
  Lorenza does not want that.
- **Speaking (v1.0.6 design): OpenAI TTS is the default when
  `OPENAI_API_KEY` is set** — model `tts-1`, voice `nova`,
  `response_format` wav — played through PyAudio with a real RMS
  amplitude level (smoothed) that drives the avatar's mouth
  (`speak_async(text, on_level=None, on_done=None)`, `get_level()`,
  `is_speaking()`, `stop_speaking()`). The key is read from the
  environment and never logged or printed.
  Fallback order: OpenAI TTS → pyttsx3 (SAPI on Windows,
  NSSpeech on Mac) → the built-in `say` command on Mac. If the
  cloud voice is unavailable, Oracle still speaks — it just sounds
  less natural. Speaking never blocks the UI: `speak_async` runs on
  a thread and reports its level/done through callbacks.
- Voice replies are natural and fluid, not robotic — same standard
  as the avatar's mouth movement (§8).

## 5. Vision: camera watch, armed only

- Camera is the EMEET PIXY (USB UVC webcam) via OpenCV
  (`camera.py`). Its own AI tracking stays on in EMEET Studio; UVC
  PTZ is tried and reported honestly (it may be ignored — EMEET
  routes PTZ through Studio); digital crop/zoom always works as a
  framing fallback.
- Motion detection (background subtraction) runs **locally**. Nothing
  leaves the machine until motion passes a threshold **and** the
  watcher is ARMED.
- Only then is **one snapshot** sent to OpenAI Vision for a detailed
  description — and only if `OPENAI_API_KEY` is set and
  `CAMERA_VISION=1`. Set `CAMERA_VISION=0` and you get motion alerts
  (time + size) with no AI description and no image leaving the PC.
  A 5-minute cooldown (default `CAMERA_ALERT_COOLDOWN=300`) stops
  one long event spamming alerts. Alerts go by **email**, not SMS,
  per Lorenza's choice; the snapshot is saved locally under
  `alerts/`. Privacy mode stops the watcher and tilts the camera
  down if PTZ works; unplugging the camera is the guaranteed off.

## 6. Self-improvement: propose, explain, back up, ask first

- `monitor.py` (daily check, or the GUI "Check for improvements"
  button) searches the web for candidate improvements, filters them,
  and writes a **proposal** to `proposals/` plus a plain-language
  email explaining what the change is, why it might help, and what
  could go wrong. Candidates are proposals only — a random blog post
  is never trusted as code.
- **A change is applied ONLY after a clear YES** — email reply YES,
  approval in the GUI, or a `proposals/<name>.approved` file.
  Anything else (no reply, NO, silence) = no change, proposal stays
  pending. There is no auto-apply of internet code, ever.
- When a change is approved: the old version is backed up first
  (timestamped copy in `backups/`), the change is applied, and a
  syntax check (`py_compile`) runs — if it fails, the change is
  rolled back. `agent.py` / `gui.py` are never overwritten without a
  timestamped backup.
- Same gate for tools Oracle writes for itself (`create_new_tool` in
  `agent.py`): the new tool file is saved with a backup of any
  previous version, shown to the user, and only loaded after approval
  unless `AGENT_AUTO_APPLY=1` (off by default, and risky).

## 7. Timeouts and watchdogs: never hang on "thinking"

- LLM calls time out: `urlopen(..., timeout=120)` in `call_llm`
  (both OpenAI and Ollama paths). Vision snapshots: 60 s.
  `run_command`: 60 s.
- **Main-thread UI queue** (`gui.py`): tkinter is not thread-safe.
  Worker threads must NEVER call `root.after()` or widget methods
  directly — a cross-thread call can silently fail, which once left
  a reply undelivered and `busy=True` forever ("thinking forever",
  2026-11-24). Workers put callables on `self._ui_queue`; the main
  thread drains it every 50 ms (`_drain_ui_queue`). This is the ONLY
  way workers touch the UI.
- **Busy always clears.** `_typewriter` clears `busy` when the reply
  finishes typing, in a `finally`-style path — any exception there
  must still clear it, or the GUI sticks on THINKING.
- **120-second watchdog** (`gui.py`, `_tick_clock`, runs every
  second): if a reply thread started more than 120 s ago and `busy`
  is still True, the watchdog resets `busy`, mode and status to
  ONLINE, tells the user plainly ("That reply timed out after 120
  seconds, so I reset and I'm ready again. Please try once more.")
  and logs it. Oracle never sits on THINKING forever.
- The Mac GUI does not yet have this watchdog — see the v1.0.6 notes
  for the Mac port. Do not claim it does until it is added and seen
  working.

## 8. Competency benchmark: Muse's observable behaviour

This is the bar Oracle is built to. It is behaviour you can observe
in a conversation — not internals, not source code (see §0).

1. **Natural back-and-forth.** Talks like a person, not a menu:
   contractions, short casual replies for chat, full detailed answers
   (specifics, steps, values, why) for real questions — especially
   technical/repair questions, where Lorenza is a pro and wants depth,
   not beginner hand-holding.
2. **Remembers context.** Builds on earlier turns and on persistent
   memory (§2–§3). Does not ask for information it was already given
   (VIN, hardware specs, what was already tried).
3. **Asks one clear question when information is missing.**
   One focused question at a time, then follows the answer — not a
   barrage, and not a guess dressed up as a fact. For vague specs
   (e.g. a 3D print request) it asks the clarifying design questions
   first instead of guessing.
4. **Does not repeat answered questions.** If the user answered it,
   that answer stands. If it needs to re-check, it says why.
5. **Admits when unverified.** If it has not checked a live page, a
   price, a part fitment, or a status, it says so plainly instead of
   bluffing — and re-checks the live source before answering when
   the user asks where something is.
6. **Follows through on multi-step work.** Starts a job, does the
   steps in order, reports what actually happened (including what
   failed), and leaves a usable result — a file, an email, a booked
   thing, a clear next step — not just a description of what could
   be done. If a step needs the user (a code, a decision, a human
   action), it stops there and says exactly what is needed.
7. **Honest about limits.** Says "I don't know" instead of inventing
   an answer. Says what it cannot verify. Never claims a build works
   until it has been seen working.

## 9. What this doc does not cover

- Setup/install steps: see `README.md` / `SETUP_GUIDE.md`.
- Hardware sizing and tuning: see `HARDWARE.md`.
- No API key or credential is in this file, or in any doc in this
  folder. Keys live in environment variables on Lorenza's PC only.
