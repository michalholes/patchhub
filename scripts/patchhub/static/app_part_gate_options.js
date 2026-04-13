/**
 * @typedef {{
 *   key: string,
 *   label: string,
 *   configRun: (value: boolean) => boolean,
 *   argvFor: (value: boolean) => string[],
 * }} GateOptionDef
 * @typedef {{
 *   configValues: Record<string, boolean> | null,
 *   overrides: Record<string, boolean>,
 *   modalOpen: boolean,
 *   loading: boolean,
 *   error: string,
 * }} GateOptionsState
 * @typedef {{
 *   mode?: string,
 *   raw_command?: string,
 *   gate_argv?: string[],
 *   error?: string,
 * }} GatePreview
 * @typedef {{ ok?: boolean, error?: string, values?: Record<string, unknown> }} GateOptionsConfigResponse
 * @typedef {{
 *   call?: function(string, ...*): *,
 *   register?: function(string, Object): void,
 * }} GateOptionsRuntime
 * @typedef {Window & typeof globalThis & { PH?: GateOptionsRuntime | null }} GateOptionsWindow
 * @typedef {EventTarget & { closest?: function(string): Element | null }} GateOptionsEventTarget
 */
var gateOptionsWindow = /** @type {GateOptionsWindow} */ (window);
var gateOptionsRuntime = gateOptionsWindow.PH || null;

function phCall(/** @type {string} */ name, /** @type {unknown[]} */ ...args) {
	if (!gateOptionsRuntime || typeof gateOptionsRuntime.call !== "function")
		return undefined;
	return gateOptionsRuntime.call(name, ...args);
}

/** @type {GateOptionDef[]} */
var gateOptionDefs = [
	{
		key: "compile_check",
		label: "Compile check",
		configRun: (/** @type {boolean} */ value) => !!value,
		argvFor: (/** @type {boolean} */ value) =>
			value ? ["--override", "compile_check=true"] : ["--no-compile-check"],
	},
	{
		key: "gates_skip_dont_touch",
		label: "Dont touch",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value
				? ["--skip-dont-touch"]
				: ["--override", "gates_skip_dont_touch=false"],
	},
	{
		key: "gates_skip_ruff",
		label: "Ruff",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value ? ["--skip-ruff"] : ["--override", "gates_skip_ruff=false"],
	},
	{
		key: "gates_skip_pytest",
		label: "Pytest",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value ? ["--skip-pytest"] : ["--override", "gates_skip_pytest=false"],
	},
	{
		key: "gates_skip_mypy",
		label: "Mypy",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value ? ["--skip-mypy"] : ["--override", "gates_skip_mypy=false"],
	},
	{
		key: "gates_skip_js",
		label: "JS",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value ? ["--skip-js"] : ["--override", "gates_skip_js=false"],
	},
	{
		key: "gates_skip_docs",
		label: "Docs",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value ? ["--skip-docs"] : ["--override", "gates_skip_docs=false"],
	},
	{
		key: "gates_skip_monolith",
		label: "Monolith",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value ? ["--skip-monolith"] : ["--override", "gates_skip_monolith=false"],
	},
	{
		key: "gates_skip_biome",
		label: "Biome",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value ? ["--skip-biome"] : ["--override", "gates_skip_biome=false"],
	},
	{
		key: "gates_skip_typescript",
		label: "Typescript",
		configRun: (/** @type {boolean} */ value) => !value,
		argvFor: (/** @type {boolean} */ value) =>
			value
				? ["--skip-typescript"]
				: ["--override", "gates_skip_typescript=false"],
	},
];

/** @type {GateOptionsState} */
var gateOptionsState = {
	configValues: null,
	overrides: {},
	modalOpen: false,
	loading: false,
	error: "",
};

function gateOptionsButton() {
	return el("gateOptionsBtn");
}

function gateOptionsBackdrop() {
	return el("gateOptionsModal");
}

function gateOptionsList() {
	return el("gateOptionsList");
}

function gateOptionsRawDisabled(/** @type {unknown} */ rawCommand) {
	return !!String(rawCommand || "").trim();
}

function gateOptionsModeSupported(
	/** @type {unknown} */ mode,
	/** @type {unknown} */ rawCommand,
) {
	var currentMode = String(mode || (el("mode") && el("mode").value) || "patch");
	if (gateOptionsRawDisabled(rawCommand)) return false;
	return (
		["patch", "finalize_live", "finalize_workspace", "rerun_latest"].indexOf(
			currentMode,
		) >= 0
	);
}

