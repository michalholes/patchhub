(() => {
	var w = /** @type {any} */ (window);
	var ui = w.AMP_PATCHHUB_UI;
	if (!ui) {
		ui = {};
		w.AMP_PATCHHUB_UI = ui;
	}

	var PH = w.PH;

	function phCall(name, ...args) {
		if (!PH || typeof PH.call !== "function") return undefined;
		return PH.call(name, ...args);
	}

	var state = {
		key: "",
		loading: false,
		manifest: null,
		committedSelected: {},
		draftSelected: {},
		modalOpen: false,
		error: "",
	};

	function el(id) {
		return /** @type {any} */ (document.getElementById(id));
	}

	function escapeHtml(s) {
		return String(s || "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#39;");
	}

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

	function manifestEntries() {
		var manifest = state.manifest || {};
		return Array.isArray(manifest.entries) ? manifest.entries : [];
	}

	function selectionMap(kind) {
		return kind === "draft" ? state.draftSelected : state.committedSelected;
	}

	function ensureSelectionDefaults(kind) {
		var selected = selectionMap(kind);
		manifestEntries().forEach((item) => {
			var name = String(item && item.zip_member ? item.zip_member : "");
			if (!name || item.selectable !== true) return;
			if (!Object.hasOwn(selected, name)) {
				selected[name] = true;
			}
		});
	}

	function resetSelectionToAll(kind) {
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
		state.draftSelected = Object.assign({}, state.committedSelected);
		ensureSelectionDefaults("draft");
	}

	function clearDraftSelection() {
		var next = {};
		manifestEntries().forEach((item) => {
			var name = String(item && item.zip_member ? item.zip_member : "");
			if (!name || item.selectable !== true) return;
			next[name] = false;
		});
		state.draftSelected = next;
	}

	function selectedEntries(kind) {
		var selected = selectionMap(kind || "committed");
		var out = [];
		manifestEntries().forEach((item) => {
			var name = String(item && item.zip_member ? item.zip_member : "");
			if (!name || item.selectable !== true) return;
			if (selected[name] !== false) out.push(name);
		});
		return out;
	}

	function selectedRepoPaths(kind) {
		var selected = selectionMap(kind || "committed");
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

	function setStripAction(action, title) {
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

	function fetchManifestForCurrentPath() {
		var patchPath = currentPatchPath();
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
			state.loading = false;
			if (!r || r.ok === false || !r.manifest) {
				state.error = String((r && r.error) || "cannot inspect zip patch");
				state.manifest = null;
				phCall("clearPmValidationPayload");
				renderStrip();
				phCall("validateAndPreview");
				return;
			}
			state.manifest = r.manifest;
			phCall("setPmValidationPayload", r.pm_validation || null);
			resetSelectionToAll("committed");
			state.draftSelected = {};
			renderStrip();
			if (state.modalOpen) renderModal();
			phCall("validateAndPreview");
		});
	}

	function syncFromInputs() {
		if (!isPatchZipMode()) {
			clearState();
			return;
		}
		var key = currentMode() + "|" + currentPatchPath();
		if (state.key !== key) {
			state.key = key;
			fetchManifestForCurrentPath();
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

	function applyPreview(preview) {
		if (!preview || typeof preview !== "object") return preview;
		if (!state.manifest || !isPatchZipMode()) return preview;
		var selected = selectedEntries("committed");
		preview.zip_subset = {
			selectable: state.manifest.selectable === true,
			selection_status: selectionStatusText(),
			selected_patch_entries: selected,
			selected_repo_paths: selectedRepoPaths("committed"),
			effective_patch_kind:
				selected.length < selectableCount()
					? "derived_subset_pending"
					: "original",
		};
		return preview;
	}

	function handleStripAction(target) {
		var box =
			target && typeof target.closest === "function"
				? target.closest("#zipSubsetStrip")
				: null;
		if (!box) return false;
		var action = String(box.dataset.action || "");
		if (action === "open") {
			openModal();
			return true;
		}
		if (action === "retry") {
			fetchManifestForCurrentPath();
			return true;
		}
		return false;
	}

	function bindEvents() {
		document.addEventListener("click", (ev) => {
			var t = /** @type {any} */ (ev && ev.target ? ev.target : null);
			if (!t) return;
			handleStripAction(t);
		});
		document.addEventListener("keydown", (ev) => {
			var t = /** @type {any} */ (ev && ev.target ? ev.target : null);
			if (!t) return;
			if (ev.key !== "Enter" && ev.key !== " ") return;
			if (!handleStripAction(t)) return;
			ev.preventDefault();
		});
	}

	ui.zipSubsetModalController = {
		onToggle(name, checked) {
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
	ui.syncZipSubsetUiFromInputs = syncFromInputs;
	ui.getZipSubsetEnqueuePayload = enqueuePayload;
	ui.getZipSubsetValidationState = validationState;
	ui.applyZipSubsetPreview = applyPreview;
	safeExport("syncZipSubsetUiFromInputs", syncFromInputs);
	safeExport("getZipSubsetEnqueuePayload", enqueuePayload);
	safeExport("getZipSubsetValidationState", validationState);
	safeExport("applyZipSubsetPreview", applyPreview);
})();
