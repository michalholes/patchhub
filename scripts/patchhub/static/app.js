// PatchHub app core (refactored split: part files).
var __ph_w = /** @type {any} */ (window);
/** @type {any} */
var PH = null;

__ph_w.AMP_PATCHHUB_UI = __ph_w.AMP_PATCHHUB_UI || {};
const AMP_UI = __ph_w.AMP_PATCHHUB_UI;

var activeJobId = null;
var autoRefreshTimer = null;

var UI_STATUS_LIMIT = 20;
var uiStatusLines = [];
var degradedNotes = [];
var infoPoolHints = { upload: "", enqueue: "", fs: "", parse: "" };
var infoPoolHintSeq = { upload: 0, enqueue: 0, fs: 0, parse: 0 };
var infoPoolSeq = 0;

var selectedJobId = null;
var liveStreamJobId = null;
var liveES = null;
var liveEvents = [];
var liveLevel = "normal";

var previewVisible = false;
var workspacesVisible = false;
var runsVisible = false;
var jobsVisible = false;
var workspacesCache = [];

function appLog(kind, message) {
	var msg = String(message || "");
	try {
		if (__ph_w.PH_BOOT && typeof __ph_w.PH_BOOT.bootLog === "function") {
			__ph_w.PH_BOOT.bootLog(kind, msg);
			return;
		}
	} catch (e) {
		// ignore
	}
	try {
		if (kind === "error") console.error("[PatchHub]", msg);
		else if (kind === "warn") console.warn("[PatchHub]", msg);
		else console.log("[PatchHub]", msg);
	} catch (e) {
		// ignore
	}
}

function rememberDegraded(message) {
	var msg = String(message || "").trim();
	if (!msg) return;
	if (degradedNotes.indexOf(msg) < 0) degradedNotes.push(msg);
	if (degradedNotes.length > UI_STATUS_LIMIT) {
		degradedNotes.splice(0, degradedNotes.length - UI_STATUS_LIMIT);
	}
	if (PH && typeof PH.has === "function" && PH.has("renderInfoPoolUi")) {
		PH.call("renderInfoPoolUi");
		return;
	}
	setLegacyPooledNode("uiDegradedBanner", "DEGRADED MODE: " + msg);
}

__ph_w.PH_APP_SHOW_DEGRADED = rememberDegraded;

async function loadParts(rt) {
	PH = rt;
	if (!PH) {
		appLog("error", "PH runtime missing");
		throw new Error("PH runtime missing");
	}

	function noteLoad(ok, note) {
		if (!ok) rememberDegraded(note);
		return ok;
	}

	// Optional modules (degraded mode if missing).
	noteLoad(
		await PH.loadScript(
			"/static/patchhub_visible_duration.js",
			"visible_duration",
		),
		"visible duration module missing",
	);
	noteLoad(
		await PH.loadScript("/static/patchhub_progress_ui.js", "progress"),
		"progress module missing",
	);
	noteLoad(
		await PH.loadScript("/static/patchhub_live_ui.js", "live"),
		"live module missing",
	);
	noteLoad(
		await PH.loadScript("/static/amp_settings.js", "amp_settings"),
		"amp settings module missing",
	);

	// App part files. Missing modules fall back to minimal built-in handlers.
	noteLoad(
		await PH.loadScript("/static/app_part_runs.js", "app_part_runs"),
		"runs module missing",
	);
	noteLoad(
		await PH.loadScript("/static/app_part_jobs.js", "app_part_jobs"),
		"jobs module missing",
	);
	noteLoad(
		await PH.loadScript(
			"/static/app_part_workspaces.js",
			"app_part_workspaces",
		),
		"workspaces module missing",
	);
	noteLoad(
		await PH.loadScript(
			"/static/app_part_pm_validation.js",
			"app_part_pm_validation",
		),
		"pm validation module missing",
	);
	noteLoad(
		await PH.loadScript("/static/app_part_info_pool.js", "app_part_info_pool"),
		"info pool module missing",
	);
	noteLoad(
		await PH.loadScript(
			"/static/app_part_queue_upload.js",
			"app_part_queue_upload",
		),
		"queue/upload module missing",
	);
	noteLoad(
		await PH.loadScript(
			"/static/app_part_gate_options.js",
			"app_part_gate_options",
		),
		"gate options module missing",
	);
	noteLoad(
		await PH.loadScript(
			"/static/app_part_zip_subset_modal.js",
			"app_part_zip_subset_modal",
		),
		"zip subset modal module missing",
	);
	noteLoad(
		await PH.loadScript(
			"/static/app_part_zip_subset.js",
			"app_part_zip_subset",
		),
		"zip subset module missing",
	);
	noteLoad(
		await PH.loadScript(
			"/static/app_part_autofill_header.js",
			"app_part_autofill_header",
		),
		"autofill/header module missing",
	);
	noteLoad(
		await PH.loadScript(
			"/static/app_part_snapshot_events.js",
			"app_part_snapshot_events",
		),
		"snapshot events module missing",
	);
	noteLoad(
		await PH.loadScript("/static/app_part_wire_init.js", "app_part_wire_init"),
		"wire init module missing; built-in fallback active",
	);
	return true;
}

