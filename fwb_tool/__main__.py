"""Allow `python -m fwb_tool ...` as an alternative to the `fwb` script."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
