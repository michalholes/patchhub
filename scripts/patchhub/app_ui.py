from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .config import AppConfig


class UiTemplateContext(Protocol):
    cfg: AppConfig

    def render_template(self, name: str) -> str: ...


def render_template(self: object, name: str) -> str:
    tpl = (Path(__file__).resolve().parent / "templates" / name).read_text(encoding="utf-8")
    return tpl


def render_index(self: UiTemplateContext) -> str:
    tpl = self.render_template("index.html")
    version = ""
    try:
        version = str(self.cfg.meta.version)
    except Exception:
        version = ""
    return tpl.replace("{{PATCHHUB_STATIC_VERSION}}", version)


def render_debug(self: UiTemplateContext) -> str:
    return self.render_template("debug.html")


def render_editor(self: UiTemplateContext) -> str:
    tpl = self.render_template("editor.html")
    version = ""
    try:
        version = str(self.cfg.meta.version)
    except Exception:
        version = ""
    return tpl.replace("{{PATCHHUB_STATIC_VERSION}}", version)