// Called by bootstrap.
__ph_w.PH_APP_MAIN = async function PH_APP_MAIN(rt) {
	await loadParts(rt);
	if (!PH || typeof PH.call !== "function") {
		appLog("error", "PatchHub runtime dispatcher unavailable");
		rememberDegraded("runtime dispatcher unavailable");
		return;
	}
	PH.call("startAppWireInit");
};

// Deterministic IDLE visible-tab backoff. ACTIVE mode is not affected.
var IDLE_BACKOFF_MS = [2000, 5000, 15000, 30000, 60000];
var idleBackoffIdx = 0;
var idleNextDueMs = 0;
var idleSigs = { jobs: "", runs: "", workspaces: "", hdr: "", snapshot: "" };

function setPreviewVisible(v) {
	previewVisible = !!v;
	var wrap = el("previewWrapRight");
	var btn1 = el("previewToggle");
	var btn2 = el("previewCollapse");
	if (wrap) wrap.classList.toggle("hidden", !previewVisible);
	var t = previewVisible ? "Hide" : "Show";
	if (btn1) btn1.textContent = previewVisible ? "Hide preview" : "Preview";
	if (btn2) btn2.textContent = t;
}

function isNearBottom(node, slack) {
	if (!node) return true;
	slack = slack == null ? 20 : slack;
	return node.scrollTop + node.clientHeight >= node.scrollHeight - slack;
}

/**
 * @param {string} id
 * @returns {any}
 */
function el(id) {
	return /** @type {any} */ (document.getElementById(id));
}

function normalizeUiStatusLines(message) {
	return String(message || "")
		.split(/\r?\n/)
		.map((line) => line.replace(/\s+/g, " ").trim())
		.filter((line) => !!line);
}

function setLegacyPooledNode(id, message) {
	var node = el(id);
	if (!node) return;
	var text = String(message || "").trim();
	node.textContent = text;
	node.classList.toggle("hidden", !text);
}

function getInfoPoolLatestHint() {
	var bestSource = "";
	var bestSeq = 0;
	Object.keys(infoPoolHints).forEach((source) => {
		if (!infoPoolHints[source]) return;
		var seq = Number(infoPoolHintSeq[source] || 0);
		if (seq <= bestSeq) return;
		bestSeq = seq;
		bestSource = source;
	});
	if (!bestSource) return { source: "", text: "" };
	return { source: bestSource, text: String(infoPoolHints[bestSource] || "") };
}

function getInfoPoolSnapshot() {
	return {
		degradedNotes: degradedNotes.slice(),
		statusLines: uiStatusLines.slice(),
		hints: {
			upload: String(infoPoolHints.upload || ""),
			enqueue: String(infoPoolHints.enqueue || ""),
			fs: String(infoPoolHints.fs || ""),
			parse: String(infoPoolHints.parse || ""),
		},
		latestHint: getInfoPoolLatestHint(),
	};
}

