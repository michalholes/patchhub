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
		} | null,
		PH_BOOT?: { bootLog?: (kind: string, msg: string) => void },
	}} */ (window);

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
})();
