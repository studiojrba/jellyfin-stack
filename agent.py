#!/usr/bin/env python3
"""
Remote Cursor cloud agent for jellyfin-stack.

Usage:
    source .venv/bin/activate
    python agent.py "Why is the autoheal service stuck?"
    python agent.py  # prompts interactively
"""

import os
import sys
from cursor_sdk import Agent, AgentOptions, CloudAgentOptions, CloudRepository, CursorAgentError

REPO = "https://github.com/studiojrba/jellyfin-stack"
MODEL = "composer-2.5"


def main() -> None:
    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        print("ERROR: CURSOR_API_KEY is not set.", file=sys.stderr)
        print("  Run: export CURSOR_API_KEY='cursor_...'", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = input("What should the agent investigate? > ").strip()
        if not prompt:
            print("No prompt provided.", file=sys.stderr)
            sys.exit(1)

    print(f"\nLaunching cloud agent on {REPO} ...")
    print(f"Prompt: {prompt}\n")

    try:
        with Agent.create(
            model=MODEL,
            api_key=api_key,
            cloud=CloudAgentOptions(repos=[CloudRepository(url=REPO, starting_ref="main")]),
        ) as agent:
            print(f"Agent ID: {agent.agent_id}\n")

            run = agent.send(prompt)
            print(f"Run ID:   {run.id}\n--- Agent output ---")

            for message in run.messages():
                if message.type == "assistant":
                    for block in message.message.content:
                        if block.type == "text":
                            print(block.text, end="", flush=True)

            result = run.wait()
            print(f"\n\n--- Done: {result.status} ---")

            if result.status == "error":
                print("Run failed. Check the agent transcript in the Cursor dashboard.", file=sys.stderr)
                sys.exit(2)

    except CursorAgentError as err:
        print(f"\nStartup failed: {err.message}", file=sys.stderr)
        print(f"Retryable: {err.is_retryable}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
