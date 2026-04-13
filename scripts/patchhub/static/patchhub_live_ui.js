(() => {
	/**
	 * @typedef {{
	 *   type?: string,
	 *   msg?: string,
	 *   kind?: string,
	 *   stage?: string,
	 *   ch?: string,
	 *   sev?: string,
	 *   summary?: boolean,
	 *   bypass?: boolean,
	 *   stdout?: string,
	 *   stderr?: string,
	 *   ok?: boolean,
	 *   event?: string,
	 *   status?: string,
	 *   reason?: string,
	 *   job_id?: string,
	 *   runner_mode?: string,
	 *   issue_id?: string,
	 *   protocol?: string,
	 *   data?: unknown,
	 *   cmd?: string,
	 *   cmd_id?: string,
	 * }} PatchhubLiveEvent
	 */
	/**
	 * @typedef {{
	 *   jobId: string,
	 *   status: string,
	 *   reason: string,
	 * }} PatchhubLiveTerminalInfo
	 */
	/**
	 * @typedef {{
	 *   mode: string,
	 *   issue_id: string,
	 * }} PatchhubTrackedFallbackMeta
	 */
	/**
	 * @typedef {{
	 *   kind: string,
	 *   msg: string,
	 * }} PatchhubBufferedStageLine
	 */
	/**
	 * @typedef {Record<string, PatchhubBufferedStageLine[]>} PatchhubStageBufferMap
	 */
	var w = /** @type {any} */ (window);
	var ui = w.AMP_PATCHHUB_UI;
	if (!ui) {
		ui = {};
		w.AMP_PATCHHUB_UI = ui;
	}

	// Module-local state. Split UI modules must not rely on app.js locals.
	/** @type {string | null} */
	var liveStreamJobId = null;
	/** @type {EventSource | null} */
	var liveES = null;
	/** @type {PatchhubLiveEvent[]} */
	var liveEvents = [];
	var MAX_LIVE_EVENTS = 20000;
	/** @type {ReturnType<typeof setTimeout> | null} */
	var liveRenderTimer = null;
	var liveLevel = "normal";
	var liveAutoscrollEnabled = true;
	/** @type {PatchhubLiveTerminalInfo | null} */
	var liveTerminalInfo = null;
	var patchesVisible = false;
	var workspacesVisible = false;
	var runsVisible = false;
	var jobsVisible = false;
	ui.liveEvents = liveEvents;

	function safeExport(
		/** @type {string} */ name,
		/** @type {(...args: unknown[]) => unknown} */ fn,
	) {
		/** @type {(...args: unknown[]) => unknown} */
		ui[name] = (...args) => {
			try {
				return fn(...args);
			} catch (e) {
				console.error(`PatchHub UI module error in ${name}:`, e);
				return undefined;
			}
		};
	}

	function el(/** @type {string} */ id) {
		return document.getElementById(id);
	}

	function apiGet(/** @type {string} */ path) {
		return fetch(path, { headers: { Accept: "application/json" } }).then((r) =>
			r.text().then((t) => {
				try {
					return JSON.parse(t);
				} catch (e) {
					return { ok: false, error: "bad json", raw: t, status: r.status };
				}
			}),
		);
	}
	function loadLiveJobId() {
		var v = null;
		try {
			v = localStorage.getItem("amp.liveJobId");
		} catch (e) {
			v = null;
		}
		if (!v) return null;
		return String(v);
	}

	function saveLiveJobId(/** @type {unknown} */ jobId) {
		try {
			localStorage.setItem("amp.liveJobId", String(jobId || ""));
		} catch (e) {}
	}

	function loadLiveLevel() {
		var v = null;
		try {
			v = localStorage.getItem("amp.liveLogLevel");
		} catch (e) {
			v = null;
		}
		if (!v) return;
		setLiveLevel(v);
	}

	function syncLiveAutoscrollToggle() {
		var btn = el("liveAutoscrollToggle");
		if (!btn) return;
		btn.classList.toggle("is-on", liveAutoscrollEnabled);
		btn.setAttribute("aria-checked", liveAutoscrollEnabled ? "true" : "false");
		btn.title = liveAutoscrollEnabled ? "Auto-scroll: on" : "Auto-scroll: off";
	}

	function loadLiveAutoscroll() {
		var v = null;
		try {
			v = localStorage.getItem("amp.liveLogAutoscroll");
		} catch (e) {
			v = null;
		}
		if (v === null) {
			syncLiveAutoscrollToggle();
			return;
		}
		setLiveAutoscrollEnabled(v !== "0");
	}

	function getLiveLevel() {
		return liveLevel;
	}

	function getLiveAutoscrollEnabled() {
		return liveAutoscrollEnabled;
	}

	function isDebugHumanLevel() {
		return liveLevel === "debug_human";
	}

	function isDebugRawLevel() {
		return liveLevel === "debug_raw";
	}

	function isDebugLevel() {
		return isDebugHumanLevel() || isDebugRawLevel();
	}

	function setLiveLevel(/** @type {unknown} */ v) {
		var nextLevel = String(v || "").trim();
		if (nextLevel === "debug") nextLevel = "debug_raw";
		if (
			[
				"quiet",
				"normal",
				"warning",
				"verbose",
				"debug_human",
				"debug_raw",
			].indexOf(nextLevel) < 0
		) {
			nextLevel = "normal";
		}
		liveLevel = nextLevel;
		try {
			localStorage.setItem("amp.liveLogLevel", liveLevel);
		} catch (e) {}
		return liveLevel;
	}

	function setLiveAutoscrollEnabled(/** @type {unknown} */ v) {
		liveAutoscrollEnabled = !!v;
		try {
			localStorage.setItem(
				"amp.liveLogAutoscroll",
				liveAutoscrollEnabled ? "1" : "0",
			);
		} catch (e) {}
		syncLiveAutoscrollToggle();
		return liveAutoscrollEnabled;
	}

	function initLiveAutoscrollToggle() {
		var btn = el("liveAutoscrollToggle");
		if (!btn) return;
		syncLiveAutoscrollToggle();
		btn.addEventListener("click", () => {
			setLiveAutoscrollEnabled(!liveAutoscrollEnabled);
			if (liveAutoscrollEnabled) renderLiveLog();
		});
	}

	function loadUiVisibility() {
		var v = null;
		try {
			v = localStorage.getItem("amp.ui.patchesVisible");
		} catch (e) {
			v = null;
		}
		if (v === "1") patchesVisible = true;
		else if (v === "0") patchesVisible = false;

		v = null;
		try {
			v = localStorage.getItem("amp.ui.workspacesVisible");
		} catch (e) {
			v = null;
		}
		if (v === "1") workspacesVisible = true;
		else if (v === "0") workspacesVisible = false;

		v = null;
		try {
			v = localStorage.getItem("amp.ui.runsVisible");
		} catch (e) {
			v = null;
		}
		if (v === "1") runsVisible = true;
		else if (v === "0") runsVisible = false;

		v = null;
		try {
			v = localStorage.getItem("amp.ui.jobsVisible");
		} catch (e) {
			v = null;
		}
		if (v === "1") jobsVisible = true;
		else if (v === "0") jobsVisible = false;

		setPatchesVisible(patchesVisible);
		setWorkspacesVisible(workspacesVisible);
		setRunsVisible(runsVisible);
		setJobsVisible(jobsVisible);
		return {
			patchesVisible: patchesVisible,
			workspacesVisible: workspacesVisible,
			runsVisible: runsVisible,
			jobsVisible: jobsVisible,
		};
	}

	function savePatchesVisible(/** @type {unknown} */ v) {
		try {
			localStorage.setItem("amp.ui.patchesVisible", v ? "1" : "0");
		} catch (e) {}
	}

	function saveWorkspacesVisible(/** @type {unknown} */ v) {
		try {
			localStorage.setItem("amp.ui.workspacesVisible", v ? "1" : "0");
		} catch (e) {}
	}

	function saveRunsVisible(/** @type {unknown} */ v) {
		try {
			localStorage.setItem("amp.ui.runsVisible", v ? "1" : "0");
		} catch (e) {}
	}

	function saveJobsVisible(/** @type {unknown} */ v) {
		try {
			localStorage.setItem("amp.ui.jobsVisible", v ? "1" : "0");
		} catch (e) {}
	}

	function setPatchesVisible(/** @type {unknown} */ v) {
		patchesVisible = !!v;
		var wrap = el("patchesWrap");
		var btn = el("patchesCollapse");
		if (wrap) wrap.classList.toggle("hidden", !patchesVisible);
		if (btn) btn.textContent = patchesVisible ? "Hide" : "Show";
	}

	function setWorkspacesVisible(/** @type {unknown} */ v) {
		workspacesVisible = !!v;
		var wrap = el("workspacesWrap");
		var btn = el("workspacesCollapse");
		if (wrap) wrap.classList.toggle("hidden", !workspacesVisible);
		if (btn) btn.textContent = workspacesVisible ? "Hide" : "Show";
	}

	function setRunsVisible(/** @type {unknown} */ v) {
		runsVisible = !!v;
		var wrap = el("runsWrap");
		var btn = el("runsCollapse");
		if (wrap) wrap.classList.toggle("hidden", !runsVisible);
		if (btn) btn.textContent = runsVisible ? "Hide" : "Show";
	}

	function setJobsVisible(/** @type {unknown} */ v) {
		jobsVisible = !!v;
		var wrap = el("jobsWrap");
		var btn = el("jobsCollapse");
		if (wrap) wrap.classList.toggle("hidden", !jobsVisible);
		if (btn) btn.textContent = jobsVisible ? "Hide" : "Show";
	}

	function setLiveStreamStatus(/** @type {unknown} */ text) {
		var box = el("liveStreamStatus");
		if (!box) return;
		box.textContent = String(text || "");
	}

	function getLiveJobId() {
		// Self-contained: do not reference app.js locals (separate module scope).
		var v = loadLiveJobId();
		if (v) return v;
		return null;
	}

	function isNonTerminalJobStatus(/** @type {unknown} */ status) {
		var statusText = String(status || "")
			.trim()
			.toLowerCase();
		return statusText === "queued" || statusText === "running";
	}

	function getTrackedLiveJobId() {
		var jobId = getLiveJobId();
		if (jobId) return String(jobId);
		if (liveStreamJobId) return String(liveStreamJobId);
		return "";
	}

	/** @param {string} trackedId */
	function hasTrackedLiveContext(trackedId) {
		if (!trackedId) return false;
		if (liveStreamJobId && String(liveStreamJobId) === trackedId) {
			return true;
		}
		if (liveES && getTrackedLiveJobId() === trackedId) {
			return true;
		}
		if ((liveEvents || []).length > 0 && getTrackedLiveJobId() === trackedId) {
			return true;
		}
		return String(w.__ph_last_enqueued_job_id || "") === trackedId;
	}

	function deriveTrackedFallbackStatus() {
		for (let i = liveEvents.length - 1; i >= 0; i--) {
			const ev = liveEvents[i];
			if (!ev || typeof ev !== "object") continue;
			if (String(ev.type || "") === "control") continue;
			if (
				String(ev.type || "") === "log" &&
				String(ev.msg || "")
					.trim()
					.toLowerCase() === "queued"
			) {
				return "queued";
			}
			return "running";
		}
		return "queued";
	}

	function deriveTrackedFallbackMeta() {
		/** @type {PatchhubTrackedFallbackMeta} */
		var meta = { mode: "", issue_id: "" };
		for (let i = 0; i < liveEvents.length; i++) {
			const ev = liveEvents[i];
			if (!ev || typeof ev !== "object") continue;
			if (String(ev.type || "") !== "hello") continue;
			meta.mode = String(ev.runner_mode || "");
			meta.issue_id = String(ev.issue_id || "");
			break;
		}
		if (!meta.mode) {
			meta.mode = String(w.__ph_last_enqueued_mode || "");
		}
		return meta;
	}

	function getTrackedActiveJob(/** @type {PatchhubJob[] | unknown} */ jobs) {
		var trackedId = getTrackedLiveJobId();
		var match = null;
		var fallbackMeta = null;
		if (!trackedId) return null;
		if (
			liveTerminalInfo &&
			String(liveTerminalInfo.jobId || "") === trackedId
		) {
			return null;
		}
		if (Array.isArray(jobs) && jobs.length) {
			match = jobs.find((job) => String(job.job_id || "") === trackedId);
			if (match) {
				return isNonTerminalJobStatus(match.status) ? match : null;
			}
		}
		if (!hasTrackedLiveContext(trackedId)) {
			return null;
		}
		fallbackMeta = deriveTrackedFallbackMeta();
		return {
			job_id: trackedId,
			status: deriveTrackedFallbackStatus(),
			mode: fallbackMeta.mode,
			issue_id: fallbackMeta.issue_id,
		};
	}

	function getTrackedActiveJobId(/** @type {PatchhubJob[] | unknown} */ jobs) {
		var tracked = getTrackedActiveJob(jobs);
		return tracked ? String(tracked.job_id || "") : "";
	}

	function hasTrackedActiveJob(/** @type {PatchhubJob[] | unknown} */ jobs) {
		return !!getTrackedActiveJobId(jobs);
	}

	function rememberTerminalEvent(
		/** @type {unknown} */ jobId,
		/** @type {unknown} */ status,
		/** @type {unknown} */ reason,
	) {
		liveTerminalInfo = {
			jobId: String(jobId || ""),
			status: String(status || ""),
			reason: String(reason || ""),
		};
		liveEvents.push({
			type: "control",
			event: "stream_end",
			job_id: String(jobId || ""),
			status: String(status || ""),
			reason: String(reason || ""),
		});
		if (liveEvents.length > MAX_LIVE_EVENTS) {
			liveEvents.splice(0, liveEvents.length - MAX_LIVE_EVENTS);
		}
		scheduleLiveRender();
	}

	function closeLiveStream() {
		if (liveES) {
			try {
				liveES.close();
			} catch (e) {}
		}
		liveES = null;
		liveStreamJobId = null;
	}

	function isSubprocessKind(/** @type {unknown} */ kind) {
		return kind === "SUBPROCESS_STDOUT" || kind === "SUBPROCESS_STDERR";
	}

	function subprocessLabelFromKind(/** @type {unknown} */ kind) {
		return kind === "SUBPROCESS_STDERR" ? "stderr" : "stdout";
	}

	function formatSubprocessLine(
		/** @type {unknown} */ kind,
		/** @type {unknown} */ message,
	) {
		var label = `[${subprocessLabelFromKind(kind)}]`;
		var payload = String(message || "");
		return payload ? `${label} ${payload}` : label;
	}

	function humanLevelAllowsLogEvent(
		/** @type {PatchhubLiveEvent | null | undefined} */ ev,
	) {
		if (!ev) return false;
		if (ev.bypass === true) return true;

		var ch = String(ev.ch || "");
		var sev = String(ev.sev || "");
		var kind = String(ev.kind || "");
		var summary = ev.summary === true;

		if (summary || sev === "ERROR") return true;
		if (liveLevel === "quiet") return false;
		if (ch === "CORE") return true;
		if (liveLevel === "normal") return false;
		if (liveLevel === "warning") {
			return ch === "DETAIL" && sev === "WARNING";
		}
		if (liveLevel === "verbose") {
			if (isSubprocessKind(kind)) return true;
			if (ch !== "DETAIL") return false;
			return sev === "WARNING" || sev === "INFO";
		}
		return false;
	}

	function filterLiveEvent(
		/** @type {PatchhubLiveEvent | null | undefined} */ ev,
	) {
		if (!ev) return false;
		if (isDebugLevel()) return true;
		var t = String(ev.type || "");
		if (t === "result") return true;
		if (t !== "log") return false;
		return humanLevelAllowsLogEvent(ev);
	}

	function compactJson(/** @type {unknown} */ value) {
		try {
			return JSON.stringify(value);
		} catch (e) {
			return "{}";
		}
	}

	function formatHumanLogEvent(/** @type {PatchhubLiveEvent} */ ev) {
		var line = String(ev.msg || "");
		if (!line) {
			line = `JSON ${compactJson(ev)}`;
		}
		if (isSubprocessKind(String(ev.kind || ""))) {
			line = formatSubprocessLine(String(ev.kind || ""), ev.msg);
		}
		if (ev.stdout || ev.stderr) {
			const out = [line];
			if (ev.stdout) out.push(`STDOUT:\n${String(ev.stdout)}`);
			if (ev.stderr) out.push(`STDERR:\n${String(ev.stderr)}`);
			return out.join("\n");
		}
		return line;
	}

	function normalizeEventStage(/** @type {unknown} */ stage) {
		return String(stage || "")
			.replace(/\s+/g, " ")
			.trim();
	}

	function stageBufferKey(
		/** @type {PatchhubLiveEvent | null | undefined} */ ev,
	) {
		var stage = normalizeEventStage(ev && ev.stage);
		return stage || "__NO_STAGE__";
	}

	function isFailedStepOutputEvent(
		/** @type {PatchhubLiveEvent | null | undefined} */ ev,
	) {
		return String((ev && ev.msg) || "").trim() === "FAILED STEP OUTPUT";
	}

	function takeBufferedStageLines(
		/** @type {PatchhubStageBufferMap} */ buffers,
		/** @type {string} */ key,
	) {
		var items = Array.isArray(buffers[key]) ? buffers[key].slice() : [];
		delete buffers[key];
		return items;
	}

	function formatFailureDetailEvent(
		/** @type {PatchhubLiveEvent} */ ev,
		/** @type {PatchhubStageBufferMap} */ stageBuffers,
	) {
		var key = stageBufferKey(ev);
		var grouped = takeBufferedStageLines(stageBuffers, key);
		if (liveLevel === "verbose" && grouped.length > 0) {
			return "";
		}
		if (grouped.length > 0 && !(ev.stdout || ev.stderr)) {
			const lines = [String(ev.msg || "FAILED STEP OUTPUT")];
			for (let i = 0; i < grouped.length; i++) {
				lines.push(formatSubprocessLine(grouped[i].kind, grouped[i].msg));
			}
			return lines.join("\n");
		}
		return formatHumanLogEvent(ev);
	}

	function formatLiveEvent(/** @type {PatchhubLiveEvent} */ ev) {
		if (isDebugRawLevel()) return compactJson(ev);

		var t = String(ev.type || "");
		if (t === "hello") {
			return (
				`HELLO protocol=${String(ev.protocol || "")} ` +
				`mode=${String(ev.runner_mode || "")} ` +
				`issue=${String(ev.issue_id || "")}`
			);
		}
		if (t === "result") {
			return ev.ok ? "RESULT: SUCCESS" : "RESULT: FAIL";
		}
		if (t === "reply") {
			const replyData =
				ev.data && typeof ev.data === "object" ? compactJson(ev.data) : "{}";
			return (
				`REPLY cmd=${String(ev.cmd || "")} ` +
				`cmd_id=${String(ev.cmd_id || "")} ` +
				`ok=${String(ev.ok === true)} data=${replyData}`
			);
		}
		if (t === "control") {
			return `CONTROL event=${String(ev.event || "")} ${compactJson(ev)}`;
		}
		return formatHumanLogEvent(ev);
	}

	function renderHumanLiveLines(
		/** @type {PatchhubLiveEvent[] | unknown} */ events,
	) {
		/** @type {string[]} */
		var lines = [];
		/** @type {PatchhubStageBufferMap} */
		var stageBuffers = Object.create(null);
		var list = Array.isArray(events) ? events : [];
		for (let i = 0; i < list.length; i++) {
			const ev = list[i];
			if (!ev || typeof ev !== "object") continue;
			const t = String(ev.type || "");
			if (t === "result") {
				lines.push(formatLiveEvent(ev));
				continue;
			}
			if (t !== "log") continue;
			const kind = String(ev.kind || "");
			if (isSubprocessKind(kind)) {
				const key = stageBufferKey(ev);
				if (!Array.isArray(stageBuffers[key])) {
					stageBuffers[key] = [];
				}
				stageBuffers[key].push({
					kind: kind,
					msg: String(ev.msg || ""),
				});
				if (liveLevel === "verbose") {
					lines.push(formatSubprocessLine(kind, ev.msg));
				}
				continue;
			}
			if (!humanLevelAllowsLogEvent(ev)) continue;
			if (isFailedStepOutputEvent(ev)) {
				const failureText = formatFailureDetailEvent(ev, stageBuffers);
				if (failureText) lines.push(failureText);
				continue;
			}
			lines.push(formatHumanLogEvent(ev));
		}
		return lines;
	}

	function renderLiveLog() {
		var box = el("liveLog");
		if (!box) return;
		var lines = [];
		var prevScrollTop = box.scrollTop;
		if (isDebugLevel()) {
			for (let i = 0; i < liveEvents.length; i++) {
				const ev = liveEvents[i];
				if (!filterLiveEvent(ev)) continue;
				lines.push(formatLiveEvent(ev));
			}
		} else {
			lines = renderHumanLiveLines(liveEvents);
		}
		box.textContent = lines.join("\n");
		if (liveAutoscrollEnabled) box.scrollTop = box.scrollHeight;
		else box.scrollTop = prevScrollTop;
		var wrap = box.parentElement;
		if (wrap && wrap.classList && wrap.classList.contains("card-tight")) {
			// no-op
		}
	}

	function scheduleLiveRender() {
		if (liveRenderTimer) return;
		liveRenderTimer = setTimeout(() => {
			liveRenderTimer = null;
			renderLiveLog();
			if (ui.updateProgressPanelFromEvents) ui.updateProgressPanelFromEvents();
		}, 50);
	}

	function getLiveLogRenderedText() {
		var box = el("liveLog");
		return box ? String(box.textContent || "") : "";
	}

	function getLiveLogSelectedText() {
		var box = el("liveLog");
		if (!box || typeof window.getSelection !== "function") return "";
		var sel = window.getSelection();
		if (!sel || !sel.rangeCount) return "";
		var text = String(sel.toString() || "");
		if (!text) return "";
		var range = sel.getRangeAt(0);
		var node =
			range && range.commonAncestorContainer
				? range.commonAncestorContainer
				: null;
		if (node && node.nodeType === 3) node = node.parentNode;
		while (node) {
			if (node === box) return text;
			node = node.parentNode;
		}
		return "";
	}

	function copyLiveTextExecCommand(/** @type {string} */ payload) {
		return new Promise((resolve, reject) => {
			var ta = null;
			var ok = false;
			try {
				if (!document || !document.body || !document.createElement) {
					reject(new Error("clipboard unavailable"));
					return;
				}
				ta = document.createElement("textarea");
				ta.value = payload;
				ta.setAttribute("readonly", "true");
				ta.style.position = "absolute";
				ta.style.left = "-9999px";
				document.body.appendChild(ta);
				ta.select();
				ok = document.execCommand && document.execCommand("copy");
				document.body.removeChild(ta);
				ta = null;
				if (ok) {
					resolve(payload);
					return;
				}
				reject(new Error("execCommand(copy) returned false"));
			} catch (e) {
				if (ta) {
					try {
						document.body.removeChild(ta);
					} catch (removeErr) {
						console.error("PatchHub live copy cleanup failed:", removeErr);
					}
				}
				reject(e);
			}
		});
	}

	function copyLiveText(/** @type {unknown} */ text) {
		var payload = String(text || "");
		if (!payload) return Promise.resolve("");
		var nav = typeof navigator !== "undefined" ? navigator : null;
		if ((!nav || !nav.clipboard) && window && window.navigator) {
			nav = window.navigator;
		}
		if (nav && nav.clipboard && nav.clipboard.writeText) {
			return nav.clipboard.writeText(payload).then(
				() => payload,
				() => copyLiveTextExecCommand(payload),
			);
		}
		return copyLiveTextExecCommand(payload);
	}

	function copyLiveSelection() {
		return copyLiveText(getLiveLogSelectedText());
	}

	function copyLiveAll() {
		return copyLiveText(getLiveLogRenderedText());
	}

	function initLiveCopyButtons() {
		var selBtn = el("liveCopySelection");
		if (selBtn) {
			selBtn.addEventListener("click", () => {
				copyLiveSelection()
					.then(() => {
						if (typeof setUiStatus === "function")
							setUiStatus("live log: selection copied");
					})
					.catch((err) => {
						if (typeof setUiError === "function")
							setUiError(String(err || "copy failed"));
					});
			});
		}
		var allBtn = el("liveCopyAll");
		if (allBtn) {
			allBtn.addEventListener("click", () => {
				copyLiveAll()
					.then(() => {
						if (typeof setUiStatus === "function")
							setUiStatus("live log: all copied");
					})
					.catch((err) => {
						if (typeof setUiError === "function")
							setUiError(String(err || "copy failed"));
					});
			});
		}
	}

	function updateProgressFromEvents() {
		var box = el("activeStage");
		if (!box) return;
		for (let i = liveEvents.length - 1; i >= 0; i--) {
			const ev = liveEvents[i];
			if (!ev) continue;
			if (String(ev.type || "") === "result") {
				box.textContent = ev.ok ? "RESULT: SUCCESS" : "RESULT: FAIL";
				return;
			}
			if (String(ev.type || "") === "log") {
				const stage = String(ev.stage || "");
				const kind = String(ev.kind || "");
				if (stage || kind) {
					box.textContent = (stage ? stage : "") + (kind ? ` / ${kind}` : "");
					return;
				}
			}
		}
	}

	function openLiveStream(/** @type {unknown} */ jobId) {
		if (!jobId) {
			closeLiveStream();
			liveEvents = [];
			ui.liveEvents = liveEvents;
			ui.liveEvents = liveEvents;
			renderLiveLog();
			if (ui.updateProgressPanelFromEvents) ui.updateProgressPanelFromEvents();
			setLiveStreamStatus("");
			return;
		}
		var jobIdText = String(jobId);

		if (liveStreamJobId === jobIdText && liveES) return;

		closeLiveStream();
		liveStreamJobId = jobIdText;
		liveTerminalInfo = null;
		liveEvents = [];
		ui.liveEvents = liveEvents;
		renderLiveLog();
		if (ui.updateProgressPanelFromEvents) ui.updateProgressPanelFromEvents();
		setLiveStreamStatus("connecting...");

		var url = `/api/jobs/${encodeURIComponent(jobIdText)}/events`;
		var es = new EventSource(url);
		liveES = es;

		es.onmessage = (e) => {
			if (!e || !e.data) return;
			var obj = null;
			try {
				obj = JSON.parse(String(e.data));
			} catch (err) {
				obj = null;
			}
			if (!obj) return;
			liveEvents.push(obj);
			if (liveEvents.length > MAX_LIVE_EVENTS) {
				liveEvents.splice(0, liveEvents.length - MAX_LIVE_EVENTS);
			}
			scheduleLiveRender();
			setLiveStreamStatus("streaming");
		};

		es.addEventListener("end", (e) => {
			var reason = "";
			var status = "";
			if (e && e.data) {
				try {
					const p = JSON.parse(String(e.data || "{}"));
					if (p && typeof p === "object") {
						reason = String(p.reason || "");
						status = String(p.status || "");
					}
				} catch (err) {}
			}
			rememberTerminalEvent(jobIdText, status, reason);
			var msg = "ended";
			if (status) msg += ` (${status})`;
			if (reason) msg += ` [${reason}]`;
			setLiveStreamStatus(msg);
			try {
				es.close();
			} catch (e2) {}
			if (liveES === es) {
				liveES = null;
			}
			if (ui.updateProgressPanelFromEvents) {
				ui.updateProgressPanelFromEvents({ forceAppliedFilesRetry: true });
			}
		});

		es.onerror = () => {
			apiGet(`/api/jobs/${encodeURIComponent(jobIdText)}`).then((r) => {
				if (!r || r.ok === false) {
					closeLiveStream();
					setLiveStreamStatus("ended [job_not_found]");
					return;
				}
				var j = r.job || {};
				var st = String(j.status || "");
				if (st && !isNonTerminalJobStatus(st)) {
					rememberTerminalEvent(jobIdText, st, "job_completed");
					closeLiveStream();
					setLiveStreamStatus(`ended (${st}) [job_completed]`);
					if (ui.updateProgressPanelFromEvents) {
						ui.updateProgressPanelFromEvents({ forceAppliedFilesRetry: true });
					}
					return;
				}
				setLiveStreamStatus("reconnecting...");
			});
		};
	}

	function jobSummaryCommit(/** @type {unknown} */ msg) {
		var text = String(msg || "")
			.replace(/\s+/g, " ")
			.trim();
		if (!text) return "";
		if (text.length <= 60) return text;
		return `${text.slice(0, 57)}...`;
	}

	function jobSummaryPatchName(/** @type {unknown} */ p) {
		var pathText = String(p || "").trim();
		if (!pathText) return "";
		pathText = pathText.replace(/\\/g, "/");
		var idx = pathText.lastIndexOf("/");
		if (idx >= 0) return pathText.slice(idx + 1);
		return pathText;
	}

	function jobSummaryDurationSeconds(
		/** @type {unknown} */ startUtc,
		/** @type {unknown} */ endUtc,
	) {
		var a = null;
		var b = null;
		var deltaMs = 0;
		if (!startUtc) return "";
		a = new Date(String(startUtc));
		b = endUtc ? new Date(String(endUtc)) : new Date(Date.now());
		if (isNaN(a.getTime()) || isNaN(b.getTime())) return "";
		deltaMs = b.getTime() - a.getTime();
		if (deltaMs < 0) return "";
		if (PH && typeof PH.call === "function") {
			return String(PH.call("formatVisibleDurationMs", deltaMs) || "");
		}
		return String(Math.floor(deltaMs / 1000));
	}

	// Exports
	var PH = w.PH;
	if (PH && typeof PH.register === "function") {
		PH.register("live", {
			loadLiveJobId,
			saveLiveJobId,
			loadLiveLevel,
			loadLiveAutoscroll,
			getLiveLevel,
			setLiveLevel,
			loadUiVisibility,
			savePatchesVisible,
			saveWorkspacesVisible,
			saveRunsVisible,
			saveJobsVisible,
			setPatchesVisible,
			setWorkspacesVisible,
			setRunsVisible,
			setJobsVisible,
			setLiveStreamStatus,
			getLiveJobId,
			isNonTerminalJobStatus,
			getTrackedActiveJob,
			getTrackedActiveJobId,
			hasTrackedActiveJob,
			closeLiveStream,
			renderLiveLog,
			filterLiveEvent,
			formatLiveEvent,
			updateProgressFromEvents,
			openLiveStream,
			jobSummaryCommit,
			jobSummaryPatchName,
			jobSummaryDurationSeconds,
			getLiveLogRenderedText,
			getLiveLogSelectedText,
			copyLiveSelection,
			copyLiveAll,
			initLiveCopyButtons,
			initLiveAutoscrollToggle,
		});
	}
	safeExport("loadLiveJobId", loadLiveJobId);
	safeExport("saveLiveJobId", saveLiveJobId);
	safeExport("loadLiveLevel", loadLiveLevel);
	safeExport("loadLiveAutoscroll", loadLiveAutoscroll);
	safeExport("getLiveLevel", getLiveLevel);
	safeExport("getLiveAutoscrollEnabled", getLiveAutoscrollEnabled);
	safeExport("setLiveLevel", setLiveLevel);
	safeExport("setLiveAutoscrollEnabled", setLiveAutoscrollEnabled);
	safeExport("loadUiVisibility", loadUiVisibility);
	safeExport("savePatchesVisible", savePatchesVisible);
	safeExport("saveWorkspacesVisible", saveWorkspacesVisible);
	safeExport("saveRunsVisible", saveRunsVisible);
	safeExport("saveJobsVisible", saveJobsVisible);
	safeExport("setPatchesVisible", setPatchesVisible);
	safeExport("setWorkspacesVisible", setWorkspacesVisible);
	safeExport("setRunsVisible", setRunsVisible);
	safeExport("setJobsVisible", setJobsVisible);
	safeExport("setLiveStreamStatus", setLiveStreamStatus);
	safeExport("getLiveJobId", getLiveJobId);
	safeExport("isNonTerminalJobStatus", isNonTerminalJobStatus);
	safeExport("getTrackedActiveJob", getTrackedActiveJob);
	safeExport("getTrackedActiveJobId", getTrackedActiveJobId);
	safeExport("hasTrackedActiveJob", hasTrackedActiveJob);
	safeExport("closeLiveStream", closeLiveStream);
	ui.filterLiveEvent = filterLiveEvent;
	ui.formatLiveEvent = formatLiveEvent;
	safeExport("renderLiveLog", renderLiveLog);
	ui.updateProgressFromEvents = updateProgressFromEvents;
	ui.openLiveStream = openLiveStream;
	ui.jobSummaryCommit = jobSummaryCommit;
	ui.jobSummaryPatchName = jobSummaryPatchName;
	ui.jobSummaryDurationSeconds = jobSummaryDurationSeconds;
	safeExport("getLiveLogRenderedText", getLiveLogRenderedText);
	safeExport("getLiveLogSelectedText", getLiveLogSelectedText);
	safeExport("copyLiveSelection", copyLiveSelection);
	safeExport("copyLiveAll", copyLiveAll);
	safeExport("initLiveCopyButtons", initLiveCopyButtons);
	safeExport("initLiveAutoscrollToggle", initLiveAutoscrollToggle);
})();
