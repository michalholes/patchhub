/** @type {any} */
var __ph_w = /** @type {any} */ (window);
var PH = /** @type {any} */ (window).PH;
var jobsCache = [];
var rerunPrepareSeq = 0;
var trackedJobDurationClock = null;
var trackedJobDurationJobId = "";

function phCall(name, ...args) {
	if (!PH || typeof PH.call !== "function") return undefined;
	return PH.call(name, ...args);
}

function getVisibleDurationNowMs() {
	var value = Number(phCall("getVisibleDurationNowMs"));
	return Number.isFinite(value) ? value : Date.now();
}

function formatVisibleDurationMs(ms) {
	var text = phCall("formatVisibleDurationMs", ms);
	var tenths = 0;
	if (text || text === "0") return String(text);
	if (!Number.isFinite(ms) || ms < 0) return "";
	tenths = Math.floor(ms / 100);
	return String((tenths / 10).toFixed(1));
}

function syncTrackedJobDurationClock(jobs) {
	var tracked = phCall("getTrackedActiveJob", jobs || []);
	var startMs = NaN;
	if (
		tracked &&
		tracked.started_utc &&
		phCall("isNonTerminalJobStatus", tracked.status)
	) {
		startMs = Date.parse(String(tracked.started_utc || ""));
		if (Number.isFinite(startMs)) {
			trackedJobDurationJobId = String(tracked.job_id || "");
			trackedJobDurationClock = phCall(
				"makeVisibleRuntimeClock",
				Math.max(0, Date.now() - startMs),
			);
			return;
		}
	}
	trackedJobDurationJobId = "";
	trackedJobDurationClock = null;
}

function getTrackedJobDurationLabel(job, tickNowMs) {
	var jobId = "";
	var runningElapsedMs = null;
	if (!job) return "";
	if (job.started_utc && job.ended_utc) {
		return String(
			phCall("jobSummaryDurationSeconds", job.started_utc, job.ended_utc) || "",
		);
	}
	jobId = String(job.job_id || "");
	if (
		job.started_utc &&
		jobId &&
		jobId === trackedJobDurationJobId &&
		trackedJobDurationClock &&
		phCall("isNonTerminalJobStatus", job.status)
	) {
		runningElapsedMs = phCall(
			"readVisibleRuntimeElapsedMs",
			trackedJobDurationClock,
			Number.isFinite(tickNowMs) ? tickNowMs : getVisibleDurationNowMs(),
		);
		if (Number.isFinite(runningElapsedMs)) {
			return formatVisibleDurationMs(runningElapsedMs);
		}
	}
	return String(
		phCall("jobSummaryDurationSeconds", job.started_utc, job.ended_utc) || "",
	);
}

function getJobsDurationSignature(tickNowMs) {
	var tracked = phCall("getTrackedActiveJob", jobsCache || []);
	var label = "";
	if (
		!tracked ||
		!tracked.started_utc ||
		!phCall("isNonTerminalJobStatus", tracked.status)
	) {
		return "";
	}
	label = getTrackedJobDurationLabel(tracked, tickNowMs);
	if (!label) return "";
	return `${String(tracked.job_id || "")}=${label}`;
}

function syncJobsDurationSurface() {
	if (!PH || typeof PH.call !== "function") return;
	if (getJobsDurationSignature(getVisibleDurationNowMs())) {
		phCall("setVisibleDurationSurface", "jobs_list_duration", {
			getSignature: getJobsDurationSignature,
			render: renderJobsList,
		});
		return;
	}
	phCall("clearVisibleDurationSurface", "jobs_list_duration");
}

function isRerunLatestListCandidate(job) {
	var mode = String((job && job.mode) || "").trim();
	var issueId = String((job && job.issue_id) || "").trim();
	var commit = String((job && job.commit_summary) || "").trim();
	return (mode === "patch" || mode === "rerun_latest") && !!issueId && !!commit;
}

function clearRerunLatestRawCommand() {
	var rawNode = el("rawCommand");
	if (rawNode) rawNode.value = "";
	clearParsedState();
	setParseHint("");
}

