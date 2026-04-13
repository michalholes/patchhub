(() => {
	/** @type {Array<{ message: string, ts?: string, source?: string, line?: number, col?: number }>} */
	var errors = [];
	/** @type {Array<{ method: string, url: string, status: number, ms: number, error?: string }>} */
	var net = [];

	function el(/** @type {string} */ id) {
		return document.getElementById(id);
	}
	function setPre(/** @type {string} */ id, /** @type {unknown} */ obj) {
		var node = el(id);
		if (!node) return;
		node.textContent =
			typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
	}

	function pushClientError(/** @type {unknown} */ err) {
		errors.push({ message: String(err), ts: new Date().toISOString() });
		setPre("clientErrors", errors);
	}

	function copyPreToClipboard(/** @type {string} */ preId) {
		var node = el(preId);
		var text = node ? node.textContent || "" : "";
		// Prefer modern clipboard API, fallback to execCommand for older contexts.
		if (navigator.clipboard && navigator.clipboard.writeText) {
			return navigator.clipboard.writeText(text);
		}
		return /** @type {Promise<void>} */ (
			new Promise((resolve, reject) => {
				/** @type {HTMLTextAreaElement | null} */
				var ta = null;
				var ok = false;
				try {
					ta = document.createElement("textarea");
					ta.value = text;
					ta.setAttribute("readonly", "true");
					ta.style.position = "absolute";
					ta.style.left = "-9999px";
					document.body.appendChild(ta);
					ta.select();
					ok = document.execCommand("copy");
					document.body.removeChild(ta);
					ta = null;
					if (ok) {
						resolve();
						return;
					}
					reject(new Error("execCommand(copy) returned false"));
				} catch (e) {
					if (ta) {
						try {
							document.body.removeChild(ta);
						} catch {
							// ignore
						}
					}
					reject(e);
				}
			})
		);
	}

	function wireFlushCopy(
		/** @type {string} */ flushBtnId,
		/** @type {string} */ copyBtnId,
		/** @type {string} */ preId,
		/** @type {() => void} */ flushFn,
	) {
		var flushBtn = el(flushBtnId);
		var copyBtn = el(copyBtnId);
		if (!flushBtn || !copyBtn) {
			pushClientError(
				new Error("Missing debug control(s): " + flushBtnId + ", " + copyBtnId),
			);
			return;
		}
		var stableCopyBtn = copyBtn;

		flushBtn.addEventListener("click", () => {
			try {
				flushFn();
			} catch (e) {
				pushClientError(e);
			}
		});
		copyBtn.addEventListener("click", () => {
			copyPreToClipboard(preId)
				.then(() => {
					// Minimal UX feedback without adding new UI elements
					var oldText = stableCopyBtn.textContent;
					stableCopyBtn.textContent = "Copied";
					setTimeout(() => {
						stableCopyBtn.textContent = oldText;
					}, 800);
				})
				.catch((e) => pushClientError(e));
		});
	}

	function loadClientStatus() {
		var raw = "";
		var arr = [];
		try {
			raw = localStorage.getItem("patchhub.client_status_log") || "[]";
			arr = JSON.parse(raw) || [];
			setPre("clientStatus", arr);
		} catch (e) {
			setPre("clientStatus", [{ error: String(e) }]);
		}
	}

	window.addEventListener("error", (e) => {
		errors.push({
			message: String(e.message || "error"),
			source: String(e.filename || ""),
			line: e.lineno || 0,
			col: e.colno || 0,
		});
		if (errors.length > 200) errors.shift();
		setPre("clientErrors", errors);
	});

	var origFetch = window.fetch;
	window.fetch = (url, opts) => {
		var started = Date.now();
		return origFetch(url, opts)
			.then((r) => {
				net.push({
					method: (opts && opts.method) || "GET",
					url: String(url),
					status: r.status,
					ms: Date.now() - started,
				});
				if (net.length > 200) net.shift();
				setPre("clientNet", net);

				loadClientStatus();
				return r;
			})
			.catch((e) => {
				net.push({
					method: (opts && opts.method) || "GET",
					url: String(url),
					status: 0,
					ms: Date.now() - started,
					error: String(e),
				});
				if (net.length > 200) net.shift();
				setPre("clientNet", net);

				loadClientStatus();
				throw e;
			});
	};

	function apiGet(/** @type {string} */ url) {
		return fetch(url, { headers: { Accept: "application/json" } }).then((r) =>
			r.json(),
		);
	}
	function apiPost(/** @type {string} */ url, /** @type {unknown} */ obj) {
		return fetch(url, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
			},
			body: JSON.stringify(obj),
		}).then((r) => r.json());
	}

	function refreshDiag() {
		apiGet("/api/debug/diagnostics").then((r) => {
			setPre("serverDiag", r);
		});
	}

	function refreshTail() {
		apiGet("/api/runner/tail?lines=200").then((/** @type {any} */ r) => {
			setPre("tail", r.tail || "");
		});
	}

	function parseCmd() {
		var raw = /** @type {HTMLInputElement} */ (el("raw")).value;
		apiPost("/api/parse_command", { raw: raw }).then((r) => {
			setPre("parsed", r);
		});
	}

	function init() {
		setPre("clientErrors", errors);
		setPre("clientNet", net);

		loadClientStatus();
		wireFlushCopy(
			"clientErrorsFlush",
			"clientErrorsCopy",
			"clientErrors",
			() => {
				errors = [];
				setPre("clientErrors", errors);
			},
		);
		wireFlushCopy(
			"clientStatusFlush",
			"clientStatusCopy",
			"clientStatus",
			() => {
				localStorage.removeItem("patchhub.client_status_log");
				loadClientStatus();
			},
		);
		wireFlushCopy("clientNetFlush", "clientNetCopy", "clientNet", () => {
			net = [];
			setPre("clientNet", net);
		});
		wireFlushCopy("serverDiagFlush", "serverDiagCopy", "serverDiag", () => {
			setPre("serverDiag", "");
		});
		wireFlushCopy("parsedFlush", "parsedCopy", "parsed", () => {
			setPre("parsed", "");
		});
		wireFlushCopy("tailFlush", "tailCopy", "tail", () => {
			setPre("tail", "");
		});

		var diagRefresh = el("diagRefresh");
		var tailRefresh = el("tailRefresh");
		var parseBtn = el("parse");
		if (diagRefresh) diagRefresh.addEventListener("click", refreshDiag);
		if (tailRefresh) tailRefresh.addEventListener("click", refreshTail);
		if (parseBtn) parseBtn.addEventListener("click", parseCmd);

		refreshDiag();
		loadClientStatus();
		setInterval(loadClientStatus, 1000);
	}

	window.addEventListener("load", init);
})();
