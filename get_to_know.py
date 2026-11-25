"""
"Get to know me" mode for Oracle (Windows, home PC only).

Optional, never required. When a person says "get to know me"
(also "learn about me", "get to know you", "let's get to know each
other"), Oracle asks the questions below ONE at a time, in a natural
voice conversation. The person can say "skip" on any question and
"stop" to end it at any time; it never asks again unless they say
the trigger again. Answers are stored locally on the PC only, under
that person's identity (identities/<name>/get_to_know.json), and are
never sent anywhere. No questions about health, money, passwords,
or addresses — the list below is the whole list.

Storage reuses identity.py's identities/ folder (same local-only
rule as voice/face profiles). The person's name comes from
question 1 ("What should I call you?"); until then answers are
kept in memory and saved under "guest" if they never give a name.
"""

import json
from datetime import datetime
from pathlib import Path

try:
    from oracle_paths import app_dir as _oracle_app_dir
    BASE_DIR = _oracle_app_dir()
except Exception:
    BASE_DIR = Path(__file__).resolve().parent
IDENTITIES_DIR = BASE_DIR / "identities"

TRIGGERS = (
    "get to know me",
    "learn about me",
    "get to know you",
    "let's get to know each other",
    "lets get to know each other",
)

STOP_WORDS = ("stop", "quit", "end", "that's enough", "never mind",
              "nevermind", "stop please", "please stop", "end this")
SKIP_WORDS = ("skip", "skip this", "skip this one", "pass", "next question")

# (group, key, question) — in order, grouped as Lorenza wrote them.
QUESTIONS = [
    ("Basics", "preferred_name",
     "What should I call you?"),
    ("Basics", "greeting_style",
     "How do you like to be greeted — casual, warm, straight to business?"),
    ("Basics", "three_words",
     "What are three words you'd use to describe yourself?"),
    ("Likes", "favourite_food",
     "What's your favourite food — and is there any food you really don't like?"),
    ("Likes", "music",
     "What kind of music do you like, and is there an artist you always go back to?"),
    ("Likes", "watching",
     "What do you like watching — movies, shows, anything you always rewatch?"),
    ("Likes", "free_time",
     "What do you do for fun when you have free time?"),
    ("Likes", "hobby",
     "What's a hobby or interest you could talk about for hours?"),
    ("Personality and how they think", "morning_or_night",
     "Are you more of a morning person or a night person?"),
    ("Personality and how they think", "big_decisions",
     "When you have a big decision to make, how do you usually think it through?"),
    ("Personality and how they think", "time_priorities",
     "What matters most to you when you're choosing what to do with your time?"),
    ("Personality and how they think", "frustration_calm",
     "What frustrates you most, and what helps you calm down?"),
    ("Personality and how they think", "learning_style",
     "How do you like to learn something new — watching, doing it hands-on, or someone walking you through it?"),
    ("Personality and how they think", "humour",
     "What's your sense of humour like — dry, silly, sarcastic?"),
    ("How Oracle should talk to them", "answer_length",
     "Do you prefer short answers, or detailed ones with the steps and the reasoning?"),
    ("How Oracle should talk to them", "do_not_bring_up",
     "Is there anything you don't want me to bring up or remind you about?"),
    ("How Oracle should talk to them", "current_goal",
     "What's one goal you're working on right now that I can help with?"),
    ("Wrap-up", "anything_else",
     "Is there anything else you want me to remember about you?"),
]


def is_trigger(text):
    low = " ".join(str(text or "").lower().split())
    return any(t in low for t in TRIGGERS)


def _safe_name(name):
    keep = "".join(c for c in str(name or "").strip()
                   if c.isalnum() or c in (" ", "-", "'", "."))
    keep = " ".join(keep.split())
    return keep[:40] if keep else "guest"


def _file_for(person):
    return IDENTITIES_DIR / _safe_name(person) / "get_to_know.json"


def load_answers(person):
    p = _file_for(person)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data.get("answers", {})
        except Exception:
            pass
    return {}


def summary_text(person):
    """Plain-text review of what was learned (for the GUI)."""
    answers = load_answers(person)
    if not answers:
        return f"I haven't learned anything about {person} yet."
    lines = [f"What I've learned about {person} (stored locally only):"]
    for _group, key, q in QUESTIONS:
        if key in answers:
            lines.append(f"- {q} {answers[key]}")
    return "\n".join(lines)


def delete_answers(person):
    p = _file_for(person)
    if p.exists():
        p.unlink()
        return f"Forgot what {person} told me in Get to know me mode."
    return f"Nothing stored for {person} to forget."


class Session:
    """One Get-to-know-me conversation. Asks one question at a time."""

    def __init__(self, person=None):
        self.person = person  # may be None until question 1 is answered
        self.index = 0
        self.answers = {}
        self.active = True

    def _progress(self):
        return (f"(question {self.index + 1} of {len(QUESTIONS)} — "
                "say 'skip' to pass, 'stop' to end)")

    def _question_text(self):
        _group, _key, q = QUESTIONS[self.index]
        return f"{q} {self._progress()}"

    def start_text(self):
        return ("Let's get to know each other — I'll ask you a few "
                "questions, one at a time, and you can skip any of them "
                "or say stop whenever you like. " + self._question_text())

    def _save(self):
        person = self.person or "guest"
        d = IDENTITIES_DIR / _safe_name(person)
        d.mkdir(parents=True, exist_ok=True)
        data = {"person": person, "answers": self.answers,
                "updated": datetime.now().isoformat()}
        _file_for(person).write_text(json.dumps(data, indent=2),
                                     encoding="utf-8")

    def _advance(self):
        self.index += 1
        if self.index >= len(QUESTIONS):
            self.active = False
            n = len(self.answers)
            name = self.person or "friend"
            return (f"That's everything — thanks for letting me get to "
                    f"know you, {name}. I remembered {n} thing(s) about "
                    "you, stored on this PC only. Say 'get to know me' "
                    "anytime if you want to add or change anything.")
        return self._question_text()

    def answer(self, text):
        """Handle one reply. Returns the next thing Oracle should say."""
        low = " ".join(str(text or "").lower().split())
        if low in STOP_WORDS:
            self.active = False
            n = len(self.answers)
            return (f"No problem — we'll stop there. I kept the {n} "
                    "thing(s) you told me, stored on this PC only.")
        if low in SKIP_WORDS:
            return self._advance()
        _group, key, _q = QUESTIONS[self.index]
        self.answers[key] = str(text or "").strip()
        if key == "preferred_name" and self.answers[key]:
            self.person = self.answers[key]
        self._save()
        return self._advance()
