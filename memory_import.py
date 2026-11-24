"""Muse-memory import for Oracle (v1.0.7) — Windows and Mac, identical logic.

What it does
------------
Reads Muse conversation exports that Lorenza provides as files
(.md / .json / .txt) and merges their facts into Oracle's own
``memory.json`` — so Oracle can inherit Muse conversations and
continue those open threads, instead of starting from zero.

Two ways facts get in:
  * Drop files into ``<app dir>/memory_import/`` and Oracle picks
    them up automatically at startup (see ``auto_import``).
  * Use the GUI: Memory > "Import Muse memory…" and pick a file.

What it does NOT do
-------------------
  * No network, no credentials, no GUI imports. Pure stdlib.
  * It never overwrites Oracle's existing facts or preferences, and
    it never writes any key or credential value anywhere — the import
    log records only the file name, the count, and the date.
  * It never mines browser history. Only files Lorenza provides.

memory.json schema (kept compatible with agent.py)
--------------------------------------------------
  {"facts": [...], "preferences": [...],
   "imported": [{"text", "topic", "date", "source", "imported_at"}],
   "imported_files": ["seed.md", ...]}

"facts" and "preferences" are Oracle's own memory, written by
agent.py. Imported Muse facts live separately under "imported" so
they are never mixed up with — or allowed to overwrite — what
Oracle already knows. "imported_files" records which files have
already been imported, so a file is never imported twice.
"""

import json
import re
import string
from datetime import datetime
from pathlib import Path

IMPORT_DIR_NAME = "memory_import"
MEMORY_FILE_NAME = "memory.json"
LOG_FILE_NAME = "memory-import.log"
SUPPORTED_SUFFIXES = {".md", ".json", ".txt"}

# ---------------------------------------------------------------- helpers

def _normalize(text):
    """Canonical form for dedup: lowercase, punctuation and extra
    whitespace stripped. Two facts that differ only in case or
    punctuation count as the same fact."""
    text = " ".join(str(text).split()).lower()
    return text.translate(str.maketrans("", "", string.punctuation)).strip()


def _memory_path(base_dir):
    return Path(base_dir) / MEMORY_FILE_NAME


def _load_memory(base_dir):
    """Read memory.json, tolerating a missing or corrupt file, and
    always return the full schema (agent.py's keys plus ours)."""
    path = _memory_path(base_dir)
    memory = {"facts": [], "preferences": [], "imported": [], "imported_files": []}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in memory:
                    if isinstance(data.get(key), list):
                        memory[key] = data[key]
                # Keep any other keys agent.py or a future version adds.
                for key, value in data.items():
                    if key not in memory:
                        memory[key] = value
        except Exception:
            pass
    return memory