function gateOptionsReason(
	/** @type {unknown} */ mode,
	/** @type {unknown} */ rawCommand,
) {
	if (gateOptionsRawDisabled(rawCommand)) {
		return "Gate options are disabled when raw command is set";
	}
	if (!gateOptionsModeSupported(mode, rawCommand)) {
		return (
			"Gate options are available for patch, finalize_live, " +
			"finalize_workspace, and rerun_latest; rollback is unsupported"
		);
	}
	return "";
}

function gateConfigValue(/** @type {string} */ key) {
	var src = gateOptionsState.configValues || {};
	return !!src[key];
}

function gateEffectiveValue(/** @type {string} */ key) {
	if (Object.hasOwn(gateOptionsState.overrides, key)) {
		return !!gateOptionsState.overrides[key];
	}
	return gateConfigValue(key);
}

function gateConfigRun(/** @type {GateOptionDef} */ def) {
	return !!def.configRun(gateConfigValue(def.key));
}

function gateThisRun(/** @type {GateOptionDef} */ def) {
	return !!def.configRun(gateEffectiveValue(def.key));
}

function normalizeGateConfigValues(
	/** @type {Record<string, unknown> | null | undefined} */ values,
) {
	var raw = values && typeof values === "object" ? values : {};
	/** @type {Record<string, boolean>} */
	var out = {};
	var i;
	var def;
	for (i = 0; i < gateOptionDefs.length; i++) {
		def = gateOptionDefs[i];
		out[def.key] = !!raw[def.key];
	}
	return out;
}

function gateOverrideArgv() {
	/** @type {string[]} */
	var argv = [];
	var i;
	var def;
	var configValue;
	var effectiveValue;
	for (i = 0; i < gateOptionDefs.length; i++) {
		def = gateOptionDefs[i];
		configValue = gateConfigValue(def.key);
		effectiveValue = gateEffectiveValue(def.key);
		if (configValue === effectiveValue) continue;
		argv = argv.concat(def.argvFor(effectiveValue));
	}
	return argv;
}

function syncGateOptionsUi(/** @type {GatePreview} */ preview) {
	var btn = gateOptionsButton();
	if (!btn) return;
	var rawCommand =
		preview && preview.raw_command ? preview.raw_command : getRawCommand();
	var mode =
		preview && preview.mode
			? preview.mode
			: String(el("mode").value || "patch");
	var supported = gateOptionsModeSupported(mode, rawCommand);
	btn.disabled = !supported;
	btn.title = gateOptionsReason(mode, rawCommand);
}

function clearGateOverrides() {
	gateOptionsState.overrides = {};
	gateOptionsState.error = "";
	if (gateOptionsState.modalOpen) renderGateOptionsModal();
}

function applyGatePreview(
	/** @type {GatePreview | null | undefined} */ preview,
) {
	/** @type {GatePreview} */
	var out = preview || {};
	var gateArgv = [];
	syncGateOptionsUi(out);
	if (gateOptionsModeSupported(out.mode, out.raw_command)) {
		gateArgv = gateOverrideArgv();
		out.gate_argv = gateArgv.slice();
	}
	return out;
}

function getGateOptionsEnqueuePayload(/** @type {unknown} */ mode) {
	if (!gateOptionsModeSupported(mode, "")) return {};
	if (!gateOptionsState.configValues) {
		if (Object.keys(gateOptionsState.overrides).length) {
			return { error: "gate options config not loaded" };
		}
		return {};
	}
	return { gate_argv: gateOverrideArgv() };
}

function renderGateOptionsModal() {
	var list = gateOptionsList();
	var html = "";
	var i;
	var def;
	var configRun;
	var thisRun;
	var rowCls;
	if (!list) return;
	if (gateOptionsState.loading) {
		list.innerHTML = '<div class="muted">Loading...</div>';
		return;
	}
	if (gateOptionsState.error) {
		list.innerHTML =
			'<div class="muted">' + escapeHtml(gateOptionsState.error) + "</div>";
		return;
	}
	for (i = 0; i < gateOptionDefs.length; i++) {
		def = gateOptionDefs[i];
		configRun = gateConfigRun(def);
		thisRun = gateThisRun(def);
		rowCls =
			thisRun !== configRun ? " gate-options-row changed" : " gate-options-row";
		html += '<div class="' + rowCls + '">';
		html +=
			'<div class="gate-options-label">' + escapeHtml(def.label) + "</div>";
		html += '<div class="gate-options-state">';
		html += '<div class="gate-options-group">';
		html += '<button type="button" class="gate-options-switch';
		html += thisRun ? " is-on" : "";
		html +=
			'" data-gate-key="' +
			escapeHtml(def.key) +
			'" data-gate-run="' +
			(thisRun ? "false" : "true") +
			'" aria-label="' +
			escapeHtml(def.label + (thisRun ? ": RUN" : ": SKIP")) +
			'" aria-pressed="' +
			(thisRun ? "true" : "false") +
			'">';
		html += '<span class="gate-options-switch-track">';
		html += '<span class="gate-options-switch-thumb"></span>';
		html += "</span>";
		html += "</button>";
		html += "</div>";
		html += "</div>";
		html += "</div>";
	}
	list.innerHTML = html;
}

