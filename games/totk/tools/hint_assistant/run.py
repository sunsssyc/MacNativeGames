#!/usr/bin/env python3.14
"""Entry point that works from any folder (python3.14 run.py hint --tier 1); see totk_hint/cli.py."""
import sys

from totk_hint.cli import main

sys.exit(main())
