// PatchHub built-in degraded-mode fallbacks.
var __ph_w = /** @type {any} */ (window);
var PH = __ph_w.PH || __ph_w.PH_RT || null;

function fallbackApplyModeRules(mode) {
	mode = String(mode || "patch");
	if (mode === "finalize_live") {
		return { issue_id: false, commit_message: true, patch_path: false };
	}
	if (mode === "finalize_workspace") {
		return { issue_id: true, commit_message: false, patch_path: false };
	}
	if (mode === "rerun_latest") {
		return { issue_id: true, commit_message: true, patch_path: true };
	}
	return { issue_id: true, commit_message: true, patch_path: true };
}

function fallbackSetStartFormState(state) {
	var issueEnabled = !!(state && state.issue_id);
	var msgEnabled = !!(state && state.commit_message);
	var patchEnabled = !!(state && state.patch_path);
	if (el("issueId")) el("issueId").disabled = !issueEnabled;
	if (el("commitMsg")) el("commitMsg").disabled = !msgEnabled;
	if (el("patchPath")) el("patchPath").disabled = !patchEnabled;
	if (el("browsePatch")) el("browsePatch").disabled = !patchEnabled;
}

function fallbackValidateAndPreview() {
	var mode = String((el("mode") && el("mode").value) || "patch");
	var issueId = String((el("issueId") && el("issueId").value) || "").trim();
	var commitMsg = String(
		(el("commitMsg") && el("commitMsg").value) || "",
	).trim();
	var patchPath = normalizePatchPath(
		String((el("patchPath") && el("patchPath").value) || "").trim(),
	);
	var rawCommand = String(
		(el("rawCommand") && el("rawCommand").value) || "",
	).trim();
	if (el("patchPath")) el("patchPath").value = patchPath;
	fallbackSetStartFormState(fallbackApplyModeRules(mode));
	var ok = !!rawCommand;
	if (!rawCommand) {
		if (mode === "finalize_live") ok = !!commitMsg;
		else if (mode === "finalize_workspace")
			ok = !!issueId && /^[0-9]+$/.test(issueId);
		else if (mode === "rerun_latest")
			ok = !!commitMsg && !!issueId && /^[0-9]+$/.test(issueId);
		else ok = !!commitMsg && !!patchPath;
	}
	var preview = {
		mode: mode,
		issue_id: issueId,
		commit_message: commitMsg,
		patch_path: patchPath,
		raw_command: rawCommand,
		degraded: true,
	};
	preview = PH.call("applyGatePreview", preview) || preview;
	setPre("previewRight", preview);
	if (el("enqueueBtn")) el("enqueueBtn").disabled = !ok;
	setInfoPoolHint("enqueue", ok ? "" : "degraded mode: missing fields");
	return ok;
}

function fallbackUploadFile(file) {
	if (!file) return;
	var fd = new FormData();
	fd.append("file", file);
	setUiStatus("upload: started " + String(file.name || ""));
	fetch("/api/upload/patch", {
		method: "POST",
		body: fd,
		headers: { Accept: "application/json" },
	})
		.then((r) =>
			r.text().then((t) => {
				try {
					return JSON.parse(t);
				} catch (e) {
					return { ok: false, error: "bad json", raw: t, status: r.status };
				}
			}),
		)
		.then((payload) => {
			pushApiStatus(payload);
			setInfoPoolHint(
				"upload",
				payload && payload.ok
					? "Uploaded: " + String(payload.stored_rel_path || "")
					: "Upload failed: " + String((payload && payload.error) || ""),
			);
			if (payload && payload.ok && payload.stored_rel_path && el("patchPath")) {
				el("patchPath").value = String(payload.stored_rel_path || "");
				fallbackValidateAndPreview();
			}
			refreshFs();
		})
		.catch((err) => {
			setInfoPoolHint("upload", "Upload failed: " + String(err));
			setUiError(String(err));
		});
}

function fallbackSetupUpload() {
	var zone = el("uploadZone");
	var browse = el("uploadBrowse");
	var input = el("uploadInput");
	if (browse && !browse.dataset.phFallbackBound) {
		browse.dataset.phFallbackBound = "1";
		browse.addEventListener("click", () => {
			if (!input) return;
			input.value = "";
			input.click();
		});
	}
	if (zone && !zone.dataset.phFallbackBound) {
		zone.dataset.phFallbackBound = "1";
		zone.addEventListener("click", () => {
			if (!input) return;
			input.value = "";
			input.click();
		});
		zone.addEventListener("dragover", (ev) => {
			ev.preventDefault();
			zone.classList.add("dragover");
		});
		zone.addEventListener("dragleave", (ev) => {
			ev.preventDefault();
			zone.classList.remove("dragover");
		});
		zone.addEventListener("drop", (ev) => {
			ev.preventDefault();
			zone.classList.remove("dragover");
			var file =
				ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
			if (file) fallbackUploadFile(file);
		});
	}
	if (input && !input.dataset.phFallbackBound) {
		input.dataset.phFallbackBound = "1";
		input.addEventListener("change", () => {
			if (input.files && input.files[0]) fallbackUploadFile(input.files[0]);
		});
	}
}

function fallbackLoadConfig() {
	return apiGet("/api/config")
		.then((r) => {
			cfg = r || null;
			if (cfg && cfg.issue && cfg.issue.default_regex) {
				try {
					issueRegex = new RegExp(cfg.issue.default_regex);
				} catch (e) {
					issueRegex = null;
				}
			}
			if (cfg && cfg.meta && cfg.meta.version) {
				setText("ampWebVersion", "v" + String(cfg.meta.version));
			}
			return cfg;
		})
		.catch(() => {
			cfg = null;
			return null;
		});
}

