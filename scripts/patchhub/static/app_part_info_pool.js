(() => {
	/**
	 * @typedef {{ source?: string, text?: string }} InfoPoolLatestHint
	 * @typedef {{
	 *   upload?: string,
	 *   enqueue?: string,
	 *   fs?: string,
	 *   parse?: string,
	 * }} InfoPoolHints
	 * @typedef {{
	 *   degradedNotes?: string[],
	 *   statusLines?: string[],
	 *   hints?: InfoPoolHints,
	 *   latestHint?: InfoPoolLatestHint,
	 *   backendDegradedNote?: string,
	 * }} InfoPoolSnapshot
	 * @typedef {{
	 *   filename_pattern?: string,
	 *   keep_count?: number,
	 *   matched_count?: number,
	 *   deleted_count?: number,
	 * }} CleanupRecentStatusRule
	 * @typedef {{
	 *   job_id?: string,
	 *   issue_id?: string,
	 *   created_utc?: string,
	 *   deleted_count?: number,
	 *   rules?: CleanupRecentStatusRule[],
	 *   summary_text?: string,
	 * }} CleanupRecentStatusItem
	 * @typedef {{
	 *   mode?: string,
	 *   authoritative_backend?: string,
	 *   backend_session_id?: string,
	 *   recovery_status?: string,
	 *   recovery_action?: string,
	 *   recovery_detail?: string,
	 *   degraded?: boolean,
	 * }} BackendModeStatus
	 * @typedef {{
	 *   cleanup_recent_status?: CleanupRecentStatusItem[],
	 *   backend_mode_status?: BackendModeStatus,
	 * }} OperatorInfoSnapshot
	 * @typedef {{
	 *   call?: function(string, ...*): *,
	 *   register?: function(string, Object): void,
	 * }} PatchHubRuntime
	 * @typedef {Window & typeof globalThis & {
	 *   PH?: PatchHubRuntime | null,
	 *   PH_BACKEND_DEGRADED_FROM_OPERATOR_INFO?: function(unknown): string,
	 *   PH_GET_OPERATOR_INFO_SNAPSHOT?: function(): OperatorInfoSnapshot,
	 *   PH_SET_OPERATOR_INFO_SNAPSHOT?: function(unknown): void,
	 *   PH_INFO_POOL_SYNC_LEGACY_DEGRADED_BANNER?: function(): void,
	 *   setBackendDegradedNote?: function(unknown): void,
	 * }} InfoPoolWindow
	 */

	/** @type {InfoPoolWindow} */
	var infoPoolWindow = /** @type {InfoPoolWindow} */ (window);
	/** @type {PatchHubRuntime | null} */
	var PH = infoPoolWindow.PH || null;

	/** @type {OperatorInfoSnapshot} */
	var operatorInfoSnapshot = {
		cleanup_recent_status: [],
		backend_mode_status: {},
	};

	var infoPoolOpen = false;
	var infoPoolBound = false;

	function infoPoolModalEl(/** @type {string} */ id) {
		return el(id);
	}

	/** @returns {InfoPoolSnapshot} */
	function infoPoolSnapshot() {
		if (typeof getInfoPoolSnapshot === "function") {
			return /** @type {InfoPoolSnapshot} */ (getInfoPoolSnapshot());
		}
		return {
			degradedNotes: [],
			statusLines: [],
			hints: { upload: "", enqueue: "", fs: "", parse: "" },
			latestHint: { source: "", text: "" },
		};
	}

	/** @returns {OperatorInfoSnapshot} */
	function infoPoolOperatorInfo() {
		return operatorInfoSnapshot;
	}

	function normalizeBackendModeStatus(/** @type {unknown} */ payload) {
		var source =
			payload && typeof payload === "object"
				? /** @type {BackendModeStatus} */ (payload)
				: {};
		return {
			mode: String(source.mode || ""),
			authoritative_backend: String(source.authoritative_backend || ""),
			backend_session_id: String(source.backend_session_id || ""),
			recovery_status: String(source.recovery_status || "not_run") || "not_run",
			recovery_action: String(source.recovery_action || ""),
			recovery_detail: String(source.recovery_detail || ""),
			degraded: !!source.degraded,
		};
	}

	function normalizeOperatorInfoSnapshot(/** @type {unknown} */ payload) {
		var source =
			payload && typeof payload === "object"
				? /** @type {OperatorInfoSnapshot} */ (payload)
				: {};
		return {
			cleanup_recent_status: Array.isArray(source.cleanup_recent_status)
				? source.cleanup_recent_status.slice()
				: [],
			backend_mode_status: normalizeBackendModeStatus(
				source.backend_mode_status,
			),
		};
	}

	function infoPoolBackendDegradedNoteFromOperatorInfo(
		/** @type {unknown} */ operatorInfo,
	) {
		var info = /** @type {OperatorInfoSnapshot} */ (
			operatorInfo && typeof operatorInfo === "object" ? operatorInfo : {}
		);
		var status = /** @type {BackendModeStatus} */ (
			info.backend_mode_status || {}
		);
		var parts = [
			status.recovery_action,
			status.recovery_detail,
			status.recovery_status,
		]
			.filter(Boolean)
			.map(String);
		if (!(status.degraded || String(status.mode || "") === "file_emergency")) {
			return "";
		}
		return parts.length
			? "Backend file_emergency: " + parts.slice(0, 2).join("; ")
			: "Backend file_emergency";
	}

	infoPoolWindow.PH_BACKEND_DEGRADED_FROM_OPERATOR_INFO =
		infoPoolBackendDegradedNoteFromOperatorInfo;
	function infoPoolCleanupSummaryText(
		/** @type {CleanupRecentStatusItem} */ item,
	) {
		var summary = String((item && item.summary_text) || "").trim();
		if (summary) return summary;
		var issue = String((item && item.issue_id) || "").trim();
		var deleted = Number((item && item.deleted_count) || 0);
		return (
			"Repo snapshot cleanup" +
			(issue ? " issue " + issue : "") +
			": deleted " +
			String(deleted) +
			" file(s)"
		);
	}

	function infoPoolMergedStatusLines(
		/** @type {InfoPoolSnapshot} */ snapshot,
		/** @type {OperatorInfoSnapshot} */ operatorInfo,
	) {
		var lines = Array.isArray(snapshot.statusLines)
			? snapshot.statusLines.slice()
			: [];
		var cleanupItems = /** @type {CleanupRecentStatusItem[]} */ (
			Array.isArray(operatorInfo.cleanup_recent_status)
				? operatorInfo.cleanup_recent_status
				: []
		);
		cleanupItems.forEach((/** @type {CleanupRecentStatusItem} */ item) => {
			lines.push(infoPoolCleanupSummaryText(item));
		});
		return lines;
	}

	function infoPoolPmSummary() {
		if (!PH || typeof PH.call !== "function") return "";
		return String(PH.call("getPmValidationSummary") || "");
	}

	function infoPoolPmSnapshot() {
		if (!PH || typeof PH.call !== "function") return null;
		return PH.call("getPmValidationSnapshot") || null;
	}

	function infoPoolCurrentBackendNote(
		/** @type {OperatorInfoSnapshot} */ operatorInfo,
	) {
		return infoPoolBackendDegradedNoteFromOperatorInfo(operatorInfo);
	}

	function infoPoolDegradedItems(
		/** @type {InfoPoolSnapshot} */ snapshot,
		/** @type {OperatorInfoSnapshot} */ operatorInfo,
	) {
		var items = [];
		var backend = infoPoolCurrentBackendNote(operatorInfo);
		if (!backend) backend = String(snapshot.backendDegradedNote || "");
		if (backend) items.push(backend);
		var degraded = Array.isArray(snapshot.degradedNotes)
			? snapshot.degradedNotes
			: [];
		if (degraded.length) {
			items.push(String(degraded[degraded.length - 1] || ""));
		}
		return items.filter(Boolean);
	}

	function infoPoolSummary(
		/** @type {InfoPoolSnapshot} */ snapshot,
		/** @type {OperatorInfoSnapshot} */ operatorInfo,
	) {
		var backend = infoPoolCurrentBackendNote(operatorInfo);
		if (!backend) backend = String(snapshot.backendDegradedNote || "");
		if (backend) {
			return "DEGRADED MODE: " + backend;
		}
		var degraded = Array.isArray(snapshot.degradedNotes)
			? snapshot.degradedNotes
			: [];
		if (degraded.length) {
			return "DEGRADED MODE: " + String(degraded[degraded.length - 1] || "");
		}
		var pmSummary = infoPoolPmSummary();
		if (pmSummary) return pmSummary;
		if (snapshot.latestHint && snapshot.latestHint.text) {
			return String(snapshot.latestHint.text || "");
		}
		var statusLines = Array.isArray(snapshot.statusLines)
			? snapshot.statusLines
			: [];
		if (statusLines.length) {
			return String(statusLines[statusLines.length - 1] || "");
		}
		return "(idle)";
	}

	function infoPoolHintValue(
		/** @type {string} */ label,
		/** @type {string} */ value,
	) {
		return (
			'<div class="info-pool-hint-row">' +
			'<div class="info-pool-hint-label">' +
			escapeHtml(label) +
			"</div>" +
			'<div class="info-pool-hint-value">' +
			escapeHtml(value || "(empty)") +
			"</div>" +
			"</div>"
		);
	}

	function infoPoolSection(
		/** @type {string} */ title,
		/** @type {string} */ bodyHtml,
	) {
		return (
			'<section class="info-pool-section">' +
			'<h3 class="info-pool-section-title">' +
			escapeHtml(title) +
			"</h3>" +
			bodyHtml +
			"</section>"
		);
	}

	function infoPoolList(
		/** @type {string[]} */ lines,
		/** @type {string} */ emptyText,
	) {
		var items = Array.isArray(lines) ? lines : [];
		if (!items.length) {
			return '<div class="info-pool-empty">' + escapeHtml(emptyText) + "</div>";
		}
		return (
			'<div class="info-pool-lines">' +
			items
				.map((/** @type {string} */ line) => {
					return '<div class="info-pool-line">' + escapeHtml(line) + "</div>";
				})
				.join("") +
			"</div>"
		);
	}

	function infoPoolPre(
		/** @type {string} */ text,
		/** @type {string} */ emptyText,
	) {
		var value = String(text || "");
		if (!value) {
			return '<div class="info-pool-empty">' + escapeHtml(emptyText) + "</div>";
		}
		return '<pre class="info-pool-pre">' + escapeHtml(value) + "</pre>";
	}

	function infoPoolPmSection(
		/** @type {Record<string, unknown> | null} */ snapshot,
	) {
		if (!snapshot || typeof snapshot !== "object") return "";
		var metaHtml = [
			infoPoolHintValue("Status", String(snapshot.status || "")),
			infoPoolHintValue("Mode", String(snapshot.effective_mode || "")),
			infoPoolHintValue("Issue", String(snapshot.issue_id || "")),
			infoPoolHintValue("Message", String(snapshot.commit_message || "")),
			infoPoolHintValue("Patch", String(snapshot.patch_path || "")),
			infoPoolHintValue(
				"Authority",
				Array.isArray(snapshot.authority_sources)
					? snapshot.authority_sources.join(", ")
					: "",
			),
			infoPoolHintValue(
				"Supplemental",
				Array.isArray(snapshot.supplemental_files)
					? snapshot.supplemental_files.join(", ")
					: "",
			),
		].join("");
		return infoPoolSection(
			"PM validation",
			'<div class="info-pool-hints">' +
				metaHtml +
				"</div>" +
				infoPoolSection(
					"Raw validator output",
					infoPoolPre(String(snapshot.raw_output || ""), "(empty)"),
				),
		);
	}

	function renderInfoPoolModal() {
		var modal = infoPoolModalEl("uiStatusModal");
		var body = infoPoolModalEl("uiStatusModalBody");
		if (!modal || !body) return;
		var snapshot = infoPoolSnapshot();
		var operatorInfo = infoPoolOperatorInfo();
		var hints = snapshot.hints || {};
		var degraded = infoPoolDegradedItems(snapshot, operatorInfo);
		var hintHtml = [
			infoPoolHintValue("Upload", String(hints.upload || "")),
			infoPoolHintValue("Start run", String(hints.enqueue || "")),
			infoPoolHintValue("Files", String(hints.fs || "")),
			infoPoolHintValue("Advanced", String(hints.parse || "")),
		].join("");
		var pmHtml = infoPoolPmSection(infoPoolPmSnapshot());
		var recentStatusLines = infoPoolMergedStatusLines(snapshot, operatorInfo);
		body.innerHTML = [
			infoPoolSection("Degraded mode", infoPoolList(degraded, "(empty)")),
			infoPoolSection(
				"Current hints",
				'<div class="info-pool-hints">' + hintHtml + "</div>",
			),
			pmHtml,
			infoPoolSection(
				"Recent status",
				infoPoolList(recentStatusLines, "(empty)"),
			),
		]
			.filter(Boolean)
			.join("");
		modal.classList.toggle("hidden", !infoPoolOpen);
		modal.setAttribute("aria-hidden", infoPoolOpen ? "false" : "true");
	}

	function infoPoolVisiblePmSummary(/** @type {string} */ summary) {
		var pmSummary = infoPoolPmSummary();
		if (!pmSummary || summary !== pmSummary) return "";
		return pmSummary;
	}

	function renderInfoPoolUi() {
		var strip = infoPoolModalEl("uiStatusBar");
		if (!strip) return;
		var summary = infoPoolSummary(infoPoolSnapshot(), infoPoolOperatorInfo());
		var visiblePmSummary = infoPoolVisiblePmSummary(summary);
		strip.textContent = summary;
		strip.classList.add("statusbar-clickable");
		strip.classList.toggle("statusbar-idle", summary === "(idle)");
		strip.classList.toggle(
			"statusbar-pm-pass",
			visiblePmSummary === "PM validation: PASS",
		);
		strip.classList.toggle(
			"statusbar-pm-fail",
			visiblePmSummary === "PM validation: FAIL",
		);
		if (infoPoolOpen) renderInfoPoolModal();
	}

	function setInfoPoolOpen(/** @type {boolean} */ nextOpen) {
		infoPoolOpen = !!nextOpen;
		renderInfoPoolModal();
	}

	function infoPoolSyncLegacyDegradedBanner() {
		var node = infoPoolModalEl("uiDegradedBanner");
		if (!node) return;
		var snapshot = infoPoolSnapshot();
		var degraded = infoPoolDegradedItems(snapshot, infoPoolOperatorInfo());
		var text = degraded.length ? String(degraded[0] || "") : "";
		node.textContent = text;
		node.classList.toggle("hidden", !text);
	}

	function infoPoolSetOperatorInfoSnapshot(/** @type {unknown} */ payload) {
		operatorInfoSnapshot = normalizeOperatorInfoSnapshot(payload);
		renderInfoPoolUi();
		infoPoolSyncLegacyDegradedBanner();
	}

	function onInfoPoolStripKeydown(/** @type {KeyboardEvent} */ event) {
		var key = event && event.key ? String(event.key) : "";
		if (key !== "Enter" && key !== " ") return;
		if (event && typeof event.preventDefault === "function") {
			event.preventDefault();
		}
		setInfoPoolOpen(true);
	}

	function onInfoPoolDocumentKeydown(/** @type {KeyboardEvent} */ event) {
		var key = event && event.key ? String(event.key) : "";
		if (key === "Escape") setInfoPoolOpen(false);
	}

	function initInfoPoolUi() {
		var strip = infoPoolModalEl("uiStatusBar");
		var modal = infoPoolModalEl("uiStatusModal");
		var closeBtn = infoPoolModalEl("uiStatusModalCloseBtn");
		if (!strip || !modal || infoPoolBound) {
			renderInfoPoolUi();
			return;
		}
		infoPoolBound = true;
		strip.addEventListener("click", () => {
			setInfoPoolOpen(true);
		});
		strip.addEventListener("keydown", onInfoPoolStripKeydown);
		if (closeBtn) {
			closeBtn.addEventListener("click", () => {
				setInfoPoolOpen(false);
			});
		}
		modal.addEventListener("click", (event) => {
			if (event && event.target === modal) setInfoPoolOpen(false);
		});
		if (document && typeof document.addEventListener === "function") {
			document.addEventListener("keydown", onInfoPoolDocumentKeydown);
		}
		renderInfoPoolUi();
		infoPoolSyncLegacyDegradedBanner();
	}

	infoPoolWindow.PH_GET_OPERATOR_INFO_SNAPSHOT = () => {
		return normalizeOperatorInfoSnapshot(operatorInfoSnapshot);
	};
	infoPoolWindow.PH_SET_OPERATOR_INFO_SNAPSHOT =
		infoPoolSetOperatorInfoSnapshot;
	infoPoolWindow.PH_INFO_POOL_SYNC_LEGACY_DEGRADED_BANNER =
		infoPoolSyncLegacyDegradedBanner;

	if (PH && typeof PH.register === "function") {
		PH.register("app_part_info_pool", {
			initInfoPoolUi,
			renderInfoPoolUi,
		});
	}
})();
