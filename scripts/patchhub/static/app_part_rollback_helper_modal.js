// @ts-nocheck
/**
 * @typedef {{
 *   entry_id?: string,
 *   label?: string,
 *   selection_paths?: string[],
 * }} RollbackEntrySummary
 * @typedef {{
 *   job_id?: string,
 *   commit_summary?: string,
 * }} RollbackChainStep
 * @typedef {{
 *   blockers?: string[],
 *   advice?: string[],
 *   actions?: string[],
 *   chain_steps?: RollbackChainStep[],
 *   dirty_overlap_paths?: string[],
 *   dirty_nonoverlap_paths?: string[],
 *   sync_paths?: string[],
 * }} RollbackHelperState
 * @typedef {{
 *   helper?: RollbackHelperState | null,
 *   selected_entry_count?: number,
 * }} RollbackPreflight
 * @typedef {{
 *   sourceJob?: {job_id?: string, commit_summary?: string} | null,
 *   availableEntries: RollbackEntrySummary[],
 *   scopeKind: string,
 *   selectedRepoPaths: string[],
 *   selectedEntryIds: string[],
 *   preflight: RollbackPreflight | null,
 *   helperOpen: boolean,
 *   subsetDraft: Record<string, boolean>,
 * }} RollbackUiState
 * @typedef {{
 *   call?: (name: string, ...args: unknown[]) => unknown,
 *   register?: (name: string, exportsObj: Record<string, unknown>) => void,
 * }} RollbackRuntime
 * @typedef {Window & typeof globalThis & {
 *   PH?: RollbackRuntime | null,
 *   AMP_PATCHHUB_UI?: {
 *     activeListModalController?: RollbackListModalController | null,
 *   } | null,
 *   __PH_ROLLBACK_STATE?: RollbackUiState | null,
 * }} RollbackWindow
 * @typedef {{
 *   onToggle?: (name: string, checked: boolean) => void,
 *   onSelectAll?: () => void,
 *   onClear?: () => void,
 *   onReset?: () => void,
 *   onCancel?: () => void,
 *   onClose?: () => void,
 *   onBackdrop?: () => void,
 *   onApply?: () => void,
 * }} RollbackListModalController
 */
var rollbackHelperWindow = /** @type {RollbackWindow} */ (window);
var rollbackHelperPh = /** @type {RollbackRuntime | null} */ (
	rollbackHelperWindow.PH || null
);

/** @param {string} name @param {...unknown} args @returns {unknown} */
function rollbackHelperPhCall(name, ...args) {
	if (!rollbackHelperPh || typeof rollbackHelperPh.call !== "function")
		return undefined;
	return rollbackHelperPh.call(name, ...args);
}

/** @returns {RollbackUiState | null} */
function rollbackHelperState() {
	return rollbackHelperWindow.__PH_ROLLBACK_STATE || null;
}

