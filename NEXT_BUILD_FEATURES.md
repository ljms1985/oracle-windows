# Next Build — Default Features Checklist

**Status: DEFERRED — not building now.**
Lorenza, 2026-11-24 18:06 EST: *"We're not going to build it now but when we do make another build all of these changes will be implemented."*

When Lorenza says go, the next build implements **all** of the items below
automatically, by default — not optional, not a plugin, nothing she has to
turn on or ask for again. **Release gate: verify every item is present and
tested in the build. If any item is missing, the build is not complete.**

## Checklist

| # | Feature | Status at deferral |
|---|---------|--------------------|
| 1 | **Fluid lip-sync** driven by real speech-audio amplitude envelope (smoothed, ~30fps eased interpolation, varied mouth shapes: closed / slightly open / wide / narrow-rounded for O,U / wider for A,E; natural closed rest pose, no snap shut) | DONE in v1.0.6 |
| 2 | **Natural voice** — OpenAI TTS (voice `nova`) as default, warm and natural rate/pitch; pyttsx3/SAPI only as fallback, never the default robotic voice | DONE in v1.0.6 |
| 3 | **Full avatar expressions matching Muse** — bob, blink, look-around, nod, mouth moves fluidly while speaking (not a single hole opening/closing) | DONE in v1.0.6 |
| 4 | **Thread-safety / no stuck thinking** — main-thread `_ui_queue`, `busy` always clears, 120s watchdog that auto-resets a stuck THINKING state with a visible timeout message | DONE in v1.0.3+ (Windows). **Mac gap: Mac GUI lacks the 120s watchdog — carry forward.** |
| 5 | **Always-listening, no wake word** — mic open, responds to Lorenza speaking directly | DONE (verified in source 2026-11-24; in v1.0.6) |
| 6 | **Camera open fix — EMEET PIXY Dual-Camera AI PTZ 4K** — fix the "can't grab frames" / -2147483638 (0x8000000A) failure: enumerate indexes 0–3 × backends DSHOW/MSMF/ANY, resolution fallback, a candidate counts only if a real frame is read; clear on-screen message if in use | DONE in v1.0.6 — PIXY is on **index 1 at 1280×720** (index 0 opens but returns no frames) |
| 7 | **Camera auto-tracking** — detect a person in frame, keep them centred, drive PTZ (pan/tilt, zoom where supported) continuously to follow movement on its own; NOT only manual tilt/pan on command. Use the PIXY's own AI tracking where exposed (SDK / UVC PTZ controls / vendor API first); fall back to software tracking (person detection + frame-centre error → PTZ commands, smoothed, no jitter/hunt). Dead zone so small movements don't cause constant panning; re-acquire after the person leaves and returns; stop safely if the camera is lost (never spin, never crash on a grab failure). On-screen Auto-Track ON/OFF toggle (default ON when camera is on and a person is in view); "track me / track this person" voice command. Tracking data stays local on her PC. **Verify live: a person walks across the room, camera follows and keeps them in frame. Do not claim it works until that live test passes.** | **DONE in working tree (unreleased, 2026-11-25) — ported from Mac v1.0.9.** `tracking.py`: OpenCV HOG people detector + Haar face/full-body cascades, largest person wins, motion fallback; dead zone 0.06, exponential smoothing 0.35, max 1 PTZ step per 0.5 s, hold 3 s / gentle return-to-centre after 15 s with no person, `camera_lost` on frame failure (no move, no crash). UVC PTZ first via DirectShow (`CameraController.ptz()`, PIXY index 1 at 1280×720); digital crop/zoom fallback to 1.25× when the PIXY ignores UVC. Wired in `camera.py` Watcher (auto-track ON by default, `set_auto_track` / `track_me` / `stop_tracking`) and `gui.py` (VISION card "Auto-Track: ON/OFF" toggle button + "Tracking: …" status label; voice: "track me", "track this person", "track <name>", "stop tracking"). Synthetic tests pass in the VM (see test below). **Live PC verification still pending — do not claim it works until a person walks across the room and the camera follows.** |
| 8 | **Manual tilt/pan on command** still available alongside auto-track | **DONE in working tree (unreleased, 2026-11-25).** The existing VISION-card Pan/Tilt/Zoom buttons (`camera_ptz`) and `CameraController.ptz()` are unchanged and work alongside auto-track; auto-track pauses during pan-and-describe sweeps and resumes after. **Live PC verification still pending.** |
| 9 | **Local face-feature recognition** — no cloud service, no outside database, no face data sent anywhere. Local library on her PC (e.g. OpenCV / face_recognition / InsightFace — pick one that actually runs on Windows with RTX 4080 Super / 64GB and verify live). Detect a face, extract its feature embedding, match against stored local profiles, identify who it is ("that's Lorenza", "that's Asia", …) and store that identity in Oracle's OWN local memory so it remembers people over time and improves matching. Learning flow: unfamiliar face seen repeatedly → ask Lorenza who it is (voice / on screen) → save name + face profile locally. Known face → greet/identify without asking again. Never auto-label when unsure — show a confidence and ask. Works with auto-tracking: as the camera follows a person, it also identifies them. Privacy per her standing rule (personal PC, her home): learning is automatic, no consent dialog; data stored LOCAL ONLY, never uploaded, never in GitHub/email/logs. She can view and delete a stored face profile. **Verify live: enrol Lorenza, have her leave and return, confirm Oracle identifies her correctly. Report library, enrolment steps, match accuracy, storage location. Do not claim it works until that live test passes.** | **DONE in working tree (unreleased, 2026-11-25) — ported from Mac v1.0.9.** `face_profiles.py`: `face_recognition` (128-d embeddings, threshold 0.6) if installed, else OpenCV-only fallback (Haar detection + HOG/pixel/histogram feature, cosine-distance threshold 0.08, deliberately strict — below threshold the answer is always "unknown", never a guessed name). **Library: OpenCV-only by default** (`face_recognition` optional only, never required; needs dlib, hard on Windows). **Storage: `faces/<name>/` next to Oracle.exe** (frozen) or next to the .py files (source run), overridable with `ORACLE_FACES_DIR`; `faces/` added to `.gitignore`, never committed/emailed/uploaded. Enrol via PEOPLE-card "Enroll face (camera)" button or voice "enrol this person as <name>"; "who is that / who do you see" answers from the track status; repeated unknown faces (5 sightings) trigger an on-screen prompt to enrol. Face identification runs ~once a second in the Watcher loop and feeds the tracker (target-name preference). Synthetic tests pass in the VM (same person identified, two different people correctly "unknown"). **Live PC verification still pending: enrol Lorenza, leave and return, confirm correct identification — do not claim it works until that passes.** |
| 10 | **Left-side API key swap UI** — "API Key / Change API Key" clearly visible on the LEFT side of the main screen on first open, no menu digging; masked (password-style) entry with Save/Cancel; saving validates with a quick OpenAI test call, updates the User env var `OPENAI_API_KEY` on Windows, active immediately; clear "Key updated" / "Key invalid" message; existing key NEVER shown in plain text (only `SET • ****…last 4`); never written into source/GitHub/logs/email | DONE in v1.0.6 |
| 11 | **Minimize-to-avatar-only mode** — minimizing hides the main GUI and leaves a frameless/transparent, draggable, always-on-top avatar alone on the desktop, still listening/talking, mouth animating; click avatar (or Restore / right-click) to restore the full GUI; full GUI remains the default on open | DONE in v1.0.6 |
| 12 | **Muse-level conversational competency** as the benchmark (observable behaviour, NOT Muse source code — that is proprietary and unavailable): natural back-and-forth, remembers context, asks one clear question when info is missing, does not repeat answered questions, admits when unverified, follows through. Replies written to be spoken naturally (conversational, contractions, varied sentence length, natural pauses, no stiff list-reading). Test with a REAL multi-turn conversation on the PC. | DONE in v1.0.6 (Windows `agent.py` PERSONALITY). **Mac gap: Mac `agent.py` PERSONALITY was not updated to the spoken style in v1.0.6 — carry forward.** |
| 13 | **AI/ML design + hardware tuning** — `AI_DESIGN.md` and `HARDWARE.md`: LLM reasoning with tool calling, multi-turn context with summarising, persistent memory, local-only voice/face learning, speech/vision, self-improvement that explains and waits for a yes, timeouts/watchdogs; tuned for **Ryzen 9 9950X3D / RTX 4080 Super (16GB VRAM, CUDA) / 64GB RAM** (NOT 128 — she removed two sticks) | DONE in v1.0.6 |
| 14 | **Muse conversation memory import** — Oracle inherits what Muse did with her on the PC: import path for Muse chat exports (.md/.json/.txt) into Oracle's persistent memory (deduped, dated, sourced); startup auto-import from a `memory_import/` folder; MEMORY card in the left deck (Import / What do you remember?); imported memory prepended to every reply's system prompt so Oracle can reference it naturally ("you told Muse on Nov 20 that…") and continue those open threads. **Muse-to-Oracle sharing via the private Tailscale/SSH tunnel is explicitly authorized by Lorenza 2026-11-24** — scope is Muse→Oracle only, local on her PC; never GitHub, email to anyone but Lorenza, or any public place. Imported memory stays local; log imports without credential values. Transfer the seed only via the SSH tunnel, never GitHub/email. | Code DONE in v1.0.7 (see State below). Seed file: `~/workspace/oracle-memory-seed/muse-memory-seed.md` (85 facts, 15 OPEN, no key values) — **not in any repo, not emailed** |
| 15 | **Job-hunting auto-submit** — submit applications on its own (fill the form, press submit, push through every time a site is NOT blocking it, without asking first); stop and hand to Lorenza only if actually blocked (CAPTCHA, sign-in code/2FA, anti-bot block, step needing a human). Follow through to the employer's own site when Indeed/another job site redirects there. If an account is required, create a username/password, saved locally only, distinct per site, recorded where she can see it, AND opened in Notepad left up on the desktop (`~/Desktop/Oracle-Accounts.txt`, appended not overwritten). | DONE in v1.0.6 (per build record — re-verify at next release) |
| 17 | **Pan-and-describe ('what do you see')** — on 'what do you see' / 'describe what you see' / 'look around' / 'scan the room', the camera pans left -> right then right -> left, capturing frames at each stop, and describes EVERYTHING seen across the whole sweep in one coherent spoken left-to-right description (vision, OpenAI via key on the machine). Physical UVC pan first; digital pan fallback (zoom 1.5x + crop slide) when the PIXY ignores UVC PTZ, stated honestly. Camera returns to its starting position; camera watch stays ON through the sweep, only auto-tracking pauses. Frames + description saved under alerts/pan-YYYYMMDD-HHMMSS/. | DONE in source 2026-11-24, **verified live on the PC** (two sweeps: 10 frames each, full descriptions; GUI intercept verified: ASK OK 'what do you see' -> 1724-char reply). Mac code ported, **not tested on a real Mac**. |
| 16 | **Windows/Mac parity** — everything built for one version must also be in the other, same capabilities on both | Ongoing rule. Known Mac gaps to close: items 4 and 12 above; Mac builds are NOT tested on a real Mac — state that plainly |

