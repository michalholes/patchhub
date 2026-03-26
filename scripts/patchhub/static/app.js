// PatchHub app core (refactored split: part files).
/**
 * @typedef {{
 *   loadScript?: function(string, string): Promise<boolean>,
 *   call?: function(string, ...*): *,
 *   has?: function(string): boolean,
 *   register?: function(string, Object): void,
 * }} PatchHubRuntime
 * @typedef {{
 *   filename_pattern?: string, keep_count?: number,
 *   matched_count?: number, deleted_count?: number,
 * }} CleanupRecentStatusRule
 * @typedef {{
 *   job_id?: string, issue_id?: string, created_utc?: string,
 *   deleted_count?: number, rules?: CleanupRecentStatusRule[], summary_text?: string,
 * }} CleanupRecentStatusItem
 * @typedef {{ cleanup_recent_status?: CleanupRecentStatusItem[] }} OperatorInfoSnapshot
 * @typedef {HTMLElement & {
 *   value?: string, disabled?: boolean, checked?: boolean, files?: FileList | null,
 * }} PatchHubUiElement
 * @typedef {Window & typeof globalThis & {
 *   AMP_PATCHHUB_UI?: PatchhubUiBridge,
 *   PH?: PatchHubRuntime | null,
 *   PH_BOOT?: { bootLog?: function(string, string): void },
 *   PH_APP_SHOW_DEGRADED?: function(string): void,
 *   PH_APP_MAIN?: function(PatchHubRuntime): Promise<void>,
 * }} PatchHubWindow
 */
var appWindow = /** @type {PatchHubWindow} */ (window);
/** @type {PatchHubRuntime | null} */
var appPhRuntime = appWindow.PH || null;

appWindow.AMP_PATCHHUB_UI = appWindow.AMP_PATCHHUB_UI || {};
var AMP_UI = /** @type {PatchhubUiBridge} */ (appWindow.AMP_PATCHHUB_UI);

var activeJobId = /** @type {string | null} */ (null);
var autoRefreshTimer = /** @type {ReturnType<typeof setInterval> | null} */ (
	null
);

var UI_STATUS_LIMIT = 20;
var uiStatusLines = /** @type {string[]} */ ([]);
var degradedNotes = /** @type {string[]} */ ([]);
var infoPoolHints = /** @type {PHStrMap} */ ({
	upload: "",
	enqueue: "",
	fs: "",
	parse: "",
});
var infoPoolHintSeq = /** @type {PHNumMap} */ ({
	upload: 0,
	enqueue: 0,
	fs: 0,
	parse: 0,
});
var infoPoolSeq = 0;
/** @type {OperatorInfoSnapshot} */
var backendOperatorInfo = { cleanup_recent_status: [] };

var selectedJobId = /** @type {string | null} */ (null);
var liveStreamJobId = /** @type {string | null} */ (null);
var liveES = /** @type {EventSource | null} */ (null);
var liveEvents = /** @type {unknown[]} */ ([]);
var liveLevel = "normal";

var previewVisible = false;
var patchesVisible = false;
var workspacesVisible = false;
var runsVisible = false;
var jobsVisible = false;
var patchesCache = [];
var workspacesCache = [];