function clearRerunLatestFormFields(statusText) {
	clearRerunLatestRawCommand();
	el("issueId").value = "";
	el("commitMsg").value = "";
	el("patchPath").value = "";
	dirty.issueId = false;
	dirty.commitMsg = false;
	dirty.patchPath = false;
	if (statusText) setUiStatus(statusText);
	phCall("validateAndPreview");
}

function resolveRerunLatestPatchPath(job) {
	var detail = job || {};
	var effective = String(detail.effective_patch_path || "").trim();
	var original = String(detail.original_patch_path || "").trim();
	var argv = Array.isArray(detail.canonical_command)
		? detail.canonical_command.slice()
		: [];
	var mode = String(detail.mode || "").trim();
	var idx = argv.indexOf("scripts/am_patch.py");
	var tail = idx >= 0 ? argv.slice(idx + 1) : [];
	var flagIdx = tail.indexOf("-l");
	if (effective) return effective;
	if (original) return original;
	if (idx < 0) return "";
	if (mode === "patch" || mode === "repair") {
		if (tail.length >= 3) return String(tail[2] || "").trim();
		return "";
	}
	if (mode === "rerun_latest") {
		if (flagIdx === 3) return String(tail[2] || "").trim();
		return "";
	}
	return "";
}

function extractRerunLatestValues(job) {
	var detail = job || {};
	var mode = String(detail.mode || "").trim();
	var issueId = String(detail.issue_id || "").trim();
	var commitMsg = String(detail.commit_message || "").trim();
	var patchPath = resolveRerunLatestPatchPath(detail);
	if ((mode !== "patch" && mode !== "rerun_latest") || !issueId || !commitMsg) {
		return null;
	}
	if (!patchPath) return null;
	return {
		issueId: issueId,
		commitMsg: commitMsg,
		patchPath: patchPath,
		jobId: String(detail.job_id || "").trim(),
	};
}

function rerunLatestPatchesRootPrefix() {
	var raw =
		cfg && cfg.paths && cfg.paths.patches_root
			? String(cfg.paths.patches_root || "")
			: "patches";
	return raw.trim().replace(/\\/g, "/").replace(/^\/+/, "").replace(/\/+$/, "");
}

function rerunLatestPatchStatRel(patchPath) {
	var full = normalizePatchPath(String(patchPath || "").trim())
		.replace(/\\/g, "/")
		.replace(/^\/+/, "");
	var prefix = rerunLatestPatchesRootPrefix();
	if (!full) return "";
	if (!prefix) return full;
	if (full === prefix) return "";
	if (full.indexOf(prefix + "/") === 0) {
		return full.slice(prefix.length + 1);
	}
	return full;
}

function loadRerunLatestUsableValues(job) {
	var values = extractRerunLatestValues(job);
	var rel = "";
	if (!values) {
		return Promise.resolve({ ok: false, reason: "detail_invalid" });
	}
	rel = rerunLatestPatchStatRel(values.patchPath);
	if (!rel) {
		return Promise.resolve({ ok: false, reason: "patch_missing" });
	}
	return apiGet("/api/fs/stat?path=" + encodeURIComponent(rel))
		.then((resp) => {
			if (!resp || resp.ok === false) {
				return { ok: false, reason: "patch_stat_error" };
			}
			if (resp.exists === false) {
				return { ok: false, reason: "patch_missing" };
			}
			return { ok: true, values: values };
		})
		.catch(() => ({ ok: false, reason: "patch_stat_error" }));
}

function applyRerunLatestValues(values, sourceLabel) {
	if (!values) return false;
	clearRerunLatestRawCommand();
	el("mode").value = "rerun_latest";
	el("issueId").value = String(values.issueId || "");
	el("commitMsg").value = String(values.commitMsg || "");
	el("patchPath").value = normalizePatchPath(String(values.patchPath || ""));
	dirty.issueId = false;
	dirty.commitMsg = false;
	dirty.patchPath = false;
	if (sourceLabel) {
		setUiStatus(
			"rerun_latest: prepared form from " +
				String(sourceLabel) +
				" job_id=" +
				String(values.jobId || ""),
		);
	}
	phCall("validateAndPreview");
	return true;
}

