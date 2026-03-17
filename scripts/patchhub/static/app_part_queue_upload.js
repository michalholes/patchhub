/** @type {any} */
var __ph_w = /** @type {any} */ (window);
var PH = /** @type {any} */ (window).PH;

function phCall(name, ...args) {
	if (!PH || typeof PH.call !== "function") return undefined;
	return PH.call(name, ...args);
}
function setStartFormState(state) {
	var issueEnabled = !!(state && state.issue_id);
	var msgEnabled = !!(state && state.commit_message);
	var patchEnabled = !!(state && state.patch_path);

	el("issueId").disabled = !issueEnabled;
	el("commitMsg").disabled = !msgEnabled;
	el("patchPath").disabled = !patchEnabled;
	var browse = el("browsePatch");
	if (browse) browse.disabled = !patchEnabled;
}

function validateAndPreview() {
	var mode = String(el("mode").value || "patch");
	var issueId = String(el("issueId").value || "").trim();
	var commitMsg = String(el("commitMsg").value || "").trim();
	var patchPath = normalizePatchPath(String(el("patchPath").value || ""));
	el("patchPath").value = patchPath;

	var raw = getRawCommand();
	PH.call("syncZipSubsetUiFromInputs");

	var modeRules = null;
	if (mode === "patch") {
		modeRules = { issue_id: true, commit_message: true, patch_path: true };
	} else if (mode === "finalize_live") {
		modeRules = { issue_id: false, commit_message: true, patch_path: false };
	} else if (mode === "finalize_workspace") {
		modeRules = { issue_id: true, commit_message: false, patch_path: false };
	} else if (mode === "rerun_latest") {
		modeRules = { issue_id: true, commit_message: true, patch_path: true };
	} else {
		modeRules = { issue_id: true, commit_message: true, patch_path: true };
	}
	setStartFormState(modeRules);

	var ok = true;

	var canonical = null;
	var preview = null;
	var gatePayload = {};

	if (raw) {
		ok = !parseInFlight && !!lastParsed && lastParsedRaw === raw;
		if (ok) {
			const p = lastParsed.parsed || {};
			const c = lastParsed.canonical || {};
			canonical = c.argv ? c.argv : [];
			const pMode = p.mode ? p.mode : mode;
			const pIssue = p.issue_id ? p.issue_id : issueId;
			const pMsg = p.commit_message ? p.commit_message : commitMsg;
			const pPatch = p.patch_path ? p.patch_path : patchPath;
			preview = {
				mode: pMode,
				issue_id: pIssue,
				commit_message: pMsg,
				patch_path: pPatch,
				canonical_argv: canonical,
				raw_command: raw,
			};
		} else {
			canonical = [];
			preview = {
				mode: mode,
				issue_id: issueId,
				commit_message: commitMsg,
				patch_path: patchPath,
				canonical_argv: canonical,
				raw_command: raw,
				parse_status: parseInFlight ? "parsing" : "needs_parse",
			};
		}
	} else {
		if (mode === "patch") {
			ok = !!commitMsg && !!patchPath;
		} else if (mode === "finalize_live") {
			ok = !!commitMsg;
		} else if (mode === "finalize_workspace") {
			ok = !!issueId && /^[0-9]+$/.test(issueId);
		} else if (mode === "rerun_latest") {
			ok = !!commitMsg && !!issueId && /^[0-9]+$/.test(issueId);
		}

		gatePayload = phCall("getGateOptionsEnqueuePayload", mode) || {};
		canonical =
			phCall(
				"computeCanonicalPreview",
				mode,
				issueId,
				commitMsg,
				patchPath,
				gatePayload.gate_argv || [],
			) || [];
		preview = {
			mode: mode,
			issue_id: issueId,
			commit_message: commitMsg,
			patch_path: patchPath,
			canonical_argv: canonical,
		};
	}
	preview = PH.call("applyZipSubsetPreview", preview) || preview;
	preview = PH.call("applyGatePreview", preview) || preview;
	var subsetState = PH.call("getZipSubsetValidationState") || {
		ok: true,
		hint: "",
	};
	if (subsetState.ok === false) ok = false;
	setPre("previewRight", preview);
	el("enqueueBtn").disabled = !ok;

	var enqueueHint = "";
	if (!raw) {
		if (ok) {
			enqueueHint = "";
		} else if (subsetState && subsetState.hint) {
			enqueueHint = String(subsetState.hint || "");
		} else if (mode === "finalize_live") {
			enqueueHint = "missing message";
		} else if (mode === "finalize_workspace") {
			enqueueHint = "missing issue id";
		} else if (mode === "rerun_latest") {
			enqueueHint = "missing issue id or message";
		} else if (mode === "patch") {
			enqueueHint = "missing commit message or patch path";
		} else {
			enqueueHint = "missing fields";
		}
	}
	setInfoPoolHint("enqueue", enqueueHint);
	tickMissingPatchClear({
		mode:
			document.hidden || !PH.call("hasTrackedActiveJob") ? "idle" : "active",
	});
}