function fallbackEnqueue() {
	if (!fallbackValidateAndPreview()) return;
	var mode = String((el("mode") && el("mode").value) || "patch");
	var body = {
		mode: mode,
		raw_command: String(
			(el("rawCommand") && el("rawCommand").value) || "",
		).trim(),
	};
	if (mode === "patch") {
		body.issue_id = String((el("issueId") && el("issueId").value) || "").trim();
		body.commit_message = String(
			(el("commitMsg") && el("commitMsg").value) || "",
		).trim();
		body.patch_path = normalizePatchPath(
			String((el("patchPath") && el("patchPath").value) || "").trim(),
		);
	} else if (mode === "finalize_live") {
		body.commit_message = String(
			(el("commitMsg") && el("commitMsg").value) || "",
		).trim();
	} else if (mode === "finalize_workspace") {
		body.issue_id = String((el("issueId") && el("issueId").value) || "").trim();
	}
	setUiStatus("enqueue: started mode=" + mode);
	apiPost("/api/jobs/enqueue", body).then((payload) => {
		pushApiStatus(payload);
		setPre("previewRight", payload);
		if (payload && payload.ok && payload.job_id) {
			setUiStatus("enqueue: ok job_id=" + String(payload.job_id || ""));
			selectedJobId = String(payload.job_id || "");
		} else {
			setUiError(String((payload && payload.error) || "enqueue failed"));
		}
		fallbackRefreshJobs();
	});
}

function fallbackRefreshRuns() {
	return apiGet("/api/runs?limit=80").then((payload) => {
		if (!payload || payload.ok === false) {
			setPre("runsList", payload);
			return payload;
		}
		setPre("runsList", payload.runs || []);
		return payload;
	});
}

function fallbackRefreshJobs() {
	return apiGet("/api/jobs").then((payload) => {
		if (!payload || payload.ok === false) {
			setPre("jobsList", payload);
			return payload;
		}
		setPre("jobsList", payload.jobs || []);
		return payload;
	});
}

function fallbackRefreshWorkspaces() {
	return apiGet("/api/workspaces").then((payload) => {
		if (!payload || payload.ok === false) {
			setPre("workspacesList", payload);
			return payload;
		}
		setPre("workspacesList", payload.items || []);
		return payload;
	});
}

function fallbackRefreshOverviewSnapshot() {
	return Promise.all([
		fallbackRefreshJobs(),
		fallbackRefreshRuns(),
		fallbackRefreshWorkspaces(),
	]);
}

function fallbackRefreshTail(lines) {
	var count = encodeURIComponent(String(lines || tailLines || 200));
	return apiGet("/api/runner/tail?lines=" + count).then((payload) => {
		if (!payload || payload.ok === false) {
			setPre("tail", payload);
			return payload;
		}
		setPre("tail", String(payload.tail || ""));
		return payload;
	});
}

function fallbackRenderIssueDetail() {
	setPre("issueTabBody", { degraded: true, selected_run: selectedRun || null });
}

var fallbackWireInitStarted = false;

function fallbackStartAppWireInit() {
	rememberDegraded("minimal fallback UI active");
	if (fallbackWireInitStarted) return;
	fallbackWireInitStarted = true;
	fallbackSetupUpload();
	if (el("fsRefresh")) el("fsRefresh").addEventListener("click", refreshFs);
	if (el("fsUp")) {
		el("fsUp").addEventListener("click", () => {
			var p = (el("fsPath") && el("fsPath").value) || "";
			el("fsPath").value = parentRel(p);
			refreshFs();
		});
	}
	if (el("workspacesRefresh")) {
		el("workspacesRefresh").addEventListener(
			"click",
			fallbackRefreshWorkspaces,
		);
	}
	if (el("runsRefresh"))
		el("runsRefresh").addEventListener("click", fallbackRefreshRuns);
	if (el("jobsRefresh"))
		el("jobsRefresh").addEventListener("click", fallbackRefreshJobs);
	if (el("enqueueBtn"))
		el("enqueueBtn").addEventListener("click", fallbackEnqueue);
	if (el("refreshAll")) {
		el("refreshAll").addEventListener("click", () => {
			refreshFs();
			fallbackRefreshOverviewSnapshot();
		});
	}
	["mode", "issueId", "commitMsg", "patchPath", "rawCommand"].forEach((id) => {
		if (!el(id) || el(id).dataset.phFallbackBound) return;
		el(id).dataset.phFallbackBound = "1";
		el(id).addEventListener(
			id === "mode" ? "change" : "input",
			fallbackValidateAndPreview,
		);
	});
	fallbackLoadConfig().then(() => {
		refreshFs();
		fallbackRefreshOverviewSnapshot();
		fallbackValidateAndPreview();
	});
}

__ph_w.PH_APP_FALLBACKS = {
	startAppWireInit: fallbackStartAppWireInit,
	setupUpload: fallbackSetupUpload,
	enqueue: fallbackEnqueue,
	validateAndPreview: fallbackValidateAndPreview,
	loadConfig: fallbackLoadConfig,
	refreshRuns: fallbackRefreshRuns,
	refreshJobs: fallbackRefreshJobs,
	refreshWorkspaces: fallbackRefreshWorkspaces,
	refreshOverviewSnapshot: fallbackRefreshOverviewSnapshot,
	refreshTail: fallbackRefreshTail,
	renderIssueDetail: fallbackRenderIssueDetail,
};

if (PH && typeof PH.register === "function") {
	PH.register("app_part_fallback", {});
}
