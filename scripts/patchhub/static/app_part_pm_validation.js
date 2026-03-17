(() => {
	var w = /** @type {any} */ (window);
	var ui = w.AMP_PATCHHUB_UI;
	if (!ui) {
		ui = {};
		w.AMP_PATCHHUB_UI = ui;
	}

	var PH = w.PH;
	var state = null;

	function safeExport(name, fn) {
		ui[name] = (...args) => {
			try {
				return fn(...args);
			} catch (e) {
				console.error(`PatchHub UI module error in ${name}:`, e);
				return undefined;
			}
		};
	}

	function normalizeList(items) {
		if (!Array.isArray(items)) return [];
		return items
			.map((item) => String(item || "").trim())
			.filter((item) => !!item);
	}

	function normalizePayload(payload) {
		if (!payload || typeof payload !== "object") return null;
		var status = String(payload.status || "")
			.trim()
			.toLowerCase();
		if (!status) return null;
		return {
			status: status,
			effective_mode: String(payload.effective_mode || "").trim(),
			issue_id: String(payload.issue_id || "").trim(),
			commit_message: String(payload.commit_message || "").trim(),
			patch_path: String(payload.patch_path || "").trim(),
			authority_sources: normalizeList(payload.authority_sources),
			supplemental_files: normalizeList(payload.supplemental_files),
			raw_output: String(payload.raw_output || ""),
		};
	}

	function summaryText(payload) {
		if (!payload || !payload.status) return "";
		var label = String(payload.status || "")
			.replace(/_/g, " ")
			.toUpperCase();
		return "PM validation: " + label;
	}

	function getPmValidationSnapshot() {
		return state ? Object.assign({}, state) : null;
	}

	function getPmValidationSummary() {
		return summaryText(state);
	}

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

	safeExport("getPmValidationSnapshot", getPmValidationSnapshot);
	safeExport("getPmValidationSummary", getPmValidationSummary);
	safeExport("setPmValidationPayload", setPmValidationPayload);
	safeExport("clearPmValidationPayload", clearPmValidationPayload);
})();
