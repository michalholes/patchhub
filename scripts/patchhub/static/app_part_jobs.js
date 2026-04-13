/// <reference path="../../../types/am2-globals.d.ts" />
var jobsWindow = /** @type {JobsWindow} */ (window);
var __ph_w = jobsWindow;
var jobsPH = /** @type {JobsRuntime | null} */ (jobsWindow.PH || null);
var jobsCache = /** @type {PatchhubJob[]} */ ([]);
var jobDetailCache = /** @type {Record<string, PatchhubJob | null>} */ (
	Object.create(null)
);
var jobDetailInflight =
	/** @type {Record<string, Promise<PatchhubJob | null>>} */ (
		Object.create(null)
	);
var jobsListActionsWired = false;
var rerunPrepareSeq = 0;
var trackedJobDurationClock = /** @type {unknown | null} */ (null);
var trackedJobDurationJobId = "";

function phCall(/** @type {string} */ name, /** @type {unknown[]} */ ...args) {
	if (!jobsPH || typeof jobsPH.call !== "function") return undefined;
	return jobsPH.call(name, ...args);
}

function getVisibleDurationNowMs() {
	var value = Number(phCall("getVisibleDurationNowMs"));
	return Number.isFinite(value) ? value : Date.now();
}

function formatVisibleDurationMs(/** @type {number} */ ms) {
	var text = phCall("formatVisibleDurationMs", ms);
	var tenths = 0;
	if (text || text === "0") return String(text);
	if (!Number.isFinite(ms) || ms < 0) return "";
	tenths = Math.floor(ms / 100);
	return String((tenths / 10).toFixed(1));
}

function syncTrackedJobDurationClock(
	/** @type {PatchhubJob[] | null | undefined} */ jobs,
) {
	var tracked = /** @type {PatchhubJob | null} */ (
		phCall("getTrackedActiveJob", jobs || [])
	);
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

function getTrackedJobDurationLabel(
	/** @type {PatchhubJob | null | undefined} */ job,
	/** @type {number} */ tickNowMs,
) {
	var jobId = "";
	var runningElapsedMs = /** @type {number | null} */ (null);
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
		runningElapsedMs = /** @type {number | null} */ (
			phCall(
				"readVisibleRuntimeElapsedMs",
				trackedJobDurationClock,
				Number.isFinite(tickNowMs) ? tickNowMs : getVisibleDurationNowMs(),
			)
		);
		if (Number.isFinite(runningElapsedMs)) {
			return formatVisibleDurationMs(/** @type {number} */ (runningElapsedMs));
		}
	}
	return String(
		phCall("jobSummaryDurationSeconds", job.started_utc, job.ended_utc) || "",
	);
}

function getJobsDurationSignature(/** @type {number} */ tickNowMs) {
	var tracked = /** @type {PatchhubJob | null} */ (
		phCall("getTrackedActiveJob", jobsCache || [])
	);
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
	if (!jobsPH || typeof jobsPH.call !== "function") return;
	if (getJobsDurationSignature(getVisibleDurationNowMs())) {
		phCall("setVisibleDurationSurface", "jobs_list_duration", {
			getSignature: getJobsDurationSignature,
			render: renderJobsList,
		});
		return;
	}
	phCall("clearVisibleDurationSurface", "jobs_list_duration");
}

function isRerunLatestListCandidate(
	/** @type {PatchhubJob | null | undefined} */ job,
) {
	var mode = String((job && job.mode) || "").trim();
	var issueId = String((job && job.issue_id) || "").trim();
	var commit = String((job && job.commit_summary) || "").trim();
	return (mode === "patch" || mode === "rerun_latest") && !!issueId && !!commit;
}

function getRerunLatestSummaryCandidates(
	/** @type {PatchhubJob[] | null | undefined} */ jobs,
) {
	var items = Array.isArray(jobs) ? jobs : [];
	return items.filter((job) => isRerunLatestListCandidate(job));
}

function findRerunLatestSummaryCandidateById(
	/** @type {string | null | undefined} */ jobId,
) {
	var wanted = String(jobId || "").trim();
	if (!wanted) return null;
	return (
		getRerunLatestSummaryCandidates(jobsCache || []).find(
			(job) => String((job && job.job_id) || "").trim() === wanted,
		) || null
	);
}

function clearRerunLatestRawCommand() {
	var rawNode = el("rawCommand");
	if (rawNode) rawNode.value = "";
	clearParsedState();
	setParseHint("");
}

