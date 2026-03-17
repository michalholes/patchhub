// PatchHub client runtime (touchable).
// Provides PH namespace: module registry, safe call access, and ordered script load.

(() => {
	/** @type {any} */
	const W = window;
	const BOOT = W.PH_BOOT || null;
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

	function logStatus(kind, message) {
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

	function setDegraded(reason) {
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

	function record(list, item, max) {
		if (!Array.isArray(list)) return;
		list.push(item);
		if (max && list.length > max) list.splice(0, list.length - max);
	}

	const registry = {};
	const diag = [];
	const once = { missing: {}, fault: {}, load: {} };

	function ensureModule(name) {
		if (!registry[name]) {
			registry[name] = {
				state: "missing",
				last_error: "",
				capabilities: [],
			};
		}
		return registry[name];
	}

	function degradedNote(moduleName, state, details) {
		const base = `Degraded mode: ${String(moduleName)} ${String(state)}`;
		if (!details) return base;
		return `${base} (${String(details)})`;
	}

	function register(moduleName, exportsObj) {
		const name = String(moduleName || "");
		const m = ensureModule(name);
		m.state = "ready";
		m.exports = exportsObj || {};
		m.capabilities = Object.keys(m.exports || {});
		record(diag, { ts: nowIso(), kind: "register", module: name }, 50);
	}

	function hasOwn(obj, key) {
		return Object.prototype.hasOwnProperty.call(obj, key);
	}

	function findCapability(capabilityName) {
		const name = String(capabilityName || "");
		const keys = Object.keys(registry);
		for (let i = 0; i < keys.length; i++) {
			const mod = registry[keys[i]];
			if (!mod || mod.state !== "ready" || !mod.exports) continue;
			if (hasOwn(mod.exports, name)) {
				return { moduleName: keys[i], handler: mod.exports[name] };
			}
		}
		return null;
	}

	function has(capabilityName) {
		return !!findCapability(capabilityName);
	}

	function findFallback(capabilityName) {
		const map = W.PH_APP_FALLBACKS || null;
		if (!map) return null;
		const fn = map[String(capabilityName || "")];
		return typeof fn === "function" ? fn : null;
	}

	function runFallback(cap, args, kind, details) {
		const fallback = findFallback(cap);
		if (!fallback) return undefined;
		record(diag, { ts: nowIso(), kind, cap, details }, 50);
		setDegraded(`fallback active: ${cap}`);
		return fallback.apply(null, args);
	}

	function call(capabilityName, ...args) {
		const cap = String(capabilityName || "");
		const hit = findCapability(cap);
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
			mod.last_error = String((e && e.message) || e || "");
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

	function loadScript(url, moduleName) {
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
