"""Continuous learning memory for Oracle (Windows).

Lorenza's rule, 2026-11-24: the PC version must have its own memory
and work like Muse on the phone — everything it hears, sees and
reads is stored in its memory so it is always learning.

What existed before this module: ``memory.json`` as a schema plus
``memory_import.py`` (one-off import of Muse chat exports) and
``gui.py`` feeding that file into the prompt via
``load_memory_text``. Nothing auto-saved what the PC agent itself
heard, saw or read — ``voice-listening.log`` is only a transcript
log, and both ``C:\\Oracle\\workspace\\memory`` and
``C:\\friend-agent\\workspace\\memory`` were empty folders.

What this module adds, all local-only on the PC, never uploaded:
  * After each voice/text exchange, durable facts and preferences
    are extracted from what was said and appended to memory.json
    (facts + preferences, with date learned + source heard/seen/
    read). Duplicates are never re-added.
  * What it sees: a named face identified, a person enrolled, a
    pan-and-describe sweep, or a motion alert leaves one short
    memory note (who was seen, when, one line about what).
  * What it reads: when reading a file / web page / repair result
    at her request produces a durable fact about her, her
    household, her cars or her projects, that fact is saved too.
  * Recall: the saved facts flow through the existing
    ``memory_import.load_memory_text`` path, so every new
    conversation already sees them. ``what_do_you_remember`` /
    ``forget_matching`` back the "What do you remember?" view and
    the "Forget that" control.

Deliberately NOT stored: raw audio, full transcripts, full camera
frames. Short factual summaries only.
"""

import re
from datetime import datetime

try:
    import memory_import
except Exception:  # pragma: no cover - missing module on some builds
    memory_import = None

# How often the same sighting may be re-noted (per person / per kind).
SIGHTING_COOLDOWN_SECONDS = 600  # 10 minutes
_last_sighting_at = {}  # (kind, key) -> epoch seconds


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _norm(text):
    if memory_import is not None:
        return memory_import._normalize(text)
    return " ".join(str(text).split()).lower().strip()


def _load(base_dir):
    if memory_import is not None:
        return memory_import._load_memory(base_dir)
    return {"facts": [], "preferences": [], "imported": [],
            "imported_files": []}


def _save(base_dir, memory):
    if memory_import is not None:
        memory_import._save_memory(base_dir, memory)


def _already_known(memory, text):
    """True if a fact/preference with the same meaning is stored.

    Exact normalised match, or one normalised text containing the
    other (so 'Lorenza likes pizza' is not re-added as 'likes pizza'
    and a longer restatement of a known fact is skipped too).
    """
    want = _norm(text)
    if not want:
        return True
    for key in ("facts", "preferences"):
        for entry in memory.get(key, []):
            have = _norm(entry.get("text", "") if isinstance(entry, dict)
                         else entry)
            if not have:
                continue
            if have == want or want in have or have in want:
                return True
    return False


def _clean(text, max_chars=200):
    text = " ".join(str(text or "").split()).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].strip() + "…"
    return text


def remember_fact(base_dir, text, topic="general", source="heard"):
    """Append one fact to memory.json unless it is already known.

    Returns True if a new fact was stored, False otherwise.
    """
    text = _clean(text)
    if not text or memory_import is None:
        return False
    memory = _load(base_dir)
    if _already_known(memory, text):
        return False
    memory.setdefault("facts", []).append(
        {"text": text, "topic": topic or "general",
         "date": _today(), "source": source or "heard"})
    _save(base_dir, memory)
    return True


def remember_preference(base_dir, text, source="heard"):
    """Append one preference (likes / dislikes / how she likes
    things done) unless it is already known. Returns True if new."""
    text = _clean(text)
    if not text or memory_import is None:
        return False
    memory = _load(base_dir)
    if _already_known(memory, text):
        return False
    memory.setdefault("preferences", []).append(
        {"text": text, "topic": "preferences",
         "date": _today(), "source": source or "heard"})
    _save(base_dir, memory)
    return True


def note_sighting(base_dir, text, key=None, cooldown=SIGHTING_COOLDOWN_SECONDS):
    """One short 'seen' note, throttled per key so a face in frame
    for an hour does not spam memory. Returns True if stored."""
    import time
    now = time.time()
    k = (key or text) if key else text
    last = _last_sighting_at.get(("seen", k))
    if last is not None and now - last < cooldown:
        return False
    _last_sighting_at[("seen", k)] = now
    return remember_fact(base_dir, text, topic="seen", source="seen")


