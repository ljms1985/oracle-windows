# Oracle for Windows — GitHub setup (build the .exe in the cloud)

You do **not** need to install packaging tools to do this. GitHub's own
Windows computers build `Oracle.exe` for you, free on the free GitHub
plan for public repos.

## 1. Repo

`https://github.com/ljms1985/oracle-windows` (public). The source in
this folder plus `.github/workflows/build-windows.yml` is pushed there.

## 2. Run the build

1. On GitHub, open the `oracle-windows` repo.
2. Click the **Actions** tab at the top.
3. In the left sidebar, click **Build Oracle for Windows**.
4. Click **Run workflow** (top right), then **Run workflow** again.
5. Wait a few minutes. The run shows a green tick when it finishes.
   If it goes red, click into it — the failing step's log says what
   went wrong (usually a missing dependency or a typo in the spec).

You can also trigger a build by pushing a tag:

```bash
git tag v1.0.0
git push --tags
```

## 3. Download the finished .exe

1. When the run is green, click into it.
2. Scroll to the bottom, to **Artifacts**. Download
   `Oracle-windows-exe` — it contains `Oracle.exe`.
3. Or download it from the GitHub Release for that version, where the
   .exe is attached as a release asset.
4. On a Windows PC, double-click `Oracle.exe`.
   **First launch: Windows SmartScreen will warn that the app is from
   an unknown publisher** — this build is unsigned (no code-signing
   certificate), so click **More info**, then **Run anyway**. That is
   expected for this build, not a broken app.
5. Set your own OpenAI API key before chatting: in Command Prompt,
   `setx OPENAI_API_KEY "your-key-here"` (permanent, for your user
   account), then open a new terminal / launch Oracle again. No key
   is bundled in the .exe — never paste your key into a chat or email.

## What the build does (short version)

`windows-latest` → installs Python 3.12, the requirements, and
PyInstaller → compile-checks every `.py` file → runs
`pyinstaller oracle-windows.spec` (single-file, windowed build of
`gui.py`, avatar bundled) → verifies `dist/Oracle.exe` starts with
the MZ header and carries a real PE signature → uploads it as an
artifact. No signing secrets, no API key.

## After the build

The .exe still needs a human test on a real Windows PC: open it,
check the avatar animates, voice replies work, and the camera starts.
The workflow only proves the app *builds* — it does not click
through the GUI. The browser-based job-application tool also needs
Playwright's Chromium on the PC (`pip install playwright` then
`playwright install chromium`) — that browser is not bundled inside
the single-file .exe.
