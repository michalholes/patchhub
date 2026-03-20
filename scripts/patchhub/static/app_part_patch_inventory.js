/** @type {any} */
var __ph_w = /** @type {any} */ (window);
var PH = /** @type {any} */ (window).PH;

function phCall(name, ...args) {
	if (!PH || typeof PH.call !== "function") return undefined;
	return PH.call(name, ...args);
}

function patchBucketLabel(item) {
	var bucket = String((item && item.source_bucket) || "");
	if (bucket === "upload_dir") return "incoming";
	return "patches";
}

function clearLoadedPatchIfDeleted(storedRelPath) {
	var current = normalizePatchPath(
		String((el("patchPath") && el("patchPath").value) || ""),
	);
	var deleted = normalizePatchPath(String(storedRelPath || ""));
	if (!current || current !== deleted) return;
	if (el("patchPath")) el("patchPath").value = "";
	if (el("issueId")) el("issueId").value = "";
	if (el("commitMsg")) el("commitMsg").value = "";
	if (el("targetRepo")) el("targetRepo").value = "";
	phCall("clearPmValidationPayload");
	clearParsedState();
	setParseHint("");
	if (typeof dirty === "object" && dirty) {
		dirty.issueId = false;
		dirty.commitMsg = false;
		dirty.patchPath = false;
		dirty.targetRepo = false;
	}
	phCall("validateAndPreview");
}

function preparePatchFormForInventoryItem(item) {
	var payload = item || {};
	phCall("prepareFormForNewPatchLoad");
	if (el("issueId")) el("issueId").value = "";
	if (el("commitMsg")) el("commitMsg").value = "";
	if (el("targetRepo")) el("targetRepo").value = "";
	if (el("patchPath")) {
		el("patchPath").value = normalizePatchPath(
			String(payload.stored_rel_path || ""),
		);
	}
	if (el("mode")) el("mode").value = "patch";
	if (el("rawCommand")) el("rawCommand").value = "";
	phCall("clearPmValidationPayload");
	clearParsedState();
	setParseHint("");
	if (String(payload.kind || "") !== "zip") {
		phCall("applyAutofillFromPayload", payload);
		return;
	}
	phCall("validateAndPreview");
}

function renderPatchesFromResponse(r) {
	var items = (r && r.items) || [];
	patchesCache = Array.isArray(items) ? items.slice() : [];

	var html = patchesCache
		.map((item, idx) => {
			var kind = String((item && item.kind) || "").trim() || "patch";
			var filename = String((item && item.filename) || "").trim();
			var commit = String((item && item.derived_commit_message) || "").trim();
			var metaParts = [];
			if (item && item.derived_issue) {
				metaParts.push("#" + String(item.derived_issue || ""));
			}
			if (item && item.derived_target_repo) {
				metaParts.push("target=" + String(item.derived_target_repo || ""));
			}
			metaParts.push(patchBucketLabel(item));
			if (item && item.mtime_utc) {
				metaParts.push(formatLocalTime(item.mtime_utc));
			}
			var meta = metaParts.join(" | ");
			var line =
				'<div class="item job-item patch-item" data-idx="' + String(idx) + '">';
			line += '<div class="name workspace-name">';
			line += '<div class="job-lines">';
			line += '<div class="job-top">';
			line += '<span class="job-commit">' + escapeHtml(filename) + "</span>";
			line +=
				'<span class="job-status st-' +
				escapeHtml(kind.toLowerCase()) +
				'">' +
				escapeHtml(kind.toUpperCase()) +
				"</span>";
			line += "</div>";
			if (commit) {
				line += '<div class="job-commit">' + escapeHtml(commit) + "</div>";
			}
			line += '<div class="job-meta">' + escapeHtml(meta) + "</div>";
			line += '<div class="actions workspace-actions">';
			line +=
				'<button type="button" class="btn btn-small patchDelete">Delete</button>';
			line += "</div>";
			line += "</div></div></div>";
			return line;
		})
		.join("");

	el("patchesList").innerHTML = html || '<div class="muted">(none)</div>';

	Array.from(el("patchesList").querySelectorAll(".patch-item")).forEach(
		(node) => {
			var idx = parseInt(node.getAttribute("data-idx") || "-1", 10);
			if (idx < 0 || idx >= patchesCache.length) return;
			var item = patchesCache[idx];
			var storedRelPath = String((item && item.stored_rel_path) || "");
			var deleteBtn = node.querySelector(".patchDelete");
			if (deleteBtn) {
				deleteBtn.addEventListener("click", (ev) => {
					ev.stopPropagation();
					if (!storedRelPath) return;
					if (!confirm(`Delete patch ${storedRelPath}?`)) return;
					apiPost("/api/fs/delete", { path: storedRelPath }).then((resp) => {
						if (!resp || resp.ok === false) {
							setFsHint(
								resp && resp.error ? String(resp.error) : "Delete failed",
							);
							return;
						}
						clearLoadedPatchIfDeleted(storedRelPath);
						refreshFs();
						refreshPatches({ mode: "user" });
					});
				});
			}
			node.addEventListener("click", () => {
				preparePatchFormForInventoryItem(item);
			});
		},
	);
}

function refreshPatches(opts) {
	opts = opts || {};
	var mode = String(opts.mode || "user");
	var qs = "";
	if (idleSigs.patches) {
		qs = "?since_sig=" + encodeURIComponent(String(idleSigs.patches || ""));
	}
	apiGetETag("patches_list", "/api/patches/inventory" + qs, {
		mode: mode,
		single_flight: mode === "periodic",
	}).then((r) => {
		if (!r || r.ok === false) {
			setPre("patchesList", r);
			return;
		}
		if (r.unchanged) return;
		if (r.sig) idleSigs.patches = String(r.sig || "");
		renderPatchesFromResponse(r);
	});
}

if (PH && typeof PH.register === "function") {
	PH.register("app_part_patch_inventory", {
		renderPatchesFromResponse,
		refreshPatches,
	});
}
