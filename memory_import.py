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

# Prompt budget for load_memory_text (fixed 2026-11-25 — see
# _ordered_entries). 24,000 chars is ~6,000 tokens (English runs
# ~4 chars/token), about 5% of gpt-4o-mini's 128k-token context, so
# the system prompt, conversation history and the reply still have
# ample room, and the per-turn token cost stays small. The full
# memory is ~159,000 chars (~40k tokens, 31% of context) and is
# mostly restatements plus near-identical camera descriptions, so
# it is deliberately NOT dumped whole: the cap stays bounded and
# the highest-value facts go first instead.
DEFAULT_MEMORY_CHARS = 24000
# Budget inside that cap reserved for key facts (identity/family
# and the two cars) — the canonical kinds measure ~7,000 chars on
# the real 2026-11-25 memory, so 8,000 leaves headroom and the
# lowest-value household restatements are what gets cut, never a
# kid's or a car's canonical fact.
KEY_FACTS_CHARS = 8000
# Motion-alert camera descriptions are near-identical paragraphs
# (~165 chars each, 47 of them on 2026-11-25) and flooded the old
# prompt. Keep only the newest few in the prompt tail.
MAX_MOTION_ALERTS = 2

# Key-fact ("anchor") matchers. Word-boundary regexes, so "son"
# does not match "person"/"Session" and "Asia" does not match
# "fantasia". An anchor is an entry that states a family role, a
# wife fact, a car fault, or the household — the facts the
# 2026-11-24 recall test proved get lost (kids, Challenger,
# Sonata/P1326).
# CORRECTION 2026-11-25 (Lorenza's own words): Anisa is Candice's
# daughter, a ninth-grader — NOT one of Lorenza's children. Anisa
# is therefore deliberately NOT in _KID_RE: an entry that merely
# mentions Anisa must never anchor as a Lorenza-kid fact, and must
# never feed the family roster. The Anisa correction itself is
# anchored separately, by _ANISA_CORRECTION_RE below.
_KID_RE = re.compile(r"\b(aiden|ariya|asia|adonis|de'aris|dearis|maliyah|avery)\b", re.IGNORECASE)
_ANISA_RE = re.compile(r"\b(anisa|anissa)\b", re.IGNORECASE)
_CANDICE_RE = re.compile(r"\bcandice\b", re.IGNORECASE)
_ROLE_RE = re.compile(r"\b(daughter|son|child|children|kids|middle|youngest|two-year-old|ninth-grader)\b", re.IGNORECASE)
_WIFE_RE = re.compile(r"\bwife\b", re.IGNORECASE)
_ASHLEY_RE = re.compile(r"\bashley\b", re.IGNORECASE)
_CAR_RE = re.compile(r"\b(challenger|sonata|p1326)\b|knock sensor|active exhaust|turn signal", re.IGNORECASE)
_HOUSEHOLD_RE = re.compile(r"\b6 kids\b", re.IGNORECASE)
# Lorenza's named children, corrected 2026-11-25 (her own words):
# Aiden, Ariya, Asia, Adonis, De'Aris, Maliyah (daughter, named
# 2026-11-25: "I have a daughter named Maliyah"), and Avery (son,
# named 2026-11-25: "As well as a son named Avery"). That is SEVEN
# named children — it conflicts with the earlier 2026-11-04
# party-of-8 figure (herself + wife + 6 kids), and the total is
# NOT yet confirmed, so NO named child is ever dropped to force
# the count to six, and the roster line says so plainly. Anisa is
# NOT in this list: she is Candice's daughter.
_NAMED_KIDS = ("Aiden", "Ariya", "Asia", "Adonis", "De'Aris", "Maliyah", "Avery")


def _family_roster_line(entries):
    """One-line family roster, or None when the memory does not
    support it: all seven named children must appear in anchor
    (key) entries. The old '6 kids' household line is deliberately
    NOT required — seven named children conflicts with that
    earlier figure, and the total is unconfirmed, so the roster
    states the seven names and flags the conflict instead of
    dropping a child to fit the old count. Anisa is never in the
    roster: the line states outright that she is Candice's
    daughter, not one of Lorenza's children."""
    key_text = " ".join(x for t, x, d, _o in entries
                        if _anchor_kind(t, x) is not None)
    if not all(re.search(r"\b" + re.escape(name) + r"\b", key_text,
                         re.IGNORECASE) for name in _NAMED_KIDS):
        return None
    return ("Lorenza's seven named children are Aiden, Ariya, Asia, "
            "Adonis, De'Aris, Maliyah, and Avery. (Note: seven named "
            "children conflicts with an earlier party-of-8 figure "
            "that said 6 kids — the total is not yet confirmed, so "
            "do not drop any named child.) Anisa is NOT one of her "
            "children: Anisa is Candice's daughter, a ninth-grader.")