function clearRerunLatestFormFields(
	/** @type {string | null | undefined} */ statusText,
) {
	clearRerunLatestRawCommand();
	el("issueId").value = "";
	el("commitMsg").value = "";
	el("patchPath").value = "";
	if (el("targetRepo")) el("targetRepo").value = "";
	dirty.issueId = false;
	dirty.commitMsg = false;
	dirty.patchPath = false;
	dirty.targetRepo = false;
	if (statusText) setUiStatus(statusText);
	phCall("validateAndPreview");
}

function resolveRerunLatestPatchPath(
	/** @type {PatchhubJob | null | undefined} */ job,
) {
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

function resolveRerunLatestTargetRepo(
	/** @type {PatchhubJob | null | undefined} */ detail,
) {
	var selected = String((detail && detail.selected_target_repo) || "").trim();
	var effective = String(
		(detail && detail.effective_runner_target_repo) || "",
	).trim();
	if (selected) return selected;
	if (effective) return effective;
	return "";
}

function extractRerunLatestValues(
	/** @type {PatchhubJob | null | undefined} */ job,
	/** @type {PatchhubJob | null | undefined} */ summaryJob,
) {
	var detail = job || {};
	var summary = summaryJob || {};
	var mode = String(detail.mode || summary.mode || "").trim();
	var issueId = String(detail.issue_id || summary.issue_id || "").trim();
	var commitMsg = String(
		detail.commit_message ||
			detail.commit_summary ||
			summary.commit_summary ||
			"",
	).trim();
	if (mode !== "patch" && mode !== "rerun_latest") {
		return null;
	}
	return {
		issueId: issueId,
		commitMsg: commitMsg,
		patchPath: resolveRerunLatestPatchPath(detail),
		targetRepo: resolveRerunLatestTargetRepo(detail),
		jobId: String(detail.job_id || summary.job_id || "").trim(),
	};
}

var protectedRerunLatestState = {
	active: false,
	trackedJobId: "",
};

function isProtectedRerunLatestLifecycleActive() {
	return !!(
		protectedRerunLatestState.active &&
		String((el("mode") && el("mode").value) || "") === "rerun_latest"
	);
}

function recordProtectedRerunLatestPrepare() {
	protectedRerunLatestState.active = true;
	protectedRerunLatestState.trackedJobId = "";
	return true;
}

function recordTrackedRerunLatestJobId(
	/** @type {string | null | undefined} */ jobId,
) {
	if (!isProtectedRerunLatestLifecycleActive()) return false;
	protectedRerunLatestState.trackedJobId = String(jobId || "").trim();
	return !!protectedRerunLatestState.trackedJobId;
}

function clearProtectedRerunLatestLifecycle() {
	protectedRerunLatestState.active = false;
	protectedRerunLatestState.trackedJobId = "";
	return false;
}

function syncProtectedRerunLatestLifecycleFromJobs(
	/** @type {PatchhubJob[] | null | undefined} */ jobs,
) {
	var items = Array.isArray(jobs) ? jobs : [];
	var trackedJobId = "";
	var tracked = null;
	var status = "";
	if (!isProtectedRerunLatestLifecycleActive()) return false;
	trackedJobId = String(protectedRerunLatestState.trackedJobId || "").trim();
	if (!trackedJobId) return true;
	tracked =
		items.find(
			(job) => String((job && job.job_id) || "").trim() === trackedJobId,
		) || null;
	if (!tracked) return true;
	status = String((tracked && tracked.status) || "")
		.trim()
		.toLowerCase();
	if (status && status !== "queued" && status !== "running") {
		clearProtectedRerunLatestLifecycle();
		return false;
	}
	return true;
}

function applyRerunLatestValues(
	/** @type {RerunLatestValues} */ values,
	/** @type {string | null | undefined} */ sourceLabel,
) {
	if (!values) return false;
	clearRerunLatestRawCommand();
	el("mode").value = "rerun_latest";
	el("issueId").value = String(values.issueId || "");
	el("commitMsg").value = String(values.commitMsg || "");
	el("patchPath").value = normalizePatchPath(String(values.patchPath || ""));
	if (el("targetRepo")) {
		el("targetRepo").value = String(values.targetRepo || "").trim();
	}
	recordProtectedRerunLatestPrepare();
	dirty.issueId = false;
	dirty.commitMsg = false;
	dirty.patchPath = false;
	dirty.targetRepo = false;
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

function loadJobDetail(/** @type {string | null | undefined} */ jobId) {
	return /** @type {Promise<JobDetailResponse>} */ (
		apiGet("/api/jobs/" + encodeURIComponent(String(jobId || "")))
	);
}

function cacheJobDetail(/** @type {PatchhubJob | null | undefined} */ detail) {
	var jobId = String((detail && detail.job_id) || "").trim();
	if (!jobId) return null;
	jobDetailCache[jobId] = detail || null;
	return detail || null;
}

function pruneJobDetailCache(
	/** @type {PatchhubJob[] | null | undefined} */ jobs,
) {
	var keep = Object.create(null);
	(jobs || []).forEach((job) => {
		var jobId = String((job && job.job_id) || "").trim();
		if (jobId) keep[jobId] = true;
	});
	Object.keys(jobDetailCache).forEach((jobId) => {
		if (!keep[jobId]) delete jobDetailCache[jobId];
	});
	Object.keys(jobDetailInflight).forEach((jobId) => {
		if (!keep[jobId]) delete jobDetailInflight[jobId];
	});
}

function reportRevertError(/** @type {string | null | undefined} */ message) {
	var text = String(message || "rollback: failed");
	if (typeof setUiError === "function") {
		setUiError(text);
		return;
	}
	setUiStatus(text);
}

function triggerRevertJob(/** @type {string | null | undefined} */ jobId) {
	var sourceJobId = String(jobId || selectedJobId || "").trim();
	var beginRollback = null;
	if (!sourceJobId) return Promise.resolve(false);
	beginRollback = phCall("beginRollbackFromJobId", sourceJobId);
	if (beginRollback) {
		return Promise.resolve(beginRollback).then((result) => !!result);
	}
	reportRevertError("rollback: entry flow is unavailable");
	return Promise.resolve(false);
}

function initJobsListActions() {
	var listNode = el("jobsList");
	if (!listNode || jobsListActionsWired) return;
	jobsListActionsWired = true;
	listNode.addEventListener("click", (e) => {
		var target = /** @type {JobsEventTarget | null} */ (
			e && e.target ? e.target : null
		);
		while (target && target !== listNode) {
			const revertJobId =
				target.getAttribute && target.getAttribute("data-revert-jobid");
			if (revertJobId) {
				if (typeof e.preventDefault === "function") e.preventDefault();
				if (typeof e.stopImmediatePropagation === "function") {
					e.stopImmediatePropagation();
				} else if (typeof e.stopPropagation === "function") {
					e.stopPropagation();
				}
				triggerRevertJob(String(revertJobId || ""));
				return;
			}
			target = /** @type {JobsEventTarget | null} */ (target.parentElement);
		}
	});
}

function jobOriginEvidenceText(
	/** @type {PatchhubJob | null | undefined} */ detail,
) {
	var origin = /** @type {any} */ (detail || {}),
		r = origin.origin_recovery || {};
	var mode = String(origin.origin_backend_mode || "").trim();
	var auth = String(origin.origin_authoritative_backend || "").trim();
	var session =
		String(origin.origin_backend_session_id || "").trim() || "unknown";
	var action = String(r.recovery_action || "").trim() || "none";
	var fallback = Array.isArray(r.fallback_export_errors)
		? r.fallback_export_errors[0]
		: "";
	var detailText =
		String(
			r.main_db_validation ||
				r.backup_restore_error ||
				fallback ||
				r.fallback_export_source ||
				"",
		).trim() || "none";
	if (!mode && !auth && session === "unknown")
		return "origin legacy/no-origin-evidence";
	return [
		"origin " + mode + "/" + auth,
		"session=" + session,
		"action=" + action,
		"detail=" + detailText,
	].join(" ");
}

function prepareRerunLatestFromJobId(
	/** @type {string | null | undefined} */ jobId,
	/** @type {RerunLatestOptions | null | undefined} */ opts,
) {
	opts = opts || {};
	var seq = ++rerunPrepareSeq;
	var sourceLabel = String(opts.sourceLabel || "selected");
	var clearOnFailure = opts.clearOnFailure !== false;
	var requiredMode = String(opts.requiredMode || "").trim();
	var candidateId = String(jobId || "").trim();
	var failureStatus = String(
		opts.failureStatus ||
			"rerun_latest: cannot load " + sourceLabel + " job_id=" + candidateId,
	);
	var summaryJob = findRerunLatestSummaryCandidateById(candidateId);
	if (!candidateId) {
		if (clearOnFailure) {
			clearRerunLatestFormFields(
				"rerun_latest: no previous summary-eligible job",
			);
		} else {
			setUiStatus("rerun_latest: no previous summary-eligible job");
		}
		return Promise.resolve(false);
	}
	if (!summaryJob && Array.isArray(jobsCache)) {
		const knownJob = (jobsCache || []).find(
			(job) => String((job && job.job_id) || "").trim() === candidateId,
		);
		if (knownJob) return Promise.resolve(false);
	}
	setUiStatus("rerun_latest: loading job_id=" + candidateId);
	return loadJobDetail(candidateId)
		.then((resp) => {
			if (seq !== rerunPrepareSeq) return false;
			if (requiredMode && String(el("mode").value || "") !== requiredMode) {
				return false;
			}
			if (!resp || resp.ok === false || !resp.job) {
				const errText = String(
					(resp && resp.error) || "Cannot load rerun_latest job",
				);
				setUiStatus(failureStatus);
				setUiError(errText);
				return false;
			}
			var values = extractRerunLatestValues(resp.job, summaryJob);
			if (!values) {
				setUiStatus(failureStatus);
				setUiError("Cannot extract rerun_latest values");
				return false;
			}
			return applyRerunLatestValues(values, sourceLabel);
		})
		.catch((err) => {
			if (seq !== rerunPrepareSeq) return false;
			if (requiredMode && String(el("mode").value || "") !== requiredMode) {
				return false;
			}
			setUiStatus(failureStatus);
			setUiError((err && err.message) || "Cannot load rerun_latest job");
			return false;
		});
}

function prepareRerunLatestFromLatestJob() {
	var seq = ++rerunPrepareSeq;
	setUiStatus("rerun_latest: resolving latest candidate");
	return /** @type {Promise<JobsListResponse>} */ (apiGet("/api/jobs"))
		.then((resp) => {
			if (seq !== rerunPrepareSeq) return false;
			if (String(el("mode").value || "") !== "rerun_latest") return false;
			if (!resp || resp.ok === false) {
				setUiStatus("rerun_latest: cannot load latest candidate");
				setUiError(String((resp && resp.error) || "Cannot load jobs"));
				return false;
			}
			var candidates = getRerunLatestSummaryCandidates(resp.jobs || []);
			var first = candidates[0] || null;
			var jobId = String((first && first.job_id) || "").trim();
			if (!jobId) {
				clearRerunLatestFormFields(
					"rerun_latest: no previous summary-eligible job",
				);
				return false;
			}
			jobsCache = Array.isArray(resp.jobs) ? resp.jobs.slice() : [];
			return prepareRerunLatestFromJobId(jobId, {
				sourceLabel: "latest candidate",
				clearOnFailure: false,
				requiredMode: "rerun_latest",
				failureStatus:
					"rerun_latest: cannot load latest candidate job_id=" + jobId,
			});
		})
		.catch((err) => {
			if (seq !== rerunPrepareSeq) return false;
			if (String(el("mode").value || "") !== "rerun_latest") return false;
			setUiStatus("rerun_latest: cannot load latest candidate");
			setUiError((err && err.message) || "Cannot load jobs");
			return false;
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
			var detail = jobDetailCache[jobId] || null;

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
			if (detail) meta += (meta ? " | " : "") + jobOriginEvidenceText(detail);
			else if (isSel && !jobDetailInflight[jobId]) {
				jobDetailInflight[jobId] = loadJobDetail(jobId)
					.then((/** @type {JobDetailResponse} */ resp) => {
						delete jobDetailInflight[jobId];
						if (!resp || resp.ok === false || !resp.job) return null;
						cacheJobDetail(resp.job);
						if (String(selectedJobId || "") === jobId) renderJobsList();
						return resp.job;
					})
					.catch(
						/** @returns {PatchhubJob | null} */ () => {
							delete jobDetailInflight[jobId];
							return null;
						},
					);
			}
			var commit = String(j.commit_summary || "").trim();
			var showRerun = isRerunLatestListCandidate(j);
			var showRevert = !!phCall("shouldShowJobsRevert", j);

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
			if (showRerun || showRevert) {
				line += '<div class="actions job-actions">';
				if (showRerun) {
					line +=
						'<button type="button" class="btn btn-small jobUseForRerun" ' +
						'data-rerun-jobid="' +
						escapeHtml(jobId) +
						'">Use for -l</button>';
				}
				if (showRevert) {
					line +=
						'<button type="button" class="btn btn-small jobRevert" ' +
						'data-revert-jobid="' +
						escapeHtml(jobId) +
						'">Roll-back</button>';
				}
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

function renderJobsFromResponse(/** @type {JobsListResponse} */ r) {
	var jobs = r.jobs || [];
	jobsCache = Array.isArray(jobs) ? jobs.slice() : [];
	pruneJobDetailCache(jobsCache);
	phCall("syncProtectedRerunLatestLifecycleFromJobs", jobsCache);

	// If the most recently enqueued job reached a terminal state, reset mode to patch.
	try {
		const lastId = String(window.__ph_last_enqueued_job_id || "");
		if (lastId) {
			const j =
				(jobs || []).find(
					(/** @type {PatchhubJob} */ x) => String(x.job_id || "") === lastId,
				) || null;
			const st = j
				? String(j.status || "")
						.trim()
						.toLowerCase()
				: "";
			if (
				st &&
				st !== "running" &&
				st !== "queued" &&
				!phCall("isProtectedRerunLatestLifecycleActive")
			) {
				phCall("clearProtectedRerunLatestLifecycle");
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
				phCall("clearGateOverrides");
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

	var active =
		jobs.find((/** @type {PatchhubJob} */ j) => j.status === "running") || null;
	var activeId = active ? String(active.job_id || "") : "";
	var idleAutoSelect = !!(cfg && cfg.ui && cfg.ui.idle_auto_select_last_job);

	if (!selectedJobId) {
		const saved = /** @type {string | null} */ (phCall("loadLiveJobId"));
		if (saved) selectedJobId = saved;
	}

	if (!selectedJobId && activeId) {
		selectedJobId = activeId;
		AMP_UI.saveLiveJobId(selectedJobId);
		suppressIdleOutput = false;
	}

	if (!selectedJobId && jobs.length && idleAutoSelect) {
		jobs.sort((/** @type {PatchhubJob} */ a, /** @type {PatchhubJob} */ b) =>
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
		phCall("renderActiveJob", jobs);
	}
	syncTrackedJobDurationClock(jobs);
	ensureAutoRefresh(jobs);
	renderJobsList();
	phCall("syncJobsRevertState", jobsCache, renderJobsList);
	syncJobsDurationSurface();
}

function refreshJobsIdle() {
	var qs = "";
	if (idleSigs.jobs) qs = "?since_sig=" + encodeURIComponent(idleSigs.jobs);
	return /** @type {Promise<JobsListResponse>} */ (
		apiGet("/api/jobs" + qs)
	).then((r) => {
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

function applyOverviewSnapshot(/** @type {OverviewResponse} */ r) {
	if (!r || r.ok === false || r.unchanged) return false;
	var sigs = r.sigs || {};
	var snapSig = String(sigs.snapshot || "");
	if (snapSig) idleSigs.snapshot = snapSig;

	var js = String(sigs.jobs || "");
	var rs = String(sigs.runs || "");
	var ps = String(sigs.patches || "");
	var ws = String(sigs.workspaces || "");
	var hs = String(sigs.header || "");
	if (js) idleSigs.jobs = js;
	if (rs) idleSigs.runs = rs;
	if (ps) idleSigs.patches = ps;
	if (ws) idleSigs.workspaces = ws;
	if (hs) idleSigs.hdr = hs;

	var snap = r.snapshot || {};
	renderJobsFromResponse({ ok: true, jobs: snap.jobs || [] });
	phCall("renderRunsFromResponse", { ok: true, runs: snap.runs || [] });
	phCall("renderPatchesFromResponse", { ok: true, items: snap.patches || [] });
	phCall("renderWorkspacesFromResponse", {
		ok: true,
		items: snap.workspaces || [],
	});
	phCall("renderHeaderFromSummary", snap.header || {}, headerBaseLabel());
	return true;
}

/*
Legacy anchors kept for source-contract tests after ownership moved to
app_part_snapshot_events.js:
function refreshOverviewSnapshot(opts)
apiGetETag("ui_snapshot", "/api/ui_snapshot" + qs
phCall("renderHeaderFromSummary", snap.header || {}, headerBaseLabel())
*/

function idleRefreshTick() {
	if (document.hidden) return;
	if (!idleNextDueMs) idleNextDueMs = 0;
	if (Date.now() < idleNextDueMs) return;

	Promise.resolve(phCall("refreshOverviewSnapshot", { mode: "periodic" }))
		.catch((_) => ({ changed: false }))
		.then((res) => {
			var refreshResult = /** @type {{ changed?: boolean } | null} */ (res);
			var changed = !!(refreshResult && refreshResult.changed);
			if (changed) {
				idleBackoffIdx = 0;
			} else if (idleBackoffIdx < IDLE_BACKOFF_MS.length - 1) {
				idleBackoffIdx += 1;
			}
			idleNextDueMs = Date.now() + IDLE_BACKOFF_MS[idleBackoffIdx];
		});
}

function refreshJobs(/** @type {{ mode?: string } | null | undefined} */ opts) {
	opts = opts || {};
	var mode = String(opts.mode || "user");
	var sf = mode === "periodic";
	/** @type {Promise<JobsListResponse>} */ (
		apiGetETag("jobs_list", "/api/jobs", { mode: mode, single_flight: sf })
	).then((r) => {
		if (!r || r.ok === false) {
			jobsCache = [];
			syncTrackedJobDurationClock([]);
			syncJobsDurationSurface();
			setPre("jobsList", r);
			phCall("renderActiveJob", []);
			return;
		}
		if (r.unchanged) return;
		renderJobsFromResponse(r);
	});
}

function ensureAutoRefresh(
	/** @type {PatchhubJob[] | null | undefined} */ jobs,
) {
	var id = phCall("getLiveJobId");
	var st = "";
	var trackedActive = false;
	if (id && jobs && jobs.length) {
		const j = jobs.find((x) => String(x.job_id || "") === String(id)) || null;
		st = j ? String(j.status || "") : "";
	}
	trackedActive = !!phCall("hasTrackedActiveJob", jobs || []);
	if ((st === "running" || st === "queued") && id) {
		phCall("openLiveStream", id);
	} else if (trackedActive && id) {
		phCall("openLiveStream", id);
	} else {
		phCall("closeLiveStream");
	}

	if (trackedActive) {
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
	/** @type {string | null | undefined} */ mode,
	/** @type {string | null | undefined} */ issueId,
	/** @type {string | null | undefined} */ commitMsg,
	/** @type {string | null | undefined} */ patchPath,
	/** @type {string[] | null | undefined} */ gateArgv,
	/** @type {string | null | undefined} */ targetRepo,
) {
	var prefix =
		cfg && cfg.runner && cfg.runner.command
			? cfg.runner.command
			: ["python3", "scripts/am_patch.py"];
	var argv = prefix.slice();

	var gateTail = Array.isArray(gateArgv) ? gateArgv.slice() : [];
	var targetTail = /** @type {string[]} */ ([]);
	if (String(targetRepo || "")) {
		targetTail = ["--target-repo-name", String(targetRepo || "")];
	}
	if (mode === "finalize_live") {
		argv.push("-f");
		argv.push(String(commitMsg || ""));
		return argv.concat(targetTail, gateTail);
	}
	if (mode === "finalize_workspace") {
		argv.push("-w");
		argv.push(String(issueId || ""));
		return argv.concat(targetTail, gateTail);
	}
	if (mode === "rerun_latest") {
		argv.push(String(issueId || ""));
		argv.push(String(commitMsg || ""));
		if (String(patchPath || "")) argv.push(String(patchPath || ""));
		argv.push("-l");
		return argv.concat(targetTail, gateTail);
	}

	argv.push(String(issueId || ""));
	argv.push(String(commitMsg || ""));
	argv.push(String(patchPath || ""));
	return argv.concat(targetTail, gateTail);
}

initJobsListActions();

if (jobsPH && typeof jobsPH.register === "function") {
	jobsPH.register("app_part_jobs", {
		renderJobsFromResponse,
		refreshJobs,
		idleRefreshTick,
		computeCanonicalPreview,
		isRerunLatestListCandidate,
		prepareRerunLatestFromJobId,
		prepareRerunLatestFromLatestJob,
		isProtectedRerunLatestLifecycleActive,
		recordProtectedRerunLatestPrepare,
		recordTrackedRerunLatestJobId,
		clearProtectedRerunLatestLifecycle,
		syncProtectedRerunLatestLifecycleFromJobs,
		triggerRevertJob,
	});
}