function loadJobDetail(jobId) {
	return apiGet("/api/jobs/" + encodeURIComponent(String(jobId || "")));
}

function prepareRerunLatestFromJobId(jobId, opts) {
	opts = opts || {};
	var seq = ++rerunPrepareSeq;
	var sourceLabel = String(opts.sourceLabel || "selected");
	var clearOnFailure = opts.clearOnFailure !== false;
	var failureStatus = String(
		opts.failureStatus ||
			"rerun_latest: selected job is not usable for Start-form autofill",
	);
	var requiredMode = String(opts.requiredMode || "").trim();
	var errText = "Cannot load rerun_latest job";
	if (!jobId) {
		if (clearOnFailure) {
			clearRerunLatestFormFields("rerun_latest: no usable previous job");
		} else {
			setUiStatus("rerun_latest: no usable previous job");
		}
		return Promise.resolve(false);
	}
	setUiStatus("rerun_latest: loading job_id=" + String(jobId));
	return loadJobDetail(jobId).then((resp) => {
		if (seq !== rerunPrepareSeq) return false;
		if (requiredMode && String(el("mode").value || "") !== requiredMode) {
			return false;
		}
		if (!resp || resp.ok === false || !resp.job) {
			errText = String((resp && resp.error) || "Cannot load rerun_latest job");
			if (clearOnFailure) {
				clearRerunLatestFormFields(failureStatus);
			} else {
				setUiStatus(failureStatus);
			}
			setUiError(errText);
			return false;
		}
		return loadRerunLatestUsableValues(resp.job).then((usable) => {
			var usableValues =
				usable && usable.ok === true && "values" in usable
					? usable.values
					: null;
			if (seq !== rerunPrepareSeq) return false;
			if (requiredMode && String(el("mode").value || "") !== requiredMode) {
				return false;
			}
			if (!usableValues) {
				if (clearOnFailure) {
					clearRerunLatestFormFields(failureStatus);
				} else {
					setUiStatus(failureStatus);
				}
				setUiError(failureStatus);
				return false;
			}
			return applyRerunLatestValues(usableValues, sourceLabel);
		});
	});
}

function prepareRerunLatestFromLatestJob() {
	var seq = ++rerunPrepareSeq;
	setUiStatus("rerun_latest: resolving latest usable job");
	return apiGet("/api/jobs").then((resp) => {
		function tryNext(candidates, idx) {
			if (seq !== rerunPrepareSeq) return Promise.resolve(false);
			if (String(el("mode").value || "") !== "rerun_latest") {
				return Promise.resolve(false);
			}
			if (idx >= candidates.length) {
				clearRerunLatestFormFields("rerun_latest: no usable previous job");
				return Promise.resolve(false);
			}
			var jobId = String(
				(candidates[idx] && candidates[idx].job_id) || "",
			).trim();
			if (!jobId) return tryNext(candidates, idx + 1);
			return loadJobDetail(jobId).then((detailResp) => {
				if (seq !== rerunPrepareSeq) return false;
				if (String(el("mode").value || "") !== "rerun_latest") return false;
				if (!detailResp || detailResp.ok === false || !detailResp.job) {
					return tryNext(candidates, idx + 1);
				}
				return loadRerunLatestUsableValues(detailResp.job).then((usable) => {
					var usableValues =
						usable && usable.ok === true && "values" in usable
							? usable.values
							: null;
					if (seq !== rerunPrepareSeq) return false;
					if (String(el("mode").value || "") !== "rerun_latest") {
						return false;
					}
					if (!usableValues) {
						return tryNext(candidates, idx + 1);
					}
					return applyRerunLatestValues(usableValues, "latest usable");
				});
			});
		}
		if (seq !== rerunPrepareSeq) return false;
		if (String(el("mode").value || "") !== "rerun_latest") return false;
		if (!resp || resp.ok === false) {
			clearRerunLatestFormFields("rerun_latest: no usable previous job");
			setUiError(String((resp && resp.error) || "Cannot load jobs"));
			return false;
		}
		var jobs = Array.isArray(resp.jobs) ? resp.jobs : [];
		var candidates = jobs.filter((job) => isRerunLatestListCandidate(job));
		if (!candidates.length) {
			clearRerunLatestFormFields("rerun_latest: no usable previous job");
			return false;
		}
		return tryNext(candidates, 0);
	});
}

