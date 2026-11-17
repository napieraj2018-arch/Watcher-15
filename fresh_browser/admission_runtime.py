"""Production entrypoint: preserve 2.0.2; bound pre-operation lock waiting only."""
from __future__ import annotations

import reliability_runtime as previous
import server
from command_admission import DEFAULT_WAIT_SECONDS, bounded_entry, install_workspace

app = previous.app
lock = install_workspace(server.workspace)
server.issue_owner_access = bounded_entry(server.issue_owner_access)
_previous_action = server.workspace.action


async def admission_action(args, automated=False, owner_context=None):
    result = await _previous_action(args, automated=automated, owner_context=owner_context)
    if args.get("action") == "runtime_status":
        result = {**result, "version": "2.0.3", "command_admission": {
            "lock_wait_timeout_seconds": DEFAULT_WAIT_SECONDS,
            "waiting_commands": lock.waiting_commands,
            "replays_commands": False,
            "cancels_started_commands": False,
        }}
    return result


server.workspace.action = admission_action