function closeGateOptionsModal() {
	gateOptionsState.modalOpen = false;
	var backdrop = gateOptionsBackdrop();
	if (backdrop) {
		backdrop.classList.add("hidden");
		backdrop.setAttribute("aria-hidden", "true");
	}
}

function openGateOptionsModal() {
	var mode = String((el("mode") && el("mode").value) || "patch");
	var rawCommand = getRawCommand();
	if (!gateOptionsModeSupported(mode, rawCommand)) {
		syncGateOptionsUi({ mode: mode, raw_command: rawCommand });
		return;
	}
	gateOptionsState.loading = true;
	gateOptionsState.error = "";
	gateOptionsState.modalOpen = true;
	renderGateOptionsModal();
	var backdrop = gateOptionsBackdrop();
	if (backdrop) {
		backdrop.classList.remove("hidden");
		backdrop.setAttribute("aria-hidden", "false");
	}
	apiGet("/api/amp/config")
		.then((r) => {
			var resp = /** @type {GateOptionsConfigResponse} */ (r);
			if (!resp || resp.ok === false) {
				gateOptionsState.error = String(
					(resp && resp.error) || "Cannot load gate options",
				);
				return;
			}
			gateOptionsState.configValues = normalizeGateConfigValues(
				resp.values || {},
			);
			gateOptionsState.error = "";
		})
		.catch((e) => {
			gateOptionsState.error = String(e || "Cannot load gate options");
		})
		.finally(() => {
			gateOptionsState.loading = false;
			renderGateOptionsModal();
		});
}

function setGateRunState(
	/** @type {string} */ key,
	/** @type {boolean} */ runEnabled,
) {
	var i;
	var def;
	var nextValue;
	for (i = 0; i < gateOptionDefs.length; i++) {
		def = gateOptionDefs[i];
		if (def.key !== key) continue;
		nextValue = def.key === "compile_check" ? !!runEnabled : !runEnabled;
		if (gateConfigValue(def.key) === nextValue) {
			delete gateOptionsState.overrides[def.key];
		} else {
			gateOptionsState.overrides[def.key] = nextValue;
		}
		renderGateOptionsModal();
		phCall("validateAndPreview");
		return;
	}
}

function initGateOptionsUi() {
	var openBtn = gateOptionsButton();
	if (openBtn) {
		openBtn.addEventListener("click", () => {
			openGateOptionsModal();
		});
	}
	var closeBtn = el("gateOptionsCloseBtn");
	if (closeBtn) {
		closeBtn.addEventListener("click", () => {
			closeGateOptionsModal();
		});
	}
	var cancelBtn = el("gateOptionsCancelBtn");
	if (cancelBtn) {
		cancelBtn.addEventListener("click", () => {
			closeGateOptionsModal();
		});
	}
	var backdrop = gateOptionsBackdrop();
	if (backdrop) {
		backdrop.addEventListener("click", (event) => {
			if (event && event.target === backdrop) closeGateOptionsModal();
		});
	}
	var list = gateOptionsList();
	if (list) {
		list.addEventListener("click", (event) => {
			var target = /** @type {GateOptionsEventTarget | null} */ (
				event && event.target ? event.target : null
			);
			var button =
				target && typeof target.closest === "function"
					? target.closest(".gate-options-switch")
					: null;
			var key;
			if (!button || !button.getAttribute) return;
			key = String(button.getAttribute("data-gate-key") || "");
			if (!key) return;
			setGateRunState(
				key,
				String(button.getAttribute("data-gate-run") || "") === "true",
			);
		});
	}
	syncGateOptionsUi({});
}

if (gateOptionsRuntime && typeof gateOptionsRuntime.register === "function") {
	const PH = gateOptionsRuntime;
	PH.register("app_part_gate_options", {
		initGateOptionsUi,
		applyGatePreview,
		clearGateOverrides,
		getGateOptionsEnqueuePayload,
		syncGateOptionsUi,
		openGateOptionsModal,
	});
}
