from __future__ import annotations

import re

import pytest
from _browser_probe import BrowserProbe
from playwright.async_api import Page, expect

pytestmark = pytest.mark.only_browser("chromium")


@pytest.mark.asyncio(loop_scope="session")
async def test_import_ui_flow_editor_shell_is_present_and_wired(
    page: Page,
    e2e_web_v3_base_url: str,
) -> None:
    probe = BrowserProbe(page)

    response = await page.goto(
        f"{e2e_web_v3_base_url}/import/ui/",
        wait_until="domcontentloaded",
        timeout=10_000,
    )
    assert response is not None and response.ok, "GET /import/ui/ did not return success"

    flow_tab = page.locator('#tabs .tabBtn[data-tab="flow"]')
    flow_panel = page.locator('.tabPanel[data-panel="flow"]')

    await flow_tab.click()
    await expect(flow_tab).to_have_class(re.compile(r"\bactive\b"))
    await expect(flow_panel).to_have_class(re.compile(r"\bactive\b"))

    await expect(page.locator("#flowReloadAll")).to_be_visible()
    await expect(page.locator("#flowValidateAll")).to_be_visible()
    await expect(page.locator("#flowSaveAll")).to_be_visible()
    await expect(page.locator("#flowResetAll")).to_be_visible()

    await expect(page.locator("#flowStepHeader")).to_have_text(
        re.compile(r"(?:Step settings \(FlowConfig draft\)|.+ - .+)"),
    )
    await expect(page.locator("#flowTransitionsPanel")).to_be_visible()
    await expect(page.locator("#flowPalettePanel")).to_be_visible()

    await probe.assert_clean()
