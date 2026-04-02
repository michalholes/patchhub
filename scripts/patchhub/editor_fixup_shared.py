from __future__ import annotations

CLIENT_ONLY_ACTIONS = {"jump_to_block", "jump_to_conflict"}


class EditorFixupError(Exception):
    pass
