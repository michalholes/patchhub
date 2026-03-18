from __future__ import annotations

from dataclasses import dataclass

from badguys._util import now_stamp


@dataclass(frozen=True)
class SubstCtx:
    issue_id: str
    now_stamp: str


def make_subst_ctx(*, issue_id: str) -> SubstCtx:
    return SubstCtx(issue_id=str(issue_id), now_stamp=now_stamp())


def subst_text(text: str, *, ctx: SubstCtx) -> str:
    return text.replace("${issue_id}", ctx.issue_id).replace("${now_stamp}", ctx.now_stamp)
