// @ts-nocheck
(() => {
	/** @typedef {{scope_kind?: string, selected_repo_paths?: string[],
	 * selected_entry_ids?: string[], selected_entry_count?: number,
	 * rollback_preflight_token?: string, can_execute?: boolean,
	 * helper?: {open?: boolean} | null}} PHRollbackPreflight */
	/** @typedef {{ok?: boolean, error?: string, job?: PatchhubJob | null,
	 * rollback?: PHRollbackPreflight | null}} PHRollbackEntryResponse */
	/** @typedef {{sourceJob: PatchhubJob | null, sourceJobId: string,
	 * availableEntries: Array<{entry_id?: string}>, scopeKind: string,
	 * selectedRepoPaths: string[], selectedEntryIds: string[],
	 * preflight: PHRollbackPreflight | null, busy: boolean}}
	 * PHRollbackUiState */
	/** @typedef {{call?: (name: string, ...args: unknown[]) => unknown,
	 * register?: (name: string, exportsObj: Record<string, unknown>) => void}}
	 * PHRollbackRuntime */
	/** @typedef {Window & typeof globalThis & {PH?: PHRollbackRuntime | null,
	 * __PH_ROLLBACK_STATE?: PHRollbackUiState | null}} PHRollbackWindow */

	/** @type {PHRollbackWindow} */
	var rollbackWindow = window;
	/** @type {PHRollbackRuntime | null} */
	var PH = rollbackWindow.PH || null;

	/** @param {string} name @param {...unknown} args @returns {unknown} */
	function phCall(name, ...args) {
		return PH && typeof PH.call === "function"
			? PH.call(name, ...args)
			: undefined;
	}

	/** @returns {PHRollbackUiState} */
	function state() {
		return /** @type {PHRollbackUiState} */ (
			phCall("rollbackGetState") || rollbackWindow.__PH_ROLLBACK_STATE || {}
		);
	}

	function preflightBody() {
		var ui = state();
		return {
			rollback_source_job_id: String(ui.sourceJobId || ""),
			rollback_scope_kind: String(ui.scopeKind || "full"),
			rollback_selected_repo_paths: /** @type {string[]} */ (
				phCall(
					"rollbackUniqueStrings",
					String(ui.scopeKind || "full") === "subset"
						? ui.selectedRepoPaths
						: [],
				) || []
			),
		};
	}

	/** @param {Promise<PHRollbackEntryResponse>} request @param {string} message */
	function resolveRollbackRequest(request, message) {
		return request
			.then((resp) => {
				phCall("rollbackPushApiStatus", resp);
				if (!resp || resp.ok === false || !resp.rollback) {
					phCall("rollbackError", String((resp && resp.error) || message));
					return false;
				}
				if (resp.job) phCall("rememberRollbackSourceJobDetail", resp.job);
				phCall(
					"rollbackApplyState",
					resp.job || state().sourceJob,
					resp.rollback,
					{ keepAvailableEntries: true },
				);
				return true;
			})
			.catch(() => {
				phCall("rollbackError", message);
				return false;
			})
			.finally(() => {
				state().busy = false;
				phCall("rollbackRenderSummary");
			});
	}

	function refreshRollbackPreflight() {
		var ui = state();
		if (!ui.sourceJobId) return Promise.resolve(false);
		ui.busy = true;
		phCall("rollbackRenderSummary");
		phCall(
			"rollbackStatus",
			"rollback: preflight source_job_id=" + ui.sourceJobId,
		);
		return resolveRollbackRequest(
			/** @type {Promise<PHRollbackEntryResponse>} */ (
				apiPost("/api/rollback/preflight", preflightBody())
			),
			"rollback: guided preflight failed",
		);
	}

	/** @param {string | null | undefined} action */
	function runRollbackHelperAction(action) {
		var ui = state();
		if (!ui.sourceJobId) return Promise.resolve(false);
		ui.busy = true;
		phCall("rollbackRenderSummary");
		phCall("rollbackStatus", "rollback: helper action " + String(action || ""));
		return resolveRollbackRequest(
			/** @type {Promise<PHRollbackEntryResponse>} */ (
				apiPost("/api/rollback/helper_action", {
					action: String(action || ""),
					...preflightBody(),
				})
			),
			"rollback: helper action failed",
		);
	}

	/** @param {string | null | undefined} jobId */
	function beginRollbackFromJobId(jobId) {
		var sourceJobId = String(jobId || "").trim();
		var ui = state();
		if (!sourceJobId) return Promise.resolve(false);
		ui.busy = true;
		phCall("rollbackRenderSummary");
		phCall("rollbackStatus", "rollback: start source_job_id=" + sourceJobId);
		return /** @type {Promise<PHRollbackEntryResponse>} */ (
			apiPost("/api/jobs/" + encodeURIComponent(sourceJobId) + "/revert", {})
		)
			.then((resp) => {
				phCall("rollbackPushApiStatus", resp);
				if (!resp || resp.ok === false || !resp.rollback || !resp.job) {
					phCall(
						"rollbackError",
						String(
							(resp && resp.error) || "rollback: cannot start guided flow",
						),
					);
					return false;
				}
				phCall("rememberRollbackSourceJobDetail", resp.job);
				ui.availableEntries = Array.isArray(resp.rollback.selected_entries)
					? resp.rollback.selected_entries.slice()
					: [];
				phCall("rollbackApplyState", resp.job, resp.rollback, {
					keepAvailableEntries: false,
				});
				return true;
			})
			.catch(() => {
				phCall("rollbackError", "rollback: cannot start guided flow");
				return false;
			})
			.finally(() => {
				ui.busy = false;
				phCall("rollbackRenderSummary");
			});
	}

	function rollbackUseFullScope() {
		var ui = state();
		var nextEntryIds;
		if (!ui.sourceJobId) return false;
		nextEntryIds = ui.availableEntries
			.map((entry) => String((entry && entry.entry_id) || "").trim())
			.filter(Boolean);
		if (
			String(ui.scopeKind || "full") === "full" &&
			String((ui.preflight && ui.preflight.scope_kind) || "") === "full"
		) {
			ui.selectedEntryIds = nextEntryIds;
			phCall("rollbackCloseHelperModal");
			phCall("rollbackRenderSummary");
			if (typeof validateAndPreview === "function") validateAndPreview();
			return true;
		}
		ui.scopeKind = "full";
		ui.selectedRepoPaths = [];
		ui.selectedEntryIds = nextEntryIds;
		phCall("rollbackCloseHelperModal");
		refreshRollbackPreflight();
		return true;
	}

	function rollbackValidationState() {
		var ui = state();
		var raw = String(phCall("rollbackRawCommand") || "").trim();
		if (!phCall("rollbackModeActive")) return { ok: true, hint: "" };
		if (raw)
			return { ok: false, hint: "rollback mode does not support raw command" };
		if (!ui.sourceJobId || !ui.sourceJob) {
			return { ok: false, hint: "select Roll-back from the Jobs list" };
		}
		if (ui.busy) return { ok: false, hint: "guided rollback is loading" };
		if (!ui.preflight)
			return { ok: false, hint: "guided rollback preflight is missing" };
		if (!ui.preflight.can_execute) {
			return {
				ok: false,
				hint: "guided rollback requires helper action or scope change",
			};
		}
		return { ok: true, hint: "" };
	}

	/** @param {Record<string, unknown> | null | undefined} preview */
	function applyRollbackPreview(preview) {
		var ui = state();
		var out = preview || {};
		if (!phCall("rollbackModeActive")) return out;
		out.rollback = {
			source_job_id: String(ui.sourceJobId || ""),
			target_repo: String(
				(ui.sourceJob && ui.sourceJob.effective_runner_target_repo) || "",
			),
			scope_kind: String(ui.scopeKind || "full"),
			selected_repo_paths:
				phCall("rollbackUniqueStrings", ui.selectedRepoPaths || []) || [],
			selected_entry_ids:
				phCall("rollbackUniqueStrings", ui.selectedEntryIds || []) || [],
			selected_entry_count: Number(phCall("rollbackSelectedEntryCount") || 0),
			can_execute: !!(ui.preflight && ui.preflight.can_execute),
		};
		return out;
	}

	function getRollbackEnqueuePayload() {
		var ui = state();
		var validation = rollbackValidationState();
		if (!validation.ok)
			return { error: validation.hint || "rollback cannot execute" };
		return {
			rollback_source_job_id: String(ui.sourceJobId || ""),
			rollback_scope_kind: String(ui.scopeKind || "full"),
			rollback_selected_repo_paths: /** @type {string[]} */ (
				phCall(
					"rollbackUniqueStrings",
					String(ui.scopeKind || "full") === "subset"
						? ui.selectedRepoPaths
						: [],
				) || []
			),
			rollback_preflight_token: String(
				(ui.preflight && ui.preflight.rollback_preflight_token) || "",
			),
		};
	}

	function syncRollbackUiFromInputs() {
		phCall("rollbackRenderSummary");
		return true;
	}

	function clearRollbackFlowState() {
		var ui = state();
		ui.sourceJob = null;
		ui.sourceJobId = "";
		ui.availableEntries = [];
		ui.scopeKind = "full";
		ui.selectedRepoPaths = [];
		ui.selectedEntryIds = [];
		ui.preflight = null;
		ui.busy = false;
		ui.helperOpen = false;
		ui.subsetDraft = Object.create(null);
		phCall("rollbackCloseSubsetPicker");
		phCall("rollbackCloseHelperModal");
		phCall("rollbackRenderSummary");
		return true;
	}

	if (PH && typeof PH.register === "function") {
		PH.register("app_part_rollback", {
			beginRollbackFromJobId,
			refreshRollbackPreflight,
			runRollbackHelperAction,
			rollbackUseFullScope,
			getRollbackValidationState: rollbackValidationState,
			applyRollbackPreview,
			getRollbackEnqueuePayload,
			syncRollbackUiFromInputs,
			clearRollbackFlowState,
		});
	}
})();
