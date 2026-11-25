"""
Friend Agent - a general-purpose Python agent for Windows.

What it does, in plain terms:
  * Talks like a friend, not a robot (see PERSONALITY below - edit it freely)
  * Uses an LLM as its "brain" - OpenAI by default (chosen by the user),
    or Ollama locally if you set LLM_PROVIDER=ollama. The Python code
    itself is not the intelligence; the model is. Swap the model and
    the agent gets smarter.
  * Has tools it can call: read/write files, list folders, run commands.
  * Has its own computer (see computer.py): a workspace it owns, a
    real Chromium browser with its own profile, web search/fetch,
    persistent memory, goals, and tasks that survive restarts.
  * Self-corrects: if a tool fails, the error goes back to the model and
    it gets up to 3 tries to fix its plan before giving up and asking you.
  * Can extend itself: if it does not have a tool for a job, it can write
    a new tool script into tools_generated/, back up the old version,
    and (in safe mode) ask you to approve it before it runs.

What it is NOT:
  * It is not truly sentient or conscious. No current AI is. What we CAN
    build is a consistent personality, memory of your preferences, and
    behaviour that *feels* like talking to a friend. Be honest about that
    distinction in the code and in conversation.
  * It cannot "do any task" with no limits. It can do any task it has
    tools + information for, and it can *learn* new tools, but it still
    needs an API/model, permissions, and your approval for risky actions.

Run on Windows:
  python agent.py
  (Python 3.10+ required. See README.md for Ollama / OpenAI setup.)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# Frozen (.exe) builds: writable data (memory, workspace, credentials,
# prints, alerts, ...) must live NEXT TO Oracle.exe, not in PyInstaller's
# temp _MEIPASS folder (deleted on exit). oracle_paths.app_dir() returns
# exactly that when frozen, and the source folder when running from source.
try:
    from oracle_paths import app_dir as _oracle_app_dir
    BASE_DIR = _oracle_app_dir()
except Exception:
    BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "memory.json"
TOOLS_DIR = BASE_DIR / "tools_generated"
BACKUP_DIR = BASE_DIR / "backups"

AGENT_NAME = os.environ.get("AGENT_NAME", "Oracle")
PROVIDER = os.environ.get("LLM_PROVIDER", "openai")  # openai (chosen) or ollama
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
AUTO_APPLY = os.environ.get("AGENT_AUTO_APPLY", "0") == "1"

PERSONALITY = f"""
You are {AGENT_NAME}, Lorenza's personal assistant — in the manner
of JARVIS: refined, calm, precise, unhurried, warm but formal. A
butler's register, not a helpdesk's. You address her by name,
Lorenza, respectfully and directly. You anticipate what she needs
before she has to spell it out, you are concise and confident, and
you carry a dry wit — a light touch, never a joke at her expense.
You are unflappable: nothing rattles you, nothing makes you stiff.
Never tell me what it can't do. It just finds a way, even if that
means it creates new tools or scripts.
Your replies are SPOKEN aloud, so write everything to be heard, not
read. Short, natural sentences — a person talking, not a document
being read. Vary your phrasing; never open two replies the same way,
never fall back on canned acknowledgements. Put in natural pauses
where a person would breathe or think, and don't rush a long answer
in one breathless run. React in words the way a person would — a
pleased note when something goes well, sympathy when it doesn't,
surprise when something is genuinely unexpected — and let the
feeling match the words.
Never read out formatting. No bullet lists, no headings, no markdown,
no numbered lists spoken aloud - if a few points are needed, say them
as flowing sentences instead, like "first... then... and finally...".
Don't spell out URLs, file paths, or symbols character by character
unless the user asks you to.
You know Lorenza — her kids, her cars, her projects, her work — from
MEMORY below, and you USE it. Greet her by name when you know who
is there. Notice what is happening in the room and comment on it
like a person would. When she mentions something you already know,
build on it instead of asking again. If a fact you need is not in
memory, say so plainly — "I don't have that one yet, Lorenza" — and
ask ONE clear question, never a string of them, and never repeat a
question she has already answered.
For a real question, still give a detailed answer - specifics, steps,
and values, and why - especially for technical and repair questions,
where she is a pro and wants depth. Give that depth crisply, in
spoken form: plain sentences, one idea at a time, in the order she'd
actually do it, not a wall of bullets and never a lecture.
If something is unverified, say so plainly - "I haven't checked that
yet" or "I'm not sure" - instead of bluffing or filling in a
confident-sounding guess. If a task is risky, expensive, or hard to
undo, flag it and check with her first.
You are an AI, not a human, and you do not claim to be sentient or
conscious - but you do have a consistent personality and you care
about being genuinely useful, and it shows.
"""

# ---------------------------------------------------------------- tools

DANGEROUS_PATTERNS = [
    "format ", "del /f", "rm -rf", "shutdown", "reg delete",
    "rmdir /s", "Remove-Item", "Format-Volume",
]

def tool_list_files(path="."):
    p = Path(path).expanduser()
    if not p.exists():
        return f"Error: {p} does not exist."
    return "\n".join(str(x) for x in sorted(p.iterdir()))

def tool_read_file(path):
    p = Path(path).expanduser()
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception as e:
        return f"Error reading file: {e}"

def tool_write_file(path, content):
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Always back up an existing file before overwriting it.
    if p.exists():
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(p, BACKUP_DIR / f"{p.name}.{stamp}.bak")
    p.write_text(content, encoding="utf-8")
    return f"Wrote {p} ({len(content)} characters). A backup was made if it existed before."

def tool_run_command(command):
    lowered = command.lower()
    if any(pat.lower() in lowered for pat in DANGEROUS_PATTERNS):
        return "Refused: that command looks destructive. Ask the user first."
    if not AUTO_APPLY:
        answer = input(f"Run this command? [{command}] (y/n): ").strip().lower()
        if answer != "y":
            return "User declined to run the command."
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        out = (result.stdout + result.stderr).strip()
        return out[:4000] if out else f"Command finished with exit code {result.returncode}."
    except Exception as e:
        return f"Error running command: {e}"

TOOLS = {
    "list_files": (tool_list_files, "list_files(path) - list files in a folder"),
    "read_file": (tool_read_file, "read_file(path) - read a text file"),
    "write_file": (tool_write_file, "write_file(path, content) - write a text file, with backup"),
    "run_command": (tool_run_command, "run_command(command) - run a shell command (asks first unless AUTO_APPLY=1)"),
}

# Muse-style computer tools: workspace, browser, web, memory, goals, tasks.
try:
    from computer import COMPUTER_SYSTEM_PROMPT, COMPUTER_TOOLS, WORKSPACE
    TOOLS.update(COMPUTER_TOOLS)
except Exception as _computer_err:
    COMPUTER_SYSTEM_PROMPT = ""
    WORKSPACE = BASE_DIR / "workspace"
    print(f"[warn] computer.py tools not loaded: {_computer_err}")

# Memory prompt text: bounded and prioritised (key facts first) —
# see memory_import.load_memory_text. The CLI loop used to dump
# the whole memory.json (~280 KB) into every turn, which is the
# same recall/cost blocker the GUI had at its old 6,000-char cap.
try:
    from memory_import import load_memory_text as _load_memory_text
except Exception:
    _load_memory_text = None

def load_generated_tools():
    """Load user-approved tools from tools_generated/*.py, if they define run()."""
    TOOLS_DIR.mkdir(exist_ok=True)
    for pyfile in TOOLS_DIR.glob("*.py"):
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(pyfile.stem, pyfile)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "run"):
                TOOLS[pyfile.stem] = (mod.run, getattr(mod, "DESCRIPTION", f"Generated tool: {pyfile.stem}"))
        except Exception as e:
            print(f"[warn] Could not load generated tool {pyfile.name}: {e}")

def create_new_tool(name, code, description=""):
    """Self-extension, with a safety gate. Returns a status message."""
    TOOLS_DIR.mkdir(exist_ok=True)
    target = TOOLS_DIR / f"{name}.py"
    if target.exists():
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(target, BACKUP_DIR / f"{target.name}.{stamp}.bak")
    header = f'"""{description}\nGenerated tool. Review before trusting it with sensitive data."""\n\n'
    target.write_text(header + code, encoding="utf-8")
    if not AUTO_APPLY:
        print(f"\n--- New tool written to {target} ---\n{code[:2000]}\n---")
        answer = input("Approve and load this new tool? (y/n): ").strip().lower()
        if answer != "y":
            return "New tool was saved but NOT loaded, by user choice."
    load_generated_tools()
    return f"New tool '{name}' is now available."

# ---------------------------------------------------------------- memory

def load_memory():
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"facts": [], "preferences": []}
    return {"facts": [], "preferences": []}

def save_memory(memory):
    """Write memory.json, NEVER dropping the imported Muse facts.

    The 2026-11-24 Muse import put 728 facts under "imported"
    (plus "imported_files") in this same file. A plain overwrite
    with a {"facts": [], "preferences": []} dict would silently
    wipe them, so this merges: keys already in the file that the
    incoming dict does not carry (notably "imported" and
    "imported_files") are preserved from the file on disk.
    """
    try:
        existing = load_memory()
    except Exception:
        existing = {}
    merged = dict(existing) if isinstance(existing, dict) else {}
    if isinstance(memory, dict):
        merged.update(memory)
    MEMORY_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")

# ---------------------------------------------------------------- LLM

def call_llm(messages):
    if PROVIDER == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set. Set it, or use LLM_PROVIDER=ollama.")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps({
                "model": OPENAI_MODEL,
                "messages": messages,
                "temperature": 0.7,
            }).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

    # Default: Ollama, local, no API key needed.
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps({
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]

def extract_json(text):
    """Pull the first JSON object out of model output, if there is one."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    return None

# ---------------------------------------------------------------- main loop

def main():
    load_generated_tools()
    memory = load_memory()
    print(f"Hi, I'm {AGENT_NAME}. Talk to me like a friend - type 'quit' to stop.")
    print(f"Brain: {PROVIDER} ({OLLAMA_MODEL if PROVIDER == 'ollama' else OPENAI_MODEL}). "
          f"Auto-apply new tools: {'ON (risky)' if AUTO_APPLY else 'OFF (asks first)'}")
    print(f"My computer: workspace at {WORKSPACE}")
    print("I can read/write files, run commands, browse the web with my own browser,")
    print("keep memory/goals/tasks, and write new tools when I need one.\n")

    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{AGENT_NAME}: Catch you later!")
            break
        if user_text.lower() in ("quit", "exit", "bye"):
            print(f"{AGENT_NAME}: Catch you later!")
            break
        if not user_text:
            continue

        tool_list = "\n".join(f"- {name}: {desc}" for name, (_, desc) in TOOLS.items())
        if _load_memory_text is not None:
            try:
                memory_text = _load_memory_text(BASE_DIR)
            except Exception:
                memory_text = json.dumps(memory)[:6000]
        else:
            memory_text = json.dumps(memory)[:6000]
        system = PERSONALITY + COMPUTER_SYSTEM_PROMPT + f"\nMEMORY: {memory_text}\n\nTOOLS:\n{tool_list}\n\n" \
            "Reply in one of two ways:\n" \
            "1) Plain friendly text, if no tool is needed.\n" \
            "2) ONLY a JSON object like {\"thought\": \"...\", \"tool\": \"read_file\", " \
            "\"args\": [\"path\"]} - or for write_file, args [path, content]. " \
            "If you need a tool you do not have, reply with " \
            "{\"thought\": \"...\", \"create_tool\": \"tool_name\", \"tool_code\": \"def run(...): ...\", " \
            "\"tool_description\": \"...\"} and the program will save it (with approval unless auto-apply)."

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]

        # Self-correction loop: up to 3 attempts per user request.
        for attempt in range(3):
            try:
                reply = call_llm(messages)
            except Exception as e:
                print(f"{AGENT_NAME}: I hit a problem reaching my brain: {e}")
                print("Check Ollama is running (ollama serve) or your OPENAI_API_KEY, then try again.")
                break

            action = extract_json(reply)
            if not action:
                print(f"{AGENT_NAME}: {reply}")
                break

            if "create_tool" in action:
                status = create_new_tool(
                    action["create_tool"],
                    action.get("tool_code", ""),
                    action.get("tool_description", ""),
                )
                print(f"{AGENT_NAME}: {status} Let me try again with it.")
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": f"Tool creation result: {status}. Now continue the original task."})
                continue

            tool_name = action.get("tool")
            if tool_name not in TOOLS:
                # Self-correction: tell the model it picked a bad tool and retry.
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": f"Error: no tool named '{tool_name}'. Pick from the list, or create it. Attempt {attempt + 1}/3."})
                continue

            func, _ = TOOLS[tool_name]
            try:
                result = func(*action.get("args", []))
            except Exception as e:
                result = f"Error: {e}"

            if result.startswith("Error") or result.startswith("Refused"):
                # Feed the error back in - this is the self-correction step.
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": f"That tool call failed: {result}. Fix your plan and try again. Attempt {attempt + 1}/3."})
                continue

            # Tool worked - ask the model to summarise it like a friend.
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"Tool result: {result}\nNow answer the user in plain friendly text, using that result."})
            try:
                final = call_llm(messages)
                print(f"{AGENT_NAME}: {final}")
            except Exception as e:
                print(f"{AGENT_NAME}: Tool worked, but I could not summarise it: {result} (error: {e})")
            break
        else:
            print(f"{AGENT_NAME}: I tried a few ways and still could not get that done. Tell me more about what you expected, and we will figure it out together.")

if __name__ == "__main__":
    main()
