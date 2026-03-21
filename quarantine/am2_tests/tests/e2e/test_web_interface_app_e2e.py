from __future__ import annotations

import re

import pytest
from _asset_inventory import (
    OUT_OF_SCOPE_BY_USER_DECISION,
    active_import_ui_paths,
    active_js_coverage_map,
    active_js_paths_in_scope,
    active_patchhub_all_paths,
    active_web_interface_paths,
)
from _browser_probe import BrowserProbe
from playwright.async_api import Page, expect

pytestmark = pytest.mark.only_browser("chromium")


def test_active_js_coverage_map_matches_scope() -> None:
    expected = active_web_interface_paths()
    expected |= active_import_ui_paths()
    expected |= active_patchhub_all_paths()

    coverage = active_js_coverage_map()
    in_scope = active_js_paths_in_scope()

    assert expected == in_scope
    assert coverage["/static/patchhub_shell.js"] == OUT_OF_SCOPE_BY_USER_DECISION


@pytest.mark.asyncio(loop_scope="session")
async def test_root_shell_boots_with_expected_script(page: Page, e2e_web_base_url: str) -> None:
    probe = BrowserProbe(page)
    expected = active_web_interface_paths()

    response = await page.goto(f"{e2e_web_base_url}/", wait_until="domcontentloaded")
    assert response is not None and response.ok, "GET / did not return a successful response"

    await expect(page).to_have_title(re.compile(r"AudioMason Web Interface"))
    await expect(page.locator("#app")).to_be_visible()
    await expect(page.get_by_text("AudioMason", exact=True)).to_be_visible()

    await probe.wait_for_script_paths(expected)
    actual = await probe.filtered_script_paths("/ui/assets/")
    assert actual == expected
    await probe.assert_clean()
