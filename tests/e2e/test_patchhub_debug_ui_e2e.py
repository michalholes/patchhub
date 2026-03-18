from __future__ import annotations

import re

import pytest
from _asset_inventory import active_patchhub_debug_paths
from _browser_probe import BrowserProbe
from playwright.async_api import Page, expect

pytestmark = pytest.mark.only_browser("chromium")


@pytest.mark.asyncio(loop_scope="session")
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