function setInfoPoolHint(source, message) {
	var key = String(source || "");
	if (!Object.hasOwn(infoPoolHints, key)) return;
	var text = String(message || "").trim();
	infoPoolHints[key] = text;
	infoPoolHintSeq[key] = text ? ++infoPoolSeq : 0;
	if (PH && typeof PH.has === "function" && PH.has("renderInfoPoolUi")) {
		PH.call("renderInfoPoolUi");
		return;
	}
	var legacyId = "";
	if (key === "upload") legacyId = "uploadHint";
	else if (key === "enqueue") legacyId = "enqueueHint";
	else if (key === "fs") legacyId = "fsHint";
	else if (key === "parse") legacyId = "parseHint";
	if (legacyId) setLegacyPooledNode(legacyId, text);
}

function renderUiStatusLines() {
	if (PH && typeof PH.has === "function" && PH.has("renderInfoPoolUi")) {
		PH.call("renderInfoPoolUi");
		return;
	}
	var node = el("uiStatusBar");
	if (!node) return;
	node.textContent = uiStatusLines.join("\n");
}

function pushUiStatusLine(message) {
	var lines = normalizeUiStatusLines(message);
	if (!lines.length) return;
	lines.forEach((line) => {
		uiStatusLines.push(line);
	});
	if (uiStatusLines.length > UI_STATUS_LIMIT) {
		uiStatusLines.splice(0, uiStatusLines.length - UI_STATUS_LIMIT);
	}
	renderUiStatusLines();
}

function setUiStatus(message) {
	pushUiStatusLine(message);
}

function setUiError(errorText) {
	pushUiStatusLine(`ERROR: ${String(errorText || "")}`);
}

function pushApiStatus(payload) {
	if (!payload) return;
	if (payload.ok === false && payload.error) {
		setUiError(String(payload.error || ""));
	}
	if (
		!payload.status ||
		!Array.isArray(payload.status) ||
		!payload.status.length
	) {
		return;
	}
	payload.status.forEach((line) => {
		pushUiStatusLine(String(line || ""));
	});
}

function setPre(id, obj) {
	var node = el(id);
	if (!node) return;
	if (typeof obj === "string") {
		node.textContent = obj;
		return;
	}
	try {
		node.textContent = JSON.stringify(obj, null, 2);
	} catch (e) {
		node.textContent = String(obj);
	}
}

function setText(id, text) {
	var node = el(id);
	if (!node) return;
	node.textContent = String(text || "");
}

function formatLocalTime(isoUtc) {
	if (!isoUtc) return "";
	var d = new Date(String(isoUtc));
	if (isNaN(d.getTime())) return String(isoUtc);
	return d.toLocaleString(undefined, {
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});
}

function apiGet(path) {
	return fetch(path, { headers: { Accept: "application/json" } }).then((r) =>
		r.text().then((t) => {
			try {
				return JSON.parse(t);
			} catch (e) {
				return {
					ok: false,
					error: "bad json",
					raw: t,
					status: r.status,
				};
			}
		}),
	);
}

var __phEtagCache = {};
var __phInFlight = {};
var __phAborters = {};

function apiAbortKey(key) {
	key = String(key || "");
	var ctl = null;
	try {
		ctl = __phAborters[key];
		if (ctl) ctl.abort();
	} catch (_) {}
	__phAborters[key] = null;
	__phInFlight[key] = null;
}

function apiGetETag(key, path, opts) {
	key = String(key || "");
	path = String(path || "");
	opts = opts || {};

	// Request policy:
	// - mode="periodic": MUST NOT start a second request if one is in-flight.
	// - mode="user" or "latest": abort prior request (deterministic: latest wins).
	var mode = String(opts.mode || "latest")
		.trim()
		.toLowerCase();
	var singleFlight = !!opts.single_flight;

	var cur = __phInFlight[key];
	if (cur && (mode === "periodic" || singleFlight)) return cur;

	if (mode !== "periodic") {
		apiAbortKey(key);
	}

	var ctl = new AbortController();
	__phAborters[key] = ctl;

	var hdr = { Accept: "application/json" };
	var et = __phEtagCache[key];
	if (et) hdr["If-None-Match"] = String(et);

	var p = fetch(path, { headers: hdr, signal: ctl.signal }).then((r) => {
		if (r.status === 304) {
			return { ok: true, unchanged: true, status: 304 };
		}
		return r.text().then((t) => {
			var obj = null;
			try {
				obj = JSON.parse(t);
			} catch (e) {
				obj = { ok: false, error: "bad json", raw: t, status: r.status };
			}
			var newEtag = r.headers.get("ETag");
			if (newEtag) __phEtagCache[key] = String(newEtag);
			return obj;
		});
	});
	__phInFlight[key] = p;
	return p.finally(() => {
		if (__phInFlight[key] === p) {
			__phInFlight[key] = null;
			__phAborters[key] = null;
		}
	});
}

