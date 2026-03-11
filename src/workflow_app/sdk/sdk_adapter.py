"""
SDKAdapter — Abstraction layer over Claude Agent SDK (module-08/TASK-1).

TODO: Implement backend — module-08/TASK-1 (auto-flow execute)
"""

from __future__ import annotations

from typing import Any, Callable


class SDKAdapter:
    """
    Wraps claude-agent-sdk for use in Workflow App.

    Responsibilities:
    - Auth check and permission mode configuration
    - Streaming output via query() with pyte VT100 rendering
    - Hook registration (Stop, PostToolUseFailure, Notification, PermissionRequest)

    TODO: Implement backend — module-08 (auto-flow execute)
    """

    def __init__(self, permission_mode: str = "acceptEdits") -> None:
        # TODO: Implement backend — module-08/TASK-1
        raise NotImplementedError("module-08 not yet implemented — run /auto-flow execute")

    def check_auth(self) -> bool:
        # TODO: Implement backend
        raise NotImplementedError("module-08/TASK-2 not yet implemented — run /auto-flow execute")

    def query(
        self,
        prompt: str,
        workspace: str,
        on_output: Callable[[str], None],
    ) -> None:
        """
        Execute a Claude command and stream output via on_output callback.

        TODO: Implement backend — module-09 (auto-flow execute)
        """
        raise NotImplementedError("module-09 not yet implemented — run /auto-flow execute")

    def send_input(self, text: str) -> None:
        """Send user input during interactive session."""
        raise NotImplementedError("module-09/TASK-3 not yet implemented — run /auto-flow execute")

    def stop(self) -> None:
        """Stop the current command execution."""
        raise NotImplementedError("module-08/TASK-3 not yet implemented — run /auto-flow execute")
