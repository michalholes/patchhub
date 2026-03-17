/** @type {any} */
var PH = /** @type {any} */ (window).PH;

function phCall(name, ...args) {
	if (!PH || typeof PH.call !== "function") return undefined;
	return PH.call(name, ...args);
}

function hasTrackedActiveJob() {
	return !!(
		PH &&
		typeof PH.call === "function" &&
		PH.call("hasTrackedActiveJob")
	);
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
				if (!r || r.ok === false) {
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
				if (!r || r.ok === false) {
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

			var seq = Promise.resolve();
			paths.sort().forEach((p) => {
				seq = seq.then(() =>
					apiPost("/api/fs/delete", { path: p }).then((r) => {
						if (!r || r.ok !== true) {
							const err = r && r.error ? String(r.error) : "unknown error";
							setFsHint("delete failed: " + err);
							throw new Error(err);
						}
						return r;
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
				if (!r || r.ok === false) {
					setFsHint("unzip failed");
					return;
				}
				refreshFs();
			});
		});
	}
	el("workspacesRefresh").addEventListener("click", () => {
		phCall("refreshWorkspaces", { mode: "user" });
	});
	el("workspacesCollapse").addEventListener("click", () => {
		workspacesVisible = !workspacesVisible;
		PH.call("setWorkspacesVisible", workspacesVisible);
		AMP_UI.saveWorkspacesVisible(workspacesVisible);
		if (workspacesVisible) phCall("refreshWorkspaces", { mode: "user" });
	});

	el("runsRefresh").addEventListener("click", () => {
		phCall("refreshRuns");
	});

	if (el("runsCollapse")) {
		el("runsCollapse").addEventListener("click", () => {
			runsVisible = !runsVisible;
			PH.call("setRunsVisible", runsVisible);
			AMP_UI.saveRunsVisible(runsVisible);
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
			PH.call("setJobsVisible", jobsVisible);
			AMP_UI.saveJobsVisible(jobsVisible);
		});
	}

	phCall("initGateOptionsUi");
	phCall("initInfoPoolUi");
	phCall("initLiveCopyButtons");
	phCall("initLiveAutoscrollToggle");

	if (el("liveLevel")) {
		el("liveLevel").addEventListener("change", () => {
			var v = String(el("liveLevel").value || "normal");
			PH.call("setLiveLevel", v);
			PH.call("renderLiveLog");
			PH.call("updateProgressFromEvents");
		});
	}

	if (el("jobsList")) {
		el("jobsList").addEventListener("click", (e) => {
			var t = e && e.target ? e.target : null;
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
					AMP_UI.saveLiveJobId(selectedJobId);
					suppressIdleOutput = false;
					phCall("refreshJobs");
					PH.call("openLiveStream", PH.call("getLiveJobId"));
					return;
				}
				t = t.parentElement;
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
			PH.call("refreshStats");
			if (hasTrackedActiveJob()) {
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
		var vis = PH.call("loadUiVisibility") || {};
		workspacesVisible = !!vis.workspacesVisible;
		runsVisible = !!vis.runsVisible;
		jobsVisible = !!vis.jobsVisible;
		PH.call("setWorkspacesVisible", workspacesVisible);
		PH.call("setRunsVisible", runsVisible);
		PH.call("setJobsVisible", jobsVisible);

		PH.call("loadLiveLevel");
		PH.call("loadLiveAutoscroll");
		var savedJobId = PH.call("loadLiveJobId");
		if (savedJobId) selectedJobId = savedJobId;
		phCall("initGateOptionsUi");
		phCall("initLiveCopyButtons");

		if (el("liveLevel")) {
			const v = PH.call("getLiveLevel");
			if (v) el("liveLevel").value = String(v);
		}

		Promise.resolve(phCall("loadConfig")).then(() => {
			refreshFs();
			PH.call("refreshStats");
			Promise.resolve(phCall("refreshOverviewSnapshot", { mode: "user" }))
				.catch((e) => setUiError(e))
				.finally(() => {
					phCall("renderIssueDetail");
					phCall("validateAndPreview");
				});

			var refreshTimer = null;
			var headerTimer = null;

			function stopTimers(opts) {
				opts = opts || {};
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
					PH.call("closeLiveStream");
				}
			}

			function startTimers(opts) {
				opts = opts || {};
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
							tickMissingPatchClear({ mode: "active" });
							phCall("stopSnapshotEvents");
							phCall("refreshJobs", { mode: "periodic" });
							if (workspacesVisible) {
								phCall("refreshWorkspaces", { mode: "periodic" });
							}
						} else {
							tickMissingPatchClear({ mode: "idle" });
							phCall("ensureSnapshotEvents");
							if (
								!PH.has("snapshotEventsNeedPolling") ||
								phCall("snapshotEventsNeedPolling")
							) {
								phCall("idleRefreshTick");
							}
						}
					} catch (e) {
						setUiError(e);
					}
				}, 2000);

				headerTimer = setInterval(() => {
					try {
						if (hasTrackedActiveJob())
							phCall("refreshHeader", { mode: "periodic" });
					} catch (e) {
						setUiError(e);
					}
				}, 5000);

				phCall("startAutofillPolling");
				if (hasTrackedActiveJob()) {
					phCall("stopSnapshotEvents");
				} else phCall("ensureSnapshotEvents");
			}

			function resyncVisible() {
				refreshFs();
				PH.call("refreshStats");
				if (hasTrackedActiveJob()) {
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
					.catch((e) => setUiError(e))
					.finally(() => {
						phCall("renderIssueDetail");
						phCall("validateAndPreview");
					});
			}

			var keepLiveStream = false;

			document.addEventListener("visibilitychange", () => {
				try {
					if (document.hidden) {
						if (PH.call("hasTrackedActiveJob")) {
							phCall("stopSnapshotEvents");
							phCall("stopAutofillPolling");
						} else {
							stopTimers();
						}
					} else {
						keepLiveStream = !!PH.call("hasTrackedActiveJob");
						resyncVisible();
						startTimers({ keepLiveStream: keepLiveStream });
					}
				} catch (e) {
					setUiError(e);
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

if (PH && typeof PH.register === "function") {
	PH.register("app_part_wire_init", {
		startAppWireInit: init,
	});
}
