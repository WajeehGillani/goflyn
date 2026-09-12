"""Console entry point."""

import argparse

from goflight_memory.agent.chat import run_chat
from goflight_memory.infra.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="GoFlight Team Memory conversational shell")
    parser.add_argument("--user", help="Contributor name (otherwise use environment or prompt)")
    args = parser.parse_args()
    run_chat(load_settings(args.user))


if __name__ == "__main__":
    main()
