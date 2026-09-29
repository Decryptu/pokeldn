import os
import sys

# A PyInstaller bundle unpacks the repository's folders under sys._MEIPASS.
ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for folder in (ROOT, os.path.join(ROOT, "vendor", "LDN")):
    if folder not in sys.path:
        sys.path.insert(0, folder)