## State at deferral (2026-11-24 ~18:06 EST)

- **v1.0.6 is the last released/installed version** (Windows installed at `C:\Oracle`, launch-tested; Mac arm64 + Intel released, untested on a real Mac).
- **v1.0.7 (memory import) was committed and tagged before this stop arrived**
  (Windows commit `d574f49`, tag `v1.0.7`; Mac commit `7093689`, tag `v1.0.7-mac`,
  Intel merge `bbc5095`, tag `v1.0.7-intel`; pushes completed ~18:03 EST).
  GitHub Actions: Windows run 45506575577 **success**; Mac arm64 run 45506589976
  **success**; Mac Intel run 45506593394 was still in progress at the stop.
  **No GitHub release was created, no email was sent, nothing was installed
  on the PC, and the source GUI was not restarted.** The v1.0.7 code is on
  GitHub only as commits/tags; it is NOT a release and NOT on her PC.
- **The PC was left exactly as it was** — nothing uninstalled, nothing
  installed, no GUI restarted in this session.
- **ElevenLabs note (for a future voice decision, only if Lorenza asks):**
  `ELEVENLABS_API_KEY` exists as a User env var on her PC (51 chars, value
  never read) but **no Oracle code uses it** — v1.0.5/v1.0.6 use OpenAI TTS.
  Do not treat it as in-use.

