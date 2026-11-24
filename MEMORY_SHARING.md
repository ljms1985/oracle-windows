# Muse → Oracle Memory Sharing — Authorization

## Authorization (2026-11-24)

Lorenza authorized Muse to share **any and all information** with the
Oracle agent, so Oracle can inherit Muse conversations and memory and
handle those threads going forward.

## Scope — read this before touching the transfer

- **From:** Muse (this assistant, its conversations and memory about Lorenza).
- **To:** the Oracle agent only — Windows Oracle and Mac Oracle, on
  Lorenza's own machines.
- **Path:** the private Tailscale/SSH tunnel only
  (`100.100.145.111`, SSH as `loren`). The transfer is local, machine
  to machine, over that private tunnel.
- **NOT authorized:** sharing with anyone else, GitHub, email to
  others, or any public place. Oracle's memory files stay local on
  Lorenza's PC/Mac. Nothing in this feature uploads memory anywhere.

## How the transfer works

1. Muse conversation exports (`.md` / `.json` / `.txt`) are placed in
   the `memory_import/` folder next to Oracle — on Windows, next to
   `Oracle.exe` (i.e. `C:\Oracle\memory_import\`); on Mac, next to
   `Oracle.app` — or picked with the GUI: **Memory > Import Muse
   memory…**
2. At startup, Oracle's GUI calls `memory_import.auto_import()`,
   which imports any files in `memory_import/` that have not been
   imported before.
3. Facts land in Oracle's `memory.json` under `"imported"`
   (`{text, topic, date, source, imported_at}`), alongside Oracle's
   own `"facts"` and `"preferences"`. Existing facts are never
   overwritten, and duplicates are skipped.
4. Every import is logged in `memory-import.log` next to
   `memory.json`: file name, new-fact count, and date only — **never
   any key or credential value**.

## Rules

- Never mine browser history for Muse conversations. Muse is
  primarily a phone app, browser history is unreliable, and history
  mining was explicitly ruled out. Only files Lorenza provides.
- Never write a seed file containing Lorenza's personal facts into
  the repos. The seed is supplied separately, via the private tunnel
  only.
- Never put memory contents, API keys, or credentials in GitHub,
  email, logs, or chat. The `memory_import/` folder and
  `memory.json` are local user data, not repo content.

## Implementation

- `memory_import.py` — parser + dedup + persistence + prompt text.
  Pure stdlib, no network, no credentials, no GUI imports.
- `gui.py` — MEMORY card in the left deck (under API KEY), startup
  auto-import line, memory in the `_ask` system prompt, "What do you
  remember?" summary.
- `agent.py` — unchanged; its `load_memory()` / `save_memory()` and
  `{"facts": [...], "preferences": [...]}` schema are kept, with
  `"imported"` and `"imported_files"` added alongside.
