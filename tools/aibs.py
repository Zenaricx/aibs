#!/usr/bin/env python3
"""Single entry point for the AIBS governed run workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from aibs_controller import main as admit
from aibs_prepare_dispatch import main as prepare_dispatch
from aibs_publish_candidate import main as publish
from aibs_record_review import main as review
from aibs_seal_candidate import main as seal
from aibs_status import main as status
from aibs_verify_candidate import main as verify


COMMANDS = {
    "admit": admit,
    "prepare-dispatch": prepare_dispatch,
    "verify": verify,
    "review": review,
    "seal": seal,
    "publish": publish,
    "status": status,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="aibs", description="AIBS governed run workflow")
    parser.add_argument("command", choices=tuple(COMMANDS))
    args, remainder = parser.parse_known_args(argv)
    return COMMANDS[args.command](remainder)


if __name__ == "__main__":
    raise SystemExit(main())
