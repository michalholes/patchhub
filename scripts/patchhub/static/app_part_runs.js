/**
 * @typedef {{
 *   issue_id?: string | number,
 *   result?: string,
 *   log_rel_path?: string,
 *   mtime_utc?: string,
 * }} PatchhubRunThin
 * @typedef {{
 *   ok?: boolean,
 *   error?: string,
 *   runs?: PatchhubRunThin[],
 *   run?: PatchhubHeaderRunDetail | null,
 *   sig?: string,
 *   unchanged?: boolean,
 * }} PatchhubRunsResponse
 * @typedef {{ ok?: boolean, text?: string, truncated?: boolean, tail?: string }} PatchhubTextResponse
 * @typedef {{ order: string[], state: Record<string, string> }} PatchhubShortProgress
 * @typedef {{
 *   call?: (name: string, ...args: unknown[]) => unknown,
 *   register?: (name: string, exportsObj: Record<string, unknown>) => void,
 * }} PatchhubRunsRuntime
 */
/** @type {PatchhubRunsRuntime | null} */
var runsPh = /** @type {any} */ (window).PH || null;
var lastRunLogPath = "";

function phCall(/** @type {string} */ name, /** @type {unknown[]} */ ...args) {
	if (!runsPh || typeof runsPh.call !== "function") return undefined;
	return runsPh.call(name, ...args);
}
function renderRunsFromResponse(/** @type {PatchhubRunsResponse} */ r) {
	runsCache = Array.isArray(r.runs) ? r.runs.slice() : [];

	var html = /** @type {PatchhubRunThin[]} */ (runsCache)
		.map((/** @type {PatchhubRunThin} */ x, idx) => {
			var log = x.log_rel_path || "";
			var link = log
				? '<a class="linklike" href="/api/fs/download?path=' +
					encodeURIComponent(log) +
					'">log</a>'
				: "";
			var sel =
				selectedRun &&
				selectedRun.issue_id === x.issue_id &&
				selectedRun.mtime_utc === x.mtime_utc
					? " *"
					: "";
			return (
				'<div class="item runitem" data-idx="' +
				String(idx) +
				'">' +
				'<span class="name">#' +
				String(x.issue_id) +
				" " +
				escapeHtml(String(x.result || "")) +
				sel +
				"</span>" +
				'<span class="actions">' +
				link +
				' <span class="muted">' +
				formatLocalTime(x.mtime_utc || "") +
				"</span></span>" +
				"</div>"
			);
		})
		.join("");

	el("runsList").innerHTML = html || '<div class="muted">(none)</div>';

	Array.from(el("runsList").querySelectorAll(".runitem .name")).forEach(
		(node) => {
			node.addEventListener("click", () => {
				var item = node.parentElement;
				if (!item) return;
				var idx = parseInt(item.getAttribute("data-idx") || "-1", 10);
				/** @type {PatchhubRunThin | null} */
				var thin = null;
				var iid = NaN;
				if (idx >= 0 && idx < runsCache.length) {
					thin = /** @type {PatchhubRunThin | null} */ (runsCache[idx] || null);
					if (!thin) return;
					iid = Number(thin.issue_id);
				}
				if (!Number.isFinite(iid)) return;
				apiGet(`/api/runs/${encodeURIComponent(String(iid))}`).then((dr) => {
					var resp = /** @type {PatchhubRunsResponse} */ (dr);
					if (!resp || resp.ok === false) {
						setPre("issueTabBody", resp);
						return;
					}
					selectedRun = resp.run || null;
					phCall("renderIssueDetail");
				});
			});
		},
	);
}

function refreshRuns(/** @type {{ mode?: string } | null | undefined} */ opts) {
	opts = opts || {};
	var mode = String(opts.mode || "user");
	/** @type {string[]} */
	var q = [];
	var issue = String(el("runsIssue").value || "").trim();
	var res = String(el("runsResult").value || "");
	if (issue) q.push(`issue_id=${encodeURIComponent(issue)}`);
	if (res) q.push(`result=${encodeURIComponent(res)}`);
	q.push("limit=80");

	apiGetETag("runs_list", `/api/runs?${q.join("&")}`, {
		mode: mode,
		single_flight: mode === "periodic",
	}).then((r) => {
		var resp = /** @type {PatchhubRunsResponse} */ (r);
		if (!resp || resp.ok === false) {
			setPre("runsList", resp);
			return;
		}
		if (resp.unchanged) return;
		var sig = String(resp.sig || "");
		if (sig) idleSigs.runs = sig;
		renderRunsFromResponse(resp);
	});
}

function refreshLastRunLog() {
	apiGet("/api/runs?limit=1").then((r) => {
		var resp = /** @type {PatchhubRunsResponse} */ (r);
		if (!resp || resp.ok === false) {
			setPre("lastRunLog", resp);
			return;
		}
		var runs = resp.runs || [];
		if (!runs.length) {
			lastRunLogPath = "";
			setPre("lastRunLog", "");
			return;
		}
		var logRel = String(runs[0].log_rel_path || "");
		if (!logRel) {
			lastRunLogPath = "";
			setPre("lastRunLog", "(no log path)");
			return;
		}

		lastRunLogPath = logRel;
		var box = el("lastRunLog");
		var wantFollow = isNearBottom(box, 24);
		var url =
			"/api/fs/read_text?path=" +
			encodeURIComponent(logRel) +
			"&tail_lines=2000";
		apiGet(url).then((rt) => {
			var textResp = /** @type {PatchhubTextResponse} */ (rt);
			if (!textResp || textResp.ok === false) {
				setPre("lastRunLog", textResp);
				return;
			}
			var t = String(textResp.text || "");
			if (textResp.truncated) t += "\n\n[TRUNCATED]";
			setPre("lastRunLog", t);
			if (wantFollow && box) box.scrollTop = box.scrollHeight;
		});
	});
}

