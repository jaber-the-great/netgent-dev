"""Shim — use `netgent eval stress <sweep|challenge> --backend …`. Kept so old invocations still work."""

import subprocess
import sys

sys.exit(subprocess.call([sys.executable, "-m", "netgent.cli", "eval", "stress", *sys.argv[1:]]))