function renderJobsList() {
	var jobs = Array.isArray(jobsCache) ? jobsCache.slice() : [];
	var trackedActiveId = String(phCall("getTrackedActiveJobId", jobs) || "");
	var tickNowMs = getVisibleDurationNowMs();
	var html = jobs
		.map((j) => {
			var jobId = String(j.job_id || "");
			var isSel = selectedJobId && String(selectedJobId) === jobId;
			var cls = `item job-item${isSel ? " selected" : ""}`;

			var issueId = String(j.issue_id || "").trim();
			var issueText = issueId ? `#${issueId}` : "(no issue)";

			var stRaw = String(j.status || "")
				.trim()
				.toLowerCase();
			var statusText = stRaw ? stRaw.toUpperCase() : "UNKNOWN";
			var statusCls = `job-status st-${stRaw || "unknown"}`;

			var metaParts = [];
			metaParts.push(`mode=${String(j.mode || "")}`);
			var pb = String(j.patch_basename || "").trim();
			if (pb) metaParts.push(`patch=${pb}`);

			var showListDuration = !!(j.started_utc && j.ended_utc);
			if (
				!showListDuration &&
				trackedActiveId &&
				jobId === trackedActiveId &&
				phCall("isNonTerminalJobStatus", j.status)
			) {
				showListDuration = true;
			}
			if (showListDuration) {
				const dur = getTrackedJobDurationLabel(j, tickNowMs);
				if (dur) metaParts.push(`dur=${dur}s`);
			}

			var meta = metaParts.join(" | ");
			var commit = String(j.commit_summary || "").trim();
			var showRerun = isRerunLatestListCandidate(j);

			var line = '<div class="' + cls + '">';
			line +=
				'<div class="name job-name" data-jobid="' + escapeHtml(jobId) + '">';
			line += '<div class="job-lines">';
			line += '<div class="job-top">';
			line += '<span class="job-issue">' + escapeHtml(issueText) + "</span>";
			line +=
				'<span class="' +
				escapeHtml(statusCls) +
				'">' +
				escapeHtml(statusText) +
				"</span>";
			line += "</div>";
			line += '<div class="job-commit">' + escapeHtml(commit) + "</div>";
			line += '<div class="job-meta">' + escapeHtml(meta) + "</div>";
			if (showRerun) {
				line += '<div class="actions job-actions">';
				line +=
					'<button type="button" class="btn btn-small jobUseForRerun" ' +
					'data-rerun-jobid="' +
					escapeHtml(jobId) +
					'">Use for -l</button>';
				line += "</div>";
			}
			line += "</div>";
			line += "</div>";
			line += "</div>";
			return line;
		})
		.join("");
	el("jobsList").innerHTML = html || '<div class="muted">(none)</div>';
}

