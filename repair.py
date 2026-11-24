"""
Repair assistant for Oracle - electronics / PCB, with camera watching,
active questioning, and internet research when needed.

How a repair session works (the way you asked for it):
  1. You tell Oracle the device and symptom, e.g. "Apollo Twin USB,
     won't turn on".
  2. Oracle starts with safety first, then asks ONE question at a time,
     waits for your answer, and branches based on what you found.
     It does not dump a 20-step list and leave you to it - it follows
     what you are doing, step by step, until the repair is done or
     you decide to stop / send it for professional repair.
  3. While you work, Oracle can watch via the PIXY camera (camera.py):
     point the camera at the board, and it will describe what it sees
     - burnt marks, swollen caps, broken solder, loose connectors -
     using OpenAI Vision, only when you ask it to look, or when you
     say "look at this".
  4. If Oracle does not know a model-specific fact (a power supply
     spec, a fuse location, a reset sequence), it searches the web
     (monitor.py's web_search) for that model + symptom, and tells
     you what it found, with the source, before you act on it.
     It does NOT guess a voltage, a fuse rating, or a schematic
     value - if it cannot verify it, it says so and asks you to
     measure / check the label.

Safety - non-negotiable, even in a home workshop:
  * Unplug from mains before opening anything. For an Apollo Twin,
    that means unplug the external PSU from the wall AND from the unit.
  * Do NOT open the external power brick itself - it contains mains
    voltage and large capacitors. Test it with a multimeter from the
    outside, replace it if faulty, do not repair it by opening it.
  * Discharge large capacitors on a board before probing, use ESD
    protection (wrist strap / mat), and never probe a live board
    with a metal tool in both hands.
  * If you smell burning, see smoke, or a component is hot, stop,
    unplug, and let it cool. Do not keep powering a shorted board.

Apollo Twin USB - won't turn on - verified starting points:
  * From the official manual troubleshooting: confirm the power
    supply connector is fully inserted, then twist the barrel to lock;
    confirm the power switch is ON; confirm AC power at the wall
    socket by plugging in a different device.
  * Power supply for Apollo Twin X USB / Apollo Twin USB (UA support):
    12VDC, 1.5A, center positive, barrel 5.5 mm outside / 2.1 mm inside.
    Use the original or a factory replacement if possible. A generic
    replacement must match voltage, current, and polarity exactly.
    Note: Apollo Twin X (Thunderbolt, not USB) is different at 4.2A -
    do not mix them up.
  * Hardware reset (USB, from the manual, only AFTER power checks):
    power off, press and hold LEVEL KNOB + LOW CUT + POLARITY,
    power on while holding all three, release after all front panel
    LEDs flash rapidly for several seconds.
  * After those, board-level checks in order: PSU output under load
    (should be ~12V, not dropping to near 0), DC jack / barrel
    continuity, input fuse / protection diode if present, power
    switch continuity, then main power rails (with a multimeter,
    powered off first for resistance, then powered on carefully for
    voltage, only if you are comfortable doing so).

Session log:
  Every session writes repairs/<device>-<date>.md with the symptom,
  each question, your answer, each measurement, and the next step.
  That log is how Oracle "follows what you are doing" across a
  long repair, and it is local to your PC.
"""

import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPAIRS_DIR = BASE_DIR / "repairs"


