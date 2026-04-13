(() => {
	/**
	 * @typedef {PatchhubToolkitResolutionRecord} ToolkitResolutionRecord
	 * @typedef {PatchhubPmValidationPayload} PmValidationPayload
	 */

	/** @type {Window & typeof globalThis} */
	var validationWindow = window;
	/** @type {PatchhubUiBridge} */
	var ui = /** @type {PatchhubUiBridge} */ (
		validationWindow.AMP_PATCHHUB_UI || {}
	);
	validationWindow.AMP_PATCHHUB_UI = ui;

	/** @type {PatchhubHeaderRuntime | null} */
	var PH = validationWindow.PH || null;
	/** @type {PmValidationPayload | null} */
	var state = null;

	/**
	 * @template T
	 * @param {string} name
	 * @param {() => T} fn
	 * @param {T} fallback
	 * @returns {T}
	 */
	function safeCall(name, fn, fallback) {
		try {
			return fn();
		} catch (e) {
			console.error(`PatchHub UI module error in ${name}:`, e);
			return fallback;
		}
	}

	/**
	 * @param {unknown[] | null | undefined} items
	 * @returns {string[]}
	 */
	function normalizeList(items) {
		if (!Array.isArray(items)) return [];
		return items
			.map((item) => String(item || "").trim())
			.filter((item) => !!item);
	}

	/**
	 * @param {unknown} payload
	 * @returns {ToolkitResolutionRecord}
	 */
	function normalizeToolkitResolution(payload) {
		var source =
			payload && typeof payload === "object"
				? /** @type {ToolkitResolutionRecord} */ (payload)
				: {};
		return {
			remote_sig: String(source.remote_sig || "").trim(),
			cached_sig_before: String(source.cached_sig_before || "").trim(),
			selected_sig: String(source.selected_sig || "").trim(),
			cache_hit: !!source.cache_hit,
			download_performed: !!source.download_performed,
			integrity_check_result: String(
				source.integrity_check_result || "",
			).trim(),
			resolution_mode: String(source.resolution_mode || "").trim(),
			checked_at: String(source.checked_at || "").trim(),
			error: String(source.error || ""),
		};
	}

	/**
	 * @param {unknown} payload
	 * @returns {PmValidationPayload | null}
	 */
	function normalizePayload(payload) {
		if (!payload || typeof payload !== "object") return null;
		var source = /** @type {PmValidationPayload} */ (payload);
		var status = String(source.status || "")
			.trim()
			.toLowerCase();
		if (!status) return null;
		return {
			status: status,
			effective_mode: String(source.effective_mode || "").trim(),
			issue_id: String(source.issue_id || "").trim(),
			commit_message: String(source.commit_message || "").trim(),
			patch_path: String(source.patch_path || "").trim(),
			authority_sources: normalizeList(source.authority_sources),
			supplemental_files: normalizeList(source.supplemental_files),
			failure_summary: String(source.failure_summary || "").trim(),
			raw_output: String(source.raw_output || ""),
			toolkit_resolution: normalizeToolkitResolution(source.toolkit_resolution),
		};
	}

	/**
	 * @param {PmValidationPayload | null} payload
	 * @returns {string}
	 */
	function summaryText(payload) {
		if (!payload?.status) return "";
		var label = String(payload.status || "")
			.replace(/_/g, " ")
			.toUpperCase();
		var failureSummary = String(payload.failure_summary || "").trim();
		if (label === "FAIL" && failureSummary) {
			return `PM validation: FAIL - ${failureSummary}`;
		}
		return `PM validation: ${label}`;
	}

	/** @returns {PmValidationPayload | null} */
	function getPmValidationSnapshot() {
		if (!state) return null;
		return Object.assign({}, state, {
			toolkit_resolution: Object.assign({}, state.toolkit_resolution || {}),
		});
	}

	/** @returns {string} */
	function getPmValidationSummary() {
		return summaryText(state);
	}

	/**
	 * @param {unknown} payload
	 * @returns {PmValidationPayload | null}
	 */
	function setPmValidationPayload(payload) {
		state = normalizePayload(payload);
		if (PH && typeof PH.has === "function" && PH.has("renderInfoPoolUi")) {
			PH.call("renderInfoPoolUi");
		}
		return getPmValidationSnapshot();
	}

	function clearPmValidationPayload() {
		state = null;
		if (PH && typeof PH.has === "function" && PH.has("renderInfoPoolUi")) {
			PH.call("renderInfoPoolUi");
		}
	}

	if (PH && typeof PH.register === "function") {
		PH.register("app_part_pm_validation", {
			getPmValidationSnapshot,
			getPmValidationSummary,
			setPmValidationPayload,
			clearPmValidationPayload,
		});
	}

	ui.getPmValidationSnapshot = function () {
		return safeCall("getPmValidationSnapshot", getPmValidationSnapshot, null);
	};
	ui.getPmValidationSummary = function () {
		return safeCall("getPmValidationSummary", getPmValidationSummary, "");
	};
	ui.setPmValidationPayload = function (payload) {
		return safeCall(
			"setPmValidationPayload",
			() => setPmValidationPayload(payload),
			null,
		);
	};
	ui.clearPmValidationPayload = function () {
		return safeCall(
			"clearPmValidationPayload",
			() => {
				clearPmValidationPayload();
			},
			undefined,
		);
	};
})();
