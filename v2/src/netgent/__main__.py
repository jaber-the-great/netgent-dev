"""Allow `python -m netgent` to invoke the CLI."""

from netgent.cli import main

raise SystemExit(main())