function apiPost(path, body) {
	return fetch(path, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Accept: "application/json",
		},
		body: JSON.stringify(body || {}),
	}).then((r) =>
		r.text().then((t) => {
			try {
				return JSON.parse(t);
			} catch (e) {
				return {
					ok: false,
					error: "bad json",
					raw: t,
					status: r.status,
				};
			}
		}),
	);
}

function joinRel(a, b) {
	a = String(a || "").replace(/\/+$/, "");
	b = String(b || "").replace(/^\/+/, "");
	if (!a) return b;
	if (!b) return a;
	return `${a}/${b}`;
}

function parentRel(p) {
	p = String(p || "").replace(/\/+$/, "");
	var idx = p.lastIndexOf("/");
	if (idx < 0) return "";
	return p.slice(0, idx);
}

function escapeHtml(s) {
	return String(s || "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

var cfg = null;
var issueRegex = null;
var fsSelected = "";
var fsChecked = {};
var fsLastRels = [];
var runsCache = [];
var selectedRun = null;
var tailLines = 200;

var dirty = { issueId: false, commitMsg: false, patchPath: false };
var latestToken = "";
var lastAutofillClearedToken = "";
var autofillTimer = null;

var patchStatInFlight = false;
var patchStatLastRel = "";
var patchStatNextDueMs = 0;
var patchStatIdleBackoffIdx = 0;

var PATCH_STAT_ACTIVE_MS = 5000;

var suppressIdleOutput = false;

var lastParsedRaw = "";
var lastParsed = null;
var parseInFlight = false;
var parseTimer = null;
var parseSeq = 0;

function patchesRootRel() {
	var p =
		cfg && cfg.paths && cfg.paths.patches_root
			? String(cfg.paths.patches_root)
			: "patches";
	return p.replace(/\/+$/, "");
}

function stripPatchesPrefix(path) {
	var pfx = patchesRootRel();
	var p = String(path || "").replace(/^\/+/, "");
	if (p === pfx) return "";
	if (p.indexOf(`${pfx}/`) === 0) return p.slice(pfx.length + 1);
	return p;
}

function normalizePatchPath(p) {
	p = String(p || "")
		.trim()
		.replace(/^\/+/, "");
	if (!p) return "";

	var pfx = patchesRootRel();
	if (p === pfx) return pfx;
	if (p.indexOf(`${pfx}/`) === 0) return p;
	return joinRel(pfx, p);
}

function clearRunFieldsBecauseMissingPatch() {
	resetMissingPatchState();
	if (el("issueId")) el("issueId").value = "";
	if (el("commitMsg")) el("commitMsg").value = "";
	if (el("patchPath")) el("patchPath").value = "";
	validateAndPreview();
}

function resetMissingPatchState() {
	patchStatLastRel = "";
	patchStatNextDueMs = 0;
	patchStatIdleBackoffIdx = 0;
}

function getMissingPatchRel() {
	if (!el("patchPath")) return "";
	var full = normalizePatchPath(String(el("patchPath").value || ""));
	var rel = stripPatchesPrefix(full);
	if (!rel) {
		resetMissingPatchState();
		return "";
	}
	return rel;
}

function nextMissingPatchDelayMs(mode, changedRel) {
	if (mode === "active") return PATCH_STAT_ACTIVE_MS;
	if (changedRel) patchStatIdleBackoffIdx = 0;
	var idx = patchStatIdleBackoffIdx;
	var delay = IDLE_BACKOFF_MS[idx] || IDLE_BACKOFF_MS[0];
	if (patchStatIdleBackoffIdx < IDLE_BACKOFF_MS.length - 1) {
		patchStatIdleBackoffIdx += 1;
	}
	return delay;
}

function tickMissingPatchClear(opts) {
	opts = opts || {};
	if (patchStatInFlight) return;

	var rel = getMissingPatchRel();
	if (!rel) return;

	var mode = String(opts.mode || "idle");
	var changedRel = rel !== patchStatLastRel;
	var now = Date.now();
	if (
		!opts.force &&
		!changedRel &&
		patchStatNextDueMs &&
		now < patchStatNextDueMs
	) {
		return;
	}

	patchStatLastRel = rel;
	patchStatInFlight = true;
	apiGet(`/api/fs/stat?path=${encodeURIComponent(rel)}`)
		.then((r) => {
			patchStatInFlight = false;
			if (r && r.ok !== false && r.exists === false) {
				clearRunFieldsBecauseMissingPatch();
				return;
			}
			patchStatNextDueMs =
				Date.now() + nextMissingPatchDelayMs(mode, changedRel);
		})
		.catch(() => {
			patchStatInFlight = false;
			patchStatNextDueMs =
				Date.now() + nextMissingPatchDelayMs(mode, changedRel);
		});
}

function setFsHint(msg) {
	setInfoPoolHint("fs", msg || "");
}

function fsUpdateSelCount() {
	var n = 0;
	for (var k in fsChecked) {
		if (Object.hasOwn(fsChecked, k)) n += 1;
	}
	var node = el("fsSelCount");
	if (node) {
		node.textContent = n ? `selected: ${String(n)}` : "";
	}
	return n;
}

function fsClearSelection() {
	fsChecked = {};
	fsUpdateSelCount();
}

function fsDownloadSelected() {
	var paths = [];
	for (var k in fsChecked) {
		if (Object.hasOwn(fsChecked, k)) paths.push(k);
	}
	if (!paths.length) {
		setFsHint("select at least one item");
		return;
	}
	paths.sort();

	fetch("/api/fs/archive", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ paths: paths }),
	})
		.then((r) => {
			if (!r.ok) {
				return r.text().then((t) => {
					setFsHint(`archive failed: ${String(t || r.status)}`);
				});
			}
			return r.blob().then((blob) => {
				var url = URL.createObjectURL(blob);
				var a = document.createElement("a");
				a.href = url;
				a.download = "selection.zip";
				document.body.appendChild(a);
				a.click();
				a.remove();
				setTimeout(() => {
					URL.revokeObjectURL(url);
				}, 1000);
			});
		})
		.catch((e) => {
			setFsHint(`archive failed: ${String(e)}`);
		});
}

