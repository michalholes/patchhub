(function () {
	/** @typedef {{action_id?: string, label?: string}} PatchHubEditorModalAction */
	/** @typedef {{
	 *   title?: string,
	 *   failure_class?: string,
	 *   failure_code?: string,
	 *   error_text?: string,
	 *   primary_id?: string,
	 *   secondary_id?: string,
	 *   actions?: PatchHubEditorModalAction[],
	 * }} PatchHubEditorModalFailure */
	/** @typedef {{onAction?: (actionId: string) => void, onClose?: () => void}} HelperCallbacks */
	/** @typedef {{onOk?: () => void, onCancel?: () => void}} UnsafeCallbacks */
	/** @typedef {{
	 *   openHelperModal: (failure: PatchHubEditorModalFailure, callbacks: HelperCallbacks) => void,
	 *   closeHelperModal: () => void,
	 *   openUnsafeModal: (callbacks: UnsafeCallbacks) => void,
	 *   closeUnsafeModal: () => void,
	 * }} PatchHubEditorModalApi */

	/** @param {string} id @returns {HTMLElement | null} */
	function byId(id) {
		return document.getElementById(id);
	}

	/** @param {HTMLElement | null} el @param {boolean} hidden */
	function setHidden(el, hidden) {
		if (!el) return;
		if (hidden) {
			el.setAttribute("hidden", "hidden");
			return;
		}
		el.removeAttribute("hidden");
	}

	/** @param {HTMLElement | null} el */
	function clearChildren(el) {
		while (el && el.firstChild) el.removeChild(el.firstChild);
	}

	/** @param {PatchHubEditorModalFailure} failure @param {HelperCallbacks} callbacks */
	function openHelperModal(failure, callbacks) {
		const modal = byId("editorHelperModal");
		const title = byId("editorHelperTitle");
		const body = byId("editorHelperBody");
		const actions = byId("editorHelperActions");
		const close = /** @type {HTMLButtonElement | null} */ (
			byId("editorHelperClose")
		);
		if (!modal || !title || !body || !actions || !close) return;
		title.textContent = String(failure.title || "Validation failed");
		clearChildren(body);
		const meta = document.createElement("div");
		meta.className = "editor-helper-meta";
		/** @type {Array<[string, string]>} */
		const rows = [
			["failure class", String(failure.failure_class || "")],
			["failure code", String(failure.failure_code || "")],
			["error", String(failure.error_text || "")],
			["primary object id", String(failure.primary_id || "")],
			["secondary object id", String(failure.secondary_id || "")],
		];
		rows.forEach(([label, value]) => {
			const wrap = document.createElement("div");
			const strong = document.createElement("strong");
			strong.textContent = `${label}: `;
			const code = document.createElement("code");
			code.textContent = value;
			wrap.appendChild(strong);
			wrap.appendChild(code);
			meta.appendChild(wrap);
		});
		body.appendChild(meta);
		clearChildren(actions);
		(Array.isArray(failure.actions) ? failure.actions : []).forEach((item) => {
			const button = document.createElement("button");
			button.type = "button";
			const actionId = String(item.action_id || "");
			button.textContent = String(item.label || actionId || "Action");
			button.dataset.actionId = actionId;
			button.addEventListener("click", () => callbacks.onAction?.(actionId));
			actions.appendChild(button);
		});
		close.onclick = () => {
			callbacks.onClose?.();
			setHidden(modal, true);
		};
		setHidden(modal, false);
	}

	function closeHelperModal() {
		setHidden(byId("editorHelperModal"), true);
	}

	/** @param {UnsafeCallbacks} callbacks */
	function openUnsafeModal(callbacks) {
		const modal = byId("editorUnsafeModal");
		const ok = /** @type {HTMLButtonElement | null} */ (byId("editorUnsafeOk"));
		const cancel = /** @type {HTMLButtonElement | null} */ (
			byId("editorUnsafeCancel")
		);
		if (!modal || !ok || !cancel) return;
		ok.onclick = () => {
			setHidden(modal, true);
			callbacks.onOk?.();
		};
		cancel.onclick = () => {
			setHidden(modal, true);
			callbacks.onCancel?.();
		};
		setHidden(modal, false);
	}

	function closeUnsafeModal() {
		setHidden(byId("editorUnsafeModal"), true);
	}

	/** @type {Window & typeof globalThis & { PatchHubEditorModal?: PatchHubEditorModalApi }} */
	const win = window;
	win.PatchHubEditorModal = {
		openHelperModal,
		closeHelperModal,
		openUnsafeModal,
		closeUnsafeModal,
	};
})();
