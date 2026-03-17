from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from playwright.async_api import Page

_RESOURCE_TYPES = {"document", "script", "stylesheet"}


@dataclass
class BrowserProbe:
    page: Page
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    failed_responses: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.page.on("pageerror", self._on_page_error)
        self.page.on("console", self._on_console)
        self.page.on("response", self._on_response)

    def _on_page_error(self, exc: BaseException) -> None:
        self.page_errors.append(f"pageerror: {exc!r}")

    def _on_console(self, message: object) -> None:
        msg_type = getattr(message, "type", None)
        if callable(msg_type):
            try:
                if msg_type() != "error":
                    return
            except Exception:
                return
        else:
            return
        text = getattr(message, "text", None)
        msg_text = text() if callable(text) else str(message)
        self.console_errors.append(f"console.error: {msg_text}")

    def _on_response(self, response: object) -> None:
        request = getattr(response, "request", None)
        if request is None:
            return
        resource_type = getattr(request, "resource_type", None)
        if resource_type not in _RESOURCE_TYPES:
            return
        status = getattr(response, "status", None)
        if not isinstance(status, int) or status < 400:
            return
        url = getattr(response, "url", "")
        path = canonical_url_path(str(url))
        self.failed_responses.append(f"{resource_type} {status} {path}")

    async def wait_for_script_paths(
        self,
        expected_paths: set[str],
        *,
        timeout_ms: int = 10_000,
    ) -> None:
        expected = sorted(expected_paths)
        await self.page.wait_for_function(
            """
            (expected) => {
              const loaded = Array.from(document.scripts)
                .map((node) => {
                  if (!node || !node.src) {
                    return "";
                  }
                  try {
                    return new URL(node.src, window.location.href).pathname;
                  } catch (err) {
                    return "";
                  }
                })
                .filter(Boolean);
              return expected.every((item) => loaded.includes(item));
            }
            """,
            arg=expected,
            timeout=timeout_ms,
        )

    async def script_paths(self) -> set[str]:
        paths = await self.page.evaluate(
            """
            () => Array.from(document.scripts)
              .map((node) => {
                if (!node || !node.src) {
                  return "";
                }
                try {
                  return new URL(node.src, window.location.href).pathname;
                } catch (err) {
                  return "";
                }
              })
              .filter(Boolean)
            """
        )
        return {str(item) for item in paths}

    async def filtered_script_paths(self, prefix: str) -> set[str]:
        paths = await self.script_paths()
        return {path for path in paths if path.startswith(prefix)}

    async def read_local_storage_json(self, key: str):
        return await self.page.evaluate(
            """
            (storageKey) => {
              const raw = window.localStorage.getItem(storageKey);
              if (!raw) {
                return null;
              }
              return JSON.parse(raw);
            }
            """,
            key,
        )

    async def assert_clean(self) -> None:
        issues = self.page_errors + self.console_errors + self.failed_responses
        assert not issues, "Frontend issues: " + " | ".join(issues)


def canonical_url_path(url: str) -> str:
    parts = urlsplit(str(url))
    return parts.path or str(url)
