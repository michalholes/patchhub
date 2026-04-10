from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Page, expect

REPO_ROOT = Path(__file__).resolve().parents[2]
_HTML_SCRIPT_RE = re.compile(r'<script\b[^>]*\bsrc="([^"]+)"', re.IGNORECASE)
_RESOURCE_TYPES = {"document", "script", "stylesheet"}

pytestmark = [
    pytest.mark.only_browser("chromium"),
    pytest.mark.skipif(
        importlib.util.find_spec("pytest_playwright_asyncio") is None,
        reason="pytest_playwright_asyncio not installed",
    ),
]


def canonical_url_path(url: str) -> str:
    parts = urlsplit(str(url))
    return parts.path or str(url)


def active_patchhub_debug_paths() -> set[str]:
    text = (REPO_ROOT / "scripts" / "patchhub" / "templates" / "debug.html").read_text(
        encoding="utf-8"
    )
    return {canonical_url_path(match) for match in _HTML_SCRIPT_RE.findall(text)}


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
        if not callable(msg_type):
            return
        try:
            if msg_type() != "error":
                return
        except Exception:
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

    async def assert_clean(self) -> None:
        issues = self.page_errors + self.console_errors + self.failed_responses
        assert not issues, "Frontend issues: " + " | ".join(issues)


@pytest.mark.asyncio(loop_scope="function")
async def test_patchhub_debug_ui_flush_and_copy_controls(
    page: Page,
    e2e_patchhub_base_url: str,
) -> None:
    probe = BrowserProbe(page)
    expected = active_patchhub_debug_paths()

    response = await page.goto(f"{e2e_patchhub_base_url}/debug", wait_until="domcontentloaded")
    assert response is not None and response.ok, "GET /debug did not return success"

    await expect(page).to_have_title(re.compile(r"PatchHub - Debug"))
    await probe.wait_for_script_paths(expected)
    assert await probe.filtered_script_paths("/static/") == expected

    for prefix in (
        "clientErrors",
        "clientStatus",
        "clientNet",
        "serverDiag",
        "parsed",
        "tail",
    ):
        await expect(page.locator(f"#{prefix}Flush")).to_be_visible()
        await expect(page.locator(f"#{prefix}Copy")).to_be_visible()

    await page.locator("#raw").fill(
        'python3 scripts/am_patch.py 1000 "test msg" patches/issue_1000_v1.zip'
    )
    await page.locator("#parse").click()
    await expect(page.locator("#parsed")).to_contain_text("issue_id")

    await page.evaluate(
        """
        () => {
          window.__patchhubCopiedText = [];
          const pushCopiedText = (text) => {
            window.__patchhubCopiedText.push(String(text));
          };
          try {
            Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: {
                writeText: (text) => {
                  pushCopiedText(text);
                  return Promise.resolve();
                },
              },
            });
          } catch (err) {
            navigator.clipboard = {
              writeText: (text) => {
                pushCopiedText(text);
                return Promise.resolve();
              },
            };
          }
          const originalExecCommand = document.execCommand
            ? document.execCommand.bind(document)
            : null;
          document.execCommand = (commandId) => {
            if (String(commandId || "").toLowerCase() === "copy") {
              const active = document.activeElement;
              const value = active && "value" in active ? active.value : "";
              pushCopiedText(value);
              return true;
            }
            return originalExecCommand ? originalExecCommand(commandId) : false;
          };
        }
        """
    )

    parsed_text = await page.locator("#parsed").text_content()
    await page.locator("#parsedCopy").click()
    await page.wait_for_function(
        "() => (window.__patchhubCopiedText || []).length > 0",
        timeout=5_000,
    )
    copied_text = await page.evaluate("() => (window.__patchhubCopiedText || []).slice()")
    assert copied_text == [parsed_text or ""]

    await page.locator("#parsedFlush").click()
    await expect(page.locator("#parsed")).to_have_text("")
    await probe.assert_clean()
