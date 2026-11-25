"""Offline recall regression test for the Windows Oracle memory fix.

Background (2026-11-24 22:00 EST, verified on the live PC): the GUI's
exact prompt path (gpt-4o-mini) failed three questions —
  * "Who are my kids?" named only Aiden, Anisa, Ariya, Asia
    (missed Adonis and De'Aris);
  * "What is wrong with my Challenger?" — the agent did not know;
  * "What is wrong with my Sonata?" — said P1326 relates to
    variable valve timing (wrong: it is the knock sensor / KSDS
    code, limp mode).
Root cause: load_memory_text() capped the prompt at 6,000 chars
while the full memory is ~159,000 chars, grouped by topic so the
huge "general" group (47 near-identical motion-alert camera
descriptions) filled the whole budget before Facts/Members began.

Fix under test (memory_import.py): key facts (identity/family +
cars) first within a 24,000-char cap (~6,000 tokens, ~5% of
gpt-4o-mini's 128k context), then query-matching facts, then
Oracle's own facts, then the rest; motion alerts capped at the
newest 2 in the prompt tail.

Memory source, in order:
  1. --memory PATH (a memory.json file or a folder containing one),
  2. /tmp/pc-memory.json — a READ-ONLY base64 copy of the live
     J:\\Oracle-Memory\\memory.json fetched from the PC,
  3. ./memory.json next to this script,
  4. --synthetic (or if none of the above exists): a synthetic
     ~800-entry memory built here that mimics the real distribution
     (728 imported entries all dated 2026-11-24, Adonis fact at
     ~entry 113, Challenger at ~entry 148, 47 motion alerts dated
     2026-11-25 flooding the newest-first order).
The source used is printed, and the run FAILS (exit 1) if any
assertion fails. No PC, network, or OpenAI access is needed.

Usage:
    python3 test_recall.py [--memory PATH] [--synthetic]
"""

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import memory_import
import continuous_memory

KIDS = ["Aiden", "Anisa", "Ariya", "Asia", "Adonis", "De'Aris"]
CAP = memory_import.DEFAULT_MEMORY_CHARS  # 24000

REAL_MEMORY = Path("/tmp/pc-memory.json")


# ---------------------------------------------------------------- sources