function renderJobsFromResponse(r) {
	var jobs = r.jobs || [];
	jobsCache = Array.isArray(jobs) ? jobs.slice() : [];

	// If the most recently enqueued job reached a terminal state, reset mode to patch.
	try {
		const lastId = String(window.__ph_last_enqueued_job_id || "");
		if (lastId) {
			const j =
				(jobs || []).find((x) => String(x.job_id || "") === lastId) || null;
			const st = j
				? String(j.status || "")
						.trim()
						.toLowerCase()
				: "";
			if (st && st !== "running" && st !== "queued") {
				const m = el("mode");
				if (m) m.value = "patch";
				try {
					const iid = el("issueId");
					if (iid) iid.value = "";
					const cm = el("commitMsg");
					if (cm) cm.value = "";
					const pp = el("patchPath");
					if (pp) pp.value = "";
					const rc = el("rawCommand");
					if (rc) rc.value = "";
				} catch (_) {}
				try {
					dirty.issueId = false;
					dirty.commitMsg = false;
					dirty.patchPath = false;
				} catch (_) {}
				PH.call("clearGateOverrides");
				try {
					if (phCall("validateAndPreview") == null && m) {
						m.dispatchEvent(new Event("change"));
					}
				} catch (_) {}
				window.__ph_last_enqueued_job_id = "";
				window.__ph_last_enqueued_mode = "";
			}
		}
	} catch (_) {}

	var active = jobs.find((j) => j.status === "running") || null;
	var activeId = active ? String(active.job_id || "") : "";
	var idleAutoSelect = !!(cfg && cfg.ui && cfg.ui.idle_auto_select_last_job);

	if (!selectedJobId) {
		const saved = PH.call("loadLiveJobId");
		if (saved) selectedJobId = saved;
	}

	if (!selectedJobId && activeId) {
		selectedJobId = activeId;
		AMP_UI.saveLiveJobId(selectedJobId);
		suppressIdleOutput = false;
	}

	if (!selectedJobId && jobs.length && idleAutoSelect) {
		jobs.sort((a, b) =>
			String(a.created_utc || "").localeCompare(String(b.created_utc || "")),
		);
		selectedJobId = String(jobs[jobs.length - 1].job_id || "");
		if (selectedJobId) AMP_UI.saveLiveJobId(selectedJobId);
		suppressIdleOutput = false;
	}
	if (
		__ph_w.AMP_PATCHHUB_UI &&
		typeof __ph_w.AMP_PATCHHUB_UI.updateProgressPanelFromEvents === "function"
	) {
		__ph_w.AMP_PATCHHUB_UI.updateProgressPanelFromEvents({ jobs });
	} else {
		PH.call("renderActiveJob", jobs);
	}
	syncTrackedJobDurationClock(jobs);
	ensureAutoRefresh(jobs);
	renderJobsList();
	syncJobsDurationSurface();
}

function refreshJobsIdle() {
	var qs = "";
	if (idleSigs.jobs) qs = "?since_sig=" + encodeURIComponent(idleSigs.jobs);
	return apiGet("/api/jobs" + qs).then((r) => {
		if (!r || r.ok === false) {
			return { changed: false, sig: idleSigs.jobs };
		}
		var sig = String(r.sig || "");
		if (sig) idleSigs.jobs = sig;
		if (r.unchanged) return { changed: false, sig: sig };
		renderJobsFromResponse(r);
		return { changed: true, sig: sig };
	});
}

function headerBaseLabel() {
	if (cfg && cfg.server && cfg.server.host && cfg.server.port) {
		return "server: " + cfg.server.host + ":" + cfg.server.port;
	}
	return "";
}

function applyOverviewSnapshot(r) {
	if (!r || r.ok === false || r.unchanged) return false;
	var sigs = r.sigs || {};
	var snapSig = String(sigs.snapshot || "");
	if (snapSig) idleSigs.snapshot = snapSig;

	var js = String(sigs.jobs || "");
	var rs = String(sigs.runs || "");
	var ws = String(sigs.workspaces || "");
	var hs = String(sigs.header || "");
	if (js) idleSigs.jobs = js;
	if (rs) idleSigs.runs = rs;
	if (ws) idleSigs.workspaces = ws;
	if (hs) idleSigs.hdr = hs;

	var snap = r.snapshot || {};
	renderJobsFromResponse({ ok: true, jobs: snap.jobs || [] });
	phCall("renderRunsFromResponse", { ok: true, runs: snap.runs || [] });
	phCall("renderWorkspacesFromResponse", {
		ok: true,
		items: snap.workspaces || [],
	});
	phCall("renderHeaderFromSummary", snap.header || {}, headerBaseLabel());
	return true;
}

