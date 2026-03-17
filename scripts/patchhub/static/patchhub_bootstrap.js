// PatchHub client bootstrap (NO-GO).
// Responsibilities:
// - global error/unhandledrejection handlers
// - bounded client status log persisted to localStorage
// - deterministic load chain: runtime -> app -> PH_APP_MAIN()
// - set degraded flag (in client status log) on first fatal start failure

(() => {
	/** @type {any} */
	const W = window;

	function getStaticVersion() {
		try {
			const el = document.querySelector('meta[name="patchhub-static-version"]');
			if (!el) return "";
			const v = el.getAttribute("content") || "";
			if (typeof v !== "string") return "";
			return v;
		} catch (e) {
			return "";
		}
	}

	function withStaticVersion(url) {
		const v = getStaticVersion();
		if (!v) return url;
		if (url.indexOf("?") >= 0) {
			return url + "&v=" + encodeURIComponent(v);
		}
		return url + "?v=" + encodeURIComponent(v);
	}
	function nowIso() {
		try {
			return new Date().toISOString();
		} catch (e) {
			return "";
		}
	}

	function tryGetLocalStorage() {
		try {
			return W.localStorage;
		} catch (e) {
			return null;
		}
	}

	function recordClientStatus(kind, message) {
		const store = tryGetLocalStorage();
		if (!store) return;
		const item = {
			ts: nowIso(),
			kind: String(kind || ""),
			msg: String(message || ""),
		};
		try {
			const raw = store.getItem("patchhub.client_status_log") || "[]";
			let arr = [];
			try {
				arr = JSON.parse(raw) || [];
			} catch (e) {
				arr = [];
			}
			arr.push(item);
			if (arr.length > 200) arr = arr.slice(arr.length - 200);
			store.setItem("patchhub.client_status_log", JSON.stringify(arr));
		} catch (e) {
			// ignore
		}
	}

	function bootLog(kind, message) {
		const msg = String(message || "");
		try {
			if (kind === "error") console.error("[PatchHub]", msg);
			else if (kind === "warn") console.warn("[PatchHub]", msg);
			else console.log("[PatchHub]", msg);
		} catch (e) {
			// ignore
		}
		recordClientStatus(kind, msg);
	}

	var degradedOnce = false;
	function setDegradedOnce(reason) {
		if (degradedOnce) return;
		degradedOnce = true;
		recordClientStatus("degraded", String(reason || ""));
	}

	function loadScript(url, label) {
		const rawUrl = String(url || "");
		const u = withStaticVersion(rawUrl);
		const l = String(label || "");
		bootLog("status", `load-start ${l} ${rawUrl}`);
		return new Promise((resolve) => {
			/** @type {HTMLScriptElement | null} */
			let s = null;
			try {
				s = document.createElement("script");
				s.src = u;
				s.async = false;
				s.onload = () => {
					bootLog("status", `load-ok ${l}`);
					resolve(true);
				};
				s.onerror = () => {
					bootLog("error", `load-fail ${l}`);
					setDegradedOnce(`fatal: load failed ${l}`);
					resolve(false);
				};
				document.head.appendChild(s);
			} catch (e) {
				bootLog("error", `load-exception ${l}`);
				setDegradedOnce(`fatal: load exception ${l}`);
				resolve(false);
			}
		});
	}

	W.addEventListener("error", (ev) => {
		try {
			const msg = (ev && ev.message) || "window error";
			bootLog("error", `Unhandled error: ${String(msg)}`);
			setDegradedOnce("fatal: unhandled error");
		} catch (e) {
			// ignore
		}
	});

	W.addEventListener("unhandledrejection", (ev) => {
		try {
			const r = ev && ev.reason;
			const msg = (r && r.message) || String(r || "unhandled rejection");
			bootLog("error", `Unhandled rejection: ${msg}`);
			setDegradedOnce("fatal: unhandled rejection");
		} catch (e) {
			// ignore
		}
	});

	W.PH_BOOT = {
		recordClientStatus,
		bootLog,
		setDegradedOnce,
	};

	async function start() {
		if (!W.PH_RT || typeof W.PH_RT !== "object") {
			W.PH_RT = {};
		}
		// Compatibility alias (legacy modules may read window.PH).
		W.PH = W.PH_RT;
		let ok = await loadScript("/static/patchhub_runtime.js", "runtime");
		if (!ok) return;
		if (W.PH_RT.__ph_runtime_ready !== true) {
			bootLog("error", "PH runtime missing");
			setDegradedOnce("fatal: PH runtime missing");
			return;
		}
		ok = await loadScript("/static/app.js", "app");
		if (!ok) return;
		try {
			if (typeof W.PH_APP_MAIN !== "function") {
				bootLog("error", "PH_APP_MAIN is missing");
				setDegradedOnce("fatal: PH_APP_MAIN missing");
				return;
			}
			await Promise.resolve(W.PH_APP_MAIN(W.PH_RT));
			bootLog("status", "app-init-ok");
		} catch (e) {
			bootLog("error", "app-init-failed");
			setDegradedOnce("fatal: app init threw");
		}
	}

	start();
})();