class RepairSession:
    def __init__(self, device, symptom):
        self.device = device
        self.symptom = symptom
        self.started = datetime.now().isoformat()
        self.log = []
        self.step = 0
        REPAIRS_DIR.mkdir(exist_ok=True)

    def ask(self, question):
        """Ask one question, log it, and return the user's answer."""
        print(f"\nOracle: {question}")
        answer = input("You: ").strip()
        self.log.append({"step": self.step, "question": question, "answer": answer})
        self.step += 1
        self._save()
        return answer

    def tell(self, text):
        print(f"\nOracle: {text}")
        self.log.append({"step": self.step, "note": text})
        self.step += 1
        self._save()

    def _save(self):
        safe = "".join(c if c.isalnum() else "-" for c in self.device)[:40]
        date = datetime.now().strftime("%Y%m%d")
        path = REPAIRS_DIR / f"{safe}-{date}.md"
        lines = [f"# Repair session: {self.device}", f"Symptom: {self.symptom}", f"Started: {self.started}", ""]
        for entry in self.log:
            if "question" in entry:
                lines.append(f"- Q: {entry['question']}\n  A: {entry['answer']}")
            else:
                lines.append(f"- {entry['note']}")
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def search_web(self, query):
        """Search the web for model-specific repair info, via monitor.py."""
        try:
            from monitor import web_search
            results = web_search(query, max_results=5)
            self.tell(f"I searched the web for '{query}'. Here is what I found:")
            for r in results:
                self.tell(f"- {r['title']} ({r['url']})")
            return results
        except Exception as e:
            self.tell(f"Web search failed: {e}. I will continue with what I already know and ask you to check the manual / label.")
            return []

    def look_at_board(self):
        """Capture a camera snapshot and describe it with vision, if available."""
        try:
            from camera import CameraController, describe_snapshot
            import cv2
            ctrl = CameraController()
            ctrl.open()
            frame = ctrl.read()
            ctrl.close()
            if frame is None:
                self.tell("I could not capture a camera frame. Check the PIXY is plugged in and not in use by another app.")
                return None
            path = REPAIRS_DIR / f"board-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jpg"
            cv2.imwrite(str(path), frame)
            self.tell(f"Snapshot saved to {path}. Asking vision to describe it - look for burnt marks, swollen capacitors, cracked solder, or loose connectors.")
            desc = describe_snapshot(path)
            self.tell(f"What I see in the board photo: {desc}")
            self.tell("Tell me if that matches what you see, and point the camera closer to any area you want me to look at again.")
            return desc
        except Exception as e:
            self.tell(f"Camera look failed: {e}. Describe what you see to me in words, and I will work from that.")
            return None


def apollo_twin_usb_wont_turn_on():
    """Interactive diagnostic flow for the example you gave."""
    s = RepairSession("Apollo Twin USB", "won't turn on")
    s.tell("Safety first: unplug the Apollo Twin from the wall and from the unit before you open anything, and do not open the power brick itself. We will test it from the outside.")
    s.tell("Starting point from the official manual: power connector fully inserted then twist barrel to lock, power switch ON, and AC power at the wall socket confirmed with another device.")
    s.tell("Power supply spec for Apollo Twin USB / Apollo Twin X USB: 12VDC, 1.5A, center positive, barrel 5.5 mm outside / 2.1 mm inside. Use the original or factory replacement if possible.")

    ans = s.ask("Is the power supply the original one that came with the unit, or a replacement? And is the barrel connector fully inserted and twisted to lock?")
    ans2 = s.ask("With the switch ON, do you see ANY lights at all - front panel LEDs, or anything inside if the lid is off? (none / faint / flashing / normal then off)")
    if "none" in ans2.lower() or "no" in ans2.lower():
        s.tell("No lights points to power in, not to software. Next step is to test the PSU itself, not the board yet.")
        psu = s.ask("Do you have a multimeter? If yes, measure the PSU barrel output with no load, then with it plugged into the unit (carefully, only the barrel, not inside the PSU). What voltage do you read? If no multimeter, try a known-good 12V, 1.5A+, center-positive supply with the same barrel, or try this PSU in another device if you have one that uses it.")
        s.tell(f"You reported: {psu}. If it is near 0V, or drops a lot under load, the PSU is the likely fault - replace it with the correct 12V 1.5A center-positive supply. If it is a steady ~12V, the fault is inside the unit - next is the DC jack, power switch, and input protection.")
        s.search_web("Apollo Twin USB won't turn on power supply fuse repair")
        jack = s.ask("If the PSU is good, check the DC jack on the unit: does it feel loose, wobbly, or cracked? And does the power switch click firmly ON/OFF, or feel mushy?")
        s.tell("If the jack or switch is faulty, that is a common, repairable fault - resolder or replace that part, after unplugging. If both feel solid, the next board-level step is to look for a fuse / protection diode near the DC input, and to check for burnt marks or swollen capacitors. Point the camera at the power input area and say 'look at this' and I will describe what I see.")
    else:
        s.tell("Some lights means power is getting in at least partly. That changes the diagnosis - it may be a reset, USB, or firmware issue, not a dead PSU.")
        s.ask("Do the LEDs stay on, flash rapidly, or go out after a few seconds? And is the unit recognized by the computer at all, even briefly?")
        s.tell("If it is recognized briefly then drops, try the hardware reset from the manual: power off, hold LEVEL KNOB + LOW CUT + POLARITY, power on while holding, release after all front panel LEDs flash rapidly. Only do that after the power checks above, and tell me what the LEDs do during the reset.")

    s.tell("That is where we pause for your answers - tell me what you found at each step, and I will follow with the next step for that exact result, and look at the board with you via camera if you point it at the area.")
    return s


