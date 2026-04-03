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

	/** @param {string} name @param {string} className @param {string | undefined} text */
	function el(name, className, text) {
		const node = document.createElement(name);
		if (className) node.className = className;
		if (text !== undefined) node.textContent = String(text);
		return node;
	}

	/** @param {string} label @param {string} value */
	function renderMetaCard(label, value) {
		const wrap = el("div", "editor-inline-card", undefined);
		wrap.appendChild(el("div", "editor-muted", label));
		wrap.appendChild(el("div", "", value || "-"));
		return wrap;
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
		title.textContent = String(failure.title || "Validation needs attention");
		clearChildren(body);
		const intro = el(
			"div",
			"editor-browser-subtitle",
			"Review the safest fix first. Alternative actions stay available below if you need them.",
		);
		body.appendChild(intro);
		const grid = el("div", "editor-helper-grid", undefined);
		grid.appendChild(
			renderMetaCard("Current problem", String(failure.failure_class || "")),
		);
		grid.appendChild(
			renderMetaCard("Technical reason", String(failure.failure_code || "")),
		);
		grid.appendChild(
			renderMetaCard("Main object", String(failure.primary_id || "")),
		);
		grid.appendChild(
			renderMetaCard("Related object", String(failure.secondary_id || "")),
		);
		body.appendChild(grid);
		if (failure.error_text) {
			body.appendChild(
				renderMetaCard("Validator message", String(failure.error_text || "")),
			);
		}
		clearChildren(actions);
		const available = Array.isArray(failure.actions) ? failure.actions : [];
		available.forEach((item, index) => {
			const actionId = String(item.action_id || "");
			const button = /** @type {HTMLButtonElement} */ (
				el(
					"button",
					index === 0 ? "editor-primary" : "",
					String(item.label || actionId || "Action"),
				)
			);
			button.type = "button";
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
