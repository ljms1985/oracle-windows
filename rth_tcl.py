# PyInstaller runtime hook — runs before gui.py starts.
# Sets TCL_LIBRARY / TK_LIBRARY to the bundled Tcl/Tk data inside
# sys._MEIPASS so tkinter's tk.Tk() can find init.tcl. This is a
# self-contained copy of the logic in oracle_paths.fix_tcl() because
# runtime hooks cannot rely on the app's own modules being importable
# yet. gui.py also calls oracle_paths.fix_tcl() before importing
# tkinter, as a second layer.
import os
import sys
from pathlib import Path

try:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        for env_name, names, roots in (
            ("TCL_LIBRARY", ("tcl8.6", "tcl8.7", "tcl"), ("_tcl_data",)),
            ("TK_LIBRARY", ("tk8.6", "tk8.7", "tk"), ("_tk_data",)),
        ):
            found = None
            candidates = [base / n for n in names]
            for root in roots:
                candidates += [base / root / n for n in names]
                candidates.append(base / root)
            for cand in candidates:
                try:
                    if (cand / "init.tcl").is_file():
                        found = cand
                        break
                except Exception:
                    pass
            if found is not None:
                os.environ[env_name] = str(found)
except Exception:
    # Never let the Tcl fix itself crash startup; tkinter will raise
    # its own error if init.tcl really is missing, and the crash log
    # in gui.py will record it.
    pass