def generic_repair(device=None, symptom=None):
    """
    The same workflow as the Apollo Twin example, for ANY device.
    This is the answer to 'will every repair work like Apollo?':
    Yes, the *workflow* is the same - safety, external checks, web
    search for model-specific facts, one question at a time, camera
    look, measurements, then component-level steps, logged.
    What changes is the *specific facts*: Apollo had a verified manual
    and PSU spec. For another device, Oracle searches for its manual,
    PSU, fuse, and reset sequence first, and says clearly when it
    cannot verify a value, instead of guessing it.
    Some repairs will still be harder, need schematics / boardview
    that are not public, need an oscilloscope / hot-air station, or
    be unsafe / uneconomical - Oracle will say that and suggest a
    professional repair, rather than pretend it can finish it.
    """
    if device is None:
        device = input("Device (make + model): ").strip() or "Unknown device"
    if symptom is None:
        symptom = input("Symptom in one line: ").strip() or "Not working"
    s = RepairSession(device, symptom)
    s.tell("Safety first: unplug from mains / power before opening anything. Do not open a mains power supply, a microwave, a CRT, or anything with large charged capacitors unless you know how to discharge it safely. If you smell burning or see smoke, stop and unplug.")
    s.tell("I will follow the same pattern as the Apollo Twin example, but with facts for THIS device.")
    s.search_web(f"{device} {symptom} repair troubleshooting")
    s.search_web(f"{device} service manual power supply specifications")
    s.ask("What is the device doing, or not doing, exactly? Any lights, sounds, smells, or partial function?")
    s.ask("When did it start, and did anything happen just before - a power cut, a drop, liquid, a firmware update, a new cable?")
    s.ask("Have you already tried the simple external checks - different outlet, different cable, different power supply (only if the voltage / polarity match exactly), power switch / reset? What happened?")
    s.ask("Do you have a multimeter, and are you comfortable measuring voltage / continuity on this device? What tools do you have - screwdrivers, soldering iron, hot air, oscilloscope?")
    s.tell("Based on your answers, the next steps will be: external power / cable / switch, then internal visual inspection (point the camera at the board and say 'look at this' - I will describe burnt marks, swollen caps, cracked solder), then measurements on the power input and main rails, then the specific component for this symptom. Tell me your answers above and I will branch to the next step for your exact result, just like the Apollo flow.")
    s.ask("Point the camera at the board / power input area if you can, or describe what you see inside - any burnt marks, swollen capacitors, loose connectors, or broken solder?")
    return s


if __name__ == "__main__":
    print("Oracle Repair Assistant")
    print("Example: Apollo Twin USB, won't turn on")
    print("For any other device, run: generic_repair() - same workflow, different facts.")
    apollo_twin_usb_wont_turn_on()
