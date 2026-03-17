/** @type {any} */
var __ph_w = /** @type {any} */ (window);
var PH = /** @type {any} */ (window).PH;

function phCall(name, ...args) {
	if (!PH || typeof PH.call !== "function") return undefined;
	return PH.call(name, ...args);
}

function renderWorkspacesFromResponse(r) {
	var items = r.items || r.workspaces || [];
	workspacesCache = items;

	var html = items
		.map((ws, idx) => {
			var issueId = Number(ws.issue_id || 0);
			var state =
				String(ws.state || "")
					.trim()
					.toUpperCase() || "CLEAN";
			var busy = !!ws.busy;
			var commit = String(ws.commit_summary || "").trim();
			var metaParts = [];
			if (ws.attempt != null) metaParts.push(`attempt=${String(ws.attempt)}`);
			if (ws.allowed_union_count != null) {
				metaParts.push(`union=${String(ws.allowed_union_count)}`);
			}
			if (busy) metaParts.push("busy");
			if (ws.mtime_utc) metaParts.push(formatLocalTime(ws.mtime_utc));
			var meta = metaParts.join(" | ");
			var stateCls = `job-status st-${String(state || "").toLowerCase()}`;
			var line =
				'<div class="item job-item workspace-item" data-idx="' +
				String(idx) +
				'">';
			line += '<div class="name workspace-name">';
			line += '<div class="job-lines">';
			line += '<div class="job-top">';
			line +=
				'<span class="job-issue">#' + escapeHtml(String(issueId)) + "</span>";
			line +=
				'<span class="' +
				escapeHtml(stateCls) +
				'">' +
				escapeHtml(state) +
				"</span>";
			line += "</div>";
			if (commit) {
				line += '<div class="job-commit">' + escapeHtml(commit) + "</div>";
			}
			line += '<div class="job-meta">' + escapeHtml(meta) + "</div>";
			line += '<div class="actions workspace-actions">';
			line +=
				'<button type="button" class="btn btn-small wsOpen">Open</button>';
			line +=
				'<button type="button" class="btn btn-small wsFinalize">Finalize (-w)</button>';
			line +=
				'<button type="button" class="btn btn-small wsDelete">Delete</button>';
			line += "</div>";
			line += "</div></div></div>";
			return line;
		})
		.join("");

	el("workspacesList").innerHTML = html || '<div class="muted">(none)</div>';

	Array.from(el("workspacesList").querySelectorAll(".workspace-item")).forEach(
		(node) => {
			var idx = parseInt(node.getAttribute("data-idx") || "-1", 10);
			if (idx < 0 || idx >= workspacesCache.length) return;
			var ws = workspacesCache[idx];
			var rel = String(ws.workspace_rel_path || "");
			var issueId = String(ws.issue_id || "");

			var openBtn = node.querySelector(".wsOpen");
			if (openBtn) {
				openBtn.addEventListener("click", () => {
					el("fsPath").value = rel;
					fsSelected = "";
					setFsHint(`workspace: ${rel}`);
					refreshFs();
				});
			}

			var finBtn = node.querySelector(".wsFinalize");
			if (finBtn) {
				finBtn.addEventListener("click", () => {
					el("mode").value = "finalize_workspace";
					el("issueId").value = issueId;
					el("commitMsg").value = "";
					el("patchPath").value = "";
					el("rawCommand").value = "";
					clearParsedState();
					setParseHint("");
					dirty.issueId = false;
					dirty.commitMsg = false;
					dirty.patchPath = false;
					setUiStatus(
						"finalize_workspace: prepared form for issue_id=" + issueId,
					);
					phCall("validateAndPreview");
				});
			}

			var delBtn = node.querySelector(".wsDelete");
			if (delBtn) {
				delBtn.addEventListener("click", () => {
					if (!rel) return;
					if (!confirm(`Delete workspace ${rel}?`)) return;
					fetch("/api/fs/delete", {
						method: "POST",
						headers: {
							"Content-Type": "application/json",
							Accept: "application/json",
						},
						body: JSON.stringify({ path: rel }),
					})
						.then((resp) => resp.json())
						.then((obj) => {
							if (!obj || obj.ok === false) {
								setFsHint(
									obj && obj.error ? String(obj.error) : "Delete failed",
								);
								return;
							}
							setFsHint(`deleted: ${rel}`);
							refreshWorkspaces({ mode: "user" });
							refreshFs();
						});
				});
			}
		},
	);
}

function refreshWorkspaces(opts) {
	opts = opts || {};
	var mode = String(opts.mode || "user");
	var sf = mode === "periodic";
	apiGetETag("workspaces_list", "/api/workspaces", {
		mode: mode,
		single_flight: sf,
	}).then((r) => {
		if (!r || r.ok === false) {
			setPre("workspacesList", r);
			return;
		}
		if (r.unchanged) return;
		var sig = String(r.sig || "");
		if (sig) idleSigs.workspaces = sig;
		renderWorkspacesFromResponse(r);
	});
}

if (PH && typeof PH.register === "function") {
	PH.register("app_part_workspaces", {
		renderWorkspacesFromResponse,
		refreshWorkspaces,
	});
}
