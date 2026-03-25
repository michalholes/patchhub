/// <reference path="./types/am2-import-ui-globals.d.ts" />
/// <reference path="./types/am2-web-interface-globals.d.ts" />
export {};

/* legacy declarations disabled; authoritative declarations moved to types/
declare global {

	type PatchhubJob = {
		job_id?: string;
		status?: string;
		created_utc?: string;
		started_utc?: string | null;
		ended_utc?: string | null;
		mode?: string;
		issue_id?: string;
		commit_summary?: string;
		commit_message?: string;
		patch_basename?: string | null;
		effective_patch_path?: string;
		original_patch_path?: string;
		canonical_command?: string[];
		selected_target_repo?: string;
		effective_runner_target_repo?: string;
		run_start_sha?: string;
		run_end_sha?: string;
	};

	type RerunLatestValues = {
		issueId: string;
		commitMsg: string;
		patchPath: string;
		targetRepo: string;
		jobId: string;
	};

	type RerunLatestOptions = {
		sourceLabel?: string;
		clearOnFailure?: boolean;
		requiredMode?: string;
		failureStatus?: string;
	};

	type JobDetailResponse = {
		ok?: boolean;
		error?: string;
		job?: PatchhubJob | null;
	};

	type RevertResponse = {
		ok?: boolean;
		error?: string;
		job?: PatchhubJob | null;
		job_id?: string;
	};

	type JobsListResponse = {
		ok?: boolean;
		error?: string;
		jobs?: PatchhubJob[];
		sig?: string;
		unchanged?: boolean;
	};

	type OverviewResponse = {
		ok?: boolean;
		error?: string;
		unchanged?: boolean;
		sigs?: {
			snapshot?: string;
			jobs?: string;
			runs?: string;
			patches?: string;
			workspaces?: string;
			header?: string;
		};
		snapshot?: {
			jobs?: PatchhubJob[];
			runs?: unknown[];
			patches?: unknown[];
			workspaces?: unknown[];
			header?: Record<string, unknown>;
		};
	};

	type JobsRuntime = {
		call?: (name: string, ...args: unknown[]) => unknown;
		has?: (name: string) => boolean;
		register?: (name: string, exportsObj: Record<string, unknown>) => void;
	};

	type JobsWindow = Window & typeof globalThis & {
		AMP_PATCHHUB_UI?: {
			updateProgressPanelFromEvents?: (payload: { jobs: PatchhubJob[] }) => void;
		};
		PH?: JobsRuntime | null;
	};

	type JobsEventTarget = EventTarget & {
		getAttribute?: (name: string) => string | null;
		parentElement?: EventTarget | null;
	};
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

declare global {
	type PatchhubJob = {
		job_id?: string;
		status?: string;
		created_utc?: string;
		started_utc?: string | null;
		ended_utc?: string | null;
		mode?: string;
		issue_id?: string;
		commit_summary?: string;
		commit_message?: string;
		patch_basename?: string | null;
		effective_patch_path?: string;
		original_patch_path?: string;
		canonical_command?: string[];
		selected_target_repo?: string;
		effective_runner_target_repo?: string;
		run_start_sha?: string;
		run_end_sha?: string;
	};

	type RerunLatestValues = {
		issueId: string;
		commitMsg: string;
		patchPath: string;
		targetRepo: string;
		jobId: string;
	};

	type RerunLatestOptions = {
		sourceLabel?: string;
		clearOnFailure?: boolean;
		requiredMode?: string;
		failureStatus?: string;
	};

	type JobDetailResponse = {
		ok?: boolean;
		error?: string;
		job?: PatchhubJob | null;
	};

	type RevertResponse = {
		ok?: boolean;
		error?: string;
		job?: PatchhubJob | null;
		job_id?: string;
	};

	type JobsListResponse = {
		ok?: boolean;
		error?: string;
		jobs?: PatchhubJob[];
		sig?: string;
		unchanged?: boolean;
	};

	type OverviewResponse = {
		ok?: boolean;
		error?: string;
		unchanged?: boolean;
		sigs?: {
			snapshot?: string;
			jobs?: string;
			runs?: string;
			patches?: string;
			workspaces?: string;
			header?: string;
		};
		snapshot?: {
			jobs?: PatchhubJob[];
			runs?: unknown[];
			patches?: unknown[];
			workspaces?: unknown[];
			header?: Record<string, unknown>;
		};
	};

	type JobsRuntime = {
		call?: (name: string, ...args: unknown[]) => unknown;
		has?: (name: string) => boolean;
		register?: (name: string, exportsObj: Record<string, unknown>) => void;
	};

	type JobsWindow = Window &
		typeof globalThis & {
			AMP_PATCHHUB_UI?: {
				updateProgressPanelFromEvents?: (payload: {
					jobs: PatchhubJob[];
				}) => void;
			};
			PH?: JobsRuntime | null;
		};

	type JobsEventTarget = EventTarget & {
		getAttribute?: (name: string) => string | null;
		parentElement?: EventTarget | null;
	};
	interface PatchhubUiValueNode extends HTMLElement {
		value: string;
		innerHTML: string;
		textContent: string;
	}

	interface PatchhubUiBridge {
		saveLiveJobId(jobId: string): void;
		updateProgressPanelFromEvents?(payload: {
			jobs: Array<Record<string, unknown>>;
		}): void;
	}

	interface PatchhubConfig {
		runner?: { command?: string[] };
		ui?: { idle_auto_select_last_job?: boolean };
		server?: { host?: string; port?: string | number };
	}

	interface PatchhubDirtyFlags {
		issueId: boolean;
		commitMsg: boolean;
		patchPath: boolean;
		targetRepo: boolean;
	}

	interface PatchhubIdleSigs {
		jobs: string;
		runs: string;
		workspaces: string;
		hdr: string;
		snapshot: string;
		patches: string;
	}

	var cfg: PatchhubConfig;
	var selectedJobId: string | null;
	var suppressIdleOutput: boolean;
	var autoRefreshTimer: ReturnType<typeof setInterval> | null;
	var idleSigs: PatchhubIdleSigs;
	var idleNextDueMs: number;
	var idleBackoffIdx: number;
	var IDLE_BACKOFF_MS: number[];
	var dirty: PatchhubDirtyFlags;
	var AMP_UI: PatchhubUiBridge;

	function el(id: string): PatchhubUiValueNode;
	function clearParsedState(): void;
	function setParseHint(message: string): void;
	function setUiStatus(message: string): void;
	function setUiError(message: string): void;
	function normalizePatchPath(value: string): string;
	function escapeHtml(value: string): string;
	function apiGet(path: string): Promise<unknown>;
	function apiGetETag(
		key: string,
		path: string,
		opts?: { mode?: string; single_flight?: boolean },
	): Promise<unknown>;
	function apiPost(
		path: string,
		body: Record<string, unknown>,
	): Promise<unknown>;
	function setPre(id: string, value: unknown): void;

	interface Window {
		__ph_last_enqueued_job_id?: string;
		__ph_last_enqueued_mode?: string;
		AMP_PATCHHUB_UI?: PatchhubUiBridge;
	}
}