function enqueue() {
	var mode = String(el("mode").value || "patch");
	var subsetPayload = {};
	var body = {
		mode: mode,
		raw_command: el("rawCommand")
			? String(el("rawCommand").value || "").trim()
			: "",
	};

	setUiStatus("enqueue: started mode=" + mode);

	if (mode === "patch") {
		body.issue_id = String(el("issueId").value || "").trim();
		body.commit_message = String(el("commitMsg").value || "").trim();
		body.patch_path = normalizePatchPath(
			String(el("patchPath").value || "").trim(),
		);
		subsetPayload = PH.call("getZipSubsetEnqueuePayload") || {};
		if (subsetPayload.error) {
			setUiError(String(subsetPayload.error || "invalid zip subset state"));
			return;
		}
		if (Array.isArray(subsetPayload.selected_patch_entries)) {
			body.selected_patch_entries =
				subsetPayload.selected_patch_entries.slice();
		}
	} else if (mode === "finalize_live") {
		body.commit_message = String(el("commitMsg").value || "").trim();
	} else if (mode === "finalize_workspace") {
		body.issue_id = String(el("issueId").value || "").trim();
	} else if (mode === "rerun_latest") {
		body.issue_id = String(el("issueId").value || "").trim();
		body.commit_message = String(el("commitMsg").value || "").trim();
		body.patch_path = normalizePatchPath(
			String(el("patchPath").value || "").trim(),
		);
	}
	var gatePayload = PH.call("getGateOptionsEnqueuePayload", mode) || {};
	if (gatePayload.error) {
		setUiError(String(gatePayload.error || "invalid gate options state"));
		return;
	}
	if (Array.isArray(gatePayload.gate_argv) && gatePayload.gate_argv.length) {
		body.gate_argv = gatePayload.gate_argv.slice();
	}

	apiPost("/api/jobs/enqueue", body).then((r) => {
		pushApiStatus(r);
		setPre("previewRight", r);
		if (r && r.ok !== false && r.job_id) {
			PH.call("clearGateOverrides");
			setUiStatus("enqueue: ok job_id=" + String(r.job_id));
			selectedJobId = String(r.job_id);
			try {
				window.__ph_last_enqueued_job_id = selectedJobId;
				window.__ph_last_enqueued_mode = String(el("mode") && el("mode").value);
			} catch (_) {}
			AMP_UI.saveLiveJobId(selectedJobId);
			suppressIdleOutput = false;
			PH.call("openLiveStream", selectedJobId);
		} else {
			setUiError(String((r && r.error) || "enqueue failed"));
		}
		phCall("refreshJobs");
	});
}

function uploadFile(file) {
	var fd = new FormData();
	fd.append("file", file);
	setUiStatus("upload: started " + String((file && file.name) || ""));
	fetch("/api/upload/patch", {
		method: "POST",
		body: fd,
		headers: { Accept: "application/json" },
	})
		.then((r) =>
			r.text().then((t) => {
				try {
					return JSON.parse(t);
				} catch (e) {
					return {
						ok: false,
						error: "bad json",
						raw: t,
						status: r.status,
					};
				}
			}),
		)
		.then((j) => {
			pushApiStatus(j);
			setInfoPoolHint(
				"upload",
				j && j.ok
					? "Uploaded: " + String(j.stored_rel_path || "")
					: "Upload failed: " + String((j && j.error) || ""),
			);
			if (j && j.ok) {
				setUiStatus("upload: ok");
			} else {
				setUiError(String((j && j.error) || "upload failed"));
			}
			if (j && j.stored_rel_path) {
				const stored = String(j.stored_rel_path);
				const n = el("patchPath");
				if (n && shouldOverwrite("patchPath", n)) {
					n.value = stored;
				}

				const relUnderRoot = stripPatchesPrefix(stored);
				const parent = parentRel(relUnderRoot);
				if (String(el("fsPath").value || "") === "") {
					el("fsPath").value = parent;
				}
			}
			phCall("applyAutofillFromPayload", j);
			refreshFs();
		})
		.catch((e) => {
			setPre("uploadResult", String(e));
			setInfoPoolHint("upload", "Upload failed: " + String(e));
			setUiError(String(e));
		});
}