/** @param {unknown} s @returns {string} */
function rollbackEscapeHtml(s) {
	return String(s || "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

/** @param {string} action @returns {string} */
function rollbackActionLabel(action) {
	if (action === "refresh") return "Refresh / re-check";
	if (action === "preserve_dirty") return "Preserve overlapping dirty changes";
	if (action === "discard_dirty") return "Discard overlapping dirty changes";
	if (action === "sync_to_authority") return "Sync selected scope to authority";
	if (action === "scope_narrow") return "Choose subset";
	if (action === "scope_expand") return "Use full scope";
	if (action === "execute_rollback") return "Execute rollback";
	return String(action || "Action");
}

/** @returns {void} */
function rollbackCloseHelperModal() {
	var state = rollbackHelperState();
	var modal = el("rollbackHelperModal");
	if (state) state.helperOpen = false;
	if (!modal) return;
	modal.classList.add("hidden");
	modal.setAttribute("aria-hidden", "true");
}

/** @returns {void} */
function rollbackRenderHelperModal() {
	var state = rollbackHelperState();
	var modal = el("rollbackHelperModal");
	var title = el("rollbackHelperTitle");
	var body = el("rollbackHelperBody");
	var actions = el("rollbackHelperActions");
	var helper = state && state.preflight && state.preflight.helper;
	if (!state || !modal || !title || !body || !actions) return;
	if (!state.helperOpen || !helper) {
		rollbackCloseHelperModal();
		return;
	}
	var sections = /** @type {string[]} */ ([]);
	var blockers = Array.isArray(helper.blockers) ? helper.blockers : [];
	var advice = Array.isArray(helper.advice) ? helper.advice : [];
	var chainSteps = Array.isArray(helper.chain_steps) ? helper.chain_steps : [];
	var dirtyOverlap = Array.isArray(helper.dirty_overlap_paths)
		? helper.dirty_overlap_paths
		: [];
	var dirtyNonoverlap = Array.isArray(helper.dirty_nonoverlap_paths)
		? helper.dirty_nonoverlap_paths
		: [];
	var syncPaths = Array.isArray(helper.sync_paths) ? helper.sync_paths : [];
	if (blockers.length) {
		sections.push(
			"<h3>Blockers</h3><ul>" +
				blockers
					.map((item) => "<li>" + rollbackEscapeHtml(item) + "</li>")
					.join("") +
				"</ul>",
		);
	}
	if (advice.length) {
		sections.push(
			"<h3>Advice</h3><ul>" +
				advice
					.map((item) => "<li>" + rollbackEscapeHtml(item) + "</li>")
					.join("") +
				"</ul>",
		);
	}
	sections.push(
		"<p><b>Selected scope:</b> " +
			rollbackEscapeHtml(
				String((state.preflight && state.preflight.selected_entry_count) || 0),
			) +
			" entries</p>",
	);
	if (dirtyOverlap.length) {
		sections.push(
			"<p><b>Overlapping dirty paths:</b> " +
				rollbackEscapeHtml(dirtyOverlap.join(", ")) +
				"</p>",
		);
	}
	if (dirtyNonoverlap.length) {
		sections.push(
			"<p><b>Unrelated dirty paths:</b> " +
				rollbackEscapeHtml(dirtyNonoverlap.join(", ")) +
				"</p>",
		);
	}
	if (syncPaths.length) {
		sections.push(
			"<p><b>Authority sync paths:</b> " +
				rollbackEscapeHtml(syncPaths.join(", ")) +
				"</p>",
		);
	}
	if (chainSteps.length) {
		sections.push(
			"<h3>Rollback chain</h3><ul>" +
				chainSteps
					.map((item) => {
						var label = [
							String((item && item.job_id) || "").trim(),
							String((item && item.commit_summary) || "").trim(),
						]
							.filter(Boolean)
							.join(" - ");
						return "<li>" + rollbackEscapeHtml(label) + "</li>";
					})
					.join("") +
				"</ul>",
		);
	}
	body.innerHTML = sections.join("");
	title.textContent = blockers.length
		? "Rollback blockers"
		: "Rollback guidance";
	actions.innerHTML = (Array.isArray(helper.actions) ? helper.actions : [])
		.map((action) => {
			return (
				'<button type="button" class="btn btn-small" data-rollback-action="' +
				rollbackEscapeHtml(action) +
				'">' +
				rollbackEscapeHtml(rollbackActionLabel(action)) +
				"</button>"
			);
		})
		.join("");
	modal.classList.remove("hidden");
	modal.setAttribute("aria-hidden", "false");
}

/** @returns {void} */
function rollbackOpenHelperModal() {
	var state = rollbackHelperState();
	if (!(state && state.preflight && state.preflight.helper)) return;
	state.helperOpen = true;
	rollbackRenderHelperModal();
}

/** @returns {void} */
function rollbackCloseSubsetPicker() {
	var ui = rollbackHelperWindow.AMP_PATCHHUB_UI;
	if (ui) ui.activeListModalController = null;
	rollbackHelperPhCall("closeZipSubsetModalView");
}

function rollbackSubsetSourceLabel(state) {
	var sourceJob = state && state.sourceJob ? state.sourceJob : null;
	var commitSummary = String(
		(sourceJob && sourceJob.commit_summary) || "",
	).trim();
	var jobId = String((sourceJob && sourceJob.job_id) || "").trim();
	if (commitSummary) return commitSummary;
	if (jobId) return "rollback source " + jobId;
	return "selected rollback source";
}

/** @returns {void} */
function rollbackRenderSubsetPicker() {
	var state = rollbackHelperState();
	var entries = state ? state.availableEntries || [] : [];
	var selectedCount = 0;
	entries.forEach((entry) => {
		var entryId = String((entry && entry.entry_id) || "").trim();
		if (state && entryId && state.subsetDraft[entryId] === true) {
			selectedCount += 1;
		}
	});
	rollbackHelperPhCall("openZipSubsetModalView", {
		title: "Select target files (" + String(entries.length) + ")",
		subtitle: "Contents of " + rollbackSubsetSourceLabel(state),
		selection_count:
			"Selected " + String(selectedCount) + " / " + String(entries.length),
		apply_disabled: selectedCount <= 0,
		rows: entries.map((entry) => {
			var entryId = String((entry && entry.entry_id) || "").trim();
			var label = String((entry && entry.label) || entryId || "rollback entry");
			return {
				zip_member: entryId,
				repo_path: label,
				checked: !!(state && state.subsetDraft[entryId] === true),
				disabled: false,
			};
		}),
	});
}

/** @returns {boolean} */
function rollbackOpenSubsetPicker() {
	var state = rollbackHelperState();
	var ui = rollbackHelperWindow.AMP_PATCHHUB_UI;
	var entries = state ? state.availableEntries || [] : [];
	var selectedSet = /** @type {Record<string, boolean>} */ (
		Object.create(null)
	);
	if (!state || !entries.length || !ui) return false;
	(state.selectedEntryIds || []).forEach((entryId) => {
		var key = String(entryId || "").trim();
		if (key) selectedSet[key] = true;
	});
	state.subsetDraft = Object.create(null);
	entries.forEach((entry) => {
		var entryId = String((entry && entry.entry_id) || "").trim();
		if (!entryId) return;
		state.subsetDraft[entryId] =
			state.scopeKind === "full" ? true : !!selectedSet[entryId];
	});
	ui.activeListModalController = /** @type {RollbackListModalController} */ ({
		onToggle(name, checked) {
			state.subsetDraft[String(name || "").trim()] = !!checked;
			rollbackRenderSubsetPicker();
		},
		onSelectAll() {
			entries.forEach((entry) => {
				var entryId = String((entry && entry.entry_id) || "").trim();
				if (entryId) state.subsetDraft[entryId] = true;
			});
			rollbackRenderSubsetPicker();
		},
		onClear() {
			entries.forEach((entry) => {
				var entryId = String((entry && entry.entry_id) || "").trim();
				if (entryId) state.subsetDraft[entryId] = false;
			});
			rollbackRenderSubsetPicker();
		},
		onReset() {
			entries.forEach((entry) => {
				var entryId = String((entry && entry.entry_id) || "").trim();
				if (entryId) state.subsetDraft[entryId] = true;
			});
			rollbackRenderSubsetPicker();
		},
		onCancel() {
			rollbackCloseSubsetPicker();
		},
		onClose() {
			rollbackCloseSubsetPicker();
		},
		onBackdrop() {
			rollbackCloseSubsetPicker();
		},
		onApply() {
			var selectedPaths = /** @type {string[]} */ ([]);
			entries.forEach((entry) => {
				var entryId = String((entry && entry.entry_id) || "").trim();
				if (!entryId || state.subsetDraft[entryId] !== true) return;
				selectedPaths = selectedPaths.concat(
					Array.isArray(entry.selection_paths) ? entry.selection_paths : [],
				);
			});
			rollbackCloseSubsetPicker();
			state.scopeKind = "subset";
			state.selectedRepoPaths = /** @type {string[]} */ (
				rollbackHelperPhCall("rollbackUniqueStrings", selectedPaths) ||
					selectedPaths
			);
			rollbackHelperPhCall("refreshRollbackPreflight");
		},
	});
	rollbackRenderSubsetPicker();
	return true;
}

/** @param {string} action @returns {void} */
function rollbackHandleAction(action) {
	var name = String(action || "").trim();
	if (!name) return;
	if (name === "scope_narrow") {
		rollbackCloseHelperModal();
		rollbackOpenSubsetPicker();
		return;
	}
	if (name === "scope_expand") {
		rollbackHelperPhCall("rollbackUseFullScope");
		return;
	}
	if (name === "execute_rollback") {
		rollbackCloseHelperModal();
		rollbackHelperPhCall("enqueue");
		return;
	}
	rollbackHelperPhCall("runRollbackHelperAction", name);
}

/** @returns {void} */
function handleSubsetStripAction(target) {
	var box =
		target && typeof target.closest === "function"
			? target.closest("#rollbackSubsetStrip")
			: null;
	if (!box) return false;
	if (String(box.dataset.action || "") !== "open") return false;
	rollbackOpenSubsetPicker();
	return true;
}

function bindRollbackUiEvents() {
	document.addEventListener("click", (ev) => {
		var target = ev && ev.target instanceof HTMLElement ? ev.target : null;
		if (!target) return;
		if (handleSubsetStripAction(target)) return;
		if (target.id === "rollbackHelperCloseBtn") {
			rollbackCloseHelperModal();
			return;
		}
		if (target.id === "rollbackHelperDoneBtn") {
			rollbackCloseHelperModal();
			return;
		}
		var action = String(
			target.getAttribute("data-rollback-action") || "",
		).trim();
		if (action) rollbackHandleAction(action);
	});
	document.addEventListener("keydown", (ev) => {
		var target = ev && ev.target instanceof HTMLElement ? ev.target : null;
		if (!target) return;
		if (ev.key !== "Enter" && ev.key !== " ") return;
		if (!handleSubsetStripAction(target)) return;
		ev.preventDefault();
	});
	var helperModal = el("rollbackHelperModal");
	if (helperModal) {
		helperModal.addEventListener("click", (ev) => {
			if (ev.target === helperModal) rollbackCloseHelperModal();
		});
	}
}

bindRollbackUiEvents();

if (rollbackHelperPh && typeof rollbackHelperPh.register === "function") {
	rollbackHelperPh.register("app_part_rollback_helper_modal", {
		rollbackOpenHelperModal,
		rollbackCloseHelperModal,
		rollbackRenderHelperModal,
		rollbackOpenSubsetPicker,
		rollbackCloseSubsetPicker,
	});
}
