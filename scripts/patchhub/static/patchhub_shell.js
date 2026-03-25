// PatchHub legacy shell (touchable).
// Kept for compatibility with older deployments that referenced this path.
// Current architecture uses:
// - patchhub_bootstrap.js (NO-GO) -> patchhub_runtime.js -> app.js

(() => {
	var W = /** @type {Window & typeof globalThis & {
		PH?: {
			register?: (moduleName: string, exportsObj: Record<string, unknown>) => void,
			has?: () => boolean,
			call?: () => unknown,
			loadScript?: () => Promise<boolean>,
			_diag?: unknown[],
			_registry?: Record<string, unknown>,
			__phJobsRevertRegisterWrapped?: boolean,
		} | null,
		PH_RT?: {
			register?: (moduleName: string, exportsObj: Record<string, unknown>) => void,
			__phJobsRevertRegisterWrapped?: boolean,
		} | null,
		PH_BOOT?: { bootLog?: (kind: string, msg: string) => void },
		apiGet?: (path: string) => Promise<JobDetailResponse>,
	}} */ (window);
	var detailCache = /** @type {Record<string, PatchhubJob | null>} */ (
		Object.create(null)
	);
	var detailCacheSummarySig = /** @type {Record<string, string>} */ (
		Object.create(null)
	);
	var detailInflight =
		/** @type {Record<string, Promise<PatchhubJob | null>>} */ (
			Object.create(null)
		);
	var detailInflightSummarySig = /** @type {Record<string, string>} */ (
		Object.create(null)
	);
	var detailFetchSeq = /** @type {Record<string, number>} */ (
		Object.create(null)
	);

	function log(/** @type {string} */ kind, /** @type {string} */ msg) {
		try {
			if (W.PH_BOOT && typeof W.PH_BOOT.bootLog === "function") {
				W.PH_BOOT.bootLog(kind, msg);
				return;
			}
		} catch (e) {
			// ignore
		}
		try {
			if (kind === "error") console.error("[PatchHub]", msg);
			else if (kind === "warn") console.warn("[PatchHub]", msg);
			else console.log("[PatchHub]", msg);
		} catch (e) {
			// ignore
		}
	}

	function own(
		/** @type {Record<string, unknown>} */ obj,
		/** @type {string} */ key,
	) {
		return Object.prototype.hasOwnProperty.call(obj, key);
	}

	function summarySig(/** @type {PatchhubJob | null | undefined} */ job) {
		return [
			String((job && job.status) || "").trim(),
			String((job && job.ended_utc) || "").trim(),
		].join("|");
	}

	function hasRevert(/** @type {PatchhubJob | null | undefined} */ detail) {
		return !!(
			String((detail && detail.effective_runner_target_repo) || "").trim() &&
			String((detail && detail.run_start_sha) || "").trim() &&
			String((detail && detail.run_end_sha) || "").trim()
		);
	}

	function clearDetail(/** @type {string} */ jobId) {
		delete detailCache[jobId];
		delete detailCacheSummarySig[jobId];
		delete detailInflight[jobId];
		delete detailInflightSummarySig[jobId];
	}

	function getApiGet() {
		if (typeof apiGet === "function") return apiGet;
		if (W && typeof W.apiGet === "function") return W.apiGet;
		return null;
	}

	function getChildren(/** @type {HTMLElement | null | undefined} */ node) {
		if (!node || !node.children) return /** @type {HTMLElement[]} */ ([]);
		return /** @type {HTMLElement[]} */ (
			Array.from(/** @type {ArrayLike<Element>} */ (node.children))
		);
	}

	function classTokens(/** @type {HTMLElement | null | undefined} */ node) {
		var raw = String((node && node.className) || "").trim();
		if (!raw) return [];
		return raw.split(/\s+/).filter(Boolean);
	}

	function hasClass(
		/** @type {HTMLElement | null | undefined} */ node,
		/** @type {string} */ name,
	) {
		return classTokens(node).indexOf(String(name || "")) >= 0;
	}

	function hasAllClasses(
		/** @type {HTMLElement | null | undefined} */ node,
		/** @type {string[]} */ names,
	) {
		return (names || []).every(function (name) {
			return hasClass(node, name);
		});
	}

	function findDescendant(
		/** @type {HTMLElement | null | undefined} */ node,
		/** @type {(child: HTMLElement) => boolean} */ predicate,
	) {
		var i = 0;
		var kids = getChildren(node);
		var hit = /** @type {HTMLElement | null} */ (null);
		for (i = 0; i < kids.length; i += 1) {
			if (predicate(kids[i])) return kids[i];
			hit = findDescendant(kids[i], predicate);
			if (hit) return hit;
		}
		return null;
	}

	function walkDescendants(
		/** @type {HTMLElement | null | undefined} */ node,
		/** @type {(child: HTMLElement) => boolean} */ predicate,
		/** @type {HTMLElement[]} */ out,
	) {
		var i = 0;
		var kids = getChildren(node);
		for (i = 0; i < kids.length; i += 1) {
			if (predicate(kids[i])) out.push(kids[i]);
			walkDescendants(kids[i], predicate, out);
		}
	}

	function findByAttr(
		/** @type {HTMLElement | null | undefined} */ node,
		/** @type {string} */ name,
		/** @type {string} */ value,
	) {
		return findDescendant(node, function (child) {
			return child.getAttribute(name) === value;
		});
	}

	function findByClasses(
		/** @type {HTMLElement | null | undefined} */ node,
		/** @type {string[]} */ names,
	) {
		return findDescendant(node, function (child) {
			return hasAllClasses(child, names);
		});
	}

	function findAncestorByClasses(
		/** @type {HTMLElement | null | undefined} */ node,
		/** @type {string[]} */ names,
	) {
		var current = node || null;
		while (current) {
			if (hasAllClasses(current, names)) return current;
			current = current.parentElement;
		}
		return null;
	}

	function listRoot() {
		if (!document || typeof document.getElementById !== "function") return null;
		return document.getElementById("jobsList");
	}

	function findJobHost(/** @type {string} */ jobId) {
		var root = listRoot();
		var marker = /** @type {HTMLElement | null} */ (null);
		if (!root) return null;
		marker = findByAttr(root, "data-jobid", String(jobId || ""));
		if (!marker) return null;
		return findAncestorByClasses(marker, ["item", "job-item"]);
	}

	function ensureActions(
		/** @type {HTMLElement | null | undefined} */ jobHost,
	) {
		var lines = /** @type {HTMLElement | null} */ (null);
		var actions = /** @type {HTMLElement | null} */ (null);
		if (!jobHost) return null;
		lines = findByClasses(jobHost, ["job-lines"]);
		if (!lines) return null;
		actions = findByClasses(lines, ["actions", "job-actions"]);
		if (actions) return actions;
		if (!document || typeof document.createElement !== "function") return null;
		actions = document.createElement("div");
		actions.className = "actions job-actions";
		lines.appendChild(actions);
		return actions;
	}

	function findRevertButtons(
		/** @type {HTMLElement | null | undefined} */ root,
		/** @type {string} */ jobId,
	) {
		var out = /** @type {HTMLElement[]} */ ([]);
		if (!root) return out;
		walkDescendants(
			root,
			function (child) {
				return child.getAttribute("data-revert-jobid") === String(jobId || "");
			},
			out,
		);
		return out;
	}

	function removeRevertButtons(/** @type {string} */ jobId) {
		var root = listRoot();
		findRevertButtons(root, jobId).forEach(function (button) {
			if (button && typeof button.remove === "function") button.remove();
		});
	}

	function ensureRevertButton(/** @type {string} */ jobId) {
		var host = findJobHost(jobId);
		var actions = /** @type {HTMLElement | null} */ (null);
		var existing = /** @type {HTMLElement[]} */ ([]);
		var button = /** @type {HTMLButtonElement | null} */ (null);
		if (!host) return;
		existing = findRevertButtons(host, jobId);
		if (existing.length) return;
		actions = ensureActions(host);
		if (!actions || !document || typeof document.createElement !== "function") {
			return;
		}
		button = document.createElement("button");
		button.className = "btn btn-small jobRevert";
		button.textContent = "Revert";
		button.setAttribute("type", "button");
		button.setAttribute("data-revert-jobid", String(jobId || ""));
		actions.appendChild(button);
	}

	function syncJob(/** @type {PatchhubJob | null | undefined} */ job) {
		var jobId = String((job && job.job_id) || "").trim();
		var sig = summarySig(job);
		var detail = /** @type {PatchhubJob | null} */ (null);
		if (!jobId) return;
		if (detailCacheSummarySig[jobId] !== sig) detail = null;
		else if (own(detailCache, jobId)) detail = detailCache[jobId];
		if (hasRevert(detail)) {
			ensureRevertButton(jobId);
			return;
		}
		removeRevertButtons(jobId);
	}

	function loadDetail(/** @type {PatchhubJob | null | undefined} */ job) {
		var jobId = String((job && job.job_id) || "").trim();
		var sig = summarySig(job);
		var fetchSeq = 0;
		var apiGetFn = getApiGet();
		if (!jobId || typeof apiGetFn !== "function") return Promise.resolve(null);
		if (detailCacheSummarySig[jobId] !== sig) clearDetail(jobId);
		if (own(detailCache, jobId) && detailCacheSummarySig[jobId] === sig) {
			return Promise.resolve(detailCache[jobId]);
		}
		if (detailInflight[jobId] && detailInflightSummarySig[jobId] === sig) {
			return detailInflight[jobId];
		}
		fetchSeq = Number(detailFetchSeq[jobId] || 0) + 1;
		detailFetchSeq[jobId] = fetchSeq;
		detailInflightSummarySig[jobId] = sig;
		detailInflight[jobId] = Promise.resolve(
			apiGetFn("/api/jobs/" + encodeURIComponent(jobId)),
		)
			.then(function (resp) {
				var detailResp = /** @type {JobDetailResponse} */ (resp);
				if (Number(detailFetchSeq[jobId] || 0) !== fetchSeq) return null;
				detailCacheSummarySig[jobId] = sig;
				detailCache[jobId] =
					detailResp && detailResp.ok !== false && detailResp.job
						? detailResp.job
						: null;
				return detailCache[jobId];
			})
			.catch(
				/** @returns {PatchhubJob | null} */ function () {
					if (Number(detailFetchSeq[jobId] || 0) !== fetchSeq) return null;
					detailCacheSummarySig[jobId] = sig;
					detailCache[jobId] = null;
					return null;
				},
			)
			.finally(
				/** @returns {void} */ function () {
					if (Number(detailFetchSeq[jobId] || 0) !== fetchSeq) return;
					delete detailInflight[jobId];
					delete detailInflightSummarySig[jobId];
				},
			);
		return detailInflight[jobId];
	}

	function syncJobs(/** @type {PatchhubJob[] | null | undefined} */ jobs) {
		(Array.isArray(jobs) ? jobs : []).forEach(function (job) {
			syncJob(job);
			loadDetail(job).then(function () {
				syncJob(job);
			});
		});
	}

	function patchJobsExports(
		/** @type {{
			renderJobsFromResponse?: (resp: JobsListResponse) => unknown,
			__phJobsRevertPatched?: boolean,
		} | null | undefined} */ exportsObj,
	) {
		var originalRender = exportsObj && exportsObj.renderJobsFromResponse;
		if (!exportsObj || exportsObj.__phJobsRevertPatched)
			return exportsObj || null;
		if (typeof originalRender !== "function") return exportsObj;
		exportsObj.renderJobsFromResponse = function (resp) {
			var listResp = /** @type {JobsListResponse} */ (resp);
			var result = originalRender.apply(this, arguments);
			Promise.resolve().then(function () {
				syncJobs(
					listResp && Array.isArray(listResp.jobs) ? listResp.jobs.slice() : [],
				);
			});
			return result;
		};
		exportsObj.__phJobsRevertPatched = true;
		return exportsObj;
	}

	function wrapRegister(
		/** @type {{
			register?: (moduleName: string, exportsObj: Record<string, unknown>) => void,
			__phJobsRevertRegisterWrapped?: boolean,
		} | null | undefined} */ ph,
	) {
		var originalRegister = ph && ph.register;
		if (!ph || typeof originalRegister !== "function") return false;
		if (ph.__phJobsRevertRegisterWrapped) return true;
		ph.register =
			/** @type {(moduleName: string, exportsObj: Record<string, unknown>) => void} */ (
				function (moduleName, exportsObj) {
					if (String(moduleName || "") === "app_part_jobs") {
						exportsObj = /** @type {Record<string, unknown>} */ (
							patchJobsExports(
								/** @type {{
								renderJobsFromResponse?: (resp: JobsListResponse) => unknown,
								__phJobsRevertPatched?: boolean,
							} | null | undefined} */ (exportsObj),
							) || {}
						);
					}
					originalRegister.call(this, moduleName, exportsObj || {});
				}
			);
		ph.__phJobsRevertRegisterWrapped = true;
		return true;
	}

	if (!W.PH) {
		log(
			"warn",
			"patchhub_shell.js is legacy; use patchhub_bootstrap.js + patchhub_runtime.js",
		);
		W.PH = {
			register: () => {},
			has: () => false,
			call: () => undefined,
			loadScript: () => Promise.resolve(false),
			_diag: [],
			_registry: {},
		};
	}

	function observe() {
		if (wrapRegister(W.PH_RT || W.PH || null)) return;
		setTimeout(observe, 0);
	}

	observe();
})();
