from __future__ import annotations

import re

import pytest
from playwright.async_api import Page, expect

pytestmark = pytest.mark.only_browser("chromium")


@pytest.mark.asyncio(loop_scope="session")
async def test_root_shell_boots(page: Page, e2e_base_url: str) -> None:
    issues: list[str] = []

    page.on("pageerror", lambda exc: issues.append(f"pageerror: {exc!r}"))
    page.on(
        "response",
        lambda response: (
            issues.append(f"{response.request.resource_type} {response.status} {response.url}")
            if response.request.resource_type in {"document", "script", "stylesheet"}
            and response.status >= 400
            else None
        ),
    )

    response = await page.goto(f"{e2e_base_url}/", wait_until="domcontentloaded")
    assert response is not None and response.ok, (
        "GET / did not return a successful document response"
    )

    await expect(page).to_have_title(re.compile(r"AudioMason Web Interface"))
    await expect(page.locator("#app")).to_be_visible()
    await expect(page.get_by_text("AudioMason", exact=True)).to_be_visible()

    assert not issues, "Frontend issues on /: " + " | ".join(issues)


@pytest.mark.asyncio(loop_scope="session")
async def test_import_ui_loads(page: Page, e2e_base_url: str) -> None:
    issues: list[str] = []

    page.on("pageerror", lambda exc: issues.append(f"pageerror: {exc!r}"))
    page.on(
        "response",
        lambda response: (
            issues.append(f"{response.request.resource_type} {response.status} {response.url}")
            if response.request.resource_type in {"document", "script", "stylesheet"}
            and response.status >= 400
            else None
        ),
    )

    response = await page.goto(f"{e2e_base_url}/import/ui/", wait_until="domcontentloaded")
    assert response is not None and response.ok, (
        "GET /import/ui/ did not return a successful document response"
    )

    await expect(page).to_have_title(re.compile(r"AudioMason Import"))
    await expect(page.locator("#tabs")).to_be_visible()
    await expect(page.locator("#start")).to_be_visible()
    await expect(page.get_by_text("Plugin-hosted UI at /import/ui/")).to_be_visible()

    assert not issues, "Frontend issues on /import/ui/: " + " | ".join(issues)
