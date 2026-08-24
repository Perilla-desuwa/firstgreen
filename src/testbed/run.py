"""Delegate ``python -m testbed.run`` to the FirstGreen-owned runner."""

from firstgreen.testbed.run import main

if __name__ == "__main__":
    raise SystemExit(main())
