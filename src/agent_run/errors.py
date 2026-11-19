from __future__ import annotations

from agent_run import exit_codes


class AgentRunError(Exception):
    def __init__(self, message: str, code: int = exit_codes.INTERNAL) -> None:
        super().__init__(message)
        self.code = code


class HitlError(AgentRunError):
    def __init__(self, reason: str, detail: str = "") -> None:
        code = exit_codes.HITL_REASON_TO_CODE.get(reason, exit_codes.INTERNAL)
        msg = f"HITL:{reason}" + (f" — {detail}" if detail else "")
        super().__init__(msg, code=code)
        self.reason = reason
        self.detail = detail
