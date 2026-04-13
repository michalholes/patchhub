/**
 * @typedef {{
 *   call: function(string, ...*): *,
 *   has: function(string): boolean,
 *   register: function(string, Object): void,
 * }} WireInitRuntime
 * @typedef {Window & typeof globalThis & { PH?: WireInitRuntime | null }} WireInitWindow
 * @typedef {{ ok?: boolean, error?: string }} WireInitApiResponse
 * @typedef {{
 *   patchesVisible?: boolean,
 *   workspacesVisible?: boolean,
 *   runsVisible?: boolean,
 *   jobsVisible?: boolean,
 * }} WireInitVisibilityState
 * @typedef {{ keepLiveStream?: boolean }} WireInitTimerOpts
 * @typedef {EventTarget & {
 *   getAttribute?: function(string): string | null,
 *   parentElement?: EventTarget | null,
 * }} WireInitEventTarget
 */
var wireInitWindow = /** @type {WireInitWindow} */ (window);
var wireInitRuntime = wireInitWindow.PH || null;

function phCall(/** @type {string} */ name, /** @type {unknown[]} */ ...args) {
	if (!wireInitRuntime || typeof wireInitRuntime.call !== "function")
		return undefined;
	return wireInitRuntime.call(name, ...args);
}

function hasTrackedActiveJob() {
	return !!(wireInitRuntime && runtimeCall("hasTrackedActiveJob"));
}

function runtimeCall(
	/** @type {string} */ name,
	/** @type {unknown[]} */ ...args
) {
	if (!wireInitRuntime) return undefined;
	return wireInitRuntime.call(name, ...args);
}

