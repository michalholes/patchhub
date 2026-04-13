// PatchHub client runtime (touchable).
// Provides PH namespace: module registry, safe call access, and ordered script load.

(() => {
	/**
	 * @typedef {{
	 *   state: string,
	 *   last_error: string,
	 *   capabilities: string[],
	 *   exports?: Record<string, unknown>,
	 * }} PatchhubRuntimeModule
	 */
	/**
	 * @typedef {{
	 *   ts: string,
	 *   kind: string,
	 *   module?: string,
	 *   cap?: string,
	 *   details?: string,
	 *   error?: string,
	 *   url?: string,
	 * }} PatchhubRuntimeDiag
	 */
	/**
	 * @typedef {{
	 *   moduleName: string,
	 *   handler: (...args: unknown[]) => unknown,
	 * }} PatchhubCapabilityHit
	 */
	/**
	 * @typedef {{
	 *   missing: Record<string, boolean>,
	 *   fault: Record<string, boolean>,
	 *   load: Record<string, boolean>,
	 * }} PatchhubRuntimeOnce
	 */
	/** @type {any} */
	const W = window;
	const BOOT = W.PH_BOOT || null;
	/** @type {Record<string, unknown>} */
	const PH_NS = W.PH_RT || {};
	W.PH_RT = PH_NS;
	W.PH = PH_NS;

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

	function withStaticVersion(/** @type {string} */ url) {
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

	function logStatus(
		/** @type {string} */ kind,
		/** @type {unknown} */ message,
	) {
		const msg = String(message || "");
		try {
			if (kind === "error") console.error("[PatchHub]", msg);
			else if (kind === "warn") console.warn("[PatchHub]", msg);
			else console.log("[PatchHub]", msg);
		} catch (e) {
			// ignore
		}
		try {
			if (BOOT && typeof BOOT.recordClientStatus === "function") {
				BOOT.recordClientStatus(kind, msg);
			}
		} catch (e) {
			// ignore
		}
	}

	function setDegraded(/** @type {unknown} */ reason) {
		try {
			if (BOOT && typeof BOOT.setDegradedOnce === "function") {
				BOOT.setDegradedOnce(reason);
			}
		} catch (e) {
			// ignore
		}
		try {
			if (typeof W.PH_APP_SHOW_DEGRADED === "function") {
				W.PH_APP_SHOW_DEGRADED(reason);
			}
		} catch (e) {
			// ignore
		}
	}

	function record(
		/** @type {PatchhubRuntimeDiag[]} */ list,
		/** @type {PatchhubRuntimeDiag} */ item,
		/** @type {number} */ max,
	) {
		if (!Array.isArray(list)) return;
		list.push(item);
		if (max && list.length > max) list.splice(0, list.length - max);
	}

	/** @type {Record<string, PatchhubRuntimeModule>} */
	const registry = {};
	/** @type {PatchhubRuntimeDiag[]} */
	const diag = [];
	/** @type {PatchhubRuntimeOnce} */
	const once = { missing: {}, fault: {}, load: {} };

	function ensureModule(/** @type {string} */ name) {
		if (!registry[name]) {
			registry[name] = {
				state: "missing",
				last_error: "",
				capabilities: [],
			};
		}
		return registry[name];
	}

	function degradedNote(
		/** @type {string} */ moduleName,
		/** @type {string} */ state,
		/** @type {string | undefined} */ details,
	) {
		const base = `Degraded mode: ${String(moduleName)} ${String(state)}`;
		if (!details) return base;
		return `${base} (${String(details)})`;
	}

	function register(
		/** @type {string} */ moduleName,
		/** @type {Record<string, unknown>} */ exportsObj,
	) {
		const name = String(moduleName || "");
		const m = ensureModule(name);
		m.state = "ready";
		m.exports = exportsObj || {};
		m.capabilities = Object.keys(m.exports || {});
		record(diag, { ts: nowIso(), kind: "register", module: name }, 50);
	}

	function hasOwn(/** @type {object} */ obj, /** @type {string} */ key) {
		return Object.hasOwn(obj, key);
	}

	/** @returns {PatchhubCapabilityHit | null} */
	function findCapability(/** @type {string} */ capabilityName) {
		const name = String(capabilityName || "");
		const keys = Object.keys(registry);
		for (let i = 0; i < keys.length; i++) {
			const mod = registry[keys[i]];
			if (!mod || mod.state !== "ready" || !mod.exports) continue;
			if (hasOwn(mod.exports, name)) {
				return {
					moduleName: keys[i],
					handler: /** @type {(...args: unknown[]) => unknown} */ (
						mod.exports[name]
					),
				};
			}
		}
		return null;
	}

	function has(/** @type {string} */ capabilityName) {
		return !!findCapability(capabilityName);
	}

	function findFallback(/** @type {string} */ capabilityName) {
		const map = W.PH_APP_FALLBACKS || null;
		if (!map) return null;
		const fn = map[String(capabilityName || "")];
		return typeof fn === "function" ? fn : null;
	}

	function runFallback(
		/** @type {string} */ cap,
		/** @type {unknown[]} */ args,
		/** @type {string} */ kind,
		/** @type {string} */ details,
	) {
		const fallback = findFallback(cap);
		if (!fallback) return undefined;
		record(diag, { ts: nowIso(), kind, cap, details }, 50);
		setDegraded(`fallback active: ${cap}`);
		return fallback.apply(null, args);
	}

	function call(
		/** @type {string} */ capabilityName,
		/** @type {unknown[]} */
		...args
	) {
		const cap = String(capabilityName || "");
		const hit = findCapability(cap);
		/** @type {{ message?: string } | null} */
		var err = null;
		if (!hit) {
			record(diag, { ts: nowIso(), kind: "missing", cap }, 50);
			if (!once.missing[cap]) {
				once.missing[cap] = true;
				logStatus("warn", degradedNote("capability", "missing", cap));
				setDegraded(`capability missing: ${cap}`);
			}
			return runFallback(cap, args, "fallback_missing", "capability missing");
		}

		try {
			return hit.handler.apply(null, args);
		} catch (e) {
			const mod = ensureModule(hit.moduleName);
			err = /** @type {{ message?: string } | null} */ (
				e && typeof e === "object" ? e : null
			);
			mod.last_error = String((err && err.message) || e || "");
			record(
				diag,
				{
					ts: nowIso(),
					kind: "fault",
					module: hit.moduleName,
					cap,
					error: mod.last_error,
				},
				50,
			);
			const note = degradedNote(hit.moduleName, "faulted", mod.last_error);
			if (!once.fault[`${hit.moduleName}:${cap}`]) {
				once.fault[`${hit.moduleName}:${cap}`] = true;
				logStatus("error", note);
				setDegraded(`capability fault: ${cap}`);
			}
			return runFallback(cap, args, "fallback_fault", mod.last_error);
		}
	}

	function loadScript(
		/** @type {string} */ url,
		/** @type {string} */ moduleName,
	) {
		const rawUrl = String(url || "");
		const u = withStaticVersion(rawUrl);
		const name = String(moduleName || "");
		const m = ensureModule(name);
		m.state = "loading";
		m.last_error = "";
		logStatus("status", `load-start ${name} ${rawUrl}`);
		return new Promise((resolve) => {
			/** @type {HTMLScriptElement | null} */
			let s = null;
			try {
				s = document.createElement("script");
				s.src = u;
				s.async = false;
				s.onload = () => {
					setTimeout(() => {
						if (m.state === "loading") {
							m.state = "faulted";
							m.last_error = "loaded but not registered";
							record(
								diag,
								{
									ts: nowIso(),
									kind: "load_no_register",
									module: name,
									url: rawUrl,
								},
								50,
							);
							if (!once.load[name]) {
								once.load[name] = true;
								logStatus(
									"error",
									degradedNote(name, "faulted", "loaded but not registered"),
								);
								setDegraded(`module load-no-register: ${name}`);
							}
						}
					}, 0);
					logStatus("status", `load-ok ${name}`);
					resolve(true);
				};
				s.onerror = () => {
					m.state = "missing";
					m.last_error = "load failed";
					record(
						diag,
						{ ts: nowIso(), kind: "load_error", module: name, url: rawUrl },
						50,
					);
					if (!once.load[name]) {
						once.load[name] = true;
						logStatus(
							"error",
							degradedNote(name, "missing", "script load failed"),
						);
						setDegraded(`module load-failed: ${name}`);
					}
					resolve(false);
				};
				document.head.appendChild(s);
			} catch (e) {
				m.state = "missing";
				m.last_error = "load exception";
				record(
					diag,
					{ ts: nowIso(), kind: "load_exception", module: name },
					50,
				);
				setDegraded(`module load-exception: ${name}`);
				resolve(false);
			}
		});
	}

	PH_NS.register = register;
	PH_NS.has = has;
	PH_NS.call = call;
	PH_NS.loadScript = loadScript;
	PH_NS._diag = diag;
	PH_NS._registry = registry;
	PH_NS.__ph_runtime_ready = true;
})();