## Dictation / STT fix — done in source 2026-11-24 ~18:22 EST (after deferral)

Lorenza: the source version "doesn't make out what's being said as well as
you do." Root causes in old `voice.py listen_once()`: Google web speech
only (no language model), default Sound Mapper mic (wrong input — not the
EMEET PIXY mic she speaks into), re-calibrated noise on every phrase,
3s listen timeout. Fix, in `voice.py` (Windows + Mac, same code):
OpenAI Whisper API (`whisper-1`) primary with a short names/topics
prompt, Google fallback, explicit EMEET PIXY mic (index 1), calibrate
once per session, `pause_threshold` 0.8, listen 10s / phrase 30s,
silence gate (RMS <0.5% or <0.4s → skip, prevents Whisper prompt-echo
hallucinations). GUI log now shows `HEARD (whisper): ...`.
Deployed to `C:\friend-agent\voice.py` + `gui.py` (backups
`voice.py.bak-20261124-stt`, `gui.py.bak-20261124-stt`), source GUI
restarted. Verified live on PC: TTS→Whisper exact MATCH on
"Hi Oracle, I drive a 2016 Dodge Challenger and I work on electronics
and PCB repair in Jacksonville."; silence → ""; live GUI transcribed
room speech with Whisper ("Lemons!" twice). **Still to do: Lorenza
speaking test sentences directly to the PC — have her say several
normal sentences and compare the HEARD lines to what she said.**
No package released, nothing installed over `C:\Oracle` (v1.0.6).