function runtimeHas(/** @type {string} */ name) {
	if (!wireInitRuntime) return false;
	return wireInitRuntime.has(name);
}
function wireButtons() {
	el("fsRefresh").addEventListener("click", refreshFs);
	el("fsUp").addEventListener("click", () => {
		var p = el("fsPath").value || "";
		el("fsPath").value = parentRel(p);
		fsSelected = "";
		setFsHint("");
		refreshFs();
	});

	if (el("fsSelectAll")) {
		el("fsSelectAll").addEventListener("click", () => {
			fsLastRels.forEach((rel) => {
				fsChecked[rel] = true;
			});
			fsUpdateSelCount();
			refreshFs();
		});
	}
	if (el("fsClear")) {
		el("fsClear").addEventListener("click", () => {
			fsClearSelection();
			refreshFs();
		});
	}
	if (el("fsDownloadSelected")) {
		el("fsDownloadSelected").addEventListener("click", () => {
			fsDownloadSelected();
		});
	}

	if (el("fsMkdir")) {
		el("fsMkdir").addEventListener("click", () => {
			var base = String(el("fsPath").value || "");
			var name = prompt("New directory name");
			if (!name) return;
			var rel = joinRel(base, name);
			apiPost("/api/fs/mkdir", { path: rel }).then((r) => {
				var resp = /** @type {WireInitApiResponse} */ (r);
				if (!resp || resp.ok === false) {
					setFsHint("mkdir failed");
					return;
				}
				refreshFs();
			});
		});
	}

	if (el("fsRename")) {
		el("fsRename").addEventListener("click", () => {
			if (!fsSelected) {
				setFsHint("focus an item first");
				return;
			}
			var base = parentRel(fsSelected);
			var curName = fsSelected.split("/").pop();
			var dstName = prompt("New name", curName || "");
			if (!dstName) return;
			var dst = joinRel(base, dstName);
			apiPost("/api/fs/rename", { src: fsSelected, dst: dst }).then((r) => {
				var resp = /** @type {WireInitApiResponse} */ (r);
				if (!resp || resp.ok === false) {
					setFsHint("rename failed");
					return;
				}
				fsSelected = dst;
				refreshFs();
			});
		});
	}

	if (el("fsDelete")) {
		el("fsDelete").addEventListener("click", () => {
			var paths = [];
			for (var k in fsChecked) {
				if (Object.hasOwn(fsChecked, k)) paths.push(k);
			}
			if (!paths.length && fsSelected) paths = [fsSelected];
			if (!paths.length) {
				setFsHint("select at least one item");
				return;
			}
			if (!confirm("Delete selected item(s)?")) return;

			/** @type {Promise<void>} */
			var seq = Promise.resolve();
			paths.sort().forEach((p) => {
				seq = seq.then(() =>
					apiPost("/api/fs/delete", { path: p }).then((r) => {
						var resp = /** @type {WireInitApiResponse} */ (r);
						if (!resp || resp.ok !== true) {
							const err =
								resp && resp.error ? String(resp.error) : "unknown error";
							setFsHint("delete failed: " + err);
							throw new Error(err);
						}
						return;
					}),
				);
			});
			seq
				.then(() => {
					fsClearSelection();
					fsSelected = "";
					refreshFs();
				})
				.catch((e) => {
					if (e && e.message) {
						setFsHint("delete failed: " + String(e.message));
					} else {
						setFsHint("delete failed");
					}
				});
		});
	}

	if (el("fsUnzip")) {
		el("fsUnzip").addEventListener("click", () => {
			if (!fsSelected || !/\.zip$/i.test(fsSelected)) {
				setFsHint("focus a .zip file first");
				return;
			}
			var base = parentRel(fsSelected);
			var dst = prompt("Destination directory", base || "");
			if (dst === null) return;
			apiPost("/api/fs/unzip", {
				zip_path: fsSelected,
				dest_dir: String(dst || ""),
			}).then((r) => {
				var resp = /** @type {WireInitApiResponse} */ (r);
				if (!resp || resp.ok === false) {
					setFsHint("unzip failed");
					return;
				}
				refreshFs();
			});
		});
	}
	if (el("patchesRefresh")) {
		el("patchesRefresh").addEventListener("click", () => {
			phCall("refreshPatches", { mode: "user" });
		});
	}
	if (el("patchesCollapse")) {
		el("patchesCollapse").addEventListener("click", () => {
			patchesVisible = !patchesVisible;
			runtimeCall("setPatchesVisible", patchesVisible);
			AMP_UI.savePatchesVisible?.(patchesVisible);
			if (patchesVisible) phCall("refreshPatches", { mode: "user" });
		});
	}

	el("workspacesRefresh").addEventListener("click", () => {
		phCall("refreshWorkspaces", { mode: "user" });
	});
	el("workspacesCollapse").addEventListener("click", () => {
		workspacesVisible = !workspacesVisible;
		runtimeCall("setWorkspacesVisible", workspacesVisible);
		AMP_UI.saveWorkspacesVisible?.(workspacesVisible);
		if (workspacesVisible) phCall("refreshWorkspaces", { mode: "user" });
	});

	el("runsRefresh").addEventListener("click", () => {
		phCall("refreshRuns");
	});

	if (el("runsCollapse")) {
		el("runsCollapse").addEventListener("click", () => {
			runsVisible = !runsVisible;
			runtimeCall("setRunsVisible", runsVisible);
			AMP_UI.saveRunsVisible?.(runsVisible);
		});
	}

	if (el("previewToggle")) {
		el("previewToggle").addEventListener("click", () => {
			setPreviewVisible(!previewVisible);
		});
	}
	if (el("previewCollapse")) {
		el("previewCollapse").addEventListener("click", () => {
			setPreviewVisible(!previewVisible);
		});
	}

	el("jobsRefresh").addEventListener("click", () => {
		phCall("refreshJobs");
	});

	if (el("jobsCollapse")) {
		el("jobsCollapse").addEventListener("click", () => {
			jobsVisible = !jobsVisible;
			runtimeCall("setJobsVisible", jobsVisible);
			AMP_UI.saveJobsVisible?.(jobsVisible);
		});
	}

	phCall("initGateOptionsUi");
	phCall("initInfoPoolUi");
	phCall("initLiveCopyButtons");
	phCall("initLiveAutoscrollToggle");

	if (el("liveLevel")) {
		el("liveLevel").addEventListener("change", () => {
			var v = String(el("liveLevel").value || "normal");
			runtimeCall("setLiveLevel", v);
			runtimeCall("renderLiveLog");
			runtimeCall("updateProgressFromEvents");
		});
	}

	if (el("jobsList")) {
		el("jobsList").addEventListener("click", (e) => {
			var t = /** @type {WireInitEventTarget | null} */ (
				e && e.target ? /** @type {WireInitEventTarget} */ (e.target) : null
			);
			while (t && t !== el("jobsList")) {
				const rerunJobId = t.getAttribute && t.getAttribute("data-rerun-jobid");
				if (rerunJobId) {
					phCall("prepareRerunLatestFromJobId", String(rerunJobId), {
						sourceLabel: "selected jobs item",
						clearOnFailure: false,
					});
					return;
				}
				const jobId = t.getAttribute && t.getAttribute("data-jobid");
				if (jobId) {
					selectedJobId = String(jobId);
					AMP_UI.saveLiveJobId?.(selectedJobId);
					suppressIdleOutput = false;
					phCall("refreshJobs");
					runtimeCall("openLiveStream", runtimeCall("getLiveJobId"));
					return;
				}
				t = /** @type {WireInitEventTarget | null} */ (t.parentElement);
			}
		});
	}

	el("enqueueBtn").addEventListener("click", () => {
		phCall("enqueue");
	});

	if (el("parseBtn")) {
		el("parseBtn").addEventListener("click", () => {
			triggerParse(getRawCommand());
		});
	}

	if (el("rawCommand")) {
		el("rawCommand").addEventListener("input", () => {
			var raw = getRawCommand();
			if (raw !== lastParsedRaw) {
				lastParsed = null;
				lastParsedRaw = "";
			}
			if (!raw) {
				clearParsedState();
				setParseHint("");
				phCall("validateAndPreview");
				return;
			}
			scheduleParseDebounced(raw);
		});

		el("rawCommand").addEventListener("paste", () => {
			setTimeout(() => {
				triggerParse(getRawCommand());
			}, 0);
		});
	}

	el("mode").addEventListener("change", () => {
		var mode = String(el("mode").value || "patch");
		if (mode === "rerun_latest") {
			phCall("prepareRerunLatestFromLatestJob");
			return;
		}
		phCall("clearProtectedRerunLatestLifecycle");
		if (mode !== "rollback") {
			phCall("clearRollbackFlowState");
		}
		validateAndPreview();
	});
	el("issueId").addEventListener("input", () => {
		dirty.issueId = true;
		phCall("validateAndPreview");
	});
	el("commitMsg").addEventListener("input", () => {
		dirty.commitMsg = true;
		phCall("validateAndPreview");
	});
	el("patchPath").addEventListener("input", () => {
		dirty.patchPath = true;
		phCall("validateAndPreview");
	});
	if (el("targetRepo")) {
		el("targetRepo").addEventListener("change", () => {
			dirty.targetRepo = true;
			phCall("validateAndPreview");
		});
	}

	var browse = el("browsePatch");
	if (browse) {
		browse.addEventListener("click", () => {
			if (!fsSelected) {
				setFsHint("select a patch file first");
				return;
			}
			el("patchPath").value = normalizePatchPath(fsSelected);
			dirty.patchPath = true;
			phCall("validateAndPreview");
		});
	}

	if (el("refreshAll")) {
		el("refreshAll").addEventListener("click", () => {
			refreshFs();
			runtimeCall("refreshStats");
			if (hasTrackedActiveJob()) {
				if (patchesVisible) {
					phCall("refreshPatches", { mode: "user" });
				}
				phCall("refreshWorkspaces", { mode: "user" });
				phCall("refreshRuns", { mode: "user" });
				phCall("refreshJobs", { mode: "user" });
				phCall("refreshHeader", { mode: "user" });
				phCall("renderIssueDetail");
				phCall("validateAndPreview");
				return;
			}
			Promise.resolve(
				phCall("refreshOverviewSnapshot", { mode: "user" }),
			).finally(() => {
				phCall("renderIssueDetail");
				phCall("validateAndPreview");
			});
		});
	}
}

