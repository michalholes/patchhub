(function () {
	/** @typedef {{ id?: string, label?: string, description?: string, active?: boolean }} WorkspaceTask */
	/** @typedef {{ action_id?: string, label?: string }} WorkspaceAction */
	/** @typedef {{ label?: string, value?: string }} WorkspaceField */
	/** @typedef {{ kind?: string, title?: string, target_id?: string, target_title?: string }} WorkspaceRelationItem */
	/** @typedef {{ title?: string, items?: WorkspaceRelationItem[] }} WorkspaceRelationSection */
	/** @typedef {{
	 *   id?: string,
	 *   title?: string,
	 *   summary?: string,
	 *   kind_label?: string,
	 *   technical_id?: string,
	 *   local_fields?: WorkspaceField[],
	 *   manual_actions?: WorkspaceAction[],
	 *   relation_sections?: WorkspaceRelationSection[],
	 * }} WorkspaceSelected */
	/** @typedef {{ title?: string, summary?: string, failure_code?: string, actions?: WorkspaceAction[], primary_id?: string, secondary_id?: string }} WorkspaceProblem */
	/** @typedef {{ status?: string, headline?: string, summary?: string }} WorkspaceHealth */
	/** @typedef {{ id?: string, title?: string, subtitle?: string, kind_label?: string, search_text?: string, has_failure?: boolean, workflow_role?: boolean, has_inbound?: boolean, has_outbound?: boolean }} WorkspaceNavItem */
	/** @typedef {{ counts?: { objects?: number, problems?: number, workflow?: number }, items?: WorkspaceNavItem[] }} WorkspaceNavigation */
	/** @typedef {{
	 *   tasks?: WorkspaceTask[],
	 *   current_problem?: WorkspaceProblem | null,
	 *   navigation?: WorkspaceNavigation,
	 *   selected_id?: string,
	 *   selected?: WorkspaceSelected,
	 *   health?: WorkspaceHealth,
	 * }} WorkspaceData */
	/** @typedef {{
	 *   workspace?: WorkspaceData,
	 *   navRoot?: HTMLElement | null,
	 *   currentRoot?: HTMLElement | null,
	 *   safetyRoot?: HTMLElement | null,
	 *   query?: string,
	 *   filterValue?: string,
	 *   onProblemFocus?: () => void,
	 *   onAddScaffold?: () => void,
	 *   onOpenTechnical?: () => void,
	 *   onCheckImpact?: () => void,
	 *   onQueryChange?: (value: string) => void,
	 *   onFilterChange?: (value: string) => void,
	 *   onSelectObject?: (value: string) => void,
	 *   onAction?: (actionId: string, primaryId: string, secondaryId: string) => void,
	 * }} WorkspaceRenderConfig */
	/** @typedef {{ render: (config: WorkspaceRenderConfig) => void, focusSelection: (selectedId: string) => void }} PatchHubEditorWorkspaceApi */

	/** @param {string} id @returns {HTMLElement | null} */
	function byId(id) {
		return document.getElementById(id);
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

	/** @param {string} label @param {string} className @param {() => void} onClick */
	function button(label, className, onClick) {
		const node = /** @type {HTMLButtonElement} */ (
			el("button", className, label)
		);
		node.type = "button";
		node.addEventListener("click", onClick);
		return node;
	}

	/** @param {HTMLElement | null} root @param {WorkspaceData} workspace @param {WorkspaceRenderConfig} callbacks */
	function renderTasks(root, workspace, callbacks) {
		clear(root);
		if (!root) return;
		const stack = el("div", "editor-task-stack", undefined);
		const title = el("div", "editor-section-title", "Start from the task");
		stack.appendChild(title);
		(workspace.tasks || []).forEach((task) => {
			const item = button(
				String(task.label || "Action"),
				`editor-task-button${task.active ? " is-active" : ""}`,
				() => {
					if (task.id === "fix_problem" && workspace.current_problem) {
						callbacks.onProblemFocus?.();
						return;
					}
					if (task.id === "add_safely") callbacks.onAddScaffold?.();
					if (task.id === "rename_relink") callbacks.onOpenTechnical?.();
					if (task.id === "check_impact") callbacks.onCheckImpact?.();
				},
			);
			item.appendChild(
				el("div", "editor-browser-subtitle", task.description || ""),
			);
			stack.appendChild(item);
		});
		const counts =
			workspace.navigation && workspace.navigation.counts
				? workspace.navigation.counts
				: {};
		const chips = el("div", "editor-chip-row", undefined);
		chips.appendChild(
			el("div", "editor-chip", `Objects: ${counts.objects || 0}`),
		);
		chips.appendChild(
			el(
				"div",
				`editor-chip ${counts.problems || 0 ? "is-bad" : "is-good"}`,
				`Problems: ${counts.problems || 0}`,
			),
		);
		chips.appendChild(
			el("div", "editor-chip", `Workflow: ${counts.workflow || 0}`),
		);
		stack.appendChild(chips);

		const browser = el("div", "editor-list-card", undefined);
		browser.appendChild(
			el("div", "editor-section-title", "Find what you need"),
		);
		const searchRow = el("div", "editor-browser-search", undefined);
		const search = document.createElement("input");
		search.type = "search";
		search.placeholder = "Search by meaning, id, or type";
		search.value = callbacks.query || "";
		search.addEventListener("input", (event) => {
			const target = /** @type {HTMLInputElement} */ (event.target);
			callbacks.onQueryChange?.(String(target.value || ""));
		});
		searchRow.appendChild(search);
		const filter = document.createElement("select");
		[
			["all", "All items"],
			["problem", "Current problem"],
			["workflow", "Workflow"],
			["inbound", "Has inbound links"],
			["outbound", "Has outbound links"],
		].forEach(([value, label]) => {
			const option = document.createElement("option");
			option.value = value;
			option.textContent = label;
			if (callbacks.filterValue === value) option.selected = true;
			filter.appendChild(option);
		});
		filter.addEventListener("change", (event) => {
			const target = /** @type {HTMLSelectElement} */ (event.target);
			callbacks.onFilterChange?.(String(target.value || "all"));
		});
		searchRow.appendChild(filter);
		browser.appendChild(searchRow);
		const list = el("div", "editor-browser-list", undefined);
		const items = (workspace.navigation && workspace.navigation.items) || [];
		const query = String(callbacks.query || "").toLowerCase();
		const filterValue = String(callbacks.filterValue || "all");
		items
			.filter(
				(item) => !query || String(item.search_text || "").includes(query),
			)
			.filter((item) => {
				if (filterValue === "problem") return !!item.has_failure;
				if (filterValue === "workflow") return !!item.workflow_role;
				if (filterValue === "inbound") return !!item.has_inbound;
				if (filterValue === "outbound") return !!item.has_outbound;
				return true;
			})
			.forEach((item) => {
				const node = button(
					String(item.title || "Item"),
					`editor-browser-item${
						item.id === workspace.selected_id ? " is-selected" : ""
					}${item.has_failure ? " is-problem" : ""}`,
					() => callbacks.onSelectObject?.(String(item.id || "")),
				);
				node.dataset.objectId = String(item.id || "");
				node.appendChild(
					el(
						"div",
						"editor-browser-subtitle",
						`${item.kind_label || "Item"} - ${item.subtitle || ""}`,
					),
				);
				list.appendChild(node);
			});
		browser.appendChild(list);
		stack.appendChild(browser);
		root.appendChild(stack);
	}

	/** @param {HTMLElement | null} root @param {WorkspaceData} workspace @param {WorkspaceRenderConfig} callbacks */
	function renderCurrent(root, workspace, callbacks) {
		clear(root);
		if (!root) return;
		const selected = workspace.selected || {};
		const section = el("div", "editor-section-stack", undefined);
		const title = el(
			"div",
			"editor-section-title",
			selected.title || "Current work",
		);
		section.appendChild(title);
		section.appendChild(
			el("div", "editor-browser-subtitle", selected.summary || ""),
		);
		const headerCard = el("div", "editor-card", undefined);
		headerCard.appendChild(
			el("div", "editor-muted", selected.kind_label || ""),
		);
		headerCard.appendChild(
			el(
				"div",
				"editor-muted",
				`Technical id: ${selected.technical_id || "-"}`,
			),
		);
		section.appendChild(headerCard);

		const fieldsCard = el("div", "editor-card", undefined);
		fieldsCard.appendChild(el("div", "editor-section-title", "Local details"));
		const fieldGrid = el("div", "editor-field-grid", undefined);
		(selected.local_fields || []).forEach((field) => {
			fieldGrid.appendChild(
				el("div", "editor-field-value-label", field.label || ""),
			);
			fieldGrid.appendChild(el("div", "", field.value || ""));
		});
		fieldsCard.appendChild(fieldGrid);
		section.appendChild(fieldsCard);

		const actionsCard = el("div", "editor-card", undefined);
		actionsCard.appendChild(
			el("div", "editor-section-title", "Relation-aware actions"),
		);
		actionsCard.appendChild(
			el(
				"div",
				"editor-field-note",
				"Preview the consequence before applying the change.",
			),
		);
		const manual = el("div", "editor-manual-actions", undefined);
		(selected.manual_actions || []).forEach((action) => {
			manual.appendChild(
				button(String(action.label || "Action"), "editor-manual-action", () =>
					callbacks.onAction?.(
						String(action.action_id || ""),
						String(selected.id || ""),
						"",
					),
				),
			);
		});
		actionsCard.appendChild(manual);
		section.appendChild(actionsCard);

		(selected.relation_sections || []).forEach((group) => {
			const card = el("div", "editor-card", undefined);
			card.appendChild(
				el("div", "editor-section-title", group.title || "Related items"),
			);
			const relationGrid = el("div", "editor-relation-grid", undefined);
			(group.items || []).forEach((item) => {
				const node = button(
					String(item.target_title || "Related item"),
					"editor-browser-item",
					() => callbacks.onSelectObject?.(String(item.target_id || "")),
				);
				node.appendChild(
					el(
						"div",
						"editor-browser-subtitle",
						`${item.kind || "relation"} - ${item.title || ""}`,
					),
				);
				relationGrid.appendChild(node);
			});
			card.appendChild(relationGrid);
			section.appendChild(card);
		});
		root.appendChild(section);
	}

	/** @param {HTMLElement | null} root @param {WorkspaceData} workspace @param {WorkspaceRenderConfig} callbacks */
	function renderSafety(root, workspace, callbacks) {
		clear(root);
		if (!root) return;
		const stack = el("div", "editor-safety-stack", undefined);
		const health = workspace.health || {};
		const healthCard = el("div", "editor-card", undefined);
		healthCard.appendChild(
			el("div", "editor-section-title", health.headline || "Workspace health"),
		);
		healthCard.appendChild(
			el("div", "editor-browser-subtitle", health.summary || ""),
		);
		const badge = el(
			"div",
			`editor-chip ${
				health.status === "healthy"
					? "is-good"
					: health.status === "problem"
						? "is-bad"
						: "is-warn"
			}`,
			`State: ${health.status || "unknown"}`,
		);
		healthCard.appendChild(badge);
		stack.appendChild(healthCard);

		if (workspace.current_problem) {
			const problem = workspace.current_problem;
			const card = el("div", "editor-card", undefined);
			card.appendChild(
				el("div", "editor-section-title", problem.title || "Current problem"),
			);
			card.appendChild(el("div", "editor-problem-text", problem.summary || ""));
			if (problem.failure_code) {
				card.appendChild(
					el(
						"div",
						"editor-muted",
						`Technical reason: ${problem.failure_code}`,
					),
				);
			}
			const actions = el("div", "editor-manual-actions", undefined);
			(problem.actions || []).forEach((action, index) => {
				const className =
					index === 0
						? "editor-problem-action editor-primary"
						: "editor-problem-action";
				actions.appendChild(
					button(String(action.label || "Action"), className, () =>
						callbacks.onAction?.(
							String(action.action_id || ""),
							String(problem.primary_id || ""),
							String(problem.secondary_id || ""),
						),
					),
				);
			});
			card.appendChild(actions);
			stack.appendChild(card);
		}

		const card = el("div", "editor-card", undefined);
		card.appendChild(
			el("div", "editor-section-title", "Need deeper technical detail?"),
		);
		card.appendChild(
			el(
				"div",
				"editor-browser-subtitle",
				"Use the advanced raw editor only when the guided surface is not enough.",
			),
		);
		card.appendChild(
			button("Open advanced raw editor", "editor-ghost", () =>
				callbacks.onOpenTechnical?.(),
			),
		);
		stack.appendChild(card);
		root.appendChild(stack);
	}

	/** @param {string} selectedId */
	function focusSelection(selectedId) {
		const node = document.querySelector(
			`[data-object-id="${CSS.escape(String(selectedId || ""))}"]`,
		);
		if (node && typeof node.scrollIntoView === "function") {
			node.scrollIntoView({ block: "nearest" });
		}
	}

	/** @param {WorkspaceRenderConfig} config */
	function render(config) {
		const workspace = config.workspace || {};
		renderTasks(config.navRoot || byId("editorTaskFirst"), workspace, config);
		renderCurrent(
			config.currentRoot || byId("editorCurrentWork"),
			workspace,
			config,
		);
		renderSafety(
			config.safetyRoot || byId("editorSafetyPanel"),
			workspace,
			config,
		);
	}

	/** @type {Window & typeof globalThis & { PatchHubEditorWorkspace?: PatchHubEditorWorkspaceApi }} */
	const win = window;
	win.PatchHubEditorWorkspace = { render, focusSelection };
})();
