// @ts-nocheck
(function () {
	const state = {
		targetRepo: "",
		document: "specification",
		revisionToken: "",
		loadedIds: [],
		logEntries: [],
		currentFailure: null,
		currentHumanText: "",
		addTypeOptions: [],
		scaffolds: {},
		workspace: null,
		selectedObjectId: "",
		navigationQuery: "",
		navigationFilter: "all",
	};

	function byId(id) {
		return document.getElementById(id);
	}

	function textValue(id) {
		const el = byId(id);
		return el ? String(el.value || "") : "";
	}

	async function fetchJson(url, options) {
		const response = await fetch(url, options || {});
		return response.json();
	}

	function addLog(level, code, message) {
		state.logEntries.push({
			ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
			level,
			code,
			message: String(message || ""),
		});
		renderLog();
	}

	function appendOps(ops) {
		if (!Array.isArray(ops)) return;
		ops.forEach((op) => {
			if (!op) return;
			state.logEntries.push({
				ts: String(op.ts || ""),
				level: String(op.level || "Info"),
				code: String(op.code || ""),
				message: String(op.message || ""),
			});
		});
		renderLog();
	}

	function renderLog() {
		const level = textValue("editorOpsLevel") || "(all)";
		const lines = state.logEntries
			.filter((entry) => level === "(all)" || entry.level === level)
			.map(
				(entry) =>
					`${entry.ts} | ${entry.level} | ${entry.code} | ${entry.message}`,
			);
		byId("editorOpsLog").textContent = lines.join("\n");
	}

	function setStatus(text) {
		byId("editorStatus").textContent = String(text || "");
	}

	function setRevision(text) {
		byId("editorRevision").textContent = String(text || "");
	}

	function currentDocumentPath() {
		return state.document === "governance"
			? "governance/governance.jsonl"
			: "governance/specification.jsonl";
	}

	function updateStatusBoxes() {
		byId("editorStatusRepo").textContent = state.targetRepo;
		byId("editorStatusFile").textContent = currentDocumentPath();
		byId("editorDirtyState").textContent =
			textValue("editorBody") === state.currentHumanText ? "clean" : "dirty";
	}

	function payload(extra) {
		return {
			target_repo: state.targetRepo,
			document: state.document,
			revision_token: state.revisionToken,
			human_text: textValue("editorBody"),
			...(extra || {}),
		};
	}

	function updateAddTypeState() {
		const body = textValue("editorBody");
		const addType = byId("editorAddType");
		const addButton = byId("editorAddBlock");
		const hasMeta = /\n\[\[object\]\][\s\S]*?\ntype = "meta"\n/.test(
			"\n" + body,
		);
		const hasBindingMeta =
			/\n\[\[object\]\][\s\S]*?\ntype = "binding_meta"\n/.test("\n" + body);
		Array.from(addType.options).forEach((option) => {
			if (option.value === "meta") option.disabled = hasMeta;
			if (option.value === "binding_meta") option.disabled = hasBindingMeta;
		});
		if (addType.selectedOptions[0] && addType.selectedOptions[0].disabled) {
			const fallback = Array.from(addType.options).find(
				(option) => !option.disabled,
			);
			if (fallback) addType.value = fallback.value;
		}
		addButton.disabled = !addType.value || addType.selectedOptions[0].disabled;
	}

	function jumpToRawObject(objectId) {
		const body = byId("editorBody");
		const idText = String(objectId || "").trim();
		if (!body || !idText) return;
		const details = document.querySelector(".editor-advanced-raw");
		if (details) details.open = true;
		const text = body.value;
		const idNeedle = `id = "${idText}"`;
		const idIndex = text.indexOf(idNeedle);
		if (idIndex < 0) return;
		const blockIndex = text.lastIndexOf("[[object]]", idIndex);
		const start = blockIndex >= 0 ? blockIndex : idIndex;
		let end = text.indexOf("\n[[object]]", idIndex + idNeedle.length);
		if (end < 0) end = text.length;
		body.focus();
		body.setSelectionRange(start, end);
	}

	function focusObject(objectId) {
		state.selectedObjectId = String(objectId || "");
		if (state.workspace) {
			state.workspace.selected_id = state.selectedObjectId;
		}
		renderWorkspace();
		if (
			window.PatchHubEditorWorkspace &&
			window.PatchHubEditorWorkspace.focusSelection
		) {
			window.PatchHubEditorWorkspace.focusSelection(state.selectedObjectId);
		}
	}

	function renderWorkspace() {
		if (!window.PatchHubEditorWorkspace) return;
		if (state.workspace && state.selectedObjectId) {
			state.workspace.selected_id = state.selectedObjectId;
		}
		window.PatchHubEditorWorkspace.render({
			navRoot: byId("editorTaskFirst"),
			currentRoot: byId("editorCurrentWork"),
			safetyRoot: byId("editorSafetyPanel"),
			workspace: state.workspace || {},
			query: state.navigationQuery,
			filterValue: state.navigationFilter,
			onQueryChange(query) {
				state.navigationQuery = query;
				renderWorkspace();
			},
			onFilterChange(value) {
				state.navigationFilter = value;
				renderWorkspace();
			},
			onSelectObject(objectId) {
				focusObject(objectId);
			},
			onProblemFocus() {
				if (state.currentFailure && state.currentFailure.primary_id) {
					focusObject(state.currentFailure.primary_id);
					openFailureModal();
				}
			},
			onAddScaffold() {
				appendScaffold();
			},
			onOpenTechnical() {
				const details = document.querySelector(".editor-advanced-raw");
				if (details) details.open = true;
				jumpToRawObject(state.selectedObjectId);
			},
			onCheckImpact() {
				if (
					state.currentFailure &&
					Array.isArray(state.currentFailure.actions) &&
					state.currentFailure.actions[0]
				) {
					previewAction(
						String(state.currentFailure.actions[0].action_id || ""),
						String(state.currentFailure.primary_id || ""),
						String(state.currentFailure.secondary_id || ""),
					);
				}
			},
			onAction(actionId, primaryId, secondaryId) {
				previewAction(actionId, primaryId, secondaryId);
			},
		});
	}

	function syncWorkspaceFromResponse(data) {
		state.workspace = data.workspace || state.workspace;
		state.currentFailure =
			data.failure || (data.validation && data.validation.failure) || null;
		if (state.workspace && state.workspace.selected_id) {
			state.selectedObjectId = String(state.workspace.selected_id || "");
		}
		renderWorkspace();
	}

	function updateFromDocument(data) {
		state.revisionToken = String(data.revision_token || "");
		state.loadedIds = Array.isArray(data.loaded_ids)
			? data.loaded_ids.slice()
			: [];
		state.currentHumanText = String(data.human_text || "");
		byId("editorBody").value = state.currentHumanText;
		setRevision(state.revisionToken);
		setStatus(data.status || "Loaded");
		syncWorkspaceFromResponse(data);
		updateAddTypeState();
		updateStatusBoxes();
	}

	function safeJsonError(text) {
		try {
			return JSON.parse(String(text || "{}"));
		} catch (_err) {
			return { error: String(text || "") };
		}
	}

	async function loadBootstrap() {
		const data = await fetchJson("/api/editor/bootstrap");
		const target = byId("editorTargetRepo");
		const addType = byId("editorAddType");
		state.addTypeOptions = Array.isArray(data.add_type_options)
			? data.add_type_options.slice()
			: [];
		state.scaffolds = data.scaffolds || {};
		state.targetRepo = String(data.target_repo || "");
		state.document = String(data.default_document || "specification");
		target.innerHTML = "";
		(data.target_repo_options || []).forEach((item) => {
			const option = document.createElement("option");
			option.value = String(item);
			option.textContent = String(item);
			target.appendChild(option);
		});
		if (!state.targetRepo) state.targetRepo = String(target.value || "");
		addType.innerHTML = "";
		state.addTypeOptions.forEach((item) => {
			const option = document.createElement("option");
			option.value = item;
			option.textContent = item;
			addType.appendChild(option);
		});
		target.value = state.targetRepo;
		byId("editorDocument").value = state.document;
		updateAddTypeState();
		updateStatusBoxes();
	}

	async function loadDocument() {
		addLog("Info", "LOAD_START", `Loading ${state.document}`);
		const query = new URLSearchParams({
			target_repo: state.targetRepo,
			document: state.document,
		});
		const data = await fetchJson(`/api/editor/document?${query.toString()}`);
		if (!data.ok) {
			const payload = safeJsonError(data.error);
			appendOps(payload.ops || []);
			addLog(
				"Error",
				"LOAD_FAIL",
				payload.error || data.error || "Load failed",
			);
			setStatus(payload.error || "Load failed");
			return;
		}
		appendOps(data.ops || []);
		updateFromDocument(data);
	}

	async function validateDocument() {
		const data = await fetchJson("/api/editor/validate", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(payload()),
		});
		appendOps(data.ops || []);
		syncWorkspaceFromResponse(data);
		if (data.validated) {
			state.revisionToken = String(data.revision_token || state.revisionToken);
			setRevision(state.revisionToken);
			setStatus("Validation passed");
			updateStatusBoxes();
			return true;
		}
		setStatus("Validation failed");
		updateStatusBoxes();
		openFailureModal();
		return false;
	}

	async function saveDocument() {
		const data = await fetchJson("/api/editor/save", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(payload()),
		});
		appendOps(data.ops || []);
		syncWorkspaceFromResponse(data);
		if (data.saved) {
			state.revisionToken = String(data.revision_token || state.revisionToken);
			state.currentHumanText = String(
				data.human_text || byId("editorBody").value,
			);
			byId("editorBody").value = state.currentHumanText;
			setRevision(state.revisionToken);
			setStatus("Saved");
			updateAddTypeState();
			updateStatusBoxes();
			return;
		}
		setStatus("Save failed");
		updateStatusBoxes();
		openFailureModal();
	}

	async function unsafeSaveDocument() {
		const data = await fetchJson("/api/editor/save_unsafe", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(payload({ confirm_unsafe_write: true })),
		});
		appendOps(data.ops || []);
		syncWorkspaceFromResponse(data);
		if (data.saved) {
			state.revisionToken = String(data.revision_token || state.revisionToken);
			state.currentHumanText = String(
				data.human_text || byId("editorBody").value,
			);
			byId("editorBody").value = state.currentHumanText;
			setRevision(state.revisionToken);
			setStatus("Unsafe save complete");
			updateAddTypeState();
			updateStatusBoxes();
			return;
		}
		setStatus("Unsafe save failed");
		updateStatusBoxes();
	}

	async function previewAction(actionId, primaryId, secondaryId) {
		if (!actionId) return;
		const jumpOnly =
			actionId === "jump_to_block" || actionId === "jump_to_conflict";
		if (jumpOnly) {
			focusObject(actionId === "jump_to_block" ? primaryId : secondaryId);
			jumpToRawObject(actionId === "jump_to_block" ? primaryId : secondaryId);
			return;
		}
		const data = await fetchJson("/api/editor/preview_action", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(
				payload({
					action_id: actionId,
					primary_id: String(primaryId || ""),
					secondary_id: String(secondaryId || ""),
				}),
			),
		});
		appendOps(data.ops || []);
		if (!data.ok) {
			setStatus(data.error || "Preview failed");
			return;
		}
		window.PatchHubEditorActionPreview.openPreviewModal(data.preview || {}, {
			onApply() {
				applyAction(actionId, primaryId, secondaryId);
				window.PatchHubEditorActionPreview.closePreviewModal();
			},
			onCancel() {},
		});
	}

	async function applyAction(actionId, primaryId, secondaryId) {
		const body = payload({
			action_id: actionId,
			primary_id: String(primaryId || ""),
			secondary_id: String(secondaryId || ""),
		});
		const data = await fetchJson("/api/editor/apply_fix", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(body),
		});
		appendOps(data.ops || []);
		syncWorkspaceFromResponse(data);
		if (data.ok) {
			byId("editorBody").value = String(
				data.human_text || byId("editorBody").value,
			);
			state.revisionToken = String(data.revision_token || state.revisionToken);
			setRevision(state.revisionToken);
			updateAddTypeState();
			setStatus(
				data.validation && data.validation.validated
					? "Fix applied"
					: "Fix applied, validate again",
			);
			updateStatusBoxes();
			if (data.validation && data.validation.validated) {
				window.PatchHubEditorModal.closeHelperModal();
			}
			return;
		}
		setStatus("Fix failed");
		openFailureModal();
	}

	function openFailureModal() {
		if (!state.currentFailure) return;
		focusObject(
			String(
				state.currentFailure.primary_id ||
					state.currentFailure.secondary_id ||
					"",
			),
		);
		window.PatchHubEditorModal.openHelperModal(state.currentFailure, {
			onClose() {
				state.currentFailure = null;
			},
			onAction(actionId) {
				previewAction(
					actionId,
					String(state.currentFailure.primary_id || ""),
					String(state.currentFailure.secondary_id || ""),
				);
			},
		});
	}

	function appendScaffold() {
		const type = textValue("editorAddType");
		const scaffold = state.scaffolds[type];
		if (!scaffold) return;
		const body = byId("editorBody");
		const prefix = body.value.trimEnd();
		body.value = `${prefix}\n\n${scaffold}`.replace(/^\n+/, "");
		updateAddTypeState();
		updateStatusBoxes();
		addLog("Info", "DIRTY_STATE", `Appended ${type}`);
	}

	function bindEvents() {
		byId("editorTargetRepo").addEventListener("change", async (event) => {
			state.targetRepo = String(event.target.value || "");
			await loadDocument();
		});
		byId("editorDocument").addEventListener("change", async (event) => {
			state.document = String(event.target.value || "specification");
			await loadDocument();
		});
		byId("editorReload").addEventListener("click", loadDocument);
		byId("editorValidate").addEventListener("click", validateDocument);
		byId("editorSave").addEventListener("click", saveDocument);
		byId("editorUnsafeSave").addEventListener("click", () => {
			addLog(
				"Warning",
				"UNSAFE_CONFIRM_OPEN",
				"Unsafe save confirmation opened",
			);
			window.PatchHubEditorModal.openUnsafeModal({
				onOk: unsafeSaveDocument,
				onCancel() {},
			});
		});
		byId("editorAddType").addEventListener("change", updateAddTypeState);
		byId("editorAddBlock").addEventListener("click", appendScaffold);
		byId("editorBody").addEventListener("input", () => {
			updateAddTypeState();
			updateStatusBoxes();
			addLog("Info", "DIRTY_STATE", "Document changed");
		});
		byId("editorOpsLevel").addEventListener("change", renderLog);
		byId("editorOpsCopy").addEventListener("click", async () => {
			await navigator.clipboard.writeText(
				byId("editorOpsLog").textContent || "",
			);
		});
		byId("editorOpsClear").addEventListener("click", () => {
			const level = textValue("editorOpsLevel") || "(all)";
			if (level === "(all)") {
				state.logEntries = [];
			} else {
				state.logEntries = state.logEntries.filter(
					(entry) => entry.level !== level,
				);
			}
			renderLog();
		});
	}

	async function main() {
		bindEvents();
		await loadBootstrap();
		await loadDocument();
	}

	window.addEventListener("load", () => {
		main().catch((error) => {
			addLog(
				"Error",
				"LOAD_FAIL",
				error && error.message ? error.message : String(error),
			);
			setStatus("Load failed");
		});
	});
})();
