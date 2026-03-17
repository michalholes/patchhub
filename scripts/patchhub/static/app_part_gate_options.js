/** @type {any} */
var __ph_w = /** @type {any} */ (window);
var PH = /** @type {any} */ (window).PH;

function phCall(name, ...args) {
	if (!PH || typeof PH.call !== "function") return undefined;
	return PH.call(name, ...args);
}

var gateOptionDefs = [
	{
		key: "compile_check",
		label: "Compile check",
		configRun: (value) => !!value,
		argvFor: (value) =>
			value ? ["--override", "compile_check=true"] : ["--no-compile-check"],
	},
	{
		key: "gates_skip_dont_touch",
		label: "Dont touch",
		configRun: (value) => !value,
		argvFor: (value) =>
			value
				? ["--skip-dont-touch"]
				: ["--override", "gates_skip_dont_touch=false"],
	},
	{
		key: "gates_skip_ruff",
		label: "Ruff",
		configRun: (value) => !value,
		argvFor: (value) =>
			value ? ["--skip-ruff"] : ["--override", "gates_skip_ruff=false"],
	},
	{
		key: "gates_skip_pytest",
		label: "Pytest",
		configRun: (value) => !value,
		argvFor: (value) =>
			value ? ["--skip-pytest"] : ["--override", "gates_skip_pytest=false"],
	},
	{
		key: "gates_skip_mypy",
		label: "Mypy",
		configRun: (value) => !value,
		argvFor: (value) =>
			value ? ["--skip-mypy"] : ["--override", "gates_skip_mypy=false"],
	},
	{
		key: "gates_skip_js",
		label: "JS",
		configRun: (value) => !value,
		argvFor: (value) =>
			value ? ["--skip-js"] : ["--override", "gates_skip_js=false"],
	},
	{
		key: "gates_skip_docs",
		label: "Docs",
		configRun: (value) => !value,
		argvFor: (value) =>
			value ? ["--skip-docs"] : ["--override", "gates_skip_docs=false"],
	},
	{
		key: "gates_skip_monolith",
		label: "Monolith",
		configRun: (value) => !value,
		argvFor: (value) =>
			value ? ["--skip-monolith"] : ["--override", "gates_skip_monolith=false"],
	},
	{
		key: "gates_skip_biome",
		label: "Biome",
		configRun: (value) => !value,
		argvFor: (value) =>
			value ? ["--skip-biome"] : ["--override", "gates_skip_biome=false"],
	},
	{
		key: "gates_skip_typescript",
		label: "Typescript",
		configRun: (value) => !value,
		argvFor: (value) =>
			value
				? ["--skip-typescript"]
				: ["--override", "gates_skip_typescript=false"],
	},
];

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

function gateOptionsRawDisabled(rawCommand) {
	return !!String(rawCommand || "").trim();
}

function gateOptionsModeSupported(mode, rawCommand) {
	var currentMode = String(mode || (el("mode") && el("mode").value) || "patch");
	if (gateOptionsRawDisabled(rawCommand)) return false;
	return (
		["patch", "finalize_live", "finalize_workspace", "rerun_latest"].indexOf(
			currentMode,
		) >= 0
	);
}

function gateOptionsReason(mode, rawCommand) {
	if (gateOptionsRawDisabled(rawCommand)) {
		return "Gate options are disabled when raw command is set";
	}
	if (!gateOptionsModeSupported(mode, rawCommand)) {
		return (
			"Gate options are available for patch, finalize_live, " +
			"finalize_workspace, and rerun_latest"
		);
	}
	return "";
}

function gateConfigValue(key) {
	var src = gateOptionsState.configValues || {};
	return !!src[key];
}

function gateEffectiveValue(key) {
	if (Object.hasOwn(gateOptionsState.overrides, key)) {
		return !!gateOptionsState.overrides[key];
	}
	return gateConfigValue(key);
}

function gateConfigRun(def) {
	return !!def.configRun(gateConfigValue(def.key));
}

function gateThisRun(def) {
	return !!def.configRun(gateEffectiveValue(def.key));
}

function normalizeGateConfigValues(values) {
	var raw = values && typeof values === "object" ? values : {};
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

function syncGateOptionsUi(preview) {
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

function applyGatePreview(preview) {
	var out = preview || {};
	var gateArgv = [];
	syncGateOptionsUi(out);
	if (gateOptionsModeSupported(out.mode, out.raw_command)) {
		gateArgv = gateOverrideArgv();
		out.gate_argv = gateArgv.slice();
	}
	return out;
}

function getGateOptionsEnqueuePayload(mode) {
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
			if (!r || r.ok === false) {
				gateOptionsState.error = String(
					(r && r.error) || "Cannot load gate options",
				);
				return;
			}
			gateOptionsState.configValues = normalizeGateConfigValues(r.values || {});
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

function setGateRunState(key, runEnabled) {
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
			var target = event && event.target ? event.target : null;
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

if (PH && typeof PH.register === "function") {
	PH.register("app_part_gate_options", {
		initGateOptionsUi,
		applyGatePreview,
		clearGateOverrides,
		getGateOptionsEnqueuePayload,
		syncGateOptionsUi,
		openGateOptionsModal,
	});
}