def _save_memory(base_dir, memory):
    _memory_path(base_dir).write_text(
        json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _log_import(base_dir, filename, new_count):
    """One log line per import: date, file, count. Never a key,
    credential, or fact text — only what was imported and when."""
    try:
        line = (f"{datetime.now():%Y-%m-%d %H:%M:%S}  "
                f"{filename}  {new_count} new fact(s)\n")
        with open(Path(base_dir) / LOG_FILE_NAME, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _file_date(path):
    """Best-effort YYYY-MM-DD for a file's facts: its modified date.
    Used only as ordering/provenance, never as a claim about when
    the fact itself was learned."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except Exception:
        return ""


# ---------------------------------------------------------------- parsing

def _clean_fact(text, topic, date, source):
    text = " ".join(str(text).split()).strip()
    if not text:
        return None
    return {"text": text, "topic": topic or "general",
            "date": date or "", "source": source or ""}


def _parse_md(path):
    """Markdown: headings become topics, bullets and plain lines
    become facts. Code fences, blank lines and horizontal rules
    are skipped. A line that is only a date heading is not a fact."""
    facts = []
    topic = "general"
    in_fence = False
    date = _file_date(path)
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if set(line) <= set("-*_=") and len(line) >= 3:
            continue  # horizontal rule / separator
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            topic = " ".join(m.group(2).split()).strip() or "general"
            continue
        # Bullets, numbered lists, or plain lines are all facts.
        m = re.match(r"^[-*+•]\s+(.*)$", line)
        if m:
            line = m.group(1).strip()
        else:
            m = re.match(r"^\d+[.)]\s+(.*)$", line)
            if m:
                line = m.group(1).strip()
        fact = _clean_fact(line, topic, date, path.name)
        if fact:
            facts.append(fact)
    return facts


def _parse_json(path):
    """JSON, in any of these shapes:
      * {"facts": [...], "preferences": [...]} (agent.py's schema) —
        plain strings, or {text, topic, date, source} objects.
      * A list of {text, topic, date, source} objects.
      * {"imported": [...]} — same object shape.
    Preferences land under topic "preferences"."""
    facts = []
    date = _file_date(path)
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    items = []
    if isinstance(data, dict):
        for key in ("facts", "imported"):
            if isinstance(data.get(key), list):
                items.extend(data[key])
        if isinstance(data.get("preferences"), list):
            for item in data["preferences"]:
                if isinstance(item, dict):
                    item = dict(item)
                    item.setdefault("topic", "preferences")
                else:
                    item = {"text": item, "topic": "preferences"}
                items.append(item)
    elif isinstance(data, list):
        items = data
    else:
        return facts
    for item in items:
        if isinstance(item, dict):
            fact = _clean_fact(item.get("text", ""), item.get("topic", "general"),
                               item.get("date", "") or date, item.get("source", "") or path.name)
        else:
            fact = _clean_fact(item, "general", date, path.name)
        if fact:
            facts.append(fact)
    return facts


def _parse_txt(path):
    """Plain text: one fact per non-empty line, topic "general"."""
    facts = []
    date = _file_date(path)
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fact = _clean_fact(raw, "general", date, path.name)
        if fact:
            facts.append(fact)
    return facts


_PARSERS = {".md": _parse_md, ".json": _parse_json, ".txt": _parse_txt}


def parse_file(path):
    """Parse one export file into [{text, topic, date, source}].
    Raises ValueError for an unsupported suffix."""
    path = Path(path)
    parser = _PARSERS.get(path.suffix.lower())
    if parser is None:
        raise ValueError(f"Unsupported file type: {path.suffix} "
                         f"(use .md, .json or .txt)")
    return parser(path)


# ---------------------------------------------------------------- import

def import_file(path, base_dir):
    """Import one file into memory.json.

    Returns the number of NEW facts added (0 if the file was
    already imported, or every fact in it was already known).
    Existing facts/preferences are never touched or overwritten."""
    path = Path(path)
    base_dir = Path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Import file not found: {path}")
    memory = _load_memory(base_dir)
    if path.name in memory.get("imported_files", []):
        return 0

    known = set()
    for fact in memory.get("facts", []):
        known.add(_normalize(fact if isinstance(fact, str) else fact.get("text", "")))
    for pref in memory.get("preferences", []):
        known.add(_normalize(pref if isinstance(pref, str) else pref.get("text", "")))
    for item in memory.get("imported", []):
        if isinstance(item, dict):
            known.add(_normalize(item.get("text", "")))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_count = 0
    for fact in parse_file(path):
        norm = _normalize(fact["text"])
        if not norm or norm in known:
            continue
        known.add(norm)
        memory.setdefault("imported", []).append({
            "text": fact["text"],
            "topic": fact["topic"],
            "date": fact["date"],
            "source": fact["source"],
            "imported_at": now,
        })
        new_count += 1

    if path.name not in memory.setdefault("imported_files", []):
        memory["imported_files"].append(path.name)
    _save_memory(base_dir, memory)
    _log_import(base_dir, path.name, new_count)
    return new_count


def import_folder(folder, base_dir):
    """Import every supported file in a folder (not recursive).
    Returns (new_fact_count, [filenames imported]). Files already
    in imported_files are skipped. Sorted, so the order is stable."""
    folder = Path(folder)
    base_dir = Path(base_dir)
    total = 0
    imported = []
    if not folder.is_dir():
        return 0, []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            already = path.name in _load_memory(base_dir).get("imported_files", [])
            if already:
                continue
            try:
                new_count = import_file(path, base_dir)
            except Exception:
                continue
            imported.append(path.name)
            total += new_count
    return total, imported


def auto_import(base_dir):
    """Scan <base_dir>/memory_import/ for export files not yet
    imported and import them. Safe to call at every startup: a
    file already in imported_files is skipped, and facts already
    known are deduplicated. Returns (new_fact_count, [filenames]).
    A missing memory_import folder is normal — it just means
    nothing new to import."""
    base_dir = Path(base_dir)
    return import_folder(base_dir / IMPORT_DIR_NAME, base_dir)


# ---------------------------------------------------------------- reading

def memory_count(base_dir):
    """Total remembered facts: Oracle's own facts + preferences +
    imported Muse facts."""
    memory = _load_memory(base_dir)
    return (len(memory.get("facts", [])) + len(memory.get("preferences", []))
            + len(memory.get("imported", [])))


def _all_entries(base_dir):
    """All memory as (topic, text, date) triples, newest first
    where a date exists. Preferences are grouped under topic
    "preferences"; Oracle's own facts under "general"."""
    memory = _load_memory(base_dir)
    entries = []
    for fact in memory.get("facts", []):
        text = fact if isinstance(fact, str) else fact.get("text", "")
        if text:
            entries.append(("general", text, ""))
    for pref in memory.get("preferences", []):
        text = pref if isinstance(pref, str) else pref.get("text", "")
        if text:
            entries.append(("preferences", text, ""))
    for item in memory.get("imported", []):
        if isinstance(item, dict) and item.get("text"):
            entries.append((item.get("topic", "general") or "general",
                            item["text"], item.get("date", "") or ""))
    # Newest first where dates exist; undated entries keep their order.
    dated = [e for e in entries if e[2]]
    undated = [e for e in entries if not e[2]]
    dated.sort(key=lambda e: e[2], reverse=True)
    return dated + undated


def load_memory_text(base_dir, max_chars=6000):
    """Compact readable text of everything Oracle remembers, for
    the system prompt: grouped by topic, newest first where dates
    exist. Bounded to max_chars so the prompt stays bounded."""
    entries = _all_entries(base_dir)
    if not entries:
        return "(No stored memory yet.)"
    grouped = {}
    order = []
    for topic, text, date in entries:
        if topic not in grouped:
            grouped[topic] = []
            order.append(topic)
        grouped[topic].append((text, date))
    lines = []
    for topic in order:
        lines.append(f"[{topic}]")
        for text, date in grouped[topic]:
            suffix = f" ({date})" if date else ""
            lines.append(f"- {text}{suffix}")
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars]
        cut = out.rfind("\n")
        out = (out[:cut] if cut > 0 else out) + "\n…(memory truncated)"
    return out


def memory_summary_lines(base_dir, max_lines=40):
    """Grouped summary for the GUI's "What do you remember?"
    button: one line per topic header plus one line per fact,
    capped at max_lines (plus a trailing count line)."""
    entries = _all_entries(base_dir)
    if not entries:
        return ["I don't remember anything yet.",
                "Import a Muse chat export (.md / .json / .txt) with the",
                "Import button, or drop files into the memory_import",
                "folder next to Oracle and restart me."]
    grouped = {}
    order = []
    for topic, text, date in entries:
        if topic not in grouped:
            grouped[topic] = []
            order.append(topic)
        grouped[topic].append((text, date))
    lines = []
    total = len(entries)
    for topic in order:
        if len(lines) >= max_lines:
            break
        lines.append(f"[{topic}]")
        for text, date in grouped[topic]:
            if len(lines) >= max_lines:
                break
            suffix = f" ({date})" if date else ""
            lines.append(f"  • {text}{suffix}")
    shown = sum(1 for line in lines if line.startswith("  •"))
    if shown < total:
        lines.append(f"…and {total - shown} more fact(s) — {total} remembered in total.")
    return lines
