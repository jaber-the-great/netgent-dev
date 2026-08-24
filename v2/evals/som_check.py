"""Shim — use `netgent eval som`. Kept so old invocations still work."""

import subprocess
import sys

sys.exit(subprocess.call([sys.executable, "-m", "netgent.cli", "eval", "som", *sys.argv[1:]]))