function refreshTail(/** @type {number | null | undefined} */ lines) {
	tailLines = lines || tailLines || 200;

	var idleGuardOn = !!(cfg && cfg.ui && cfg.ui.clear_output_on_autofill);
	var jid = phCall("getLiveJobId");
	if (!jid && suppressIdleOutput && idleGuardOn) {
		setPre("tail", "");
		return;
	}

	var linesQ = encodeURIComponent(String(tailLines));
	var url = `/api/runner/tail?lines=${linesQ}`;
	if (jid) {
		url =
			"/api/jobs/" +
			encodeURIComponent(String(jid)) +
			"/log_tail?lines=" +
			linesQ;
	}
	apiGet(url).then((r) => {
		var resp = /** @type {PatchhubTextResponse} */ (r);
		if (!resp || resp.ok === false) {
			setPre("tail", resp);
			return;
		}
		var t = String(resp.tail || "");
		setPre("tail", t);
	});
}

function parseProgressFromText(/** @type {unknown} */ text) {
	var lines = String(text || "").split(/\r?\n/);
	/** @type {string[]} */
	var order = [];
	/** @type {Record<string, string>} */
	var state = {};
	var currentRunning = "";

	function normStepName(/** @type {unknown} */ s) {
		return String(s || "")
			.replace(/\s+/g, " ")
			.trim();
	}

	function ensureStep(/** @type {string} */ name) {
		if (!name) return;
		if (!Object.hasOwn(state, name)) {
			state[name] = "pending";
		}
		if (order.indexOf(name) < 0) order.push(name);
	}

	function setState(/** @type {string} */ name, /** @type {string} */ st) {
		name = normStepName(name);
		if (!name) return;
		ensureStep(name);
		state[name] = st;
	}

	for (let i = 0; i < lines.length; i++) {
		const raw = String(lines[i] || "");
		const s = raw.trim();
		if (!s) continue;

		if (s.indexOf("DO:") === 0) {
			const stepDo = normStepName(s.slice(3));
			setState(stepDo, "running");
			currentRunning = stepDo;
			continue;
		}

		if (s.indexOf("OK:") === 0) {
			const stepOk = normStepName(s.slice(3));
			setState(stepOk, "ok");
			if (currentRunning === stepOk) currentRunning = "";
			continue;
		}

		if (s.indexOf("FAIL:") === 0) {
			const stepFail = normStepName(s.slice(5));
			setState(stepFail, "fail");
			if (currentRunning === stepFail) currentRunning = "";
			continue;
		}

		if (s.indexOf("ERROR:") === 0 || s === "FAIL" || s.indexOf("FAIL ") === 0) {
			if (currentRunning) setState(currentRunning, "fail");
		}
	}

	if (currentRunning) {
		for (let j = 0; j < order.length; j++) {
			const nm = order[j];
			if (state[nm] === "running" && nm !== currentRunning) {
				state[nm] = "pending";
			}
		}
	}

	for (let k = 0; k < order.length; k++) {
		const nm2 = order[k];
		if (!Object.hasOwn(state, nm2)) state[nm2] = "pending";
	}

	return { order: order, state: state };
}

function pickProgressSummaryLine(/** @type {unknown} */ text) {
	var lines = String(text || "").split(/\r?\n/);
	for (let i = lines.length - 1; i >= 0; i--) {
		const s = String(lines[i] || "").trim();
		if (!s) continue;

		if (s.indexOf("RESULT:") === 0) return s;
		if (s.indexOf("STATUS:") === 0) return s;
		if (s.indexOf("FAIL:") === 0) return s;
		if (s.indexOf("OK:") === 0) return s;
		if (s.indexOf("DO:") === 0) return s;
	}
	return "(idle)";
}

function renderProgressSteps(/** @type {PatchhubShortProgress} */ progress) {
	var box = el("progressSteps");
	if (!box) return;

	var order = progress && progress.order ? progress.order : [];
	var state = progress && progress.state ? progress.state : {};

	if (!order.length) {
		box.innerHTML = "";
		return;
	}

	var html = "";
	for (let i = 0; i < order.length; i++) {
		const name = order[i];
		const st = state[name] || "pending";
		html += '<div class="step">';
		html += `<span class="dot ${escapeHtml(st)}"></span>`;
		html += `<span class="step-name">${escapeHtml(name)}</span>`;
		if (st === "running") {
			html += '<span class="pill running">RUNNING</span>';
		}
		html += "</div>";
	}

	box.innerHTML = html;
}

function renderProgressSummary(/** @type {unknown} */ summaryLine) {
	var node = el("progressSummary");
	if (!node) return;
	node.textContent = String(summaryLine || "(idle)");
}

function updateShortProgressFromText(/** @type {unknown} */ text) {
	var progress = parseProgressFromText(text);
	renderProgressSteps(progress);
	renderProgressSummary(pickProgressSummaryLine(text));
}

function normStepName(/** @type {unknown} */ s) {
	return String(s || "")
		.replace(/\s+/g, " ")
		.trim();
}

if (runsPh && typeof runsPh.register === "function") {
	const PH = runsPh;
	if (PH.register) {
		PH.register("app_part_runs", {
			renderRunsFromResponse,
			refreshRuns,
			refreshLastRunLog,
			refreshTail,
			updateShortProgressFromText,
		});
	}
}
