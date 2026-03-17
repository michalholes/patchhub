(() => {
	function el(id) {
		return document.getElementById(id);
	}

	function apiGet(path) {
		return fetch(path, { headers: { Accept: "application/json" } }).then((r) =>
			r.text().then((t) => {
				try {
					return JSON.parse(t);
				} catch (e) {
					return { ok: false, error: "bad json", raw: t, status: r.status };
				}
			}),
		);
	}

	function apiPost(path, body) {
		return fetch(path, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
			},
			body: JSON.stringify(body || {}),
		}).then((r) =>
			r.text().then((t) => {
				try {
					return JSON.parse(t);
				} catch (e) {
					return { ok: false, error: "bad json", raw: t, status: r.status };
				}
			}),
		);
	}

	function setStatus(msg, isError) {
		var node = el("ampStatus");
		if (!node) return;
		node.textContent = String(msg || "");
		node.classList.toggle("status-error", !!isError);
		node.classList.toggle("status-ok", !isError && !!msg);
	}

	function clearStatus() {
		setStatus("", false);
	}

	function toggleVisible(btnId, wrapId) {
		var btn = el(btnId);
		var wrap = el(wrapId);
		if (!btn || !wrap) return;
		var nowHidden = !wrap.classList.contains("hidden");
		wrap.classList.toggle("hidden", nowHidden);
		btn.textContent = nowHidden ? "Show" : "Hide";
	}

	function mk(tag, cls, text) {
		var n = document.createElement(tag);
		if (cls) n.className = cls;
		if (text != null) n.textContent = String(text);
		return n;
	}

	function cloneListValue(v) {
		if (!Array.isArray(v)) return [];
		return v.map((x) => String(x == null ? "" : x));
	}

	function parseListToken(v) {
		return String(v == null ? "" : v).trim();
	}

	function listValuesEqual(a, b) {
		const aa = cloneListValue(a);
		const bb = cloneListValue(b);
		if (aa.length !== bb.length) return false;
		for (let i = 0; i < aa.length; i++) {
			if (aa[i] !== bb[i]) return false;
		}
		return true;
	}

	function listDisplayValue(v) {
		return v === "" ? "(empty)" : String(v);
	}

	function humanizeKey(key) {
		var s = String(key || "");
		var parts = s.split("_").filter((t) => !!t);
		var out = [];
		parts.forEach((t) => {
			var token = String(t || "");
			if (!token) return;
			var first = token.charAt(0).toUpperCase();
			var rest = token.slice(1).toLowerCase();
			out.push(first + rest);
		});
		return out.join(" ");
	}

	function fallbackHelp(p, key) {
		var o = p || {};
		var type = o && o.type != null ? String(o.type) : "";
		var defv =
			o && Object.prototype.hasOwnProperty.call(o, "default")
				? JSON.stringify(o.default)
				: "";
		var sec = o && o.section != null ? String(o.section) : "";
		var ro = "";
		if (o && Object.prototype.hasOwnProperty.call(o, "read_only")) {
			ro = o.read_only ? "true" : "false";
		}
		return (
			"Type: " +
			type +
			"; " +
			"Default: " +
			defv +
			"; " +
			"Section: " +
			sec +
			"; " +
			"Read-only: " +
			ro
		);
	}

	function schemaToFields(schemaObj) {
		if (schemaObj && Array.isArray(schemaObj.fields)) {
			return schemaObj.fields;
		}

		if (schemaObj && schemaObj.policy && typeof schemaObj.policy === "object") {
			const out = [];
			Object.keys(schemaObj.policy).forEach((k) => {
				var p = schemaObj.policy[k] || {};

				var kind = "str";
				if (Array.isArray(p.enum) && p.enum.length > 0) kind = "enum";
				else if (p.type === "bool") kind = "bool";
				else if (p.type === "int") kind = "int";
				else if (p.type === "list[str]") kind = "list_str";

				var label = "";
				if (p.label && String(p.label).trim() && p.label !== k)
					label = String(p.label);
				else label = humanizeKey(k);

				var help = "";
				if (p.help && String(p.help).trim()) help = String(p.help);
				else help = fallbackHelp(p, k);

				out.push({
					key: k,
					kind: kind,
					label: label,
					help: help,
					enum: Array.isArray(p.enum) ? p.enum : null,
					section: p.section || "",
					read_only: !!p.read_only,
				});
			});
			out.sort((a, b) => {
				var as = String(a.section || "");
				var bs = String(b.section || "");
				if (as < bs) return -1;
				if (as > bs) return 1;
				var ak = String(a.key || "");
				var bk = String(b.key || "");
				if (ak < bk) return -1;
				if (ak > bk) return 1;
				return 0;
			});
			return out;
		}

		return [];
	}

	function renderChipList(container, key, values, onChange) {
		container.textContent = "";

		var chips = mk("div", "chips", null);
		container.appendChild(chips);

		function redraw(list) {
			chips.textContent = "";
			list.forEach((v, idx) => {
				var chip = mk("span", "chip", null);
				chip.appendChild(mk("span", "chip-text", listDisplayValue(v)));
				if (v === "") chip.title = "Empty string item";
				var x = mk("button", "chip-x", "x");
				x.type = "button";
				x.addEventListener("click", () => {
					var next = list.slice();
					next.splice(idx, 1);
					onChange(key, next);
					values = next;
					redraw(next);
				});
				chip.appendChild(x);
				chips.appendChild(chip);
			});
		}

		function addValue(v) {
			var cur = cloneListValue(values);
			cur.push(v);
			inp.value = "";
			onChange(key, cur);
			values = cur;
			redraw(cur);
		}

		var row = mk("div", "row", null);
		var inp = mk("input", "input", null);
		inp.placeholder = "Add item and press Enter";
		inp.addEventListener("keydown", (ev) => {
			if (ev.key !== "Enter") return;
			ev.preventDefault();
			var v = parseListToken(inp.value);
			if (!v) return;
			addValue(v);
		});
		row.appendChild(inp);
		var addEmpty = mk("button", "input", "Add empty item");
		addEmpty.type = "button";
		addEmpty.addEventListener("click", () => {
			addValue("");
		});
		row.appendChild(addEmpty);
		container.appendChild(row);

		redraw(cloneListValue(values));
	}

	function renderFields(
		schemaFields,
		baseValues,
		values,
		onChange,
		filterText,
	) {
		var wrap = el("ampFields");
		if (!wrap) return;
		wrap.textContent = "";

		var ftxt = String(filterText || "").toLowerCase();

		schemaFields.forEach((f) => {
			var key = String(f.key || "");
			var kind = String(f.kind || "str");
			var enumVals = Array.isArray(f.enum) ? f.enum : null;
			var label = String(f.label != null ? f.label : key);
			var help = String(f.help != null ? f.help : "");
			var readOnly = !!f.read_only;

			if (ftxt) {
				const kHit = key.toLowerCase().indexOf(ftxt) >= 0;
				const lHit = label.toLowerCase().indexOf(ftxt) >= 0;
				if (!kHit && !lHit) return;
			}

			var row = mk("div", "amp-row", null);
			row.id = "ampRow__" + key;
			if (help) row.title = help;
			if (readOnly) row.classList.add("amp-readonly");

			var keyBox = mk("div", "amp-key", label);
			keyBox.title = "Key: " + key;
			keyBox.appendChild(mk("div", "amp-key-sub", key));
			row.appendChild(keyBox);

			var ctl = mk("div", "amp-control", null);

			if (readOnly) {
				let ro = "";
				if (kind === "list_str")
					ro = cloneListValue(values[key]).map(listDisplayValue).join(", ");
				else if (kind === "bool") ro = !!values[key] ? "true" : "false";
				else ro = String(values[key] == null ? "" : values[key]);
				ctl.appendChild(mk("span", "amp-readonly-value", ro));
				row.appendChild(ctl);
				wrap.appendChild(row);
				return;
			}

			if (kind === "bool") {
				const sw = mk("label", "switch", null);
				const cb = mk("input", null, null);
				cb.type = "checkbox";
				cb.checked = !!values[key];
				cb.addEventListener("change", () => {
					onChange(key, !!cb.checked);
				});
				sw.appendChild(cb);
				sw.appendChild(mk("span", "slider", null));
				ctl.appendChild(sw);
			} else if (kind === "enum" && enumVals) {
				const sel = mk("select", "input", null);
				enumVals.forEach((optV) => {
					var opt = mk("option", null, String(optV));
					opt.value = String(optV);
					sel.appendChild(opt);
				});
				sel.value = String(values[key] == null ? "" : values[key]);
				sel.addEventListener("change", () => {
					onChange(key, String(sel.value));
				});
				ctl.appendChild(sel);
			} else if (kind === "int") {
				const ni = mk("input", "input", null);
				ni.type = "number";
				ni.value = String(values[key] == null ? "" : values[key]);
				ni.addEventListener("change", () => {
					var raw = String(ni.value == null ? "" : ni.value);
					var n = parseInt(raw, 10);
					onChange(key, Number.isFinite(n) ? n : 0);
				});
				ctl.appendChild(ni);
			} else if (kind === "list_str") {
				const box = mk("div", "amp-list", null);
				ctl.appendChild(box);
				renderChipList(box, key, values[key], onChange);
			} else {
				const ti = mk("input", "input", null);
				ti.type = "text";
				ti.value = String(values[key] == null ? "" : values[key]);
				ti.addEventListener("change", () => {
					onChange(key, String(ti.value));
				});
				ctl.appendChild(ti);
			}

			row.appendChild(ctl);

			if (baseValues) {
				const baseV = baseValues[key];
				const curV = values[key];
				let dirty = false;
				if (kind === "list_str") {
					dirty = !listValuesEqual(baseV, curV);
				} else if (kind === "bool") {
					dirty = !!baseV !== !!curV;
				} else if (kind === "int") {
					dirty = baseV !== curV;
				} else {
					dirty =
						String(baseV == null ? "" : baseV) !==
						String(curV == null ? "" : curV);
				}
				if (dirty) row.classList.add("amp-dirty");
			}

			wrap.appendChild(row);
		});
	}

	function init() {
		var btnCollapse = el("ampCollapse");
		if (btnCollapse) {
			btnCollapse.addEventListener("click", () => {
				toggleVisible("ampCollapse", "ampWrap");
			});
		}

		var schema = null;
		var baseValues = null;
		var curValues = {};
		var fieldKinds = {};
		var filterText = "";

		function cloneValues(src) {
			var out = {};
			Object.keys(fieldKinds).forEach((k) => {
				var kind = fieldKinds[k];
				var v =
					src && Object.prototype.hasOwnProperty.call(src, k)
						? src[k]
						: undefined;
				if (kind === "list_str") {
					out[k] = cloneListValue(v);
				} else if (kind === "bool") {
					out[k] = !!v;
				} else if (kind === "int") {
					out[k] = typeof v === "number" ? v : 0;
				} else {
					out[k] = String(v == null ? "" : v);
				}
			});
			return out;
		}

		function isDirty(k) {
			var kind = fieldKinds[k] || "str";
			var a = baseValues ? baseValues[k] : undefined;
			var b = curValues[k];
			if (kind === "list_str") return !listValuesEqual(a, b);
			if (kind === "bool") return !!a !== !!b;
			return a !== b;
		}

		function updateRowDirty(k) {
			var row = el("ampRow__" + k);
			if (!row) return;
			if (isDirty(k)) row.classList.add("amp-dirty");
			else row.classList.remove("amp-dirty");
		}

		function setCur(k, v) {
			curValues[k] = v;
			updateRowDirty(k);
		}

		function reload() {
			clearStatus();
			return apiGet("/api/amp/schema").then((s) => {
				if (!s || s.ok === false) {
					setStatus(s && s.error ? s.error : "schema load failed", true);
					return;
				}
				schema = s.schema;
				return apiGet("/api/amp/config").then((c) => {
					if (!c || c.ok === false) {
						setStatus(c && c.error ? c.error : "config load failed", true);
						return;
					}
					var fields = schemaToFields(schema || {});
					fieldKinds = {};
					fields.forEach((f) => {
						var k = String(f.key || "");
						var kind = String(f.kind || "str");
						fieldKinds[k] = kind;
					});

					baseValues = cloneValues(c.values || {});
					curValues = cloneValues(baseValues);

					renderFields(fields, baseValues, curValues, setCur, filterText);
					setStatus("Loaded", false);
				});
			});
		}

		function post(dry) {
			clearStatus();
			return apiPost("/api/amp/config", {
				values: curValues,
				dry_run: !!dry,
			}).then((r) => {
				if (!r || r.ok === false) {
					setStatus(r && r.error ? r.error : "update failed", true);
					return;
				}
				baseValues = r.values || baseValues;
				if (!dry) {
					const fields = schemaToFields(schema || {});
					curValues = cloneValues(baseValues);
					renderFields(fields, baseValues, curValues, setCur, filterText);
				}
				setStatus(dry ? "Validation OK" : "Saved", false);
			});
		}

		var btnReload = el("ampReload");
		if (btnReload) btnReload.addEventListener("click", reload);

		var btnValidate = el("ampValidate");
		if (btnValidate)
			btnValidate.addEventListener("click", () => {
				post(true);
			});

		var btnSave = el("ampSave");
		if (btnSave)
			btnSave.addEventListener("click", () => {
				post(false);
			});

		var btnRevert = el("ampRevert");
		if (btnRevert) {
			btnRevert.addEventListener("click", () => {
				if (!baseValues || !schema) return;
				curValues = cloneValues(baseValues);
				renderFields(
					schemaToFields(schema || {}),
					baseValues,
					curValues,
					setCur,
					filterText,
				);
				setStatus("Reverted", false);
			});
		}

		var inpFilter = /** @type {HTMLInputElement|null} */ (el("ampFilter"));
		if (inpFilter) {
			inpFilter.addEventListener("input", () => {
				filterText = String(inpFilter.value || "");
				renderFields(
					schemaToFields(schema || {}),
					baseValues,
					curValues,
					setCur,
					filterText,
				);
			});
		}

		reload();
	}

	var PH = window.PH;
	if (PH && typeof PH.register === "function") {
		PH.register("amp_settings", {
			initAmpSettings: init,
		});
	}
})();
