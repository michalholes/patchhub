(function () {
	/** @typedef {{ title?: string, validated?: boolean, failure?: { title?: string } }} PatchHubPostValidation */
	/** @typedef {{
	 *   title?: string,
	 *   summary?: string,
	 *   consequences?: string[],
	 *   affected_objects?: string[],
	 *   post_validation?: PatchHubPostValidation,
	 * }} PatchHubActionPreview */
	/** @typedef {{ onApply?: () => void, onCancel?: () => void }} PatchHubPreviewCallbacks */
	/** @typedef {{
	 *   openPreviewModal: (preview: PatchHubActionPreview, callbacks: PatchHubPreviewCallbacks) => void,
	 *   closePreviewModal: () => void,
	 * }} PatchHubEditorActionPreviewApi */

	/** @param {string} id @returns {HTMLElement | null} */
	function byId(id) {
		return document.getElementById(id);
	}

	/** @param {HTMLElement | null} node @param {boolean} hidden */
	function setHidden(node, hidden) {
		if (!node) return;
		if (hidden) {
			node.setAttribute("hidden", "hidden");
			return;
		}
		node.removeAttribute("hidden");
	}

	/** @param {HTMLElement | null} node */
	function clear(node) {
		while (node && node.firstChild) {
			node.removeChild(node.firstChild);
		}
	}

	/** @param {string} name @param {string} className @param {string | undefined} text */
	function el(name, className, text) {
		const node = document.createElement(name);
		if (className) node.className = className;
		if (text !== undefined) node.textContent = String(text);
		return node;
	}

	/** @param {PatchHubActionPreview} preview @param {PatchHubPreviewCallbacks} callbacks */
	function openPreviewModal(preview, callbacks) {
		const modal = byId("editorPreviewModal");
		const title = byId("editorPreviewTitle");
		const body = byId("editorPreviewBody");
		const actions = byId("editorPreviewActions");
		const close = byId("editorPreviewClose");
		if (!modal || !title || !body || !actions || !close) return;
		title.textContent = String(preview.title || "Preview change");
		clear(body);
		const grid = el("div", "editor-preview-grid", undefined);
		const summary = el("div", "editor-inline-card", undefined);
		summary.appendChild(el("div", "editor-section-title", "What this will do"));
		summary.appendChild(
			el("div", "editor-browser-subtitle", preview.summary || ""),
		);
		(preview.consequences || []).forEach((item) => {
			summary.appendChild(el("div", "", `- ${item}`));
		});
		grid.appendChild(summary);
		const impact = el("div", "editor-inline-card", undefined);
		impact.appendChild(el("div", "editor-section-title", "Affected items"));
		(preview.affected_objects || []).forEach((item) => {
			impact.appendChild(el("div", "", item));
		});
		const post = preview.post_validation || {};
		impact.appendChild(
			el(
				"div",
				"editor-muted",
				`Validation after apply: ${post.validated ? "passes" : "still needs attention"}`,
			),
		);
		if (post.failure && post.failure.title) {
			impact.appendChild(
				el("div", "editor-muted", `Follow-up: ${post.failure.title}`),
			);
		}
		grid.appendChild(impact);
		body.appendChild(grid);
		clear(actions);
		const apply = /** @type {HTMLButtonElement} */ (
			el("button", "editor-primary", "Apply this change")
		);
		apply.type = "button";
		apply.addEventListener("click", () => callbacks.onApply?.());
		actions.appendChild(apply);
		const cancel = /** @type {HTMLButtonElement} */ (
			el("button", "", "Cancel")
		);
		cancel.type = "button";
		cancel.addEventListener("click", () => {
			callbacks.onCancel?.();
			setHidden(modal, true);
		});
		actions.appendChild(cancel);
		close.onclick = () => {
			callbacks.onCancel?.();
			setHidden(modal, true);
		};
		setHidden(modal, false);
	}

	function closePreviewModal() {
		setHidden(byId("editorPreviewModal"), true);
	}

	/** @type {Window & typeof globalThis & { PatchHubEditorActionPreview?: PatchHubEditorActionPreviewApi }} */
	const win = window;
	win.PatchHubEditorActionPreview = { openPreviewModal, closePreviewModal };
})();
