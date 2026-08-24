"""Shim — use `netgent eval observation`. Kept so old invocations still work."""

import subprocess
import sys

sys.exit(subprocess.call([sys.executable, "-m", "netgent.cli", "eval", "observation", *sys.argv[1:]]))
