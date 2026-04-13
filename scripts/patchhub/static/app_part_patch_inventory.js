/** @type {any} */
var __ph_w = /** @type {any} */ (window);
/** @type {PatchhubHeaderRuntime | null} */
var patchInventoryPh = /** @type {any} */ (window).PH || null;

/**
 * @typedef {{
 *   stored_rel_path?: string,
 *   source_bucket?: string,
 *   kind?: string,
 *   filename?: string,
 *   derived_commit_message?: string,
 *   derived_issue?: string | number,
 *   derived_target_repo?: string,
 *   mtime_utc?: string,
 * }} PatchInventoryItem
 * @typedef {{
 *   ok?: boolean,
 *   error?: string,
 *   items?: PatchInventoryItem[],
 *   sig?: string,
 *   unchanged?: boolean,
 * }} PatchInventoryResponse
 */

function phCall(/** @type {string} */ name, /** @type {unknown[]} */ ...args) {
	if (!patchInventoryPh || typeof patchInventoryPh.call !== "function")
		return undefined;
	return patchInventoryPh.call(name, ...args);
}

function patchBucketLabel(
	/** @type {PatchInventoryItem | null | undefined} */ item,
) {
	var bucket = String((item && item.source_bucket) || "");
	if (bucket === "upload_dir") return "incoming";
	return "patches";
}

function clearLoadedPatchIfDeleted(/** @type {unknown} */ storedRelPath) {
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

function preparePatchFormForInventoryItem(
	/** @type {PatchInventoryItem | null | undefined} */ item,
) {
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

function renderPatchesFromResponse(/** @type {PatchInventoryResponse} */ r) {
	var items = Array.isArray(r && r.items)
		? /** @type {PatchInventoryItem[]} */ (r.items)
		: [];
	patchesCache = items.slice();

	var html = /** @type {PatchInventoryItem[]} */ (patchesCache)
		.map((/** @type {PatchInventoryItem} */ item, idx) => {
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
			var item = /** @type {PatchInventoryItem} */ (patchesCache[idx]);
			var storedRelPath = String((item && item.stored_rel_path) || "");
			var deleteBtn = node.querySelector(".patchDelete");
			if (deleteBtn) {
				deleteBtn.addEventListener("click", (ev) => {
					ev.stopPropagation();
					if (!storedRelPath) return;
					if (!confirm(`Delete patch ${storedRelPath}?`)) return;
					apiPost("/api/fs/delete", { path: storedRelPath }).then((resp) => {
						var deleteResp = /** @type {{ ok?: boolean, error?: string }} */ (
							resp
						);
						if (!deleteResp || deleteResp.ok === false) {
							setFsHint(
								deleteResp && deleteResp.error
									? String(deleteResp.error)
									: "Delete failed",
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

function refreshPatches(
	/** @type {{ mode?: string } | null | undefined} */ opts,
) {
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
		var resp = /** @type {PatchInventoryResponse} */ (r);
		if (!resp || resp.ok === false) {
			setPre("patchesList", resp);
			return;
		}
		if (resp.unchanged) return;
		if (resp.sig) idleSigs.patches = String(resp.sig || "");
		renderPatchesFromResponse(resp);
	});
}

if (patchInventoryPh && typeof patchInventoryPh.register === "function") {
	patchInventoryPh.register("app_part_patch_inventory", {
		renderPatchesFromResponse,
		refreshPatches,
	});
}
