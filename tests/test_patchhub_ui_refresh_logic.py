from __future__ import annotations

from pathlib import Path


def _read(rel: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / rel).read_text(encoding="utf-8")


def test_idle_overview_refresh_uses_snapshot_endpoint() -> None:
    src = _read("scripts/patchhub/static/app_part_jobs.js")
    assert "function refreshOverviewSnapshot(opts)" in src
    assert 'apiGetETag("ui_snapshot", "/api/ui_snapshot" + qs' in src
    assert 'phCall("renderHeaderFromSummary", snap.header || {}, headerBaseLabel())' in src


def test_runs_refresh_uses_etag_single_flight_wrapper() -> None:
    src = _read("scripts/patchhub/static/app_part_runs.js")
    assert 'apiGetETag("runs_list", `/api/runs?${q.join("&")}`' in src
    assert 'single_flight: mode === "periodic"' in src


def test_wire_init_uses_snapshot_first_idle_flow() -> None:
    src = _read("scripts/patchhub/static/app_part_wire_init.js")
    assert 'phCall("refreshOverviewSnapshot", { mode: "user" })' in src
    assert 'phCall("refreshRuns", { mode: "user" });' in src
    assert 'phCall("refreshHeader", { mode: "user" });' in src


def test_hidden_active_keeps_active_orchestration_paths() -> None:
    wire_src = _read("scripts/patchhub/static/app_part_wire_init.js")
    assert "function hasTrackedActiveJob()" in wire_src
    assert "activeMode = hasTrackedActiveJob();" in wire_src
    assert "if (document.hidden && !activeMode) {" in wire_src
    assert "startTimers({ keepLiveStream: keepLiveStream });" in wire_src

    snapshot_src = _read("scripts/patchhub/static/app_part_snapshot_events.js")
    assert 'PH.call("hasTrackedActiveJob") || document.hidden' in snapshot_src


def test_live_progress_stays_on_structured_stream_sources() -> None:
    progress_src = _read("scripts/patchhub/static/patchhub_progress_ui.js")
    jobs_src = _read("scripts/patchhub/static/app_part_jobs.js")
    duration_src = _read("scripts/patchhub/static/patchhub_visible_duration.js")
    app_src = _read("scripts/patchhub/static/app.js")
    assert 'String(ev.event || "") === "stream_end"' in progress_src
    assert "function updateProgressPanelFromTailText(text, opts)" not in progress_src
    assert 'PH.call("setVisibleDurationSurface", "progress_card_duration"' in progress_src
    assert 'phCall("setVisibleDurationSurface", "jobs_list_duration"' in jobs_src
    assert 'PH.register("visible_duration"' in duration_src
    assert '"/static/patchhub_visible_duration.js"' in app_src

    runs_src = _read("scripts/patchhub/static/app_part_runs.js")
    assert 'phCall("updateProgressPanelFromTailText", t);' not in runs_src


def test_tracked_active_helper_does_not_depend_on_empty_jobs_only() -> None:
    src = _read("scripts/patchhub/static/patchhub_live_ui.js")
    assert "function hasTrackedLiveContext(trackedId)" in src
    assert "if (match) {" in src
    assert "if (!hasTrackedLiveContext(trackedId)) {" in src
    assert "status: deriveTrackedFallbackStatus()," in src


def test_main_ui_does_not_auto_poll_tail_sources() -> None:
    wire_src = _read("scripts/patchhub/static/app_part_wire_init.js")
    assert 'phCall("refreshTail", tailLines);' not in wire_src

    enqueue_src = _read("scripts/patchhub/static/app_part_queue_upload.js")
    assert 'phCall("refreshTail", tailLines);' not in enqueue_src


def test_debug_and_fallback_do_not_auto_load_runner_tail() -> None:
    debug_src = _read("scripts/patchhub/static/debug.js")
    init_section = debug_src.split("function init()", 1)[1]
    assert "refreshTail();" not in init_section

    fallback_src = _read("scripts/patchhub/static/app_part_fallback.js")
    assert "fallbackRefreshTail(tailLines);" not in fallback_src


def test_progress_panel_replaces_retained_terminal_state_on_new_tracked_job() -> None:
    src = _read("scripts/patchhub/static/patchhub_progress_ui.js")
    assert 'return { text: "STATUS: QUEUED", status: "running" };' in src
    assert "var active = getTrackedActiveJob(jobs);" in src
    assert "renderActiveJob(jobs);" in src


def test_missing_patch_check_has_no_separate_watchdog_timer() -> None:
    wire_src = _read("scripts/patchhub/static/app_part_wire_init.js")
    assert "patchStatTimer" not in wire_src
    assert "setInterval(tickMissingPatchClear, 1000)" not in wire_src
    assert 'tickMissingPatchClear({ mode: "idle" });' in wire_src
    assert 'tickMissingPatchClear({ mode: "active" });' in wire_src


def test_missing_patch_check_uses_empty_path_guard_and_backoff_state() -> None:
    app_src = _read("scripts/patchhub/static/app.js")
    assert "function getMissingPatchRel()" in app_src
    assert "if (!rel) {" in app_src
    assert "patchStatNextDueMs" in app_src
    assert "patchStatIdleBackoffIdx" in app_src
    assert "PATCH_STAT_ACTIVE_MS = 5000" in app_src
