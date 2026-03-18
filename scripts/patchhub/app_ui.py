from __future__ import annotations

from pathlib import Path


def render_template(self, name: str) -> str:
    tpl = (Path(__file__).resolve().parent / "templates" / name).read_text(encoding="utf-8")
    return tpl


def render_index(self) -> str:
    tpl = self.render_template("index.html")
    version = ""
    try:
        version = str(self.cfg.meta.version)
    except Exception:
        version = ""
    return tpl.replace("{{PATCHHUB_STATIC_VERSION}}", version)


def render_debug(self) -> str:
    return self.render_template("debug.html")
