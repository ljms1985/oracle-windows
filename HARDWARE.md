# Oracle for Windows — Hardware (v1.0.6)

Verified hardware for Lorenza's PC, and how Oracle is tuned to it.
Concise: what each part is for, and what not to do with it.

## Verified hardware

| Part | Spec | Role in Oracle |
| --- | --- | --- |
| CPU | AMD Ryzen 9 9950X3D (16 cores / 32 threads) | Parallel work: listening, camera, tools, UI |
| GPU | NVIDIA RTX 4080 Super, 16 GB VRAM, CUDA | Local vision / face matching, smooth avatar animation |
| RAM | **64 GB** DDR5-6000 | Context + memory cache, camera frame buffers, local models |
| Storage | 2 TB SSD + 3 TB HDD (5 TB total) | SSD: program, models, workspace. HDD: bulk files, prints, archives |
| Motherboard | MSI MPG X670E Carbon WiFi | — |
| Cooler | NZXT Kraken Elite 360 AIO | Keeps the 9950X3D sustained under parallel load |
| PSU | Redragon 80+ Platinum 1000 W | Headroom for GPU + CPU under simultaneous load |
| Camera | EMEET PIXY Dual-Camera AI PTZ 4K (USB UVC) | Watch, face matching, repair assistance |

> **Correction (2026-11-24): RAM is 64 GB, not 128 GB.** It was
> recorded as 128 GB; Lorenza confirmed 64 GB on 2026-11-24 after
> removing two sticks. Anything sized for 128 GB (context cache,
> frame buffers, local models) must be re-checked against 64 GB.
> Do not re-record it as 128 GB.

## CPU — Ryzen 9 9950X3D: run things in parallel, keep the GUI on the main thread

- 16 cores / 32 threads is the reason Oracle can listen, watch the
  camera, run tools and keep the UI responsive at the same time.
  Assign them that way: **one thread each** for listening
  (speech recognition), camera watcher (motion detection), tool/LLM
  work, and the self-improvement check. None of those may block the
  GUI.
- **GUI on the main thread only.** Tkinter is not thread-safe: worker
  threads never call widget methods or `root.after()` directly — they
  put callables on the main-thread UI queue, drained every 50 ms
  (see `AI_DESIGN.md` §7). This is the rule that stops the
  "thinking forever" hang.
- The 3D V-Cache helps sustained parallel work, but it does not make
  single-threaded Python fast — do not assume a slow serial step
  will be saved by the CPU. Split work across threads, or accept
  the wait and show it (busy indicator + watchdog, not silence).

## GPU — RTX 4080 Super 16 GB VRAM, CUDA: use it for vision, don't leave it idle

- **Local vision and face matching belong on the GPU.** Face
  detection/matching, frame processing for the camera watcher, and
  any local vision model should run CUDA-accelerated. Do not leave
  the 4080 Super idle while the CPU does vision work — that is the
  slowest possible arrangement on this machine.
- **Avatar animation is GPU work too.** The animated avatar (blink,
  look-around, nod, mouth moving with speech) should render
  smoothly from the GPU; a choppy avatar on a 4080 Super means the
  rendering path is wrong, not that the hardware is short.
- 16 GB VRAM is generous but not infinite: a local vision/face model
  plus frame buffers plus the avatar must fit together. Load one
  local model at a time where possible, release it when the watcher
  is off, and never page VRAM to system RAM for routine work.
- The cloud LLM (OpenAI) and cloud TTS still do the thinking and
  speaking — the GPU is for local seeing and animating, not for
  replacing the brain.

## RAM — 64 GB: size everything to fit comfortably, no paging

- 64 GB is plenty for Oracle — **if** it is budgeted. Size these to
  fit together without paging:
  - **Context / memory cache:** the live conversation history plus
    the running summary (§2 of `AI_DESIGN.md`). Cap it; summarise
    older turns instead of keeping an unbounded history in RAM.
  - **Camera frame buffers:** 1080p frames for motion detection,
    plus the shared `latest_frame` for the GUI preview. 4K frames
    are much heavier — 1080p is the default for motion + vision
    for a reason. Do not hold multiple 4K frames in memory.
  - **Local models:** face-recognition / local vision models and
    any offline speech model. Keep one loaded at a time; unload
    when not in use.
- If Oracle ever starts paging on this machine, something is sized
  wrong (unbounded history, unreleased frames, or two big models
  loaded at once) — fix the sizing, don't add RAM as the answer.
- Workspace files (memory, goals, tasks, tools, prints) are small
  JSON/text; they live on the SSD and are not a RAM concern.

## Storage

- SSD (2 TB): the program, Python environment, local models, and the
  workspace. Fast load matters here.
- HDD (3 TB): bulk storage — recordings, snapshots under `alerts/`,
  STL prints, archives. Do not put model files or the live workspace
  on the HDD and then wonder why loading is slow.

## What not to do

- Do not run vision on the CPU while the GPU sits idle.
- Do not grow conversation history, frame buffers, or loaded models
  without a cap — 64 GB is not 128 GB.
- Do not block the main (GUI) thread with listening, camera, LLM,
  or tool work. Ever. That is what the UI queue and the 120-second
  watchdog exist to prevent.
- No API key or credential is in this file. Keys live in environment
  variables on Lorenza's PC only.