function enableGlobalDropOverlay() {
	var counter = 0;

	function show() {
		document.body.classList.add("dragging");
	}
	function hide() {
		document.body.classList.remove("dragging");
	}

	document.addEventListener("dragenter", (e) => {
		e.preventDefault();
		counter += 1;
		show();
	});

	document.addEventListener("dragover", (e) => {
		e.preventDefault();
		show();
	});

	document.addEventListener("dragleave", (e) => {
		e.preventDefault();
		counter -= 1;
		if (counter <= 0) {
			counter = 0;
			hide();
		}
	});

	document.addEventListener("drop", (e) => {
		e.preventDefault();
		counter = 0;
		hide();
		var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
		if (f) uploadFile(f);
	});
}

function setupUpload() {
	var zone = el("uploadZone");
	var browse = el("uploadBrowse");
	var input = el("uploadInput");

	function openPicker() {
		if (!input) return;
		input.value = "";
		input.click();
	}

	if (browse) {
		browse.addEventListener("click", () => {
			openPicker();
		});
	}
	if (zone) {
		zone.addEventListener("click", () => {
			openPicker();
		});

		function setDrag(on) {
			if (on) zone.classList.add("dragover");
			else zone.classList.remove("dragover");
		}

		zone.addEventListener("dragenter", (e) => {
			e.preventDefault();
			setDrag(true);
		});
		zone.addEventListener("dragleave", (e) => {
			e.preventDefault();
			setDrag(false);
		});
		zone.addEventListener("dragover", (e) => {
			e.preventDefault();
			setDrag(true);
		});
		zone.addEventListener("drop", (e) => {
			e.preventDefault();
			setDrag(false);
			var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
			if (f) uploadFile(f);
		});
	}

	if (input) {
		input.addEventListener("change", () => {
			if (input.files && input.files[0]) uploadFile(input.files[0]);
		});
	}

	window.addEventListener("dragover", (e) => {
		e.preventDefault();
	});
	window.addEventListener("drop", (e) => {
		e.preventDefault();
	});
}

function loadConfig() {
	return apiGet("/api/config")
		.then((r) => {
			cfg = r || null;
			if (cfg && cfg.issue && cfg.issue.default_regex) {
				try {
					issueRegex = new RegExp(cfg.issue.default_regex);
				} catch (e) {
					issueRegex = null;
				}
			}
			if (cfg && cfg.meta && cfg.meta.version) {
				setText("ampWebVersion", "v" + String(cfg.meta.version));
			}
			phCall("refreshHeader");
			if (cfg && cfg.ui) {
				if (cfg.ui.base_font_px) {
					document.documentElement.style.fontSize =
						String(cfg.ui.base_font_px) + "px";
				}
				if (cfg.ui.drop_overlay_enabled) {
					enableGlobalDropOverlay();
				}
			}
			return cfg;
		})
		.catch(() => {
			cfg = null;
			return null;
		});
}

function shouldOverwrite(fieldKey, node) {
	if (!cfg || !cfg.autofill) return String(node.value || "").trim() === "";
	var pol = String(cfg.autofill.overwrite_policy || "");
	if (pol === "only_if_empty") return String(node.value || "").trim() === "";
	if (pol === "if_not_dirty") return !dirty[fieldKey];
	return false;
}

if (PH && typeof PH.register === "function") {
	PH.register("app_part_queue_upload", {
		validateAndPreview,
		enqueue,
		setupUpload,
		loadConfig,
		shouldOverwriteField: shouldOverwrite,
	});
}