_QUERY_STOPWORDS = frozenset(
    "what is the are was were do does did can could would should how why when where who whom whose which that this these those and or but not for with about into your you my her his its their our the a an of to in on at by".split()
)

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
    """All memory as (topic, text, date, origin) tuples, newest
    first where a date exists. Preferences are grouped under topic
    "preferences"; Oracle's own facts under "general". Origin is
    "own" for facts/preferences Oracle itself learned and
    "imported" for Muse-export facts, so the prompt builder can
    rank Oracle's own fresh facts above the bulk import.

    NOTE on dates: all 728 imported items share the import date
    2026-11-24, so newest-first ordering is meaningless across
    them — within one date, entries keep their file order. That
    is exactly why load_memory_text must prioritise by content
    (key facts first), not by date alone: date order alone let
    47 near-identical motion-alert paragraphs fill the old
    6,000-char prompt and starve out the kids and the cars."""
    memory = _load_memory(base_dir)
    entries = []
    for fact in memory.get("facts", []):
        text = fact if isinstance(fact, str) else fact.get("text", "")
        # Use the fact's own date: Oracle's own newly learned facts
        # are dated today, so newest-first ordering puts them at the
        # top of the prompt. (Before this fix facts were added
        # undated, so after the 728-fact Muse import they fell
        # behind all imported entries and were cut off by the
        # 6000-char prompt cap — the agent never saw what it had
        # just learned.)
        date = fact.get("date", "") if isinstance(fact, dict) else ""
        if text:
            entries.append(("general", text, date, "own"))
    for pref in memory.get("preferences", []):
        text = pref if isinstance(pref, str) else pref.get("text", "")
        date = pref.get("date", "") if isinstance(pref, dict) else ""
        if text:
            entries.append(("preferences", text, date, "own"))
    for item in memory.get("imported", []):
        if isinstance(item, dict) and item.get("text"):
            entries.append((item.get("topic", "general") or "general",
                            item["text"], item.get("date", "") or "",
                            "imported"))
    # Newest first where dates exist; undated entries keep their order.
    dated = [e for e in entries if e[2]]
    undated = [e for e in entries if not e[2]]
    dated.sort(key=lambda e: e[2], reverse=True)
    return dated + undated


def _is_motion_alert(text):
    """A camera motion-alert description: long, near-identical,
    and almost no durable information. Only the newest few ever
    belong in a prompt."""
    return str(text).strip().lower().startswith("motion alert:")


def _anchor_kind(topic, text):
    """Key-fact kind for one entry, or None. Kind order is the
    fill order inside the key-facts budget: the Anisa correction
    first (it overrides the old wrong roster), then index lines
    name each person outright, kid-role/wife lines state the
    relationship, car lines state the faults, household lines
    restate the 6-kid party (useful context, first to be cut if
    the budget runs out)."""
    if _ANISA_RE.search(text) and _CANDICE_RE.search(text):
        return "correction"
    if topic in ("Members", "People Index") and (
            _KID_RE.search(text) or _ASHLEY_RE.search(text)):
        return "index"
    if _KID_RE.search(text) and _ROLE_RE.search(text):
        return "kid-role"
    if _WIFE_RE.search(text) and _ASHLEY_RE.search(text):
        return "wife"
    if _CAR_RE.search(text):
        return "car"
    if _HOUSEHOLD_RE.search(text):
        return "household"
    return None


def _query_words(query):
    """Content words from the user's question (lowercased,
    >= 4 chars, stopwords dropped) for query-boost matching."""
    if not query:
        return set()
    words = set()
    for word in re.findall(r"[a-z']+", str(query).lower()):
        if len(word) >= 4 and word not in _QUERY_STOPWORDS:
            words.add(word)
    return words


def _matches_query(text, words):
    if not words:
        return False
    low = str(text).lower()
    return any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words)