function setParseHint(msg) {
	setInfoPoolHint("parse", msg || "");
}

function getRawCommand() {
	var n = el("rawCommand");
	if (!n) return "";
	return String(n.value || "").trim();
}

function clearParsedState() {
	lastParsedRaw = "";
	lastParsed = null;
	parseInFlight = false;
}

function triggerParse(raw) {
	raw = String(raw || "").trim();
	if (!raw) {
		clearParsedState();
		setParseHint("");
		validateAndPreview();
		return;
	}

	parseInFlight = true;
	lastParsedRaw = "";
	lastParsed = null;
	setParseHint("Parsing...");
	setUiStatus("parse_command: started");
	validateAndPreview();

	parseSeq += 1;
	var mySeq = parseSeq;
	apiPost("/api/parse_command", { raw: raw }).then((r) => {
		if (mySeq !== parseSeq) return;
		parseInFlight = false;

		if (!r || r.ok === false) {
			clearParsedState();
			setParseHint(`Parse failed: ${String((r && r.error) || "")}`);
			setUiError(String((r && r.error) || "parse failed"));
			validateAndPreview();
			return;
		}

		pushApiStatus(r);

		lastParsedRaw = raw;
		lastParsed = r;
		setParseHint("");
		if (r.parsed && typeof r.parsed === "object") {
			if (r.parsed.mode) el("mode").value = String(r.parsed.mode);
			if (r.parsed.issue_id != null) {
				el("issueId").value = String(r.parsed.issue_id || "");
			}
			if (r.parsed.commit_message != null) {
				el("commitMsg").value = String(r.parsed.commit_message || "");
			}
			if (r.parsed.patch_path != null) {
				el("patchPath").value = String(r.parsed.patch_path || "");
			}
		}

		validateAndPreview();
	});
}

