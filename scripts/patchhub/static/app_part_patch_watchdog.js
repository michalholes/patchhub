(() => {
	var patchWatchdogWindow = /** @type {Window & typeof globalThis & {
	 *   PH?: {
	 *     register?: function(string, Object): void,
	 *   } | null,
	 *   cfg?: {
	 *     paths?: {
	 *       patches_root?: string,
	 *       upload_dir?: string,
	 *     },
	 *   } | null,
	 * }} */ (window);
	var PH = patchWatchdogWindow.PH || null;
	function phCall(
		/** @type {string} */ name,
		/** @type {unknown[]} */ ...args
	) {
		if (!PH || typeof PH.call !== "function") return undefined;
		return PH.call(name, ...args);
	}
	function isProtectedRerunLatestLifecycleActive() {
		return !!phCall("isProtectedRerunLatestLifecycleActive");
	}
	function getPatchWatchdogConfig() {
		if (patchWatchdogWindow.cfg) return patchWatchdogWindow.cfg;
		if (typeof cfg !== "undefined") {
			return /** @type {{ paths?: { patches_root?: string, upload_dir?: string } } | null} */ (
				cfg
			);
		}
		return null;
	}
	var patchStatInFlight = false;
	var patchStatLastRel = "";
	var patchStatNextDueMs = 0;
	var patchStatIdleBackoffIdx = 0;
	var PATCH_STAT_ACTIVE_MS = 5000;
	/** @type {number[]} */
	var PATCH_STAT_IDLE_BACKOFF_MS = Array.isArray(globalThis.IDLE_BACKOFF_MS)
		? globalThis.IDLE_BACKOFF_MS.slice()
		: [2000, 5000, 15000, 30000, 60000];
	var OUTSIDE_MONITORED_TOP_LEVEL = {
		successful: true,
		unsuccessful: true,
		artifacts: true,
		logs: true,
		workspaces: true,
	};

	function patchesRootRel() {
		var config = getPatchWatchdogConfig();
		var paths = config && config.paths ? config.paths : null;
		var p =
			paths && paths.patches_root ? String(paths.patches_root) : "patches";
		return p.replace(/\\/g, "/").replace(/^\/+/, "").replace(/\/+$/, "");
	}

	function uploadRelUnderPatchesRoot() {
		var config = getPatchWatchdogConfig();
		var paths = config && config.paths ? config.paths : null;
		var uploadDir = paths && paths.upload_dir ? String(paths.upload_dir) : "";
		var value = uploadDir
			.replace(/\\/g, "/")
			.replace(/^\/+/, "")
			.replace(/\/+$/, "");
		var prefix = patchesRootRel();
		if (!value || !prefix) return "";
		if (value === prefix) return "";
		if (value.indexOf(prefix + "/") !== 0) return "";
		return value.slice(prefix.length + 1);
	}

	function normalizeMissingPatchRel(/** @type {unknown} */ path) {
		var prefix = patchesRootRel();
		var value = String(path || "")
			.trim()
			.replace(/\\/g, "/")
			.replace(/^\/+/, "")
			.replace(/\/+$/, "");
		if (!value) return "";
		if (prefix && value === prefix) return "";
		if (prefix && value.indexOf(prefix + "/") === 0) {
			return value.slice(prefix.length + 1);
		}
		return value;
	}

	function isDirectChildFile(
		/** @type {unknown} */ rel,
		/** @type {unknown} */ prefix,
	) {
		var value = normalizeMissingPatchRel(rel);
		var base = normalizeMissingPatchRel(prefix);
		var remainder = value;
		if (!value) return false;
		if (base) {
			if (value.indexOf(base + "/") !== 0) return false;
			remainder = value.slice(base.length + 1);
		}
		return !!remainder && remainder.indexOf("/") < 0;
	}

	/** @param {unknown} rel */
	function isInventoryMonitoredPatchRel(rel) {
		var value = normalizeMissingPatchRel(rel);
		var topLevel = "";
		if (!value) return false;
		topLevel = value.split("/", 1)[0] || "";
		if (
			OUTSIDE_MONITORED_TOP_LEVEL[
				/** @type {keyof typeof OUTSIDE_MONITORED_TOP_LEVEL} */ (topLevel)
			]
		)
			return false;
		if (isDirectChildFile(value, "")) return true;
		return isDirectChildFile(value, uploadRelUnderPatchesRoot());
	}

	function resetMissingPatchState() {
		patchStatLastRel = "";
		patchStatNextDueMs = 0;
		patchStatIdleBackoffIdx = 0;
	}

	function clearRunFieldsBecauseMissingPatch() {
		if (isProtectedRerunLatestLifecycleActive()) return;
		resetMissingPatchState();
		if (el("issueId")) el("issueId").value = "";
		if (el("commitMsg")) el("commitMsg").value = "";
		if (el("patchPath")) el("patchPath").value = "";
		validateAndPreview();
	}

	function getMissingPatchRel() {
		var patchNode = el("patchPath");
		var rel = "";
		if (!patchNode) return "";
		rel = normalizeMissingPatchRel(String(patchNode.value || ""));
		if (!rel) {
			resetMissingPatchState();
			return "";
		}
		if (!isInventoryMonitoredPatchRel(rel)) {
			resetMissingPatchState();
			return "";
		}
		return rel;
	}

	function nextMissingPatchDelayMs(
		/** @type {string} */ mode,
		/** @type {boolean} */ changedRel,
	) {
		var idx = 0;
		var delay = 0;
		if (mode === "active") return PATCH_STAT_ACTIVE_MS;
		if (changedRel) patchStatIdleBackoffIdx = 0;
		idx = patchStatIdleBackoffIdx;
		delay =
			PATCH_STAT_IDLE_BACKOFF_MS[idx] || PATCH_STAT_IDLE_BACKOFF_MS[0] || 2000;
		if (patchStatIdleBackoffIdx < PATCH_STAT_IDLE_BACKOFF_MS.length - 1) {
			patchStatIdleBackoffIdx += 1;
		}
		return delay;
	}

	function syncMissingPatchStateAfterResponse(
		/** @type {string} */ requestRel,
	) {
		var currentRel = "";
		if (isProtectedRerunLatestLifecycleActive()) {
			patchStatNextDueMs = 0;
			return "";
		}
		currentRel = getMissingPatchRel();
		if (!currentRel) {
			patchStatNextDueMs = 0;
			return "";
		}
		if (currentRel !== requestRel) {
			patchStatLastRel = currentRel;
			patchStatNextDueMs = 0;
			patchStatIdleBackoffIdx = 0;
			return "";
		}
		return currentRel;
	}

	function tickMissingPatchClear(
		/** @type {{ mode?: string, force?: boolean } | null | undefined} */ opts,
	) {
		var rel = "";
		var requestRel = "";
		var mode = "idle";
		var changedRel = false;
		var now = 0;
		opts = opts || {};
		if (isProtectedRerunLatestLifecycleActive()) return;
		rel = getMissingPatchRel();
		if (!rel) return;
		mode = String(opts.mode || "idle");
		changedRel = rel !== patchStatLastRel;
		if (patchStatInFlight) {
			patchStatLastRel = rel;
			return;
		}
		now = Date.now();
		if (
			!opts.force &&
			!changedRel &&
			patchStatNextDueMs &&
			now < patchStatNextDueMs
		) {
			return;
		}
		patchStatLastRel = rel;
		requestRel = rel;
		patchStatInFlight = true;
		apiGet(`/api/fs/stat?path=${encodeURIComponent(requestRel)}`)
			.then((response) => {
				var statResp = /** @type {{ ok?: boolean, exists?: boolean }} */ (
					response
				);
				var currentRel = "";
				patchStatInFlight = false;
				currentRel = syncMissingPatchStateAfterResponse(requestRel);
				if (statResp && statResp.ok !== false && statResp.exists === false) {
					if (currentRel === requestRel) {
						clearRunFieldsBecauseMissingPatch();
					}
					return;
				}
				if (currentRel === requestRel) {
					patchStatNextDueMs =
						Date.now() + nextMissingPatchDelayMs(mode, changedRel);
				}
			})
			.catch(() => {
				var currentRel = "";
				patchStatInFlight = false;
				currentRel = syncMissingPatchStateAfterResponse(requestRel);
				if (currentRel === requestRel) {
					patchStatNextDueMs =
						Date.now() + nextMissingPatchDelayMs(mode, changedRel);
				}
			});
	}

	if (PH && typeof PH.register === "function") {
		PH.register("app_part_patch_watchdog", {
			isInventoryMonitoredPatchRel: isInventoryMonitoredPatchRel,
			resetMissingPatchState: resetMissingPatchState,
			tickMissingPatchClear: tickMissingPatchClear,
		});
	}
})();