def _ordered_entries(base_dir, query=None):
    """Memory entries in prompt order: [(topic, text, date, is_key)].

    1. Key facts first — the Anisa correction, identity/family +
       cars, kind order (correction, index, kid-role, wife, car,
       household), capped at
       KEY_FACTS_CHARS. These are never crowded out: on the real
       2026-11-25 memory the canonical kinds measure ~7,000
       chars, so they always fit, and only household restatements
       are cut if the budget runs out.
    2. Entries matching the user's question (query boost) — so a
       question about any other topic gets its relevant facts
       first too, not just the three known anchor topics.
    3. Oracle's own facts/preferences (what it learned itself),
       newest first, minus motion alerts.
    4. Remaining imported facts, in newest-first/file order.
    5. Motion alerts last, newest MAX_MOTION_ALERTS only — the
       rest stay in memory.json, they just never reach the prompt.
    """
    entries = _all_entries(base_dir)
    words = _query_words(query)
    anchors = {}  # id(entry) -> kind rank
    kind_rank = {"correction": 0, "index": 1, "kid-role": 2, "wife": 3, "car": 4,
                 "household": 5}
    for entry in entries:
        kind = _anchor_kind(entry[0], entry[1])
        if kind is not None:
            anchors[id(entry)] = kind_rank[kind]
    key, rest = [], []
    for entry in entries:
        (key if id(entry) in anchors else rest).append(entry)
    # Kind order first, stable within a kind (keeps _all_entries order).
    key.sort(key=lambda e: anchors[id(e)])
    key_out, key_chars = [], 0
    for entry in key:
        line_len = len(entry[1]) + len(entry[2]) + 6
        if key_chars + line_len > KEY_FACTS_CHARS:
            continue  # skip this restatement; a shorter later one may fit
        key_out.append(entry)
        key_chars += line_len
    # Anchors cut by the key-facts budget are NOT lost: they fall
    # through to the recent fill below, in normal order.
    key_ids = {id(e) for e in key_out}
    rest = [e for e in entries if id(e) not in key_ids]

    motion, other = [], []
    for entry in rest:
        (motion if _is_motion_alert(entry[1]) else other).append(entry)
    query_hits = [e for e in other if _matches_query(e[1], words)]
    query_ids = {id(e) for e in query_hits}
    own = [e for e in other if e[3] == "own" and id(e) not in query_ids]
    imported = [e for e in other
                if e[3] != "own" and id(e) not in query_ids]
    ordered = ([(t, x, d, True) for t, x, d, _o in key_out]
               + [(t, x, d, False) for t, x, d, _o in query_hits]
               + [(t, x, d, False) for t, x, d, _o in own]
               + [(t, x, d, False) for t, x, d, _o in imported]
               + [(t, x, d, False) for t, x, d, _o
                  in motion[:MAX_MOTION_ALERTS]])
    return ordered


def load_memory_text(base_dir, max_chars=DEFAULT_MEMORY_CHARS, query=None):
    """Compact readable text of everything Oracle remembers, for
    the system prompt: key facts (identity/family, cars) first,
    then entries matching the user's question, then Oracle's own
    facts, then the rest newest-first. Bounded to max_chars so
    the prompt stays bounded — default 24,000 chars (~6,000
    tokens, ~5% of gpt-4o-mini's context; the full memory is
    ~159,000 chars and is deliberately never dumped whole).

    Truncation is at a line boundary and always notes how many
    facts were shown out of the total, so a cut prompt never
    silently pretends to be complete — and the key facts, listed
    first under their own header, are the last thing cut."""
    ordered = _ordered_entries(base_dir, query=query)
    if not ordered:
        return "(No stored memory yet.)"
    total = len(ordered)
    lines = []
    in_key = True
    lines.append("[Key facts — always included]")
    roster = _family_roster_line(
        [(t, x, d, o) for t, x, d, o in _all_entries(base_dir)])
    if roster:
        lines.append(f"- {roster}")
    for _topic, text, date, is_key in ordered:
        if in_key and not is_key:
            lines.append("[Recent memory]")
            in_key = False
        suffix = f" ({date})" if date else ""
        lines.append(f"- {text}{suffix}")
    out = "\n".join(lines)
    if len(out) <= max_chars:
        return out
    # Cut at a line boundary under the cap, then note the cut.
    cut = out.rfind("\n", 0, max_chars)
    shown = out[:cut].count("\n- ") if cut > 0 else 0
    note = (f"\n…(memory truncated — showing {shown} of {total} "
            f"facts; key facts above are always included)")
    head = out[:cut] if cut > 0 else out[:max_chars]
    if len(head) + len(note) > max_chars:
        cut2 = head.rfind("\n", 0, max_chars - len(note))
        head = head[:cut2] if cut2 > 0 else head[:max_chars - len(note)]
        shown = head.count("\n- ")
        note = (f"\n…(memory truncated — showing {shown} of {total} "
                f"facts; key facts above are always included)")
    return head + note


def memory_summary_lines(base_dir, max_lines=40):
    """Grouped summary for the GUI's "What do you remember?"
    button: key facts first, then the rest in prompt order,
    capped at max_lines (plus a trailing count line). Uses the
    same prioritised order as load_memory_text, so the summary
    no longer fills up with motion alerts before reaching the
    kids or the cars."""
    ordered = _ordered_entries(base_dir)
    if not ordered:
        return ["I don't remember anything yet.",
                "Import a Muse chat export (.md / .json / .txt) with the",
                "Import button, or drop files into the memory_import",
                "folder next to Oracle and restart me."]
    lines = []
    total = len(ordered)
    shown_key = False
    for _topic, text, date, is_key in ordered:
        if len(lines) >= max_lines:
            break
        if is_key and not shown_key:
            lines.append("[Key facts]")
            shown_key = True
        suffix = f" ({date})" if date else ""
        lines.append(f"  • {text}{suffix}")
    shown = sum(1 for line in lines if line.startswith("  •"))
    if shown < total:
        lines.append(f"…and {total - shown} more fact(s) — {total} remembered in total.")
    return lines