function scheduleParseDebounced(raw) {
	if (parseTimer) {
		clearTimeout(parseTimer);
		parseTimer = null;
	}
	parseTimer = setTimeout(() => {
		parseTimer = null;
		triggerParse(raw);
	}, 350);
}

function refreshFs() {
	var path = el("fsPath").value || "";
	apiGet(`/api/fs/list?path=${encodeURIComponent(path)}`).then((r) => {
		if (!r || r.ok === false) {
			setPre("fsList", r);
			return;
		}
		var items = r.items || [];
		fsLastRels = [];
		var html = items
			.map((it) => {
				var name = it.name;
				var isDir = !!it.is_dir;
				var rel = joinRel(path, name);
				fsLastRels.push(rel);

				var displayName = isDir ? `${name}/` : name;
				var isSelected = fsSelected === rel;
				var cls = `item fsitem${isSelected ? " selected" : ""}`;
				var checked = fsChecked[rel] ? " checked" : "";

				var dl = "";
				if (!isDir) {
					dl =
						'<button class="btn btn-small btn-inline fsDl" data-rel="' +
						escapeHtml(rel) +
						'">Download</button>';
				}

				return (
					'<div class="' +
					cls +
					'" data-rel="' +
					escapeHtml(rel) +
					'" data-isdir="' +
					(isDir ? "1" : "0") +
					'">' +
					'<input class="fsChk" type="checkbox" data-rel="' +
					escapeHtml(rel) +
					'" aria-label="Select" ' +
					checked +
					" />" +
					'<span class="name">' +
					escapeHtml(displayName) +
					"</span>" +
					'<span class="actions"><span class="muted">' +
					String(it.size || 0) +
					"</span>" +
					dl +
					"</span>" +
					"</div>"
				);
			})
			.join("");

		el("fsList").innerHTML = html || '<div class="muted">(empty)</div>';
		fsUpdateSelCount();

		Array.from(el("fsList").querySelectorAll(".fsChk")).forEach((node) => {
			node.addEventListener("click", (ev) => {
				ev.stopPropagation();
				var rel = node.getAttribute("data-rel") || "";
				if (!rel) return;
				if (node.checked) {
					fsChecked[rel] = true;
				} else {
					delete fsChecked[rel];
				}
				fsUpdateSelCount();
			});
		});

		Array.from(el("fsList").querySelectorAll(".fsDl")).forEach((node) => {
			node.addEventListener("click", (ev) => {
				ev.stopPropagation();
				var rel = node.getAttribute("data-rel") || "";
				if (!rel) return;
				window.location.href = `/api/fs/download?path=${encodeURIComponent(rel)}`;
			});
		});

		Array.from(el("fsList").querySelectorAll(".fsitem .name")).forEach(
			(node) => {
				node.addEventListener("click", () => {
					var item = node.parentElement;
					var rel = item.getAttribute("data-rel") || "";
					var isDir = (item.getAttribute("data-isdir") || "0") === "1";
					if (isDir) {
						el("fsPath").value = rel;
						fsSelected = "";
						setFsHint("");
						refreshFs();
						return;
					}

					fsSelected = rel;
					setFsHint(`focused: ${rel}`);

					if (/\.(zip|patch|diff)$/i.test(rel)) {
						el("patchPath").value = normalizePatchPath(rel);

						let m = null;
						if (issueRegex) {
							try {
								m = issueRegex.exec(rel);
							} catch (e) {
								m = null;
							}
						}
						if (!m) {
							m = /(?:issue_|#)(\d+)/i.exec(rel) || /(\d{3,6})/.exec(rel);
						}
						if (m && m[1] && !String(el("issueId").value || "").trim()) {
							el("issueId").value = String(m[1]);
						}
						validateAndPreview();
					}

					refreshFs();
				});
			},
		);
	});
}

// Built-in degraded-mode fallbacks live in /static/app_part_fallback.js.

// App parts are loaded by PH_APP_MAIN via PH.loadScript to avoid relying on
// document.write order, and to ensure bootstrap can observe failures.
