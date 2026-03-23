(() => {
	/**
	 * @typedef {{
	 *   jobs?: string,
	 *   runs?: string,
	 *   patches?: string,
	 *   workspaces?: string,
	 *   header?: string,
	 *   operator_info?: string,
	 *   snapshot?: string,
	 * }} OverviewSigs
	 * @typedef {{
	 *   filename_pattern?: string,
	 *   keep_count?: number,
	 *   matched_count?: number,
	 *   deleted_count?: number,
	 * }} CleanupRecentStatusRule
	 * @typedef {{
	 *   job_id?: string,
	 *   issue_id?: string,
	 *   created_utc?: string,
	 *   deleted_count?: number,
	 *   rules?: CleanupRecentStatusRule[],
	 *   summary_text?: string,
	 * }} CleanupRecentStatusItem
	 * @typedef {{
	 *   cleanup_recent_status?: CleanupRecentStatusItem[],
	 * }} OperatorInfoSnapshot
	 * @typedef {{
	 *   jobs?: Array<Object>,
	 *   runs?: Array<Object>,
	 *   patches?: Array<Object>,
	 *   workspaces?: Array<Object>,
	 *   header?: Object,
	 *   operator_info?: OperatorInfoSnapshot,
	 * }} OverviewSnapshot
	 * @typedef {{
	 *   call?: function(string, ...*): *,
	 *   register?: function(string, Object): void,
	 * }} PatchHubRuntime
	 * @typedef {Window & typeof globalThis & {
	 *   PH?: PatchHubRuntime | null,
	 *   refreshOverviewSnapshot?: function(Object=): Promise<Object>,
	 *   ensureSnapshotEvents?: function(): void,
	 *   stopSnapshotEvents?: function(): void,
	 *   snapshotEventsNeedPolling?: function(): boolean,
	 * }} PatchHubWindow
	 */

	/** @type {PatchHubWindow} */
	var snapshotEventsWindow = window;
	/** @type {PatchHubRuntime | null} */
	var snapshotEventsRuntime = window.PH || null;
	var snapshotEventsSource = null;

	function phCall(name, ...args) {
		if (
			!snapshotEventsRuntime ||
			typeof snapshotEventsRuntime.call !== "function"
		)
			return undefined;
		return snapshotEventsRuntime.call(name, ...args);
	}
	var snapshotEventsHealthy = false;
	var snapshotSeenSeq = 0;
	var snapshotAppliedSeq = 0;
	var overviewSnapshotCache = null;

	function updateSnapshotEventSigs(payload) {
		var sigs = (payload && payload.sigs) || {};
		var snapSig = String(sigs.snapshot || "");
		if (snapSig) idleSigs.snapshot = snapSig;
		var js = String(sigs.jobs || "");
		var rs = String(sigs.runs || "");
		var ps = String(sigs.patches || "");
		var ws = String(sigs.workspaces || "");
		var hs = String(sigs.header || "");
		var os = String(sigs.operator_info || "");
		if (js) idleSigs.jobs = js;
		if (rs) idleSigs.runs = rs;
		if (ps) idleSigs.patches = ps;
		if (ws) idleSigs.workspaces = ws;
		if (hs) idleSigs.hdr = hs;
		if (os) idleSigs.operator_info = os;
	}

	function snapshotEventOperatorInfoChanged(payload) {
		var sigs = (payload && payload.sigs) || {};
		var nextSig = String(sigs.operator_info || "");
		if (!nextSig) return false;
		return nextSig !== String(idleSigs.operator_info || "");
	}

	function handleSnapshotEventPayload(payload) {
		var seq = Number((payload && payload.seq) || 0);
		if (!Number.isNaN(seq) && seq <= snapshotSeenSeq) return false;
		if (!Number.isNaN(seq)) snapshotSeenSeq = seq;
		updateSnapshotEventSigs(payload);
		return true;
	}

	function overviewHeaderBaseLabel() {
		if (cfg && cfg.server && cfg.server.host && cfg.server.port) {
			return "server: " + cfg.server.host + ":" + cfg.server.port;
		}
		return "";
	}

	function cloneOverviewSnapshot(snapshot) {
		if (!snapshot) return null;
		return {
			jobs: Array.isArray(snapshot.jobs)
				? snapshot.jobs.map((x) => ({ ...x }))
				: [],
			runs: Array.isArray(snapshot.runs)
				? snapshot.runs.map((x) => ({ ...x }))
				: [],
			patches: Array.isArray(snapshot.patches)
				? snapshot.patches.map((x) => ({ ...x }))
				: [],
			workspaces: Array.isArray(snapshot.workspaces)
				? snapshot.workspaces.map((x) => ({ ...x }))
				: [],
			header: snapshot.header ? { ...snapshot.header } : {},
			operator_info: snapshot.operator_info
				? { ...snapshot.operator_info }
				: { cleanup_recent_status: [] },
		};
	}

	function applyOverviewSnapshotData(snapshot, sigs, seq) {
		snapshot = snapshot || {};
		overviewSnapshotCache = cloneOverviewSnapshot(snapshot);
		updateSnapshotEventSigs({ sigs: sigs || {} });
		if (typeof setOperatorInfoSnapshot === "function") {
			setOperatorInfoSnapshot(snapshot.operator_info || {});
		}
		phCall("renderJobsFromResponse", { ok: true, jobs: snapshot.jobs || [] });
		phCall("renderRunsFromResponse", { ok: true, runs: snapshot.runs || [] });
		phCall("renderPatchesFromResponse", {
			ok: true,
			items: snapshot.patches || [],
		});
		phCall("renderWorkspacesFromResponse", {
			ok: true,
			items: snapshot.workspaces || [],
		});
		phCall(
			"renderHeaderFromSummary",
			snapshot.header || {},
			overviewHeaderBaseLabel(),
		);
		seq = Number(seq || 0);
		if (!Number.isNaN(seq) && seq > 0) {
			snapshotAppliedSeq = seq;
			if (seq > snapshotSeenSeq) snapshotSeenSeq = seq;
		}
	}

	function overviewJobKey(item) {
		return String((item && item.job_id) || "");
	}

	function overviewRunKey(item) {
		return (
			String((item && item.issue_id) || "") +
			"|" +
			String((item && item.mtime_utc) || "")
		);
	}

	function overviewPatchKey(item) {
		return String((item && item.stored_rel_path) || "");
	}

	function overviewWorkspaceKey(item) {
		return (
			String((item && item.issue_id) || "") +
			"|" +
			String((item && item.workspace_rel_path) || "")
		);
	}

	function applyDeltaOrder(items, keyFn, orderedKeys) {
		if (!Array.isArray(orderedKeys) || !orderedKeys.length) return items;
		var pending = new Map();
		items.forEach((item) => {
			pending.set(keyFn(item), { ...item });
		});
		var ordered = [];
		orderedKeys.forEach((key) => {
			var item = pending.get(String(key || ""));
			if (!item) return;
			ordered.push(item);
			pending.delete(String(key || ""));
		});
		pending.forEach((item) => {
			ordered.push(item);
		});
		return ordered;
	}

	function mergeDeltaItems(before, delta, keyFn) {
		delta = delta || {};
		var items = Array.isArray(before) ? before.map((x) => ({ ...x })) : [];
		var index = new Map();
		items.forEach((item, idx) => {
			index.set(keyFn(item), idx);
		});

		(delta.removed || []).forEach((item) => {
			var key = keyFn(item);
			if (!index.has(key)) return;
			var idx = index.get(key);
			items.splice(idx, 1);
			index = new Map();
			items.forEach((nextItem, nextIdx) => {
				index.set(keyFn(nextItem), nextIdx);
			});
		});

		(delta.updated || []).forEach((item) => {
			var key = keyFn(item);
			if (!index.has(key)) return;
			items[index.get(key)] = { ...item };
		});

		(delta.added || []).forEach((item) => {
			var key = keyFn(item);
			if (index.has(key)) {
				items[index.get(key)] = { ...item };
				return;
			}
			items.push({ ...item });
		});
		return applyDeltaOrder(items, keyFn, delta.ordered_keys);
	}

	function applyOverviewDelta(delta) {
		if (!overviewSnapshotCache) return false;
		if (!delta || delta.ok === false) return false;
		if (delta.resync_needed) return false;
		var next = cloneOverviewSnapshot(overviewSnapshotCache) || {
			jobs: [],
			runs: [],
			patches: [],
			workspaces: [],
			header: {},
			operator_info: { cleanup_recent_status: [] },
		};
		next.jobs = mergeDeltaItems(next.jobs, delta.jobs || {}, overviewJobKey);
		next.runs = mergeDeltaItems(next.runs, delta.runs || {}, overviewRunKey);
		next.patches = mergeDeltaItems(
			next.patches,
			delta.patches || {},
			overviewPatchKey,
		);
		next.workspaces = mergeDeltaItems(
			next.workspaces,
			delta.workspaces || {},
			overviewWorkspaceKey,
		);
		if (delta.header_changed) {
			next.header = delta.header ? { ...delta.header } : {};
		}
		applyOverviewSnapshotData(next, delta.sigs || {}, delta && delta.seq);
		return true;
	}

	function fetchOverviewDelta() {
		if (!snapshotAppliedSeq) {
			return Promise.resolve({ ok: true, resync_needed: true, seq: 0 });
		}
		return apiGet(
			"/api/ui_snapshot_delta?since_seq=" +
				encodeURIComponent(String(snapshotAppliedSeq)),
		);
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
		}).then((r) => {
			if (!r || r.ok === false) return { changed: false };
			if (r.unchanged) return { changed: false };
			applyOverviewSnapshotData(r.snapshot || {}, r.sigs || {}, r.seq);
			return { changed: true };
		});
	}

	function stopSnapshotEvents() {
		if (snapshotEventsSource) {
			try {
				snapshotEventsSource.close();
			} catch (_) {}
		}
		snapshotEventsSource = null;
		snapshotEventsHealthy = false;
	}

	function openSnapshotEvents() {
		var PH = snapshotEventsRuntime;
		if (
			snapshotEventsSource ||
			PH.call("hasTrackedActiveJob") ||
			document.hidden
		)
			return;
		if (typeof EventSource !== "function") {
			snapshotEventsHealthy = false;
			return;
		}
		snapshotEventsHealthy = false;
		var es = new EventSource("/api/events");
		snapshotEventsSource = es;
		es.addEventListener("snapshot_state", (ev) => {
			var payload = null;
			try {
				payload = JSON.parse(String(ev.data || "{}"));
			} catch (_) {
				return;
			}
			handleSnapshotEventPayload(payload);
			snapshotEventsHealthy = true;
		});
		es.addEventListener("snapshot_changed", (ev) => {
			var payload = null;
			try {
				payload = JSON.parse(String(ev.data || "{}"));
			} catch (_) {
				return;
			}
			var operatorInfoChanged = snapshotEventOperatorInfoChanged(payload);
			if (!handleSnapshotEventPayload(payload)) return;
			snapshotEventsHealthy = true;
			if (operatorInfoChanged) {
				refreshOverviewSnapshot({ mode: "latest" }).catch((e) => {
					setUiError(e);
				});
				return;
			}
			fetchOverviewDelta()
				.then((delta) => {
					if (!applyOverviewDelta(delta)) {
						return refreshOverviewSnapshot({ mode: "latest" });
					}
					return { changed: true };
				})
				.catch((e) => {
					setUiError(e);
					return refreshOverviewSnapshot({ mode: "latest" });
				})
				.catch((e) => {
					setUiError(e);
				});
		});
		es.onerror = () => {
			stopSnapshotEvents();
		};
	}

	function ensureSnapshotEvents() {
		if (
			snapshotEventsRuntime &&
			snapshotEventsRuntime.call("hasTrackedActiveJob")
		) {
			stopSnapshotEvents();
			return;
		}
		if (!snapshotEventsSource) {
			openSnapshotEvents();
		}
	}

	function snapshotEventsNeedPolling() {
		return !snapshotEventsHealthy;
	}

	snapshotEventsWindow.refreshOverviewSnapshot = refreshOverviewSnapshot;
	snapshotEventsWindow.ensureSnapshotEvents = ensureSnapshotEvents;
	snapshotEventsWindow.stopSnapshotEvents = stopSnapshotEvents;
	snapshotEventsWindow.snapshotEventsNeedPolling = snapshotEventsNeedPolling;

	if (
		snapshotEventsRuntime &&
		typeof snapshotEventsRuntime.register === "function"
	) {
		const PH = snapshotEventsRuntime;
		PH.register("app_part_snapshot_events", {
			refreshOverviewSnapshot,
			ensureSnapshotEvents,
			stopSnapshotEvents,
			snapshotEventsNeedPolling,
		});
	}
})();