function refreshOverviewSnapshot(opts) {
	opts = opts || {};
	var mode = String(opts.mode || "user");
	var qs = "";
	if (idleSigs.snapshot) {
		qs = "?since_sig=" + encodeURIComponent(idleSigs.snapshot);
	}
	return apiGetETag("ui_snapshot", "/api/ui_snapshot" + qs, {
		mode: mode,
		single_flight: mode === "periodic",
	}).then((r) => ({ changed: applyOverviewSnapshot(r) }));
}

function idleRefreshTick() {
	if (document.hidden) return;
	if (!idleNextDueMs) idleNextDueMs = 0;
	if (Date.now() < idleNextDueMs) return;

	refreshOverviewSnapshot({ mode: "periodic" })
		.catch((_) => ({ changed: false }))
		.then((res) => {
			var changed = !!(res && res.changed);
			if (changed) {
				idleBackoffIdx = 0;
			} else if (idleBackoffIdx < IDLE_BACKOFF_MS.length - 1) {
				idleBackoffIdx += 1;
			}
			idleNextDueMs = Date.now() + IDLE_BACKOFF_MS[idleBackoffIdx];
		});
}

function refreshJobs(opts) {
	opts = opts || {};
	var mode = String(opts.mode || "user");
	var sf = mode === "periodic";
	apiGetETag("jobs_list", "/api/jobs", { mode: mode, single_flight: sf }).then(
		(r) => {
			if (!r || r.ok === false) {
				jobsCache = [];
				syncTrackedJobDurationClock([]);
				syncJobsDurationSurface();
				setPre("jobsList", r);
				PH.call("renderActiveJob", []);
				return;
			}
			if (r.unchanged) return;
			renderJobsFromResponse(r);
		},
	);
}

function ensureAutoRefresh(jobs) {
	var id = PH.call("getLiveJobId");
	var st = "";
	if (id && jobs && jobs.length) {
		const j = jobs.find((x) => String(x.job_id || "") === String(id)) || null;
		st = j ? String(j.status || "") : "";
	}
	if (st === "running" || st === "queued") PH.call("openLiveStream", id);
	else PH.call("closeLiveStream");

	if (PH.call("hasTrackedActiveJob")) {
		// Do not start a separate polling timer here.
		// Polling is centralized in app_part_wire_init.js and is stopped when tab is hidden.
		if (autoRefreshTimer) {
			clearInterval(autoRefreshTimer);
			autoRefreshTimer = null;
		}
		return;
	}
	if (autoRefreshTimer) {
		clearInterval(autoRefreshTimer);
		autoRefreshTimer = null;
	}
}

function computeCanonicalPreview(
	mode,
	issueId,
	commitMsg,
	patchPath,
	gateArgv,
) {
	var prefix =
		cfg && cfg.runner && cfg.runner.command
			? cfg.runner.command
			: ["python3", "scripts/am_patch.py"];
	var argv = prefix.slice();

	var gateTail = Array.isArray(gateArgv) ? gateArgv.slice() : [];
	if (mode === "finalize_live") {
		argv.push("-f");
		argv.push(String(commitMsg || ""));
		return argv.concat(gateTail);
	}
	if (mode === "finalize_workspace") {
		argv.push("-w");
		argv.push(String(issueId || ""));
		return argv.concat(gateTail);
	}
	if (mode === "rerun_latest") {
		argv.push(String(issueId || ""));
		argv.push(String(commitMsg || ""));
		if (String(patchPath || "")) argv.push(String(patchPath || ""));
		argv.push("-l");
		return argv.concat(gateTail);
	}

	argv.push(String(issueId || ""));
	argv.push(String(commitMsg || ""));
	argv.push(String(patchPath || ""));
	return argv.concat(gateTail);
}

if (PH && typeof PH.register === "function") {
	PH.register("app_part_jobs", {
		renderJobsFromResponse,
		refreshJobs,
		refreshOverviewSnapshot,
		idleRefreshTick,
		computeCanonicalPreview,
		isRerunLatestListCandidate,
		prepareRerunLatestFromJobId,
		prepareRerunLatestFromLatestJob,
	});
}
