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
		rollback_scope_manifest_rel_path?: string;
		rollback_scope_manifest_hash?: string;
		rollback_authority_kind?: string;
		rollback_authority_source_ref?: string;
		rollback_available?: boolean;
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
		disabled?: boolean;
		checked?: boolean;
		files?: FileList | null;
		placeholder?: string;
	}

	type PatchhubStringMap = Record<string, string>;
	type PatchhubNumberMap = Record<string, number>;
	type PatchhubMaybeElement = HTMLElement | null | undefined;
	type PatchhubMaybeNumber = number | null | undefined;
	type PHStrMap = PatchhubStringMap;
	type PHNumMap = PatchhubNumberMap;
	type PHElRef = PatchhubMaybeElement;
	type PHNumRef = PatchhubMaybeNumber;
	type PatchhubStatusPayload =
		| {
				ok?: boolean;
				error?: string;
				status?: string[];
		  }
		| null
		| undefined;
	type PatchhubGetEtagOpts =
		| {
				mode?: string;
				single_flight?: boolean;
		  }
		| null
		| undefined;
	type PatchhubParseCommandResponse = {
		ok?: boolean;
		error?: string;
		parsed?: {
			mode?: string;
			issue_id?: string;
			commit_message?: string;
			patch_path?: string;
		};
	};
	type PatchhubFsListResponse = {
		ok?: boolean;
		items?: Array<{ name?: string; is_dir?: boolean; size?: number }>;
	};

	interface PatchhubInfoPoolLatestHint {
		source?: string;
		text?: string;
	}

	interface PatchhubInfoPoolHints {
		upload?: string;
		enqueue?: string;
		fs?: string;
		parse?: string;
	}

	interface PatchhubInfoPoolSnapshot {
		degradedNotes?: string[];
		statusLines?: string[];
		hints?: PatchhubInfoPoolHints;
		latestHint?: PatchhubInfoPoolLatestHint;
		backendDegradedNote?: string;
	}

	interface PatchhubToolkitResolutionRecord {
		remote_sig?: string;
		cached_sig_before?: string;
		selected_sig?: string;
		cache_hit?: boolean;
		download_performed?: boolean;
		integrity_check_result?: string;
		resolution_mode?: string;
		checked_at?: string;
		error?: string;
	}

	interface PatchhubPmValidationPayload {
		status?: string;
		effective_mode?: string;
		issue_id?: string;
		commit_message?: string;
		patch_path?: string;
		authority_sources?: string[];
		supplemental_files?: string[];
		failure_summary?: string;
		raw_output?: string;
		toolkit_resolution?: PatchhubToolkitResolutionRecord | null;
	}

	interface PatchhubUiBridge {
		saveLiveJobId(jobId: string): void;
		savePatchesVisible(visible: boolean): void;
		saveWorkspacesVisible(visible: boolean): void;
		saveRunsVisible(visible: boolean): void;
		saveJobsVisible(visible: boolean): void;
		updateProgressPanelFromEvents(payload?: {
			jobs: Array<Record<string, unknown>>;
		}): void;
		getPmValidationSnapshot(): PatchhubPmValidationPayload | null;
		getPmValidationSummary(): string;
		setPmValidationPayload(
			payload: unknown,
		): PatchhubPmValidationPayload | null;
		clearPmValidationPayload(): void;
		initInfoPoolUi(): void;
		renderInfoPoolUi(): void;
	}

	interface PatchhubConfig {
		runner?: { command?: string[] };
		issue?: { issue_id?: string | number; default_regex?: string };
		meta?: { commit_message?: string; version?: string | number };
		autofill?: {
			enabled?: boolean;
			fill_patch_path?: boolean;
			fill_issue_id?: boolean;
			fill_commit_message?: boolean;
			poll_interval_seconds?: string | number;
		};
		targeting?: { zip_target_prefill_enabled?: boolean };
		ui?: {
			idle_auto_select_last_job?: boolean;
			show_autofill_clear_status?: boolean;
			clear_output_on_autofill?: boolean;
		};
		server?: { host?: string; port?: string | number };
		paths?: { patches_root?: string };
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

	type CleanupRecentStatusRule = {
		filename_pattern?: string;
		keep_count?: number;
		matched_count?: number;
		deleted_count?: number;
	};

	type CleanupRecentStatusItem = {
		job_id?: string;
		issue_id?: string;
		created_utc?: string;
		deleted_count?: number;
		rules?: CleanupRecentStatusRule[];
		summary_text?: string;
	};

	interface PatchhubOperatorInfoSnapshot {
		cleanup_recent_status?: CleanupRecentStatusItem[];
		backend_mode_status?: Record<string, unknown>;
	}

	interface PatchhubHeaderRuntime {
		call: (name: string, ...args: unknown[]) => unknown;
		has: (name: string) => boolean;
		register: (name: string, exportsObj: Record<string, unknown>) => void;
	}

	interface PatchhubAutofillHeaderWindow extends Window {
		__ph_patch_load_seq?: number;
		PH?: PatchhubHeaderRuntime | null;
	}

	interface PatchhubHeaderLock {
		held?: boolean;
	}

	interface PatchhubHeaderQueue {
		queued?: number;
		running?: number;
	}

	interface PatchhubHeaderRuns {
		count?: number;
	}

	interface PatchhubHeaderSummary {
		queue?: PatchhubHeaderQueue;
		lock?: PatchhubHeaderLock;
		runs?: PatchhubHeaderRuns;
		stats?: Record<string, unknown>;
	}

	interface PatchhubDiagnosticsDisk {
		total?: number;
		used?: number;
	}

	interface PatchhubDiagnosticsProcess {
		rss_bytes?: number;
	}

	interface PatchhubDiagnosticsHost {
		loadavg_1?: number;
		net_rx_bytes_total?: number;
		net_tx_bytes_total?: number;
	}

	interface PatchhubDiagnosticsResources {
		process?: PatchhubDiagnosticsProcess;
		host?: PatchhubDiagnosticsHost;
	}

	interface PatchhubHeaderDiagnostics extends PatchhubHeaderSummary {
		ok?: boolean;
		disk?: PatchhubDiagnosticsDisk;
		resources?: PatchhubDiagnosticsResources;
	}

	interface PatchhubLatestPatchResponse {
		ok?: boolean;
		error?: string;
		unchanged?: boolean;
		found?: boolean;
		token?: string;
		stored_rel_path?: string;
		derived_issue?: string | number;
		derived_commit_message?: string;
		derived_target_repo?: string;
	}

	interface PatchhubDiagnosticsResponse extends PatchhubHeaderDiagnostics {
		unchanged?: boolean;
	}

	interface PatchhubReadTextResponse {
		ok?: boolean;
		text?: string;
		truncated?: boolean;
	}

	interface PatchhubHeaderRunDetail {
		issue_id?: string | number;
		result?: string;
		mtime_utc?: string;
		log_rel_path?: string;
		archived_patch_rel_path?: string;
		diff_bundle_rel_path?: string;
		success_zip_rel_path?: string;
	}

	var cfg: PatchhubConfig;
	var selectedJobId: string | null;
	var selectedRun: PatchhubHeaderRunDetail | null;
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
	function validateAndPreview(): unknown;
	function normalizePatchPath(value: string): string;
	function escapeHtml(value: string): string;
	function getInfoPoolSnapshot(): PatchhubInfoPoolSnapshot;
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
		activeJobId?: string | null;
		AMP_PATCHHUB_UI?: PatchhubUiBridge;
		PH?: PatchhubHeaderRuntime | null;
		PH_BACKEND_DEGRADED_FROM_OPERATOR_INFO?: (operatorInfo: unknown) => string;
		PH_GET_OPERATOR_INFO_SNAPSHOT?: () => PatchhubOperatorInfoSnapshot;
		PH_SET_OPERATOR_INFO_SNAPSHOT?: (payload: unknown) => void;
		PH_INFO_POOL_SYNC_LEGACY_DEGRADED_BANNER?: () => void;
	}
}
