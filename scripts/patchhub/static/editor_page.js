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

	function payload() {
		return {
			target_repo: state.targetRepo,
			document: state.document,
			revision_token: state.revisionToken,
			human_text: textValue("editorBody"),
		};
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
		updateAddTypeState();
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
		if (!state.targetRepo) {
			state.targetRepo = String(target.value || "");
		}
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

	function safeJsonError(text) {
		try {
			return JSON.parse(String(text || "{}"));
		} catch (_err) {
			return { error: String(text || "") };
		}
	}

	async function validateDocument() {
		const data = await fetchJson("/api/editor/validate", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(payload()),
		});
		appendOps(data.ops || []);
		if (data.validated) {
			state.revisionToken = String(data.revision_token || state.revisionToken);
			setRevision(state.revisionToken);
			setStatus("Validation passed");
			return true;
		}
		state.currentFailure = data.failure || null;
		setStatus("Validation failed");
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
		if (data.saved) {
			state.revisionToken = String(data.revision_token || state.revisionToken);
			byId("editorBody").value = String(
				data.human_text || byId("editorBody").value,
			);
			setRevision(state.revisionToken);
			setStatus("Saved");
			updateAddTypeState();
			return;
		}
		state.currentFailure = data.failure || null;
		setStatus("Save failed");
		openFailureModal();
	}

	async function unsafeSaveDocument() {
		const data = await fetchJson("/api/editor/save_unsafe", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify(payload()),
		});
		appendOps(data.ops || []);
		if (data.saved) {
			state.revisionToken = String(data.revision_token || state.revisionToken);
			byId("editorBody").value = String(
				data.human_text || byId("editorBody").value,
			);
			setRevision(state.revisionToken);
			setStatus("Unsafe save complete");
			updateAddTypeState();
			return;
		}
		setStatus("Unsafe save failed");
		state.currentFailure = data.failure || null;
	}

	function openFailureModal() {
		if (!state.currentFailure) return;
		window.PatchHubEditorModal.openHelperModal(state.currentFailure, {
			onClose() {
				state.currentFailure = null;
			},
			async onAction(actionId) {
				if (actionId === "jump_to_block" || actionId === "jump_to_conflict") {
					const targetId =
						actionId === "jump_to_block"
							? state.currentFailure.primary_id
							: state.currentFailure.secondary_id;
					jumpToObject(targetId);
					return;
				}
				const body = {
					target_repo: state.targetRepo,
					document: state.document,
					revision_token: state.revisionToken,
					human_text: textValue("editorBody"),
					action_id: actionId,
					primary_id: String(state.currentFailure.primary_id || ""),
					secondary_id: String(state.currentFailure.secondary_id || ""),
				};
				const data = await fetchJson("/api/editor/apply_fix", {
					method: "POST",
					headers: { "content-type": "application/json" },
					body: JSON.stringify(body),
				});
				appendOps(data.ops || []);
				if (data.ok) {
					byId("editorBody").value = String(
						data.human_text || byId("editorBody").value,
					);
					state.revisionToken = String(
						data.revision_token || state.revisionToken,
					);
					setRevision(state.revisionToken);
					updateAddTypeState();
				}
				const validation = data.validation || {
					validated: false,
					failure: state.currentFailure,
				};
				if (validation.validated) {
					state.currentFailure = null;
					setStatus("Fix applied");
					window.PatchHubEditorModal.closeHelperModal();
					return;
				}
				state.currentFailure = validation.failure || null;
				openFailureModal();
			},
		});
	}

	function jumpToObject(objectId) {
		const body = byId("editorBody");
		const idText = String(objectId || "").trim();
		if (!body || !idText) return;
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

	function appendScaffold() {
		const type = textValue("editorAddType");
		const scaffold = state.scaffolds[type];
		if (!scaffold) return;
		const body = byId("editorBody");
		const prefix = body.value.trimEnd();
		body.value = `${prefix}\n\n${scaffold}`.replace(/^\n+/, "");
		updateAddTypeState();
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