def note_read(base_dir, text):
    """A durable fact learned from something Oracle read for her
    (file, web page, repair result). Returns True if stored."""
    return remember_fact(base_dir, text, topic="read", source="read")


# ------------------------------------------------------------ extraction

_REMEMBER = re.compile(
    r"^(?:please\s+)?(?:remember|don't forget|dont forget|note)\s+"
    r"(?:that\s+)?(.+)$", re.IGNORECASE)
_FAVOURITE = re.compile(
    r"\bmy (?:favourite|favorite) (\w[\w ]*?) is (.+)$", re.IGNORECASE)
_LIKE = re.compile(r"\bi (?:really )?(?:like|love) (.+)$", re.IGNORECASE)
_DISLIKE = re.compile(
    r"\bi (?:really )?(?:don't like|do not like|dislike|hate|can't stand) "
    r"(.+)$", re.IGNORECASE)
_CALL_ME = re.compile(r"\bcall me (\w[\w\- ]*?)[.!?]?\s*$", re.IGNORECASE)
_PREFER = re.compile(r"\bi prefer (.+)$", re.IGNORECASE)


def _strip_trailing_punct(text):
    return re.sub(r"[.!?]+$", "", str(text).strip())


def extract_from_exchange(user_text, reply_text=None):
    """Heuristic durable facts/preferences from one exchange.

    Conservative by design: only explicit 'remember…', likes /
    dislikes, favourites, 'call me…', and 'I prefer…' are kept.
    Ordinary chat is NOT memorised — the point is durable facts,
    not a transcript. Returns [(kind, text)] with kind 'fact' or
    'preference'.
    """
    found = []
    text = " ".join(str(user_text or "").split()).strip()
    if not text:
        return found
    low = text.lower()

    m = _REMEMBER.match(text)
    if m:
        fact = _strip_trailing_punct(m.group(1))
        if len(fact) >= 4:
            found.append(("fact", fact))
        return found  # explicit remember wins; do not double-extract

    m = _CALL_ME.search(text)
    if m:
        name = _strip_trailing_punct(m.group(1))
        if name:
            found.append(("fact", f"Preferred name: {name}"))
            return found

    m = _FAVOURITE.search(text)
    if m:
        found.append(("preference",
                      f"Favourite {m.group(1).strip()}: "
                      f"{_strip_trailing_punct(m.group(2))}"))
        return found

    m = _DISLIKE.search(text)
    if m:
        found.append(("preference",
                      f"Dislikes {_strip_trailing_punct(m.group(1))}"))
        return found

    m = _LIKE.search(text)
    if m:
        found.append(("preference",
                      f"Likes {_strip_trailing_punct(m.group(1))}"))
        return found

    m = _PREFER.search(text)
    if m:
        found.append(("preference",
                      f"Prefers {_strip_trailing_punct(m.group(1))}"))
        return found

    if low.startswith("my goal is ") or low.startswith("i'm working on "):
        found.append(("fact", _strip_trailing_punct(text)))
    return found


def remember_exchange(base_dir, user_text, reply_text=None):
    """Extract and store durable facts from one exchange.

    Returns how many new facts/preferences were stored (0 is
    normal — most chat is not a durable fact).
    """
    added = 0
    for kind, text in extract_from_exchange(user_text, reply_text):
        if kind == "preference":
            added += bool(remember_preference(base_dir, text))
        else:
            added += bool(remember_fact(base_dir, text))
    return added


# ------------------------------------------------------------ carry-over
# (dedicated data drive / J:\Oracle-Memory)

def copy_memory_to(new_base_dir, old_base_dir):
    """Carry the whole memory home to a new data drive WITHOUT
    starting from zero: copies memory.json and the memory_import/
    folder (source files + import log) from ``old_base_dir`` to
    ``new_base_dir``, then verifies the counts match. Never deletes
    the source. Returns (old_counts, new_counts) as
    (facts, preferences, imported) triples.

    Used when the memory home moves to J:\\Oracle-Memory: the 728
    imported Muse facts must arrive intact (729 total in the source
    build, 728 in the installed build). Raises ValueError when the
    copy does not verify.
    """
    import shutil
    from pathlib import Path
    old_base = Path(old_base_dir)
    new_base = Path(new_base_dir)
    new_base.mkdir(parents=True, exist_ok=True)
    old_counts = memory_counts(old_base)
    src = old_base / "memory.json"
    if not src.exists():
        raise ValueError(f"No memory.json in {old_base} — nothing to carry.")
    shutil.copy2(src, new_base / "memory.json")
    src_import = old_base / "memory_import"
    if src_import.is_dir():
        dst_import = new_base / "memory_import"
        dst_import.mkdir(parents=True, exist_ok=True)
        for item in src_import.iterdir():
            if item.is_file():
                shutil.copy2(item, dst_import / item.name)
    new_counts = memory_counts(new_base)
    if new_counts != old_counts:
        raise ValueError(
            f"Memory carry-over did not verify: {old_base} had "
            f"{old_counts}, {new_base} has {new_counts}. Source kept.")
    return old_counts, new_counts

