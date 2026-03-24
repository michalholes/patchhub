/// <reference path="./types/am2-import-ui-globals.d.ts" />
/// <reference path="./types/am2-web-interface-globals.d.ts" />
export {};

/* legacy declarations disabled; authoritative declarations moved to types/
declare global {
	interface Window {
		// --- import/ui globals (realne sa nastavuju v JS assets) ---
		AM2EditorHTTP: any;
		AM2FlowEditor: any;
		AM2FlowEditorState: any; // ak pouzivas AM2FlowEditorState
		FlowEditorState: any; // flow_editor_state.js nastavuje window.FlowEditorState
		AM2FlowConfigEditor: any;
		AM2WizardDefinitionEditor: any;
		AM2UI: any;

		// --- Wizard Definition editor components ---
		AM2WDDomIcons: any;
		AM2WDEdgesIntegrity: any;
		AM2WDStepDetailsLoader: any;
		AM2WDDetailsRender: any;
		AM2WDGraphStable: any;
		AM2WDLayoutRoot: any;
		AM2WDPaletteRender: any;
		AM2WDRawError: any;
		AM2WDSidebar: any;

		AmpSettings: any;

		// --- Patchhub ---
		PH_APP_START: any; // app_part_wire_init.js nastavuje window.PH_APP_START

		__AM_APP_LOADED__: any;
		__AM_UI_LOGS__: any;
		__AM_JS_ERRORS__: any;
		__AM_FETCH_CAPTURE_INSTALLED__: any;

		_amPushJsError: any; // podla logu existuje toto meno
		// ak kod pouziva _amPushJSError, bud oprav kod na _amPushJsError, alebo sem pridaj aj alias:
		_amPushJSError?: any;

		__ph_last_enqueued_job_id: any;
		__ph_last_enqueued_mode: any;
	}

	// Ak sa to vola globalne bez window. (napr. startBookFlow())
	function startBookFlow(...args: any[]): any;
}

*/