## Camera watch ALWAYS ON + live preview box — done in source 2026-11-24 ~18:35 EST (after deferral)

Lorenza: "Camera watch should always be on from the start of the program,
from the time the AI agent opens camera watch should already be running."
Plus: "add like a small box in the lower right hand corner of the GUI
that shows what the camera's seeing."

Before: watch was manual-only — `watcher` started as `None`, label
"Camera: OFF", nothing watched until she clicked "Start camera watch".
Fix, in `gui.py` (Windows + Mac, same behaviour): `_start_camera_watch_auto()`
at the end of `__init__` starts watch in a worker thread (slow camera
probe never blocks the GUI opening) and retries every 30 s if the camera
is busy / fails to open, showing "Camera: OFF — retrying (N)" plainly —
never silently off. Stop button / Privacy mode sets
`_camera_watch_user_stopped`, which also stops the retry loop. Pan-and-
describe reuses the same watcher/controller, so watch stays on through
a sweep. Preview: `_build_cam_preview()` / `_update_cam_preview()` —
a small 232×152 box, lower right corner, just above the input bar (never
covers SEND), showing the live feed from `camera.latest_frame` (same
feed watch uses, no second camera open), refreshed every 200 ms, with
a plain message in the box when there is no frame / camera is off.
Deployed to `C:\friend-agent\gui.py` (MD5 e1999c66facfc6710f9a0b905d25fe40,
backup `gui.py.bak-20261124-camwatch`), source GUI restarted via
`OracleSourceRun`. Verified live on PC: log `18:35:18 CAMERA WATCH
AUTO-STARTED: Watcher started. Armed=True. Camera index 1 via DSHOW at
1920x1080` with no click; screenshot `camwatch-pc-live-20261124.png`
shows CAM: ON pill, "Stop camera watch" button, and a real live PIXY
frame (room, person holding a child) in the CAMERA box lower right.
No package released, nothing installed over `C:\Oracle` (v1.0.6).

## When the next build starts

1. Start from v1.0.7 as the base (memory import already in).
2. Implement items 7, 8, 9 (auto-track, manual PTZ, local face recognition)
   in source on the PC first, verify live, then fold into the package builds.
3. Close the Mac gaps in items 4 and 12.
4. Re-verify every DONE item above in the new build — a regression in any
   item fails the release gate.
5. Then commit, tag, build via Actions, verify SHAs, release, email
   (install link + source separately, Lorenza only for source), install on
   the PC, and launch-test in Session 1.
