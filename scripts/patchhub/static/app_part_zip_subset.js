(() => {
	/**
	 * @typedef {{
	 *   zip_member?: string,
	 *   repo_path?: string,
	 *   selectable?: boolean,
	 * }} ZipSubsetManifestEntry
	 * @typedef {{
	 *   entries?: ZipSubsetManifestEntry[],
	 *   patch_entry_count?: number,
	 *   selectable?: boolean,
	 *   reason?: string,
	 * }} ZipSubsetManifest
	 * @typedef {{
	 *   ok?: boolean,
	 *   error?: string,
	 *   manifest?: ZipSubsetManifest,
	 *   pm_validation?: unknown,
	 *   derived_issue?: unknown,
	 *   derived_commit_message?: unknown,
	 *   derived_target_repo?: unknown,
	 * }} ZipSubsetManifestResponse
	 * @typedef {{
	 *   key: string,
	 *   loading: boolean,
	 *   manifest: ZipSubsetManifest | null,
	 *   committedSelected: Record<string, boolean>,
	 *   draftSelected: Record<string, boolean>,
	 *   modalOpen: boolean,
	 *   error: string,
	 *   requestSeq: number,
	 * }} ZipSubsetState
	 * @typedef {{
	 *   mode?: string,
	 *   raw_command?: string,
	 *   zip_subset?: {
	 *     selectable?: boolean,
	 *     selection_status?: string,
	 *     selected_patch_entries?: string[],
	 *     selected_repo_paths?: string[],
	 *     effective_patch_kind?: string,
	 *   },
	 * }} ZipSubsetPreview
	 * @typedef {{
	 *   error?: string,
	 *   selected_patch_entries?: string[],
	 * }} ZipSubsetEnqueuePayload
	 * @typedef {{ ok: boolean, hint: string }} ZipSubsetValidationState
	 * @typedef {{
	 *   call?: (name: string, ...args: unknown[]) => unknown,
	 *   has?: (name: string) => boolean,
	 *   register?: (name: string, exportsObj: Record<string, unknown>) => void,
	 * }} ZipSubsetRuntime
	 * @typedef {Window & typeof globalThis & {
	 *   AMP_PATCHHUB_UI?: PatchhubUiBridge & Record<string, unknown>,
	 *   PH?: ZipSubsetRuntime | null,
	 *   __ph_patch_load_seq?: number,
	 * }} ZipSubsetWindow
	 * @typedef {HTMLElement & {
	 *   value?: string,
	 *   checked?: boolean,
	 *   disabled?: boolean,
	 *   dataset?: DOMStringMap,
	 *   innerHTML: string,
	 *   textContent: string,
	 *   title: string,
	 *   tabIndex: number,
	 * }} ZipSubsetElement
	 */
	var w = /** @type {ZipSubsetWindow} */ (window);
	var ui =
		/** @type {(PatchhubUiBridge & Record<string, unknown>) | undefined} */ (
			w.AMP_PATCHHUB_UI
		);
	if (!ui) {
		ui = /** @type {PatchhubUiBridge & Record<string, unknown>} */ ({});
		w.AMP_PATCHHUB_UI = ui;
	}
	var uiBridge = /** @type {PatchhubUiBridge & Record<string, unknown>} */ (ui);

	var PH = w.PH;

	function phCall(
		/** @type {string} */ name,
		/** @type {unknown[]} */ ...args
	) {
		if (!PH || typeof PH.call !== "function") return undefined;
		return PH.call(name, ...args);
	}

	/** @type {ZipSubsetState} */
	var state = {
		key: "",
		loading: false,
		manifest: null,
		committedSelected: {},
		draftSelected: {},
		modalOpen: false,
		error: "",
		requestSeq: 0,
	};

	function el(/** @type {string} */ id) {
		return /** @type {ZipSubsetElement | null} */ (document.getElementById(id));
	}

	function escapeHtml(/** @type {unknown} */ s) {
		return String(s || "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#39;");
	}

	function safeExport(
		/** @type {string} */ name,
		/** @type {(...args: unknown[]) => unknown} */ fn,
	) {
		uiBridge[name] = (/** @type {unknown[]} */ ...args) => {
			try {
				return fn(...args);
			} catch (e) {
				console.error(`PatchHub UI module error in ${name}:`, e);
				return undefined;
			}
		};
	}

	function currentMode() {
		var node = el("mode");
		return node ? String(node.value || "patch") : "patch";
	}

	function currentPatchPath() {
		var node = el("patchPath");
		if (!node) return "";
		if (typeof normalizePatchPath !== "function") {
			return String(node.value || "").trim();
		}
		return normalizePatchPath(String(node.value || "").trim());
	}

	function currentRawCommand() {
		if (typeof getRawCommand === "function") return getRawCommand();
		return "";
	}

	function isPatchZipMode() {
		return currentMode() === "patch" && /\.zip$/i.test(currentPatchPath());
	}

	function isRawLocked() {
		return !!currentRawCommand();
	}

	function currentPatchLoadSeq() {
		var raw = Number(w.__ph_patch_load_seq || 0);
		return Number.isFinite(raw) ? raw : 0;
	}

	function zipSubsetStateKey() {
		return [currentMode(), currentPatchPath(), currentPatchLoadSeq()].join("|");
	}

	function manualPatchReloadRequested() {
		return !!(typeof dirty === "object" && dirty && dirty.patchPath === true);
	}

	function manifestEntries() {
		var manifest = state.manifest || {};
		return Array.isArray(manifest.entries) ? manifest.entries : [];
	}

	function selectionMap(/** @type {string} */ kind) {
		return kind === "draft" ? state.draftSelected : state.committedSelected;
	}

	function ensureSelectionDefaults(/** @type {string} */ kind) {
		var selected = selectionMap(kind);
		manifestEntries().forEach((item) => {
			var name = String(item && item.zip_member ? item.zip_member : "");
			if (!name || item.selectable !== true) return;
			if (!Object.hasOwn(selected, name)) {
				selected[name] = true;
			}
		});
	}

	function resetSelectionToAll(/** @type {string} */ kind) {
		/** @type {Record<string, boolean>} */
		var next = {};
		manifestEntries().forEach((item) => {
			var name = String(item && item.zip_member ? item.zip_member : "");
			if (!name || item.selectable !== true) return;
			next[name] = true;
		});
		if (kind === "draft") {
			state.draftSelected = next;
			return;
		}
		state.committedSelected = next;
	}

	function cloneCommittedToDraft() {
		state.draftSelected = /** @type {Record<string, boolean>} */ (
			Object.assign({}, state.committedSelected)
		);
		ensureSelectionDefaults("draft");
	}

	function clearDraftSelection() {
		/** @type {Record<string, boolean>} */
		var next = {};
		manifestEntries().forEach((item) => {
			var name = String(item && item.zip_member ? item.zip_member : "");
			if (!name || item.selectable !== true) return;
			next[name] = false;
		});
		state.draftSelected = next;
	}

	function selectedEntries(/** @type {string} */ kind) {
		var selected = selectionMap(kind || "committed");
		/** @type {string[]} */
		var out = [];
		manifestEntries().forEach((item) => {
			var name = String(item && item.zip_member ? item.zip_member : "");
			if (!name || item.selectable !== true) return;
			if (selected[name] !== false) out.push(name);
		});
		return out;
	}

	function selectedRepoPaths(/** @type {string} */ kind) {
		var selected = selectionMap(kind || "committed");
		/** @type {string[]} */
		var out = [];
		manifestEntries().forEach((item) => {
			var name = String(item && item.zip_member ? item.zip_member : "");
			var repo = String(item && item.repo_path ? item.repo_path : "");
			if (!name || !repo || item.selectable !== true) return;
			if (selected[name] !== false) out.push(repo);
		});
		return out;
	}

	function selectableCount() {
		return manifestEntries().filter((item) => item.selectable === true).length;
	}

	function hideModal() {
		state.modalOpen = false;
		phCall("closeZipSubsetModalView");
	}

	function clearState() {
		state.key = "";
		state.loading = false;
		state.manifest = null;
		state.committedSelected = {};
		state.draftSelected = {};
		state.modalOpen = false;
		state.error = "";
		phCall("clearPmValidationPayload");
		hideModal();
		renderStrip();
	}

	function selectionStatusText() {
		var total = selectableCount();
		var selected = selectedEntries("committed").length;
		if (!total) return "";
		if (selected === total) return `Using uploaded zip (${total} files)`;
		return `Selected ${selected} / ${total} files`;
	}

	function draftStatusText() {
		var total = selectableCount();
		var selected = selectedEntries("draft").length;
		if (!total) return "All 0 selected";
		if (selected === total) return `All ${total} selected`;
		return `Selected ${selected} / ${total}`;
	}

	function setStripAction(
		/** @type {unknown} */ action,
		/** @type {unknown} */ title,
	) {
		var box = el("zipSubsetStrip");
		if (!box) return;
		box.dataset.action = String(action || "");
		box.title = String(title || "");
		if (action) {
			box.setAttribute("role", "button");
			box.tabIndex = 0;
			return;
		}
		box.removeAttribute("role");
		box.removeAttribute("tabindex");
	}

	function renderStrip() {
		var box = el("zipSubsetStrip");
		if (!box) return;
		if (!isPatchZipMode()) {
			box.classList.add("hidden");
			box.innerHTML = "";
			setStripAction("", "");
			return;
		}

		box.classList.remove("hidden");
		if (state.loading) {
			box.innerHTML =
				'<div class="zip-subset-strip-inner"><b>ZIP patch detected</b>' +
				'<span class="muted"> | Loading target files...</span></div>';
			setStripAction("", "");
			return;
		}

		if (state.error) {
			box.innerHTML =
				'<div class="zip-subset-strip-inner"><b>ZIP patch detected</b>' +
				'<span class="muted"> | ' +
				escapeHtml(state.error) +
				" | Retry</span></div>";
			setStripAction("retry", state.error);
			return;
		}

		var manifest = state.manifest || {};
		var total = Number(manifest.patch_entry_count || 0);
		var selectable = manifest.selectable === true;
		var primary = `ZIP patch detected: ${String(total)} target files`;
		var detail = "";
		var note = "";
		ensureSelectionDefaults("committed");
		detail = selectable
			? selectionStatusText()
			: String(manifest.reason || "read only");
		if (isRawLocked()) {
			note = "Subset disabled while raw command is set.";
		} else if (!selectable) {
			note = "Subset available only for PM per-file zip patches.";
		}
		box.innerHTML =
			'<div class="zip-subset-strip-inner"><b>' +
			escapeHtml(primary) +
			'</b><span class="muted"> | ' +
			escapeHtml(detail) +
			(note ? ` | ${escapeHtml(note)}` : "") +
			"</span></div>";
		setStripAction("open", [primary, detail, note].filter(Boolean).join(" | "));
	}

	function modalModel() {
		var total = selectableCount();
		var baseName = currentPatchPath().split("/").pop() || "patch.zip";
		ensureSelectionDefaults("draft");
		return {
			title: "Select target files (" + String(total) + ")",
			subtitle: "Contents of " + baseName,
			selection_count: draftStatusText(),
			apply_disabled: !state.manifest || isRawLocked(),
			rows: manifestEntries().map((item) => {
				var name = String(item && item.zip_member ? item.zip_member : "");
				var repo = String(item && item.repo_path ? item.repo_path : "");
				return {
					zip_member: name,
					repo_path: repo || name,
					checked: state.draftSelected[name] !== false,
					disabled: item.selectable !== true || isRawLocked(),
				};
			}),
		};
	}

	function renderModal() {
		if (!PH || typeof PH.has !== "function") return;
		if (!PH.has("renderZipSubsetModal")) return;
		phCall("renderZipSubsetModal", modalModel());
	}

	function discardDraftAndClose() {
		state.draftSelected = {};
		hideModal();
	}

	function openModal() {
		if (!state.manifest) return;
		cloneCommittedToDraft();
		state.modalOpen = true;
		if (
			PH &&
			typeof PH.has === "function" &&
			PH.has("openZipSubsetModalView")
		) {
			phCall("openZipSubsetModalView", modalModel());
			return;
		}
		renderModal();
	}

	function applyModalDraft() {
		state.committedSelected = Object.assign({}, state.draftSelected);
		ensureSelectionDefaults("committed");
		hideModal();
		renderStrip();
		phCall("validateAndPreview");
	}

	function fetchManifestForCurrentPath(/** @type {string} */ requestKey) {
		var patchPath = currentPatchPath();
		var loadSeq = currentPatchLoadSeq();
		var requestSeq = ++state.requestSeq;
		state.loading = true;
		state.error = "";
		state.manifest = null;
		state.committedSelected = {};
		state.draftSelected = {};
		phCall("clearPmValidationPayload");
		renderStrip();
		apiGet(
			"/api/patches/zip_manifest?path=" + encodeURIComponent(patchPath),
		).then((r) => {
			var resp = /** @type {ZipSubsetManifestResponse} */ (r);
			var targetNode = el("targetRepo");
			var payload = /** @type {PatchhubLatestPatchResponse} */ ({
				stored_rel_path: patchPath,
				derived_issue:
					resp && Object.hasOwn(resp, "derived_issue")
						? resp.derived_issue
						: null,
				derived_commit_message:
					resp && Object.hasOwn(resp, "derived_commit_message")
						? resp.derived_commit_message
						: null,
				derived_target_repo:
					resp && Object.hasOwn(resp, "derived_target_repo")
						? resp.derived_target_repo
						: null,
			});
			if (requestSeq !== state.requestSeq) return;
			if (!isPatchZipMode()) return;
			if (state.key !== requestKey) return;
			if (currentPatchPath() !== patchPath) return;
			if (currentPatchLoadSeq() !== loadSeq) return;
			state.loading = false;
			if (!resp || resp.ok === false || !resp.manifest) {
				state.error = String(
					(resp && resp.error) || "cannot inspect zip patch",
				);
				state.manifest = null;
				phCall("clearPmValidationPayload");
				renderStrip();
				phCall("validateAndPreview");
				return;
			}
			state.manifest = resp.manifest;
			phCall("setPmValidationPayload", resp.pm_validation || null);
			resetSelectionToAll("committed");
			state.draftSelected = {};
			renderStrip();
			if (state.modalOpen) renderModal();
			if (typeof applyAutofillFromPayload === "function") {
				applyAutofillFromPayload(payload);
				return;
			}
			if (
				targetNode &&
				cfg &&
				cfg.targeting &&
				cfg.targeting.zip_target_prefill_enabled &&
				payload.derived_target_repo != null &&
				phCall("shouldOverwriteField", "targetRepo", targetNode)
			) {
				targetNode.value = String(payload.derived_target_repo || "");
			}
			phCall("validateAndPreview");
		});
	}

	function syncFromInputs() {
		var key = "";
		if (!isPatchZipMode()) {
			clearState();
			return;
		}
		key = zipSubsetStateKey();
		if (manualPatchReloadRequested()) {
			phCall("prepareFormForNewPatchLoad");
			key = zipSubsetStateKey();
		}
		if (state.key !== key) {
			state.key = key;
			fetchManifestForCurrentPath(key);
			return;
		}
		renderStrip();
		if (state.modalOpen) renderModal();
	}

	function enqueuePayload() {
		if (!state.manifest || state.loading || isRawLocked()) return {};
		if (state.manifest.selectable !== true) return {};
		var selected = selectedEntries("committed");
		var total = selectableCount();
		if (!selected.length) {
			return { error: "no selected files" };
		}
		if (selected.length >= total) return {};
		return { selected_patch_entries: selected.slice() };
	}

	function validationState() {
		if (!isPatchZipMode()) return { ok: true, hint: "" };
		if (state.loading) return { ok: false, hint: "loading zip target files" };
		if (state.error) return { ok: false, hint: state.error };
		if (!state.manifest || state.manifest.selectable !== true) {
			return { ok: true, hint: "" };
		}
		if (isRawLocked()) return { ok: true, hint: "" };
		if (!selectedEntries("committed").length) {
			return { ok: false, hint: "no selected files" };
		}
		return { ok: true, hint: "" };
	}

	function applyPreview(
		/** @type {ZipSubsetPreview | null | undefined} */ preview,
	) {
		if (!preview || typeof preview !== "object") return preview;
		if (!state.manifest || !isPatchZipMode()) return preview;
		var selected = selectedEntries("committed");
		var total = selectableCount();
		if (selected.length >= total) {
			delete preview.zip_subset;
			return preview;
		}
		preview.zip_subset = {
			selectable: state.manifest.selectable === true,
			selection_status: selectionStatusText(),
			selected_patch_entries: selected,
			selected_repo_paths: selectedRepoPaths("committed"),
			effective_patch_kind: "derived_subset_pending",
		};
		return preview;
	}

	function handleStripAction(/** @type {Element | null} */ target) {
		var box = /** @type {ZipSubsetElement | null} */ (
			target && typeof target.closest === "function"
				? target.closest("#zipSubsetStrip")
				: null
		);
		if (!box) return false;
		var action = String(box.dataset.action || "");
		if (action === "open") {
			openModal();
			return true;
		}
		if (action === "retry") {
			if (!isPatchZipMode()) return false;
			state.key = zipSubsetStateKey();
			fetchManifestForCurrentPath(state.key);
			return true;
		}
		return false;
	}

	function bindEvents() {
		document.addEventListener("click", (ev) => {
			var target = ev && ev.target instanceof HTMLElement ? ev.target : null;
			if (!target) return;
			handleStripAction(target);
		});
		document.addEventListener("keydown", (ev) => {
			var target = ev && ev.target instanceof HTMLElement ? ev.target : null;
			if (!target) return;
			if (ev.key !== "Enter" && ev.key !== " ") return;
			if (!handleStripAction(target)) return;
			ev.preventDefault();
		});
	}

	uiBridge.zipSubsetModalController = {
		onToggle(/** @type {unknown} */ name, /** @type {unknown} */ checked) {
			state.draftSelected[String(name || "")] = !!checked;
			renderModal();
		},
		onSelectAll() {
			resetSelectionToAll("draft");
			renderModal();
		},
		onClear() {
			clearDraftSelection();
			renderModal();
		},
		onReset() {
			resetSelectionToAll("draft");
			renderModal();
		},
		onCancel() {
			discardDraftAndClose();
		},
		onClose() {
			discardDraftAndClose();
		},
		onBackdrop() {
			discardDraftAndClose();
		},
		onApply() {
			applyModalDraft();
		},
	};

	bindEvents();

	if (PH && typeof PH.register === "function") {
		PH.register("app_part_zip_subset", {
			syncZipSubsetUiFromInputs: syncFromInputs,
			getZipSubsetEnqueuePayload: enqueuePayload,
			getZipSubsetValidationState: validationState,
			applyZipSubsetPreview: applyPreview,
			openZipSubsetModal: openModal,
		});
	}
	uiBridge.syncZipSubsetUiFromInputs = syncFromInputs;
	uiBridge.getZipSubsetEnqueuePayload = enqueuePayload;
	uiBridge.getZipSubsetValidationState = validationState;
	uiBridge.applyZipSubsetPreview = applyPreview;
	safeExport("syncZipSubsetUiFromInputs", syncFromInputs);
	safeExport("getZipSubsetEnqueuePayload", enqueuePayload);
	safeExport("getZipSubsetValidationState", validationState);
	safeExport("applyZipSubsetPreview", (preview) =>
		applyPreview(/** @type {ZipSubsetPreview | null | undefined} */ (preview)),
	);
})();
