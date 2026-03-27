// @ts-nocheck
(() => {
	/** @typedef {{entry_id?: string, lifecycle_kind?: string,
	 * old_path?: string, new_path?: string, label?: string,
	 * selection_paths?: string[], restore_paths?: string[]}}
	 * PHRollbackEntrySummary */
	/** @typedef {{open?: boolean, actions?: string[]}} PHRollbackHelperState */
	/** @typedef {{scope_kind?: string, selected_repo_paths?: string[],
	 * selected_entry_ids?: string[], selected_entries?: PHRollbackEntrySummary[],
	 * selected_entry_count?: number, dirty_overlap_paths?: string[],
	 * sync_paths?: string[], chain_required?: boolean, can_execute?: boolean,
	 * rollback_preflight_token?: string,
	 * helper?: PHRollbackHelperState | null}} PHRollbackPreflight */
	/** @typedef {{sourceJob: PatchhubJob | null, sourceJobId: string,
	 * availableEntries: PHRollbackEntrySummary[], scopeKind: string,
	 * selectedRepoPaths: string[], selectedEntryIds: string[],
	 * preflight: PHRollbackPreflight | null, busy: boolean,
	 * helperOpen: boolean, subsetDraft: Record<string, boolean>,
	 * lastSourceStatus: string, lastScopeStatus: string}}
	 * PHRollbackUiState */
	/** @typedef {{call?: (name: string, ...args: unknown[]) => unknown,
	 * register?: (name: string, exportsObj: Record<string, unknown>) => void}}
	 * PHRollbackRuntime */
	/** @typedef {Window & typeof globalThis & {PH?: PHRollbackRuntime | null,
	 * getRawCommand?: () => string, pushApiStatus?: (payload: unknown) => void,
	 * __PH_ROLLBACK_STATE?: PHRollbackUiState | null}} PHRollbackWindow */
	/** @typedef {PatchHubUiValueNode & {disabled: boolean}} PHRollbackDisabledNode */

	/** @type {PHRollbackWindow} */
	var rollbackWindow = window;
	/** @type {PHRollbackRuntime | null} */
	var PH = rollbackWindow.PH || null;
	/** @type {PHRollbackUiState | null | undefined} */
	var rollbackState = rollbackWindow.__PH_ROLLBACK_STATE;
	if (!rollbackState) {
		rollbackState = {
			sourceJob: null,
			sourceJobId: "",
			availableEntries: [],
			scopeKind: "full",
			selectedRepoPaths: [],
			selectedEntryIds: [],
			preflight: null,
			busy: false,
			helperOpen: false,
			subsetDraft: Object.create(null),
			lastSourceStatus: "",
			lastScopeStatus: "",
		};
		rollbackWindow.__PH_ROLLBACK_STATE = rollbackState;
	}

	/** @param {string} name @param {...unknown} args @returns {unknown} */
	function phCall(name, ...args) {
		return PH && typeof PH.call === "function"
			? PH.call(name, ...args)
			: undefined;
	}

	/** @param {unknown} payload */
	function pushApiStatusIfPresent(payload) {
		if (typeof rollbackWindow.pushApiStatus === "function") {
			rollbackWindow.pushApiStatus(payload);
		}
	}

	function rollbackRawCommand() {
		var rawNode = el("rawCommand");
		if (typeof rollbackWindow.getRawCommand === "function") {
			return String(rollbackWindow.getRawCommand() || "");
		}
		return rawNode ? String(rawNode.value || "") : "";
	}

	/** @param {unknown[] | string[] | null | undefined} values @returns {string[]} */
	function uniqueStrings(values) {
		/** @type {string[]} */
		var out = [];
		/** @type {Record<string, boolean>} */
		var seen = Object.create(null);
		(values || []).forEach((value) => {
			var text = String(value || "").trim();
			if (text && !seen[text]) {
				seen[text] = true;
				out.push(text);
			}
		});
		return out;
	}

	/** @param {string | null | undefined} message */
	function rollbackError(message) {
		setUiError(String(message || "rollback: failed"));
	}

	/** @param {string | null | undefined} message */
	function rollbackStatus(message) {
		setUiStatus(String(message || "rollback"));
	}

	function rollbackModeActive() {
		var modeNode = el("mode");
		return !!(modeNode && String(modeNode.value || "") === "rollback");
	}

	function targetNode() {
		return /** @type {PHRollbackDisabledNode | null} */ (el("targetRepo"));
	}

	/** @param {boolean} locked */
	function setTargetLocked(locked) {
		var node = targetNode();
		if (node) node.disabled = !!locked;
	}

	function selectedEntryCount() {
		var preflight = rollbackState.preflight;
		return (
			Number(preflight && preflight.selected_entry_count) ||
			rollbackState.availableEntries.length ||
			0
		);
	}

	function sourceSummaryText() {
		/** @type {string[]} */
		var parts = [];
		var sourceJob = rollbackState.sourceJob;
		if (sourceJob) {
			parts.push("Job " + String(sourceJob.job_id || ""));
			if (sourceJob.issue_id) {
				parts.push("issue " + String(sourceJob.issue_id || ""));
			}
			if (sourceJob.commit_summary) {
				parts.push(String(sourceJob.commit_summary || ""));
			}
		}
		if (!parts.length) return "Select Roll-back from the Jobs list";
		return parts.join(" | ");
	}

	function scopeSummaryText() {
		var preflight = rollbackState.preflight;
		/** @type {string[]} */
		var parts = [
			(rollbackState.scopeKind === "subset" ? "Subset" : "Full") +
				" scope: " +
				String(selectedEntryCount()) +
				" entries",
		];
		if (preflight && preflight.dirty_overlap_paths?.length) {
			parts.push("Overlapping dirty paths block execution");
		}
		if (preflight && preflight.sync_paths?.length) {
			parts.push("Authority sync required");
		}
		if (preflight && preflight.chain_required) {
			parts.push("Rollback chain required");
		}
		return parts.join(" | ");
	}

	function logSummaryToOperatorInfo(active) {
		var sourceText =
			active && rollbackState.sourceJob
				? "rollback source: " + sourceSummaryText()
				: "";
		var scopeText =
			active && rollbackState.sourceJob
				? "rollback scope: " + scopeSummaryText()
				: "";
		if (sourceText && sourceText !== rollbackState.lastSourceStatus) {
			rollbackState.lastSourceStatus = sourceText;
			rollbackStatus(sourceText);
		}
		if (scopeText && scopeText !== rollbackState.lastScopeStatus) {
			rollbackState.lastScopeStatus = scopeText;
			rollbackStatus(scopeText);
		}
		if (!active) {
			rollbackState.lastSourceStatus = "";
			rollbackState.lastScopeStatus = "";
		}
	}

	function renderSubsetStrip(node) {
		var total = rollbackState.availableEntries.length;
		var selected = selectedEntryCount();
		var detail = "";
		var note = "";
		var primary = "Rollback source scope";
		if (!total) {
			node.classList.add("hidden");
			node.innerHTML = "";
			node.removeAttribute("role");
			node.removeAttribute("tabindex");
			node.title = "";
			node.dataset.action = "";
			return;
		}
		node.classList.remove("hidden");
		if (rollbackState.scopeKind === "subset") {
			primary = "Selected target files";
			detail =
				"Selected " + String(selected) + " / " + String(total) + " entries";
		} else {
			detail = "Using full source scope (" + String(total) + " entries)";
		}
		if (rollbackState.busy) {
			note = "Loading guided rollback preflight...";
			node.dataset.action = "";
			node.removeAttribute("role");
			node.removeAttribute("tabindex");
		} else {
			note = "Click to choose subset";
			node.dataset.action = "open";
			node.setAttribute("role", "button");
			node.tabIndex = 0;
		}
		node.title = [primary, detail, note].filter(Boolean).join(" | ");
		node.innerHTML =
			'<div class="zip-subset-strip-inner"><b>' +
			primary +
			'</b><span class="muted"> | ' +
			detail +
			(note ? " | " + note : "") +
			"</span></div>";
	}

	function renderSummary() {
		var subsetStrip = el("rollbackSubsetStrip");
		var active = rollbackModeActive();
		var target = targetNode();
		if (target && rollbackState.sourceJob) {
			target.value = String(
				rollbackState.sourceJob.effective_runner_target_repo || "",
			);
		}
		setTargetLocked(active);
		if (!subsetStrip) {
			if (!active) phCall("rollbackCloseHelperModal");
			logSummaryToOperatorInfo(active);
			return;
		}
		if (!active) {
			subsetStrip.classList.add("hidden");
			subsetStrip.innerHTML = "";
			subsetStrip.dataset.action = "";
			phCall("rollbackCloseHelperModal");
			logSummaryToOperatorInfo(false);
			return;
		}
		renderSubsetStrip(subsetStrip);
		logSummaryToOperatorInfo(true);
		phCall("rollbackRenderHelperModal");
	}

	/**
	 * @param {PatchhubJob | null | undefined} job
	 * @param {PHRollbackPreflight | null | undefined} preflight
	 * @param {{keepAvailableEntries?: boolean} | null | undefined} options
	 */
	function applyRollbackState(job, preflight, options) {
		var keepAvailable = !!(options && options.keepAvailableEntries);
		var modeNode = el("mode");
		var rawNode = el("rawCommand");
		rollbackState.sourceJob = job || rollbackState.sourceJob;
		rollbackState.sourceJobId = String(
			(job && job.job_id) || rollbackState.sourceJobId || "",
		).trim();
		rollbackState.preflight = preflight || null;
		rollbackState.scopeKind = String(
			(preflight && preflight.scope_kind) || rollbackState.scopeKind || "full",
		);
		rollbackState.selectedRepoPaths = uniqueStrings(
			(preflight && preflight.selected_repo_paths) ||
				rollbackState.selectedRepoPaths ||
				[],
		);
		rollbackState.selectedEntryIds = uniqueStrings(
			(preflight && preflight.selected_entry_ids) ||
				rollbackState.selectedEntryIds ||
				[],
		);
		if (!keepAvailable || !rollbackState.availableEntries.length) {
			rollbackState.availableEntries = Array.isArray(
				preflight && preflight.selected_entries,
			)
				? /** @type {PHRollbackEntrySummary[]} */ (
						((preflight && preflight.selected_entries) || []).slice()
					)
				: rollbackState.availableEntries;
		}
		if (modeNode) modeNode.value = "rollback";
		if (rawNode) rawNode.value = "";
		if (typeof clearParsedState === "function") clearParsedState();
		if (typeof setParseHint === "function") setParseHint("");
		renderSummary();
		if (typeof validateAndPreview === "function") validateAndPreview();
		if (preflight && preflight.helper && preflight.helper.open) {
			phCall("rollbackOpenHelperModal");
		}
	}

	if (PH && typeof PH.register === "function") {
		PH.register("app_part_rollback_state", {
			rollbackGetState: () => rollbackState,
			rollbackPushApiStatus: pushApiStatusIfPresent,
			rollbackRawCommand,
			rollbackUniqueStrings: uniqueStrings,
			rollbackError,
			rollbackStatus,
			rollbackModeActive,
			rollbackSelectedEntryCount: selectedEntryCount,
			rollbackRenderSummary: renderSummary,
			rollbackApplyState: applyRollbackState,
		});
	}
})();
