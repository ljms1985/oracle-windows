# Oracle Security Knowledge — Ethical Pen Testing, Hacking Concepts, Jailbreaking

This is Oracle's study / practice curriculum. It is for learning and
for authorized testing of systems you own or are authorized to test.

## Ground rule

Before any active test, Oracle asks: do you own this target, or do you
have written authorization to test it? If not, it stops and helps you
build a lab target instead. That rule is in `security.py`.

## 1. Penetration testing — the full workflow

- **Scope:** targets, time window, allowed techniques, out-of-scope systems.
- **Recon:** passive (DNS, WHOIS, certificates, public repos) then active (in scope only).
- **Scanning:** Nmap for hosts/ports/services, version detection, OS fingerprinting.
- **Enumeration:** SMB, SNMP, web directories, API endpoints, user accounts (in lab).
- **Vulnerability analysis:** CVE matching, misconfigurations, default credentials (in lab).
- **Exploitation:** lab-only, with VM snapshots. Learn the concept (e.g. SQL injection,
  XSS, buffer overflow, privilege escalation) and how to fix it, not just how to run it.
- **Post-exploitation & reporting:** what an attacker could reach, evidence, severity,
  remediation steps, re-test.

## 2. Tool families to learn (in a lab)

- Network: Nmap, Wireshark, tcpdump
- Web: Burp Suite, OWASP ZAP, SQLmap (against your own test apps: DVWA, Juice Shop)
- Password auditing (your own hashes, in a lab): John the Ripper, Hashcat
- Exploitation framework (lab only): Metasploit against Metasploitable / vulnerable VMs
- Wireless (your own network only): Aircrack-ng concepts, WPA2/WPA3 auditing of your own AP
- Mobile: Frida / Objection concepts for your own apps, in a test environment

## 3. PIN testing — legitimate form

- How lockouts work, how to test your own lockout policy safely with test accounts.
- PIN entropy: why 4-digit PINs are weak, why length + lockout + MFA matter.
- Auditing your own password/PIN hashes in a lab to find weak ones, then changing them.
- Official recovery for a device you own and forgot the PIN for — manufacturer reset
  with proof of ownership, not brute-forcing someone else's device.

## 4. Hacking concepts — defensive framing

For each attack class, Oracle should be able to explain: how it works,
how to detect it, and how to prevent it.
- Phishing / social engineering — detection, training, MFA, email authentication (SPF/DKIM/DMARC)
- Malware / persistence — how it hides, how to hunt it, how to clean it
- Privilege escalation — Windows/Linux misconfigurations, how to harden
- Web attacks — SQLi, XSS, CSRF, SSRF, IDOR — with fixes (parameterized queries, encoding, auth checks)
- Network attacks — MITM, DNS spoofing, ARP spoofing — in a lab, with TLS / VPN / network segmentation as fixes

## 5. Jailbreaking and rooting — your own device only

- **iOS jailbreaking:** what it does (removes Apple's restrictions, gives root access),
  types (tethered, semi-tethered, untethered, semi-untethered), why tools are version-specific,
  risks (bricking, security, banking apps, warranty), backup-first rule.
- **Android rooting:** bootloader unlock (wipes device), Magisk (systemless root),
  custom recovery (TWRP), risks and how to return to stock.
- **After:** only trusted sources, keep a stock backup, understand that a rooted/jailbroken
  device is less trustworthy for banking and work apps.

## 6. Defensive hardening — the other half

- Patching, MFA everywhere, strong unique passwords + password manager, lockout policies
- Windows: Defender, firewall, BitLocker, least privilege, audit logging
- Home network: router firmware, change default passwords, guest network, WPA3, disable UPnP if unused
- Phone: OS updates, app permissions, lock screen, Find My / remote wipe for your own device

## Practice lab to build first

1. A Windows VM + a Kali Linux VM (VirtualBox / Hyper-V, host-only network)
2. Metasploitable or DVWA / Juice Shop as a deliberately vulnerable target
3. Your own home network, with permission, for Nmap scanning practice
4. Your own phone, backed up, if you want to practise jailbreaking/rooting concepts

Start there, and Oracle can walk through each technique in that lab, step by step.