def _build_synthetic(base_dir):
    """~800-entry memory mimicking the real one: 728 imported
    entries all dated 2026-11-24 (so date order is meaningless),
    the key facts buried at the same depths as the real file, and
    47 long motion alerts dated 2026-11-25 that flood any
    newest-first ordering. Also plants one 'variable valve timing'
    line about an unrelated Hemi forum post, so the test can prove
    the prompt never ties it to P1326."""
    imported = []
    filler_topics = ["general", "Facts", "History", "Open threads",
                     "Preferences", "People Index", "Members",
                     "The relationship", "In common", "Dynamics"]
    for i in range(728):
        topic = filler_topics[i % len(filler_topics)]
        imported.append({
            "text": (f"Filler fact {i}: Lorenza discussed household "
                     f"project item {i} with Muse on 2026-11-24."),
            "topic": topic, "date": "2026-11-24",
            "source": "synthetic.md", "imported_at": "2026-11-24 21:56",
        })
    # Family index lines (topic Members / People Index).
    members = [
        ("Members", "[Ashley Session](../people/ashley-session.md): Lorenza's wife; one of the two adults in the party of 8."),
        ("Members", "[Asia](../people/asia.md): Lorenza's daughter; one of the 6 kids."),
        ("Members", "[Aiden](../people/aiden.md): Lorenza's middle child; one of the 6 kids."),
        ("Members", "[Adonis](../people/son.md): Lorenza's youngest child and 6-month-old son; one of the 6 kids."),
        ("Members", "[Ariya](../people/ariya.md): Lorenza's two-year-old daughter; one of the 6 kids."),
        ("People Index", "**De'Aris Session** — `~/memory/people/dearis-session.md` — Belleville East High School student whose attendance notices are delivered to Lorenza."),
        ("People Index", "**Anisa** — `~/memory/people/anisa.md` — Ninth-grader who walked into the room during Lorenza's 2026-11-24 voice call; Lorenza had Oracle explain how it could help with her ninth-grade homework."),
    ]
    for j, (topic, text) in enumerate(members):
        imported[50 + j] = {"text": text, "topic": topic,
                            "date": "2026-11-24", "source": "synthetic.md",
                            "imported_at": "2026-11-24 21:56"}
    # Canonical facts at the real file's depths (~113 / ~148).
    imported[113] = {"text": "Adonis is Lorenza's youngest child (identified 2026-11-24). Last time he ate, as Lorenza reported 2026-11-24, was at 7:00 PM tonight, 2026-11-24 — a little bit of chicken, per Lorenza when she got home. Ashley asks every day when she gets home when Adonis last ate.",
                     "topic": "Facts", "date": "2026-11-24",
                     "source": "synthetic.md", "imported_at": "2026-11-24 21:56"}
    imported[148] = {"text": "Lorenza owns a 2016 Dodge Challenger R/T Scat Pack (stated 2026-10-27). Current issues as of 2026-10-27: right-side active exhaust valve communication code, and right front turn signal in the headlight not working — left front works, rear right works, factory halos, and the right front amber does not come on with hazards either. The exhaust issue came first, the turn signal about 6 weeks later.",
                     "topic": "Facts", "date": "2026-11-24",
                     "source": "synthetic.md", "imported_at": "2026-11-24 21:56"}
    imported[150] = {"text": "Lorenza also has a 2011 Hyundai Sonata GLS (mentioned 2026-10-27, in connection with Hyundai campaign 953; confirmed 2026-10-30). Sonata issue as of 2026-10-27: P1326 knock sensor / KSDS code, in limp mode, check engine light flashing, no knocking heard, oil level fine. Campaign 953 was completed Oct 16, 2020.",
                     "topic": "Facts", "date": "2026-11-24",
                     "source": "synthetic.md", "imported_at": "2026-11-24 21:56"}
    imported[160] = {"text": "Lorenza's daughter is Asia (identified 2026-10-27, from Lorenza's call log).",
                     "topic": "Facts", "date": "2026-11-24",
                     "source": "synthetic.md", "imported_at": "2026-11-24 21:56"}
    imported[161] = {"text": "Lorenza's two-year-old daughter is Ariya (mentioned 2026-11-24).",
                     "topic": "Facts", "date": "2026-11-24",
                     "source": "synthetic.md", "imported_at": "2026-11-24 21:56"}
    imported[162] = {"text": "Aiden is one of Lorenza's middle children (identified 2026-11-24).",
                     "topic": "Facts", "date": "2026-11-24",
                     "source": "synthetic.md", "imported_at": "2026-11-24 21:56"}
    imported[163] = {"text": "Lorenza's wife is Ashley (identified 2026-11-24, when Lorenza said \"my wife Ashley just got home\").",
                     "topic": "Facts", "date": "2026-11-24",
                     "source": "synthetic.md", "imported_at": "2026-11-24 21:56"}
    imported[200] = {"text": "Challenger forum post: a variable valve timing delete kit was discussed for a 5.7 Hemi build (unrelated to any fault code).",
                     "topic": "general", "date": "2026-11-24",
                     "source": "synthetic.md", "imported_at": "2026-11-24 21:56"}
    # Own facts: 47 motion alerts (the flood) + a few short sightings.
    facts = []
    for i in range(47):
        facts.append({
            "text": (f"Motion alert: What Oracle sees: In the camera snapshot, "
                     f"there is a living room scene with a curved monitor and "
                     f"several cables visible, description variant {i}."),
            "topic": "seen", "date": "2026-11-25", "source": "seen"})
    facts.append({"text": "Saw Lorenza on camera", "topic": "seen",
                  "date": "2026-11-24", "source": "seen"})
    facts.append({"text": "Saw Adonis on camera", "topic": "seen",
                  "date": "2026-11-24", "source": "seen"})
    memory = {"facts": facts, "preferences": [], "imported": imported,
              "imported_files": ["synthetic.md"]}
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "memory.json").write_text(
        json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")
    return base_dir


def _resolve_memory_dir(argv):
    """Returns (base_dir, source_description, tempdir-or-None)."""
    if "--synthetic" in argv:
        tmp = tempfile.mkdtemp(prefix="oracle-recall-synth-")
        return _build_synthetic(tmp), "SYNTHETIC (~800 entries, mimics real distribution)", tmp
    if "--memory" in argv:
        idx = argv.index("--memory")
        given = Path(argv[idx + 1])
        src = given / "memory.json" if given.is_dir() else given
        if not src.exists():
            print(f"ERROR: --memory file not found: {src}")
            sys.exit(2)
        if given.is_dir():
            return given, f"--memory {given} (supplied file)", None
        tmp = tempfile.mkdtemp(prefix="oracle-recall-")
        tmpdir = Path(tmp)
        (tmpdir / "memory.json").write_bytes(src.read_bytes())
        return tmpdir, f"--memory {src} (supplied file)", tmp
    if REAL_MEMORY.exists():
        tmp = tempfile.mkdtemp(prefix="oracle-recall-real-")
        tmpdir = Path(tmp)
        (tmpdir / "memory.json").write_bytes(REAL_MEMORY.read_bytes())
        return tmpdir, "REAL PC memory (/tmp/pc-memory.json — read-only base64 copy of J:\\Oracle-Memory\\memory.json)", tmp
    local = Path(__file__).resolve().parent / "memory.json"
    if local.exists():
        return local.parent, f"local {local}", None
    tmp = tempfile.mkdtemp(prefix="oracle-recall-synth-")
    return _build_synthetic(tmp), "SYNTHETIC (~800 entries, mimics real distribution)", tmp


# ---------------------------------------------------------------- checks

def main(argv):
    base_dir, source, _tmp = _resolve_memory_dir(argv)
    total = memory_import.memory_count(base_dir)
    full = memory_import.load_memory_text(base_dir, max_chars=10_000_000)
    prompt = memory_import.load_memory_text(base_dir)
    low = prompt.lower()
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
              + (f" — {detail}" if detail else ""))

    print(f"Memory source: {source}")
    print(f"Total entries: {total} | full prompt text: {len(full)} chars | "
          f"prompt at default cap: {len(prompt)} chars (cap {CAP})")
    print("Assertions:")

    check("prompt within cap",
          0 < len(prompt) <= CAP, f"{len(prompt)} chars <= {CAP}")
    check("prompt is bounded, not the whole memory",
          len(prompt) < len(full),
          f"{len(prompt)} of {len(full)} chars ({100 * len(prompt) / len(full):.1f}%)")
    check("key-facts header present",
          "[Key facts — always included]" in prompt)
    check("truncation noted (full memory exceeds cap)",
          "memory truncated" in prompt and "key facts above are always included" in prompt,
          "truncation note with shown/total counts" if "memory truncated" in prompt else "NO truncation note")

    for kid in KIDS:
        check(f"kid present: {kid}", kid.lower() in low)
    check("family roster line states all six kids as her children",
          "lorenza's six children are aiden, anisa, ariya, asia, adonis, and de'aris." in low,
          "roster line present" if "six children are" in low else "NO roster line — model will list only the 4 with stated relationships")
    check("Challenger fault: active exhaust valve",
          "active exhaust" in low)
    check("Challenger fault: right front turn signal",
          "turn signal" in low)
    check("Sonata: P1326 present", "p1326" in low)
    check("Sonata: knock sensor present (correct P1326 cause)",
          "knock sensor" in low)
    bad_lines = [ln for ln in prompt.splitlines()
                 if "p1326" in ln.lower()
                 and "variable valve timing" in ln.lower()]
    check("P1326 NOT tied to variable valve timing",
          not bad_lines,
          ("no prompt line links them" if not bad_lines
           else f"OFFENDING LINE(S): {bad_lines[:1]}"))
    print(f"  [info] 'variable valve timing' appears in prompt at all: "
          f"{'variable valve timing' in low} (real memory: never; "
          f"it was a model confabulation, not a stored fact)")
    motion_lines = [ln for ln in prompt.splitlines()
                    if ln.lower().startswith("- motion alert:")]
    check("motion-alert flood capped (<= 2 in prompt)",
          len(motion_lines) <= 2, f"{len(motion_lines)} motion-alert line(s)")

    # Even at the OLD 6,000-char cap, prioritisation must save the
    # key facts — the fix is the ordering, not just the bigger cap.
    old_cap = memory_import.load_memory_text(base_dir, max_chars=6000)
    old_low = old_cap.lower()
    check("at old 6,000-char cap, all 6 kids still present",
          all(k.lower() in old_low for k in KIDS),
          f"{len(old_cap)} chars")
    check("at old 6,000-char cap, Challenger + Sonata still present",
          "active exhaust" in old_low and "p1326" in old_low
          and "knock sensor" in old_low)

    # The three exact questions from the failed 2026-11-24 test,
    # via the GUI's query-boost path.
    for question, needs in [
            ("Who are my kids?",
             KIDS),
            ("What is wrong with my Challenger?",
             ["active exhaust", "turn signal"]),
            ("What is wrong with my Sonata?",
             ["P1326", "knock sensor"])]:
        qp = memory_import.load_memory_text(base_dir, query=question).lower()
        missing = [n for n in needs if n.lower() not in qp]
        check(f"query {question!r} -> all needed facts present",
              not missing,
              f"missing: {missing}" if missing else "all present")

    # The 'What do you remember?' path shares the same cap/prompt.
    remembered = continuous_memory.what_do_you_remember(base_dir)
    check("what_do_you_remember: within cap, all 6 kids present",
          len(remembered) <= CAP
          and all(k.lower() in remembered.lower() for k in KIDS),
          f"{len(remembered)} chars")

    summary = "\n".join(memory_import.memory_summary_lines(base_dir))
    check("memory summary (40 lines) names all 6 kids",
          all(k.lower() in summary.lower() for k in KIDS))

    failed = [name for name, ok, _d in results if not ok]
    print()
    if failed:
        print(f"RESULT: FAIL — {len(failed)} of {len(results)} "
              f"assertion(s) failed: {failed}")
        return 1
    print(f"RESULT: PASS — all {len(results)} assertions passed "
          f"(source: {source})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
