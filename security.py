"""
Security knowledge for Oracle - ethical penetration testing, defensive
security, and jailbreaking / rooting your OWN devices.

Scope - read this first, it is built into how Oracle should use this:
  * Oracle is well-versed in these topics for LEARNING and for testing
    systems you OWN, or systems you have explicit written authorization
    to test (for example, a lab VM, your home network, your own phone,
    or a bug-bounty target within its published scope).
  * Oracle must NOT use this knowledge to break into someone else's
    device, account, network, or PIN/lock screen without authorization.
    Before any scan, test, or exploit step, Oracle asks:
      "Do you own this target, or do you have written authorization to test it?"
    If the answer is no, or unclear, it stops that step and explains
    how to set up a lab target instead.
  * This module is methodology + defensive knowledge, not a bundle of
    ready-to-run exploits against other people's systems. It teaches
    the workflow, the tools, and how to fix what you find.

What is covered (see SECURITY_KNOWLEDGE.md for the full curriculum):
  1. Penetration testing methodology: scope, recon, scanning,
     enumeration, exploitation (in a lab), privilege escalation,
     persistence (for testing), and reporting / remediation.
  2. Common tool families: Nmap, Wireshark, Burp Suite, Metasploit
     (lab only), Hydra / John (for auditing YOUR OWN password hashes
     in a lab), SQLmap (for YOUR OWN test apps), etc.
  3. PIN / password testing, done legitimately: testing lockout
     policies, PIN strength, and password policies on YOUR OWN
     accounts and test devices, in a lab, with test accounts - not
     brute-forcing a real person's phone or account.
  4. Jailbreaking / rooting YOUR OWN device: iOS jailbreak concepts
     (tethered / semi-tethered / untethered, checkm8-style bootrom
     concepts, palera1n / Dopamine-style tools as examples - check
     current compatibility for your exact iOS version and device),
     Android rooting (unlock bootloader, Magisk, custom recovery),
     risks (bricking, voided warranty, security loss, banking apps
     refusing to run), and backup-first steps.
  5. Defensive side: hardening, patching, MFA, lockout, logging,
     and how to turn a finding into a fix.

How Oracle uses this:
  * When you ask about a security topic, Oracle loads this knowledge
    and answers in that framework, with the authorization check above.
  * For a hands-on test, Oracle will first help you build a lab:
    a Windows VM, a Linux VM (Kali / Ubuntu), a vulnerable-by-design
    test app (DVWA, Metasploitable, Juice Shop), and your own phone
    in a test state - not a live target you do not own.
"""

import os

AUTHORIZATION_REQUIRED = True


def check_authorization(target, owned_or_authorized=False):
    """
    Gate for any active testing step.
    Returns (allowed, message). If owned_or_authorized is False,
    Oracle must ask the user and stop.
    """
    if owned_or_authorized:
        return True, f"Authorization confirmed for {target}. Proceeding in scope."
    return False, (
        f"Stopped: I do not have confirmation that you own {target} or have "
        "written authorization to test it. Tell me: do you own it, or do you "
        "have written authorization? If not, I can help you set up a lab "
        "target (a VM or vulnerable test app) to practise the same technique safely."
    )


def pen_test_checklist(target="your lab target"):
    return f"""
Pen test checklist for {target} - authorized testing only:
  1. Scope & authorization - write down what is in scope, what is out,
     and keep the authorization proof. Stop if scope is unclear.
  2. Recon - passive only at first: DNS, WHOIS, public info, no active probing
     outside scope.
  3. Scanning - Nmap / service detection on in-scope hosts only.
  4. Enumeration - services, versions, shares, web endpoints, on in-scope hosts.
  5. Vulnerability analysis - match versions to known CVEs, test in a lab
     first, never run a destructive exploit on a live system you do not own.
  6. Exploitation (lab only) - use Metasploit / manual exploits against
     your test VM, with snapshots so you can roll back.
  7. Privilege escalation & post-exploitation - in the lab, document how
     you got there, not how to hide from a real owner.
  8. Reporting & remediation - what was found, how severe, how to fix it,
     and re-test after the fix.
"""


def pin_and_password_testing_guidance():
    return """
PIN / password testing - legitimate version:
  * Test YOUR OWN lockout policy: how many wrong PINs before lockout,
    how long the lockout lasts, and whether a test account locks.
  * Test PIN strength in a lab: use test accounts with weak, common,
    and strong PINs/passwords, and audit your own password hashes
    (e.g. from a lab VM you control) with John / Hashcat to see
    which would crack quickly - then change them.
  * Do NOT brute-force a real person's phone, account, or PIN. That
    is unauthorized access, it will lock the account, and it can
    destroy data. If you forgot YOUR OWN PIN, use the manufacturer's
    official recovery / reset process for that device, with proof
    of ownership, not a brute-force tool.
"""


def jailbreak_guidance(device="your own device"):
    return f"""
Jailbreaking / rooting {device} - your own device only, backup first:
  * Back up everything first. Jailbreaking / rooting can brick a device
    and can wipe data.
  * iOS: jailbreak tools are version- and device-specific. Check current
    compatibility for your exact iOS version and chip before you start,
    and use only the official site for that tool - fake jailbreak sites
    are a common malware source. Expect: warranty / support changes,
    some banking and work apps may refuse to run, and you must keep
    the device updated carefully or you may lose the jailbreak.
  * Android: rooting usually means unlocking the bootloader (which
    wipes the device), then flashing Magisk / a custom recovery.
    Check your exact model and carrier - some carriers / models do
    not allow bootloader unlock.
  * After rooting/jailbreaking: only install software from sources
    you trust, keep a way back (stock firmware / backup), and do not
    use a rooted device as your only banking device without
    understanding the risk.
"""