def what_do_you_remember(base_dir, max_chars=None):
    """Full readable text of everything stored, for the 'What do
    you remember?' view (same text the brain sees in its prompt).

    Default cap is memory_import.DEFAULT_MEMORY_CHARS (24,000):
    the old 6,000-char default starved the prompt — on the real
    2026-11-25 memory it showed only motion-alert camera
    descriptions and none of the kids or the cars. The default
    lives in memory_import so the two can never drift apart
    again; pass max_chars explicitly to override it."""
    if memory_import is None:
        return "(Memory is unavailable — memory_import.py is missing.)"
    if max_chars is None:
        max_chars = getattr(memory_import, "DEFAULT_MEMORY_CHARS", 24000)
    return memory_import.load_memory_text(base_dir, max_chars=max_chars)


# ------------------------------------------------------------ "where did I
# leave X?" — answer from the visual-memory log

_LEFT_BEHIND = re.compile(
    r"(?:where did i (?:leave|put|place|set down|drop)"
    r"|where(?:'s| is) (?:my|the)"
    r"|where did (?:my|the)"
    r"|have you seen (?:my|the)"
    r"|did you see (?:my|the)"
    r"|where is (?:my|the))\s+(.+?)(?:[?.!]|$)",
    re.IGNORECASE)
_LEFT_BEHIND_STOPWORDS = {"my", "the", "a", "an"}


def extract_left_behind_thing(text):
    """The thing in a 'where did I leave / where is my X?' question,
    or None when the text is not that kind of question. 'Where did
    I leave my keys?' -> 'keys'; 'where is the remote?' -> 'remote'."""
    m = _LEFT_BEHIND.search(" ".join(str(text or "").split()))
    if not m:
        return None
    words = [w for w in re.split(r"\s+", m.group(1).strip().lower())
             if w and w not in _LEFT_BEHIND_STOPWORDS]
    thing = " ".join(words).strip(" ?.!").strip()
    return thing or None


def find_last_seen(base_dir, thing):
    """Last stored sighting mentioning ``thing`` (newest first), as
    a plain sentence with its date, or None when nothing in memory
    ever mentioned it. 'Seen'-topic facts (camera sightings: faces,
    sweeps, motion alerts, pan-and-describe notes) are searched
    first, then every other fact. Never guesses: no match means
    None, and the caller must say so plainly."""
    thing = " ".join(str(thing or "").lower().split())
    if not thing:
        return None
    words = [w for w in thing.split() if len(w) > 2]
    if not words:
        return None
    memory = _load(base_dir)
    entries = []
    for key in ("facts", "preferences", "imported"):
        for entry in memory.get(key, []):
            if isinstance(entry, dict):
                entries.append(entry)

    def _matches(entry):
        text = _norm(entry.get("text", ""))
        return all(w in text for w in words)

    for seen_first in (True, False):
        for entry in reversed(entries):
            if seen_first and entry.get("topic") != "seen":
                continue
            if _matches(entry):
                date = entry.get("date") or "an earlier date"
                return (f"{str(entry.get('text', '')).strip()} "
                        f"(noted {date})")
    return None


def forget_matching(base_dir, substring):
    """Remove every stored fact/preference/imported item whose text
    contains ``substring`` (case-insensitive). Returns how many
    were removed. Used by the 'Forget that' control."""
    if memory_import is None:
        return 0
    needle = _norm(substring)
    if not needle:
        return 0
    memory = _load(base_dir)
    removed = 0
    for key in ("facts", "preferences", "imported"):
        kept = []
        for entry in memory.get(key, []):
            text = entry.get("text", "") if isinstance(entry, dict) else entry
            if needle in _norm(text):
                removed += 1
            else:
                kept.append(entry)
        memory[key] = kept
    if removed:
        _save(base_dir, memory)
    return removed


def memory_counts(base_dir):
    """(facts, preferences, imported) counts — for the before/after
    numbers in the source test report."""
    memory = _load(base_dir)
    return (len(memory.get("facts", [])),
            len(memory.get("preferences", [])),
            len(memory.get("imported", [])))