function appLog(/** @type {string} */ kind, /** @type {string} */ message) {
	var msg = String(message || "");
	try {
		if (appWindow.PH_BOOT && typeof appWindow.PH_BOOT.bootLog === "function") {
			appWindow.PH_BOOT.bootLog(kind, msg);
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

function canRenderInfoPoolUi() {
	return !!(
		appPhRuntime &&
		typeof appPhRuntime.has === "function" &&
		appPhRuntime.has("renderInfoPoolUi")
	);
}

function rememberDegraded(/** @type {string} */ message) {
	var msg = String(message || "").trim();
	if (!msg) return;
	if (degradedNotes.indexOf(msg) < 0) degradedNotes.push(msg);
	if (degradedNotes.length > UI_STATUS_LIMIT) {
		degradedNotes.splice(0, degradedNotes.length - UI_STATUS_LIMIT);
	}
	if (canRenderInfoPoolUi()) {
		appPhRuntime.call("renderInfoPoolUi");
		return;
	}
	setLegacyPooledNode("uiDegradedBanner", "DEGRADED MODE: " + msg);
}

appWindow.PH_APP_SHOW_DEGRADED = rememberDegraded;

async function loadParts(/** @type {PatchHubRuntime} */ rt) {
	appPhRuntime = rt;
	var PH = appPhRuntime;
	if (!PH) {
		appLog("error", "PH runtime missing");
		throw new Error("PH runtime missing");
	}
	function noteLoad(/** @type {boolean} */ ok, /** @type {string} */ note) {
		if (!ok) rememberDegraded(note);
		return ok;
	}
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
			"/static/app_part_jobs_revert.js",
			"app_part_jobs_revert",
		),
		"jobs revert module missing",
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
			"/static/app_part_patch_inventory.js",
			"app_part_patch_inventory",
		),
		"patch inventory module missing",
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
			"/static/app_part_patch_watchdog.js",
			"app_part_patch_watchdog",
		),
		"patch watchdog module missing",
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
appWindow.PH_APP_MAIN = async function PH_APP_MAIN(
	/** @type {PatchHubRuntime} */ rt,
) {
	await loadParts(rt);
	var PH = appPhRuntime;
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
var idleSigs = {
	jobs: "",
	runs: "",
	patches: "",
	workspaces: "",
	hdr: "",
	operator_info: "",
	snapshot: "",
};

function setPreviewVisible(/** @type {unknown} */ v) {
	previewVisible = !!v;
	var wrap = el("previewWrapRight");
	var btn1 = el("previewToggle");
	var btn2 = el("previewCollapse");
	if (wrap) wrap.classList.toggle("hidden", !previewVisible);
	var t = previewVisible ? "Hide" : "Show";
	if (btn1) btn1.textContent = previewVisible ? "Hide preview" : "Preview";
	if (btn2) btn2.textContent = t;
}

function isNearBottom(
	/** @type {PHElRef} */ node,
	/** @type {PHNumRef} */ slack,
) {
	if (!node) return true;
	slack = slack == null ? 20 : slack;
	return node.scrollTop + node.clientHeight >= node.scrollHeight - slack;
}

/**
 * @param {string} id
 * @returns {PatchHubUiElement | null}
 */
function el(id) {
	return document.getElementById(id);
}

function normalizeUiStatusLines(/** @type {string} */ message) {
	return String(message || "")
		.split(/\r?\n/)
		.map((line) => line.replace(/\s+/g, " ").trim())
		.filter((line) => !!line);
}

function setLegacyPooledNode(
	/** @type {string} */ id,
	/** @type {string} */ message,
) {
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

/** @returns {OperatorInfoSnapshot} */
function normalizeOperatorInfoSnapshot(/** @type {unknown} */ payload) {
	var info = /** @type {OperatorInfoSnapshot} */ (
		payload && typeof payload === "object" ? payload : {}
	);
	var cleanup = Array.isArray(info.cleanup_recent_status)
		? info.cleanup_recent_status.map(
				(/** @type {CleanupRecentStatusItem} */ item) => ({ ...item }),
			)
		: [];
	return { cleanup_recent_status: cleanup };
}

/** @returns {OperatorInfoSnapshot} */
function getOperatorInfoSnapshot() {
	return normalizeOperatorInfoSnapshot(backendOperatorInfo);
}

function setOperatorInfoSnapshot(/** @type {unknown} */ payload) {
	backendOperatorInfo = normalizeOperatorInfoSnapshot(payload);
	if (canRenderInfoPoolUi()) appPhRuntime.call("renderInfoPoolUi");
}

function setInfoPoolHint(
	/** @type {string} */ source,
	/** @type {string} */ message,
) {
	var key = String(source || "");
	if (!Object.hasOwn(infoPoolHints, key)) return;
	var text = String(message || "").trim();
	infoPoolHints[key] = text;
	infoPoolHintSeq[key] = text ? ++infoPoolSeq : 0;
	if (canRenderInfoPoolUi()) {
		appPhRuntime.call("renderInfoPoolUi");
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
	if (canRenderInfoPoolUi()) {
		appPhRuntime.call("renderInfoPoolUi");
		return;
	}
	var node = el("uiStatusBar");
	if (!node) return;
	node.textContent = uiStatusLines.join("\n");
}

function pushUiStatusLine(/** @type {string} */ message) {
	var lines = normalizeUiStatusLines(message);
	if (!lines.length) return;
	lines.forEach((/** @type {string} */ line) => {
		uiStatusLines.push(line);
	});
	if (uiStatusLines.length > UI_STATUS_LIMIT) {
		uiStatusLines.splice(0, uiStatusLines.length - UI_STATUS_LIMIT);
	}
	renderUiStatusLines();
}

function setUiStatus(/** @type {string} */ message) {
	pushUiStatusLine(message);
}

function setUiError(/** @type {string} */ errorText) {
	pushUiStatusLine(`ERROR: ${String(errorText || "")}`);
}

function pushApiStatus(/** @type {PatchhubStatusPayload} */ payload) {
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

function setPre(/** @type {string} */ id, /** @type {unknown} */ obj) {
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

function setText(/** @type {string} */ id, /** @type {unknown} */ text) {
	var node = el(id);
	if (!node) return;
	node.textContent = String(text || "");
}

function formatLocalTime(/** @type {string | null | undefined} */ isoUtc) {
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

function apiGet(/** @type {string} */ path) {
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

var __phEtagCache = /** @type {PHStrMap} */ ({});
var __phInFlight = /** @type {Record<string, Promise<unknown> | null>} */ ({});
var __phAborters = /** @type {Record<string, AbortController | null>} */ ({});

function apiAbortKey(/** @type {string} */ key) {
	key = String(key || "");
	var ctl = null;
	try {
		ctl = __phAborters[key];
		if (ctl) ctl.abort();
	} catch (_) {}
	__phAborters[key] = null;
	__phInFlight[key] = null;
}

function apiGetETag(
	/** @type {string} */ key,
	/** @type {string} */ path,
	/** @type {PatchhubGetEtagOpts} */ opts,
) {
	key = String(key || "");
	path = String(path || "");
	opts = opts || {};

	// Request policy:
	// - mode="periodic": MUST NOT start a second request if one is in-flight.
	// - mode="user" or "latest": abort prior request (deterministic: latest wins).
	var mode = String((opts && opts.mode) || "latest")
		.trim()
		.toLowerCase();
	var singleFlight = !!(opts && opts.single_flight);

	var cur = __phInFlight[key];
	if (cur && (mode === "periodic" || singleFlight)) return cur;

	if (mode !== "periodic") {
		apiAbortKey(key);
	}

	var ctl = new AbortController();
	__phAborters[key] = ctl;

	var hdr = /** @type {PHStrMap} */ ({ Accept: "application/json" });
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

function apiPost(
	/** @type {string} */ path,
	/** @type {Record<string, unknown>} */ body,
) {
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

function joinRel(/** @type {string} */ a, /** @type {string} */ b) {
	a = String(a || "").replace(/\/+$/, "");
	b = String(b || "").replace(/^\/+/, "");
	if (!a) return b;
	if (!b) return a;
	return `${a}/${b}`;
}

function parentRel(/** @type {string} */ p) {
	p = String(p || "").replace(/\/+$/, "");
	var idx = p.lastIndexOf("/");
	if (idx < 0) return "";
	return p.slice(0, idx);
}

function escapeHtml(/** @type {string} */ s) {
	return String(s || "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

var cfg = /** @type {PatchhubConfig | null} */ (null);
var issueRegex = /** @type {RegExp | null} */ (null);
var fsSelected = "";
var fsChecked = /** @type {Record<string, boolean>} */ ({});
var fsLastRels = /** @type {string[]} */ ([]);
var runsCache = /** @type {unknown[]} */ ([]);
var selectedRun = /** @type {unknown | null} */ (null);
var tailLines = 200;

var dirty = {
	issueId: false,
	commitMsg: false,
	patchPath: false,
	targetRepo: false,
};
var latestToken = "";
var lastAutofillClearedToken = "";
var autofillTimer = /** @type {ReturnType<typeof setTimeout> | null} */ (null);

var suppressIdleOutput = false;

var lastParsedRaw = "";
var lastParsed = /** @type {Record<string, unknown> | null} */ (null);
var parseInFlight = false;
var parseTimer = /** @type {ReturnType<typeof setTimeout> | null} */ (null);
var parseSeq = 0;

function patchesRootRel() {
	var p =
		cfg && cfg.paths && cfg.paths.patches_root
			? String(cfg.paths.patches_root)
			: "patches";
	return p.replace(/\/+$/, "");
}

function stripPatchesPrefix(/** @type {string} */ path) {
	var pfx = patchesRootRel();
	var p = String(path || "").replace(/^\/+/, "");
	if (p === pfx) return "";
	if (p.indexOf(`${pfx}/`) === 0) return p.slice(pfx.length + 1);
	return p;
}

function normalizePatchPath(/** @type {string} */ p) {
	p = String(p || "")
		.trim()
		.replace(/^\/+/, "");
	if (!p) return "";

	var pfx = patchesRootRel();
	if (p === pfx) return pfx;
	if (p.indexOf(`${pfx}/`) === 0) return p;
	return joinRel(pfx, p);
}

function setFsHint(/** @type {string} */ msg) {
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

function setParseHint(/** @type {string} */ msg) {
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

function triggerParse(/** @type {string} */ raw) {
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
	apiPost("/api/parse_command", { raw: raw }).then((resp) => {
		var r = /** @type {PatchhubParseCommandResponse} */ (resp);
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

function scheduleParseDebounced(/** @type {string} */ raw) {
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
	var path = String(el("fsPath").value || "");
	apiGet(`/api/fs/list?path=${encodeURIComponent(path)}`).then((resp) => {
		var r = /** @type {PatchhubFsListResponse} */ (resp);
		if (!r || r.ok === false) {
			setPre("fsList", r);
			return;
		}
		var items = r.items || [];
		fsLastRels = [];
		var html = items
			.map(
				(
					/** @type {{ name?: string, is_dir?: boolean, size?: number }} */ it,
				) => {
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
				},
			)
			.join("");

		el("fsList").innerHTML = html || '<div class="muted">(empty)</div>';
		fsUpdateSelCount();

		Array.from(el("fsList").querySelectorAll(".fsChk")).forEach((node) => {
			var checkbox = /** @type {PatchHubUiElement} */ (node);
			checkbox.addEventListener("click", (ev) => {
				ev.stopPropagation();
				var rel = checkbox.getAttribute("data-rel") || "";
				if (!rel) return;
				if (checkbox.checked === true) {
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
