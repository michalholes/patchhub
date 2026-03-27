(() => {
	/**
	 * @typedef {{
	 *   onToggle?: (name: string, checked: boolean) => void,
	 *   onSelectAll?: () => void,
	 *   onClear?: () => void,
	 *   onReset?: () => void,
	 *   onCancel?: () => void,
	 *   onClose?: () => void,
	 *   onBackdrop?: () => void,
	 *   onApply?: () => void,
	 * }} ListModalController
	 * @typedef {{
	 *   call?: (name: string, ...args: unknown[]) => unknown,
	 *   has?: (name: string) => boolean,
	 *   register?: (name: string, exportsObj: Record<string, unknown>) => void,
	 * }} ListModalRuntime
	 * @typedef {Window & typeof globalThis & {
	 *   AMP_PATCHHUB_UI?: {
	 *     zipSubsetModalController?: ListModalController | null,
	 *     activeListModalController?: ListModalController | null,
	 *     renderZipSubsetModal?: (model: Record<string, unknown>) => void,
	 *     openZipSubsetModalView?: (model: Record<string, unknown>) => void,
	 *     closeZipSubsetModalView?: () => void,
	 *   },
	 *   PH?: ListModalRuntime | null,
	 * }} ListModalWindow
	 * @typedef {HTMLElement & {
	 *   value?: string,
	 *   checked?: boolean,
	 *   disabled?: boolean,
	 *   innerHTML: string,
	 *   textContent: string,
	 * }} ListModalElement
	 */
	var w = /** @type {ListModalWindow} */ (window);
	var ui = w.AMP_PATCHHUB_UI;
	if (!ui) {
		ui = {};
		w.AMP_PATCHHUB_UI = ui;
	}

	function el(id) {
		return /** @type {ListModalElement | null} */ (document.getElementById(id));
	}

	function escapeHtml(s) {
		return String(s || "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#39;");
	}

	function controller() {
		return ui.activeListModalController || ui.zipSubsetModalController || null;
	}

	function setVisible(on) {
		var node = el("zipSubsetModal");
		if (!node) return;
		node.classList.toggle("hidden", !on);
		node.setAttribute("aria-hidden", on ? "false" : "true");
	}

	function render(model) {
		var title = el("zipSubsetModalTitle");
		var subtitle = el("zipSubsetModalSubtitle");
		var list = el("zipSubsetModalList");
		var count = el("zipSubsetSelectionCount");
		var apply = el("zipSubsetApplyBtn");
		if (!title || !subtitle || !list || !count || !apply) return;

		var safeModel = model && typeof model === "object" ? model : {};
		var rows = Array.isArray(safeModel.rows) ? safeModel.rows : [];
		var html = rows
			.map((row) => {
				var entry = String(row && row.zip_member ? row.zip_member : "");
				var repo = String(row && row.repo_path ? row.repo_path : "");
				var checked = !!(row && row.checked === true);
				var disabled = !!(row && row.disabled === true);
				return (
					'<label class="zip-subset-item">' +
					'<input type="checkbox" class="zip-subset-check" data-zip-entry="' +
					escapeHtml(entry) +
					'" ' +
					(checked ? 'checked="checked" ' : "") +
					(disabled ? 'disabled="disabled" ' : "") +
					"/>" +
					'<span class="zip-subset-path">' +
					escapeHtml(repo || entry) +
					"</span>" +
					"</label>"
				);
			})
			.join("");

		title.textContent = String(safeModel.title || "Select target files");
		subtitle.textContent = String(
			safeModel.subtitle || "Contents of patch.zip",
		);
		count.textContent = String(safeModel.selection_count || "All 0 selected");
		apply.disabled = safeModel.apply_disabled === true;
		list.innerHTML = html || '<div class="muted">(no patch entries)</div>';
	}

	function open(model) {
		render(model);
		setVisible(true);
	}

	function close() {
		setVisible(false);
	}

	function bindEvents() {
		document.addEventListener("click", (ev) => {
			var target = ev && ev.target instanceof HTMLElement ? ev.target : null;
			var ctl = controller();
			if (!target || !ctl) return;
			if (target.id === "zipSubsetCloseBtn") {
				ctl.onClose && ctl.onClose();
				return;
			}
			if (target.id === "zipSubsetCancelBtn") {
				ctl.onCancel && ctl.onCancel();
				return;
			}
			if (target.id === "zipSubsetApplyBtn") {
				ctl.onApply && ctl.onApply();
				return;
			}
			if (target.id === "zipSubsetSelectAllBtn") {
				ctl.onSelectAll && ctl.onSelectAll();
				return;
			}
			if (target.id === "zipSubsetClearBtn") {
				ctl.onClear && ctl.onClear();
				return;
			}
			if (target.id === "zipSubsetResetBtn") {
				ctl.onReset && ctl.onReset();
			}
		});

		document.addEventListener("change", (ev) => {
			var target = ev && ev.target instanceof HTMLElement ? ev.target : null;
			var ctl = controller();
			if (!target || !ctl || !target.classList) return;
			if (!target.classList.contains("zip-subset-check")) return;
			var name = String(target.getAttribute("data-zip-entry") || "");
			if (!name) return;
			ctl.onToggle &&
				ctl.onToggle(
					name,
					!!(/** @type {HTMLInputElement} */ (target).checked),
				);
		});

		var backdrop = el("zipSubsetModal");
		if (backdrop) {
			backdrop.addEventListener("click", (ev) => {
				var ctl = controller();
				if (!ctl) return;
				if (ev.target === backdrop) ctl.onBackdrop && ctl.onBackdrop();
			});
		}
	}

	bindEvents();
	ui.renderZipSubsetModal = render;
	ui.openZipSubsetModalView = open;
	ui.closeZipSubsetModalView = close;

	var PH = w.PH;
	if (PH && typeof PH.register === "function") {
		PH.register("app_part_zip_subset_modal", {
			renderZipSubsetModal: render,
			openZipSubsetModalView: open,
			closeZipSubsetModalView: close,
		});
	}
})();
