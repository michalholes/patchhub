(() => {
	var w = /** @type {any} */ (window);
	var ui = w.AMP_PATCHHUB_UI;
	if (!ui) {
		ui = {};
		w.AMP_PATCHHUB_UI = ui;
	}
	var tickerId = null;
	var surfaces = Object.create(null);

	function nowMs() {
		try {
			if (
				typeof performance === "object" &&
				performance &&
				typeof performance.now === "function"
			) {
				return performance.now();
			}
		} catch (e) {
			// ignore
		}
		return Date.now();
	}

	function formatVisibleDurationMs(ms) {
		var tenths = 0;
		if (!Number.isFinite(ms)) return "";
		if (ms < 0) return "";
		tenths = Math.floor(ms / 100);
		return String((tenths / 10).toFixed(1));
	}

	function makeVisibleRuntimeClock(baseElapsedMs) {
		if (!Number.isFinite(baseElapsedMs)) return null;
		if (baseElapsedMs < 0) baseElapsedMs = 0;
		return {
			anchorElapsedMs: baseElapsedMs,
			anchorNowMs: nowMs(),
		};
	}

	function readVisibleRuntimeElapsedMs(clock, tickNowMs) {
		if (!clock || !Number.isFinite(clock.anchorElapsedMs)) return null;
		var currentNowMs = Number.isFinite(tickNowMs) ? tickNowMs : nowMs();
		var deltaMs = currentNowMs - Number(clock.anchorNowMs || 0);
		if (!Number.isFinite(deltaMs) || deltaMs < 0) deltaMs = 0;
		return Number(clock.anchorElapsedMs) + deltaMs;
	}

	function computeSignature(name, tickNowMs) {
		var surface = surfaces[name];
		if (!surface || typeof surface.getSignature !== "function") return "";
		var sig = surface.getSignature(tickNowMs);
		return typeof sig === "string" ? sig : "";
	}

	function hasRunningSurface() {
		var names = Object.keys(surfaces);
		for (let i = 0; i < names.length; i++) {
			if (computeSignature(names[i], nowMs())) return true;
		}
		return false;
	}

	function tickSurfaces() {
		var currentNowMs = nowMs();
		var names = Object.keys(surfaces);
		var anyRunning = false;
		for (let i = 0; i < names.length; i++) {
			const name = names[i];
			const surface = surfaces[name];
			if (!surface) continue;
			const sig = computeSignature(name, currentNowMs);
			if (sig) anyRunning = true;
			if (sig === surface.lastSignature) continue;
			surface.lastSignature = sig;
			if (typeof surface.render === "function") {
				surface.render();
			}
		}
		if (!anyRunning && tickerId) {
			clearInterval(tickerId);
			tickerId = null;
		}
	}

	function syncTicker() {
		if (hasRunningSurface()) {
			if (!tickerId) tickerId = setInterval(tickSurfaces, 100);
			return;
		}
		if (tickerId) {
			clearInterval(tickerId);
			tickerId = null;
		}
	}

	function setVisibleDurationSurface(name, spec) {
		name = String(name || "").trim();
		if (!name) return;
		if (
			!spec ||
			typeof spec.getSignature !== "function" ||
			typeof spec.render !== "function"
		) {
			delete surfaces[name];
			syncTicker();
			return;
		}
		surfaces[name] = {
			getSignature: spec.getSignature,
			render: spec.render,
			lastSignature: computeSignature(name, nowMs()),
		};
		syncTicker();
	}

	function clearVisibleDurationSurface(name) {
		name = String(name || "").trim();
		if (!name) return;
		delete surfaces[name];
		syncTicker();
	}

	function getVisibleDurationTickerCount() {
		return tickerId ? 1 : 0;
	}

	var PH = w.PH;
	if (PH && typeof PH.register === "function") {
		PH.register("visible_duration", {
			getVisibleDurationNowMs: nowMs,
			formatVisibleDurationMs,
			makeVisibleRuntimeClock,
			readVisibleRuntimeElapsedMs,
			setVisibleDurationSurface,
			clearVisibleDurationSurface,
			getVisibleDurationTickerCount,
		});
	}
	ui.getVisibleDurationTickerCount = getVisibleDurationTickerCount;
})();