function init() {
	function start() {
		phCall("setupUpload");
		wireButtons();
		setPreviewVisible(false);
		var vis = /** @type {WireInitVisibilityState} */ (
			runtimeCall("loadUiVisibility") || {}
		);
		patchesVisible = !!vis.patchesVisible;
		workspacesVisible = !!vis.workspacesVisible;
		runsVisible = !!vis.runsVisible;
		jobsVisible = !!vis.jobsVisible;
		runtimeCall("setPatchesVisible", patchesVisible);
		runtimeCall("setWorkspacesVisible", workspacesVisible);
		runtimeCall("setRunsVisible", runsVisible);
		runtimeCall("setJobsVisible", jobsVisible);

		runtimeCall("loadLiveLevel");
		var PH = wireInitRuntime;
		if (PH && typeof PH.call === "function") PH.call("loadLiveAutoscroll");
		var savedJobId = runtimeCall("loadLiveJobId");
		if (savedJobId) selectedJobId = String(savedJobId);
		phCall("initGateOptionsUi");
		phCall("initLiveCopyButtons");

		if (el("liveLevel")) {
			const v = runtimeCall("getLiveLevel");
			if (v) el("liveLevel").value = String(v);
		}

		Promise.resolve(phCall("loadConfig")).then(() => {
			refreshFs();
			runtimeCall("refreshStats");
			Promise.resolve(phCall("refreshOverviewSnapshot", { mode: "user" }))
				.catch((e) => setUiError(e))
				.finally(() => {
					phCall("renderIssueDetail");
					phCall("validateAndPreview");
				});

			/** @type {ReturnType<typeof setInterval> | null} */
			var refreshTimer = null;
			/** @type {ReturnType<typeof setInterval> | null} */
			var headerTimer = null;

			function stopTimers(/** @type {WireInitTimerOpts} */ opts = {}) {
				if (refreshTimer) {
					clearInterval(refreshTimer);
					refreshTimer = null;
				}
				if (headerTimer) {
					clearInterval(headerTimer);
					headerTimer = null;
				}
				phCall("stopAutofillPolling");
				phCall("stopSnapshotEvents");
				if (!opts.keepLiveStream) {
					runtimeCall("closeLiveStream");
				}
			}

			function startTimers(/** @type {WireInitTimerOpts} */ opts = {}) {
				var activeMode = false;
				stopTimers({ keepLiveStream: !!opts.keepLiveStream });

				refreshTimer = setInterval(() => {
					try {
						activeMode = hasTrackedActiveJob();
						if (document.hidden && !activeMode) {
							stopTimers();
							return;
						}
						if (activeMode) {
							phCall("tickMissingPatchClear", { mode: "active" });
							phCall("stopSnapshotEvents");
							phCall("refreshJobs", { mode: "periodic" });
							if (patchesVisible) {
								phCall("refreshPatches", { mode: "periodic" });
							}
							if (workspacesVisible) {
								phCall("refreshWorkspaces", { mode: "periodic" });
							}
						} else {
							phCall("tickMissingPatchClear", { mode: "idle" });
							phCall("ensureSnapshotEvents");
							if (
								!runtimeHas("snapshotEventsNeedPolling") ||
								phCall("snapshotEventsNeedPolling")
							) {
								phCall("idleRefreshTick");
							}
						}
					} catch (e) {
						setUiError(String(e));
					}
				}, 2000);

				headerTimer = setInterval(() => {
					try {
						if (hasTrackedActiveJob())
							phCall("refreshHeader", { mode: "periodic" });
					} catch (e) {
						setUiError(String(e));
					}
				}, 5000);

				phCall("startAutofillPolling");
				if (hasTrackedActiveJob()) {
					phCall("stopSnapshotEvents");
				} else phCall("ensureSnapshotEvents");
			}

			function resyncVisible() {
				refreshFs();
				runtimeCall("refreshStats");
				if (hasTrackedActiveJob()) {
					if (patchesVisible) {
						phCall("refreshPatches", { mode: "user" });
					}
					if (workspacesVisible) {
						phCall("refreshWorkspaces", { mode: "user" });
					}
					phCall("refreshRuns", { mode: "user" });
					phCall("refreshJobs", { mode: "user" });
					phCall("refreshHeader", { mode: "user" });
					phCall("renderIssueDetail");
					phCall("validateAndPreview");
					return;
				}
				Promise.resolve(phCall("refreshOverviewSnapshot", { mode: "user" }))
					.catch((e) => setUiError(String(e)))
					.finally(() => {
						phCall("renderIssueDetail");
						phCall("validateAndPreview");
					});
			}

			var keepLiveStream = false;

			document.addEventListener("visibilitychange", () => {
				try {
					if (document.hidden) {
						if (runtimeCall("hasTrackedActiveJob")) {
							phCall("stopSnapshotEvents");
							phCall("stopAutofillPolling");
						} else {
							stopTimers();
						}
					} else {
						keepLiveStream = !!runtimeCall("hasTrackedActiveJob");
						resyncVisible();
						startTimers({ keepLiveStream: keepLiveStream });
					}
				} catch (e) {
					setUiError(String(e));
				}
			});

			startTimers();

			phCall("initAmpSettings");
		});
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", start);
	} else {
		start();
	}
}

if (wireInitRuntime && typeof wireInitRuntime.register === "function") {
	const PH = wireInitRuntime;
	PH.register("app_part_wire_init", {
		startAppWireInit: init,
	});
}
