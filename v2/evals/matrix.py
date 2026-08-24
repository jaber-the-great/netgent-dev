"""Shim — use `netgent eval matrix`. Kept so old invocations still work."""

import subprocess
import sys

sys.exit(subprocess.call([sys.executable, "-m", "netgent.cli", "eval", "matrix", *sys.argv[1:]]))
