# PatchHub Specification (scripts/patchhub)
Status: AUTHORITATIVE SPECIFICATION
Applies to: scripts/patchhub/*
Language: ENGLISH (ASCII ONLY)

Specification Version: 1.13.0-spec
Code Baseline: audiomason2-main.zip (as provided in this chat)

-------------------------------------------------------------------------------

1. Purpose

PatchHub is the web UI for operating the AM Patch runner (scripts/am_patch.py).

PatchHub provides:
- Patch upload and storage under the repo patches directory
- Canonical command parsing and construction for runner invocation
- A single-runner execution queue (one active runner at a time)
- Live observation of runner output and runner jsonl stream
- Browsing of runner artifacts (logs, successful/unsuccessful archives, web job artifacts)
- Limited filesystem operations within a patches-root jail (config gated)
- Read root-level target.txt from uploaded patch zips for display and target prefill

PatchHub does NOT:
- Generate patches
- Modify uploaded patch zip contents in place
- Create a derived zip unless the user explicitly requested zip subset selection
- Bypass runner gates
- Replace or re-implement runner logic

All repository mutations are performed only by scripts/am_patch.py.
PatchHub is an operator UI, not the authority.

-------------------------------------------------------------------------------

2. Authority and Constraints

Authority order for PatchHub behavior:
1) AUDIOMASON2_PROJECT_CONTRACT.md (base invariants: determinism, anti-monolith, ASCII)
2) scripts/am_patch.py and its spec/manual (runner is authority)
3) This PatchHub specification
4) PatchHub implementation (scripts/patchhub)

Constraints that apply to scripts/patchhub:
- Deterministic behavior (given same config + same filesystem state + same requests)
- Structural integrity (anti-monolith, no catch-all hubs)
- ASCII-only for authoritative docs and responses using ensure_ascii where applicable
- No hidden network activity

2.1 Versioning and Spec Sync (HARD)

Before changing PatchHub behavior, the developer MUST read this specification.

Any behavior change (UI/API/validation/defaults) MUST include:
- a corresponding update to this specification
- a PatchHub runtime version bump in scripts/patchhub/patchhub.toml ([meta].version)

Versioning uses SemVer: MAJOR.MINOR.PATCH
- MAJOR: incompatible behavior change
- MINOR: backward compatible functionality (additive)
- PATCH: backward compatible bug fix

The runtime version MUST NOT be hardcoded in code.

2.2 Idle and Background Activity (HARD)

- PatchHub server MUST NOT use timeout-based polling for the main job queue idle loop.
- The job queue idle loop MUST block on queue.get() and MUST wake only on new work or on stop.
- PatchHub UI visibility handling MUST distinguish four UI states:
  - visible+active
  - visible+idle
  - hidden+active
  - hidden+idle
- When the PatchHub UI document is hidden (document.hidden == true) and no non-terminal
  tracked job exists, the UI MUST pause all periodic refresh timers and MUST close
  active SSE/EventSource connections.
- When the document becomes hidden during a non-terminal tracked job, the UI MUST
  preserve the active lifecycle until backend-confirmed completion.
  - In hidden+active, the UI MUST NOT degrade the tracked job from ACTIVE to IDLE
    only because the document became hidden.
  - In hidden+active, the UI MUST NOT disable the active-mode orchestration path
    required for correct completion detection.
  - In hidden+active, the tracked live job SSE stream MUST remain available until a
    terminal backend signal is observed.
- When the document becomes visible again, the UI MUST resume or reconcile state as
  required by the current tracked job state.
- In `visible+idle`, PatchHub UI routes MUST NOT automatically poll:
  - GET /api/runner/tail
  - GET /api/jobs/<job_id>/log_tail
- In `visible+idle`, the Progress card MUST be derived only from structured state
  (persisted job events, selected job detail, or retained terminal state) and MUST
  NOT be synthesized from raw tail text.
- GET /api/runner/tail is raw-text only and MUST NOT be used for:
  - liveness detection
  - overview invalidation
  - progress reconstruction
  - selected-job state
- Visible duration timer creation MUST be centralized to prevent duplicated
  timers across multiple hide/show cycles.
- Visible duration timers are limited to user-visible elapsed/duration surfaces:
  - the Progress header overall elapsed timer,
  - the Jobs list tracked-row elapsed timer,
  - the Progress per-gate duration pills.
- Polling, refresh, autofill, debug, and missing-patch backoff intervals are
  outside the visible duration timer scope and MUST NOT be folded into the shared
  visible duration controller.

2.3 Client Fault Tolerance (HARD)

- PatchHub UI MUST remain functional if any optional client module fails to load
  or throws at runtime ("degraded mode").
- Failures MUST NOT be silently swallowed.
- The UI MUST surface client faults visibly (banner/panel) and MUST also log them
  via console.error.
- A "degraded mode" indicator MUST be shown whenever a client module is missing
  or failed.
- A fault-tolerance bootstrap script MUST be loaded before any other UI scripts
  and MUST:
  - register window "error" and "unhandledrejection" handlers,
  - provide a safe accessor for optional modules (missing module => visible
    fault + fallback no-op behavior),
  - keep a bounded in-memory list of recent client faults for display.

2.3.1 Bootstrap Identity and No-Go Policy (HARD)

- The PatchHub client bootstrap script MUST be exactly:
  - scripts/patchhub/static/patchhub_bootstrap.js

- index.html MUST load the bootstrap script before any other client script.
- index.html MUST NOT load any other PatchHub client scripts directly.
  - In particular, app.js MUST NOT be included via a direct <script src=...>.

- The bootstrap script is NO-GO.
  - Any patch touching scripts/patchhub/static/patchhub_bootstrap.js MUST be
    rejected unless the issue text contains an explicit approval line from
    Michal permitting a bootstrap change.

2.3.2 Debug Survivability and Fatal Degraded Flag (HARD)

- GET /debug MUST remain functional even if the main UI fails to load or throws
  at runtime.
- The bootstrap MUST persist a bounded client status log to localStorage key:
  - patchhub.client_status_log
- The /debug UI MUST display patchhub.client_status_log.

- The bootstrap MUST set a "degraded" flag in patchhub.client_status_log on the
  first fatal start failure.
- A fatal start failure includes at minimum:
  - failure to load runtime script(s),
  - failure to load app.js,
  - app init throwing (after app.js was loaded).

2.4 Refresh Policy: ACTIVE vs IDLE (HARD)

- The UI MUST implement ACTIVE and IDLE refresh behavior over the four UI states:
  - visible+active
  - visible+idle
  - hidden+active
  - hidden+idle
- ACTIVE is defined by the presence of a tracked non-terminal job.
  - The tracked active job MUST be the selected live job while that job remains in
    a non-terminal state (`queued` or `running`).
  - `document.hidden` alone MUST NOT clear ACTIVE for the tracked non-terminal job.
- During ACTIVE (`visible+active` and `hidden+active`), the UI MUST provide
  near-realtime updates for:
  - live logs,
  - job state/progress (top-right),
  - stop/cancel responsiveness,
  - the tracked active-job elapsed timer in the Progress card header.
- During ACTIVE, the Active job controls MUST be derived from the tracked
  non-terminal job identity together with PatchHub queue/runner actionability
  signals. The UI MUST NOT use current `/api/jobs` list membership as the sole
  criterion for whether Cancel or Hard stop AMP is shown or hidden.
- A temporary `/api/jobs` snapshot gap for the tracked non-terminal job MUST NOT
  by itself suppress Cancel or Hard stop AMP controls.
- If the backend later rejects Cancel or Hard stop AMP for that tracked job, the
  UI MUST leave the form state intact and MUST show an explicit operator-visible
  status/error rather than relying on preventive hiding.
- IDLE is defined by the absence of a tracked non-terminal job.
  - In `visible+idle`, the UI MUST use a deterministic backoff policy for visible-tab
    refresh (see 2.5.1). The UI MUST NOT refresh more frequently than the first
    backoff interval.
  - In `hidden+idle`, the UI MUST perform no refresh or streaming activity.
- In IDLE mode, the UI MUST NOT re-fetch or re-render data that has not changed
  ("conditional refresh").
- Timer creation MUST remain centralized and MUST NOT duplicate refresh loops.

2.5 Conditional Refresh Tokens (HARD)

- APIs that return frequently refreshed UI data MUST expose a stable "version
  token" for each logical payload, including at minimum:
  - runs list,
  - jobs list,
  - header/status summary,
  - latest patch discovery.
- The UI MUST supply the last-seen token on refresh.
- If the token matches (no changes), the server MUST return an "unchanged"
  response without recomputing expensive payloads.
- The UI MUST skip DOM updates if the data is unchanged.


2.5.1 Deterministic IDLE Visible Backoff (HARD)

Scope
- Applies only when the UI is in IDLE mode and document.hidden == false.
- ACTIVE mode behavior MUST NOT be changed by this policy.

Backoff sequence
- The UI MUST use a fixed, deterministic sequence of refresh intervals
  (no jitter). Default sequence: 2s, 5s, 15s, 30s, 60s.
- The sequence MUST be controlled by a single JS constant to enable rollback
  by editing one value.

Reset and advance rules
- The UI MUST track last-seen change tokens (sig) for: jobs, runs, header, latest patch discovery.
- On a refresh attempt, if all sig values are unchanged, the UI MUST advance
  one step in the backoff sequence (capped at the last element).
- If any sig value changes, the UI MUST reset to the first element.
- The UI MUST NOT update the DOM when the server indicates unchanged=true.

Failure mode
- If a sig is incorrect (false-unchanged), UI updates will be delayed.
- Therefore, sig MUST cover all user-visible state for that payload, including
  memory-resident queue jobs and persisted web-jobs state for the active
  backend mode.
- In `db_primary` mode, sig MUST NOT depend on per-job file-tree artifacts
  under `patches/artifacts/web_jobs/<job_id>/`.
- In `file_emergency` mode, sig MUST cover the emergency file-backed web-jobs
  state.

Server contract (canonical transport: HTTP ETag/304)
- Each refresh API MUST compute a stable string token field: sig.
- The server MUST expose the current token as an HTTP ETag header.
- The UI MUST send the last-seen token using If-None-Match.
- If If-None-Match matches the current token, the server MUST respond with:
  HTTP 304 Not Modified (no response body) and MUST NOT compute expensive payload fields.

JSON fallback (compatibility)
- Each refresh API MUST also accept the last-seen token via query parameter since_sig.
- If since_sig matches current sig, the server MUST respond with:
  { ok: true, unchanged: true, sig: <sig> }
  and MUST NOT compute expensive payload fields.
2.6 Runs Indexing: Tail Scan and Cache (HARD)

- Runs result parsing MUST scan from end-of-file and MUST stop as soon as RESULT
  is found.
- Unchanged logs MUST NOT be re-read. Caching MUST be keyed by deterministic file
  metadata (e.g. mtime_ns and size).
- The runs list MUST be able to scale to thousands of logs without full file
  reads on each refresh.

2.6.1 Background Indexer for jobs/runs/ui_snapshot (HARD)

Normal path behavior
- When a background indexer is ready, list endpoints MUST NOT perform any
  filesystem scan or parsing work in the request handler path.
  - This includes scanning logs, scanning legacy web-job artifacts, reading
    legacy `job.json`, and reading/parsing run logs.
- In `db_primary` mode, jobs/ui_snapshot request handlers MUST use the
  persisted web-jobs DB and/or precomputed in-memory snapshots; they MUST NOT
  read legacy per-job files under `patches/artifacts/web_jobs/<job_id>/`.
- In this state, list endpoints MUST serve precomputed, in-memory snapshots and
  MUST limit request handler work to O(n) filtering + JSON serialization.

Indexer behavior
- PatchHub MUST run a background indexer task that maintains snapshots for:
  - jobs list (see 7.2.8)
  - runs list (see 7.2.6 runs; includes canceled runs)
  - ui_snapshot payload (see 2.9)
- On server startup, the indexer MUST perform an initial full scan/build for
  those snapshots.
- After startup, the indexer MUST refresh snapshots on a deterministic polling
  interval configured by `cfg.indexing.poll_interval_seconds`.
- The refresh work MUST execute outside request handlers.

Failure mode
- A bug or crash in the indexer can cause stale UI data.
- If the indexer is not ready, or if it is in an error state, endpoints MAY
  fall back to legacy on-demand request-path behavior.
- In `db_primary` mode, this fallback MAY query the web-jobs DB directly, but
  MUST NOT scan legacy per-job files under `patches/artifacts/web_jobs/`.
- In `file_emergency` mode, this fallback MAY read the emergency file-backed
  web-jobs state.

Debug support
- PatchHub MUST provide a debug-only endpoint to trigger a full rescan:
  `POST /api/debug/indexer/force_rescan` (see 7.3.10).

2.7 Live Events Rendering Limits (HARD)

- The UI MUST throttle high-frequency live event rendering and MUST bound
  in-memory live event storage (ring buffer).
- Throttling MUST NOT break stop/cancel responsiveness.



2.8 Single-Flight Requests (HARD)

Goal: prevent overlapping requests that create backend pressure when responses are slow.

- For each refresh endpoint (jobs, runs, header/stats, ui_snapshot, latest patch),
  the UI MUST enforce single-flight: at most one in-flight request per endpoint.
- If a periodic tick occurs while a request for that endpoint is still in-flight,
  the UI MUST NOT start a second request for the same endpoint.
- If a user action triggers a refresh while a request is in-flight, the UI MUST
  abort the prior request and start a new request.
- Aborting MUST use AbortController.
- The behavior MUST be deterministic (no jitter).

2.9 Batching: /api/ui_snapshot (HARD)

Goal: reduce HTTP overhead by batching multiple list endpoints into one response.

Endpoint
- GET /api/ui_snapshot

Payload
- The response MUST include, at minimum:
  - jobs list (thin, see 2.11),
  - runs list (thin, see 2.11),
  - workspaces list (thin, see 2.11),
  - header/status summary for stable overview rendering.
- The snapshot header payload MUST contain only stable overview fields.
- Volatile host or telemetry diagnostics MUST NOT be included in
  snapshot.header.

Tokens and caching
- The server MUST compute and expose a stable sig for each sub-payload:
  - jobs_sig, runs_sig, workspaces_sig, header_sig.
- header_sig MUST cover all user-visible state present in snapshot.header.
- Volatile diagnostics fields exposed by /api/debug/diagnostics MUST NOT be
  included in header_sig and MUST NOT invalidate the overview snapshot.
- The server MUST compute a snapshot_sig that changes if any sub-payload changes.
- The full snapshot response MUST include the authoritative current overview seq.
- The response MUST include:
  { ok: true, seq: <int>,
    snapshot: { jobs: [...], runs: [...], workspaces: [...], header: {...} },
    sigs: { jobs: <jobs_sig>, runs: <runs_sig>, workspaces: <workspaces_sig>,
      header: <header_sig>, snapshot: <snapshot_sig> } }
- The snapshot endpoint MUST support ETag/304 using snapshot_sig.

Client behavior
- In IDLE mode, the UI SHOULD prefer /api/ui_snapshot over multiple list calls.
- ACTIVE mode MAY continue to use specialized endpoints for near-realtime
  (tail, live stream) without routing through the snapshot endpoint.
- On a successful full snapshot apply, the client MUST treat the returned seq
  as the authoritative locally applied overview seq.

2.10 HTTP ETag and 304 Not Modified (HARD)

- For refresh APIs covered by 2.5 / 2.5.1, ETag/304 is the canonical transport.
- The ETag value MUST be derived from the current sig.
- The server MUST treat If-None-Match strictly:
  - exact string match => 304 with empty body.
- The server MUST include the ETag header on 200 responses.
- The server MAY include the ETag header on 304 responses.

2.10.1 Global Snapshot Events (HARD)

Goal: push overview invalidation without endpoint-by-endpoint polling.

Endpoint
- GET /api/events

Event model
- This endpoint is the authoritative SSE channel for overview snapshot state.
- On connect, the server MUST send exactly one initial snapshot_state event.
- When the overview snapshot changes, the server MUST send a snapshot_changed
  event.
- Events MUST be deterministic and ordered.
- Events MUST be keyed to the single overview snapshot model used by
  /api/ui_snapshot.

Payload requirements
- snapshot_state and snapshot_changed MUST include at minimum:
  - seq: <int>
  - sigs.jobs
  - sigs.runs
  - sigs.workspaces
  - sigs.header
  - sigs.snapshot
- The sig values in SSE payloads MUST match the current overview snapshot.

Client behavior
- The UI MUST use /api/events only for overview invalidation.
- On snapshot_changed, the UI MAY fetch /api/ui_snapshot or
  /api/ui_snapshot_delta.
- The seq carried by an SSE event is the authoritative current backend overview
  seq.
- The client MUST NOT use the just-received event seq as since_seq unless that
  same seq is already the locally applied overview seq.
- SSE events MUST NOT replace specialized ACTIVE-mode job live event streams.

2.10.2 Snapshot Delta Cursor (HARD)

Goal: transfer overview changes without re-sending the full snapshot.

Cursor model
- PatchHub MUST use exactly one monotonic cursor seq for the entire overview
  snapshot model.
- Separate cursors for jobs, runs, workspaces, or header are forbidden.

Endpoint
- GET /api/ui_snapshot_delta?since_seq=<int>

Delta payload
- The response MUST include at minimum:
  - seq: <int>
  - sigs.jobs
  - sigs.runs
  - sigs.workspaces
  - sigs.header
  - sigs.snapshot
  - jobs: { added: [...], updated: [...], removed: [...] }
  - runs: { added: [...], updated: [...], removed: [...] }
  - workspaces: { added: [...], updated: [...], removed: [...] }
  - header_changed: <bool>
  - header: {...} only when header_changed is true

Failure and resync rules
- If since_seq is outside the retained delta window, the server MUST return an
  explicit resync-needed response.
- The client MUST send the last locally applied overview seq as since_seq.
- The client MUST advance its locally applied overview seq only after a delta
  apply succeeds or after a full /api/ui_snapshot apply succeeds.
- The UI MUST fall back to a full GET /api/ui_snapshot on delta failure,
  stale cursor, or resync-needed response.

2.11 Thin DTO Contracts (HARD)

Jobs list item (JobListItem)
- jobs list endpoints MUST return a thin DTO with fields:
  - job_id: string
  - status: string
  - created_utc: string
  - started_utc: string|null
  - ended_utc: string|null
  - mode: string
  - issue_id: string
  - commit_summary: string (single line; deterministic truncation)
  - patch_basename: string|null (filename only; no directory; null if absent)

Runs list item (RunListItem)
- runs list endpoints MUST return a thin DTO with fields:
  - issue_id: int
  - result: string
  - mtime_utc: string
  - log_rel_path: string
  - artifact_refs: array of string (may be empty)

Workspaces list item (WorkspaceListItem)
- workspace list endpoints MUST return a thin DTO with fields:
  - issue_id: int
  - workspace_rel_path: string
  - state: string (DIRTY|CLEAN|KEPT_AFTER_SUCCESS)
  - busy: bool
  - mtime_utc: string
  - attempt: int|null
  - commit_summary: string|null (single line; deterministic truncation)
  - allowed_union_count: int|null

Detail separation
- List DTOs MUST NOT include full commit message text, raw command text, or
  patch filesystem paths.
- Detailed job/run fields MUST be served only by detail endpoints.
- For runs, PatchHub does not define a separate run-detail JSON route beyond
  `GET /api/runs?issue_id=<int>` (optionally with `limit=1`); log text MUST be
  fetched via `GET /api/fs/read_text` using the run's `log_rel_path`
  (`tail_lines` recommended).
- A `log_rel_path` under `artifacts/web_jobs/...` is a PatchHub-owned virtual
  read-only path. In `db_primary` mode it MAY resolve to DB-backed content and
  does not require a physical file to exist.

2.12 Server Sorting and Filtering Cost (HARD)

- List endpoints MUST avoid repeated full materialization + full sort work when
  there is no change.
- For default (unfiltered) list views, the unchanged path MUST return 304 (or
  JSON unchanged) without constructing the list or sorting it.
- If server-side sort/filter is expensive, the implementation MUST use
  incremental or cached ordering keyed by deterministic signatures.


-------------------------------------------------------------------------------

3. Structure (Modules and Responsibilities)

Primary modules:
- asgi/asgi_app.py: HTTP routing, request parsing, response writing (ASGI backend)
- asgi/async_app_core.py: App wiring (composition) for ASGI backend
- config.py: TOML config loading (patchhub.toml)
- fs_jail.py: patches-root jail and CRUD gating
- app_api_core.py: config, parse_command, runs, runner_tail, diagnostics
- app_api_jobs.py: jobs enqueue/list/get/log_tail/cancel
- app_api_upload.py: upload patch artifacts
- app_api_fs.py: fs list/read_text/mkdir/rename/delete/unzip
- asgi/asgi_app.py: /api/fs/archive and /api/jobs/<job_id>/events routes
- asgi/async_event_pump.py: single socket->jsonl event persistence pump (one per job)
- asgi/job_event_broker.py: in-memory per-job event broadcast used for low-latency SSE
- asgi/sse_jsonl_stream.py: JSONL tailing fallback for SSE after restart
- asgi/async_queue.py: job queue, lock, override injection, job persistence
- asgi/async_runner_exec.py: runner subprocess executor
- indexing.py: historical runs indexing from patches/logs
  - Uses deterministic in-process caching for /api/runs results.
  - Cache invalidation is signature-based: (count, max mtime_ns) of matching log files.
- job_store.py: on-disk job.json reader and job listing
  - Uses deterministic in-process caching for /api/jobs/list disk scans.
  - Cache invalidation is signature-based: (count, max mtime_ns) of job.json files.
- issue_alloc.py: issue id allocation by scanning patches dirs
- models.py: dataclasses for JobRecord, RunEntry, AppStats

Anti-monolith rule (for PatchHub code):
- No catch-all file names (utils.py/common.py/helpers.py/misc.py forbidden).
- Keep modules responsibility-specific.
- Prefer extraction over growth.

-------------------------------------------------------------------------------


3.1 UI Fault Containment and Degraded Mode (HARD)

Goal: A failure of any optional UI module MUST NOT crash the PatchHub UI shell.
The UI MUST remain operable in a degraded mode.

Definitions:
- Shell: the always-loaded bootstrap layer responsible for initialization, routing UI events, and rendering fallbacks.
- Module: an optional feature bundle that registers capabilities with the Shell (e.g. live log view, progress rendering).

3.1.1 Shell requirement (HARD)
- A Shell layer MUST exist and MUST be the only mandatory bootstrap.
- The Shell MUST be able to start and render "minimal viable UI" even when zero modules are loaded.

3.1.2 Dispatcher / capability mediator (HARD)
- All calls from the Shell/application code to module functionality MUST go through a centralized dispatcher (capability mediator).
- The dispatcher MUST provide at least:
  - has(capability_name) -> bool
  - call(capability_name, *args, **kwargs) -> any
- call(...) MUST be existence-safe:
  - Calling a non-existent capability MUST NOT raise an exception.
  - It MUST return a stable default (implementation-defined; MUST be documented).
- call(...) MUST be exception-safe:
  - Exceptions thrown by a capability handler MUST be caught inside the dispatcher.
  - The exception MUST NOT propagate to the top-level UI runtime.
- The dispatcher MUST be fault-aware:
  - When a capability throws, its owning module MUST be marked faulted and further calls MAY be short-circuited to defaults.

3.1.3 Deterministic module registration (HARD)
- Each module MUST register itself with:
  - a stable module name (ASCII),
  - a deterministic list of exported capabilities,
  - an optional version string.
- The Shell MUST maintain a module registry with states at minimum:
  - missing, ready, faulted
  - and last_error (string) for diagnostics.

3.1.4 Robust module loading (HARD)
- Module loading MUST provide an explicit success/failure signal to the Shell.
- A module load failure (e.g. 404, parse error) MUST NOT crash the UI.
- The Shell MUST mark the module as missing and render fallbacks for dependent sections.

3.1.5 Explicit UI fallbacks (HARD)
- Any UI section that depends on an optional capability MUST have an explicit fallback renderer.
- Fallback UI MUST clearly indicate degraded mode and identify the missing/faulted module/capability.

3.1.6 Timer/event crash-chain prevention (HARD)
- Top-level periodic refresh ticks and event entrypoints MUST be guarded so that one exception does not stop the loop.
- Any module-invoking work inside timers/events MUST use the dispatcher.

3.1.7 Minimal viable UI without modules (HARD)
Minimal viable UI MUST work when all modules are missing/faulted:
- Patch upload (UI and API path unchanged).
- Start run (enqueue) (UI and API path unchanged).
- Manual refresh of runs/jobs/fs (at least raw JSON rendering is acceptable).
- Display of error status and degraded-mode state.

3.1.8 UI module contract (HARD)
The specification MUST treat modules as optional and MUST define:
- registration shape (module name, capability map),
- dispatcher semantics (existence-safe + exception-safe + fault-aware),
- module registry states and diagnostics fields,
- required fallback behavior for missing/faulted capabilities.


4. Filesystem Model and Jail

4.1 Root of jail
All PatchHub filesystem operations are restricted to patches_root, where:
- patches_root = (repo_root / cfg.paths.patches_root).resolve()

IMPORTANT: PatchHub does NOT provide general repo-root browsing.
It is patches-root only.

4.2 Path input rules (fs_jail.py)
For any rel_path passed to filesystem endpoints:
- MUST be repo-relative to patches_root (no leading "/")
- MUST NOT contain backslashes ("\\")
- MUST be ASCII only
- MUST NOT escape patches_root after resolution
  (candidate = (patches_root / rel_path).resolve(); candidate must be patches_root or under it)

4.3 CRUD gating (fs_jail.py)
CRUD operations are gated by:
- cfg.paths.allow_crud (boolean)
- cfg.paths.crud_allowlist (list of top-level directory names under patches_root)

Allowlist semantics:
- rel_path normalized by stripping leading/trailing "/".
- If normalized is empty, it is allowed only if "" is present in crud_allowlist.
- If normalized contains no "/", it is a root-level entry (file or directory).
  It is allowed if "" is present in crud_allowlist, or if the exact name is present.
- Otherwise, the top-level segment (before first "/") must be in crud_allowlist.
- For the Workspace inventory feature, PatchHub CRUD MAY be enabled for workspace
  trees by including "workspaces" in crud_allowlist.
- When "workspaces" is present in crud_allowlist, the existing filesystem mutation
  endpoints remain authoritative for workspace delete/rename/mkdir/unzip behavior.

If allow_crud is false, all mutation endpoints MUST fail with an error.

4.4 Symlink behavior
Jail enforcement uses Path.resolve(). If resolution ends outside patches_root,
the request MUST fail. This rejects symlink escapes that resolve outside the jail.

-------------------------------------------------------------------------------

5. Configuration (patchhub.toml)

5.1 File
Config file: scripts/patchhub/patchhub.toml

5.2 Required keys (hard)
The loader (config.py) requires the following keys to exist:
- [server] host, port
- [runner] command, default_verbosity, queue_enabled, runner_config_toml
- [paths] patches_root, upload_dir, allow_crud, crud_allowlist
- [upload] max_bytes, allowed_extensions, ascii_only_names
- [issue] default_regex, allocation_start, allocation_max
- [indexing] log_filename_regex, stats_windows_days

UI/autofill have defaults (see config.py).

5.2.0 Optional keys (runner)

- [runner] ipc_handshake_wait_s (int, default 1)
  - Handshake wait injected into AM Patch via web overrides.
  - Value MUST be an integer >= 1.
- [runner] post_exit_grace_s (int, default 5)
  - Shared post-exit grace for bounded completion waits after runner exit.
  - The same value MUST bound both:
    - stdout tail drain in the runner executor, and
    - IPC shutdown-tail completion in the async job queue.
  - Value MUST be an integer >= 1.
- [runner] terminate_grace_s (int, default 3)
  - Grace between SIGTERM and SIGKILL for PatchHub-owned forced stop paths.
  - The same value MUST bound both:
    - running-cancel fallback termination after graceful IPC cancel cannot be
      used or fails, and
    - explicit hard-stop termination of the live runner process group.
  - Value MUST be an integer >= 1.
  - This key MUST NOT change post-exit status mapping semantics; it governs
    only the pre-exit forced-stop ladder.

5.2.1 Optional keys (server)

- [server] backend (string)
  - "asgi": async backend (FastAPI + uvicorn). This is the only supported backend.
  - "sync": removed / unsupported (legacy synchronous backend)

Default behavior is backend="asgi".

5.2.2 Optional keys (indexing)

- [indexing] poll_interval_seconds (int, default 2)
  - Polling interval for the background indexer described in 2.6.1.

5.3 Key semantics used by API
- cfg.meta.version: shown in UI and /api/config
- cfg.runner.command: runner prefix argv (default ["python3","scripts/am_patch.py"])
- cfg.paths.upload_dir: destination directory for uploads (must be under patches_root)
- cfg.autofill.*: controls /api/patches/latest scanning and filename derivation

UI behavior toggles (additive):
- cfg.ui.clear_output_on_autofill (bool, default true)
  If true, when the UI detects a new autofill token it clears the previous output
  (live log, tail view, progress summary and steps) and suppresses idle tail refresh.
- cfg.ui.show_autofill_clear_status (bool, default true)
  If true and output is cleared due to autofill, the UI sets the status bar line:
  "autofill: loaded new patch, output cleared".
- cfg.ui.idle_auto_select_last_job (bool, default false)
  If true, when idle and no job is selected, the UI auto-selects the most recent job.

Autofill zip filtering (additive):
- cfg.autofill.scan_zip_require_patch (bool, default false)
  If true, /api/patches/latest ignores .zip candidates that do not contain at least one
  file entry ending with ".patch" anywhere in the zip.

Autofill issue id from zip (additive):
- cfg.autofill.zip_issue_enabled (bool, default true)
  If true, PatchHub reads an issue id from a root-only text member in a selected/uploaded
  .zip and uses it as the derived issue id.
- cfg.autofill.zip_issue_filename (string, default "ISSUE_NUMBER.txt")
  Zip member name to read. The member MUST be at the zip root (no "/" or "\").
- cfg.autofill.zip_issue_max_bytes (int, default 128)
  Maximum uncompressed size allowed for the issue file.
- cfg.autofill.zip_issue_max_ratio (int, default 200)
  Compression ratio guard (file_size/compress_size).

Validation rules:
- Content MUST be ASCII-only and MUST NOT contain "\r".
- PatchHub strips at most one trailing "\n"; other whitespace is preserved.
- Result MUST be digits only (str.isdigit()).

Derivation precedence:
1) Valid issue id from zip ISSUE_NUMBER.txt
2) Filename derivation via cfg.autofill.issue_regex
3) cfg.autofill.issue_default_if_no_match

-------------------------------------------------------------------------------

6. Response Envelope (JSON)

All JSON responses written by app_support._ok/_err MUST follow:
- Success:
  { "ok": true, ...additional fields... }
- Error:
  { "ok": false, "error": "<string>" }

The following endpoints do NOT use the envelope:
- GET /api/fs/download (raw bytes streaming)
- POST /api/fs/archive (raw zip bytes streaming)
- GET /static/* (raw bytes)

All JSON is encoded with:
- json.dumps(..., ensure_ascii=True, indent=2)
- Content-Type: application/json
- Cache-Control: no-store

6.1 Optional status messages (additive)

JSON responses MAY include an optional field:
- status: ["<string>", ...]

Rules:
- status is additive and MUST NOT break existing clients
- status strings are short, human readable, and non-spammy
- a failure response uses {"ok": false, "error": "..."} and MAY also include status

-------------------------------------------------------------------------------

7. HTTP Surface (Routes, Inputs, Outputs)

HTTP route registration and ASGI request/response entrypoints are owned by
`asgi/asgi_app.py`.

Route-specific handling MAY be delegated to responsibility-specific helper
modules, but PatchHub MUST NOT describe `server.py` as the HTTP route
authority.

7.1 UI routes (GET)
- GET /
  Output: text/html; charset=utf-8 (main UI)

- GET /debug
  Output: text/html; charset=utf-8 (debug UI)

Debug UI per-feed controls (templates/debug.html, static/debug.js):
- Each debug feed MUST provide a Flush control that clears only that feed's
  currently displayed buffer.
- Each debug feed MUST provide a Copy control that copies the exact
  currently visible text of that feed to the clipboard.
- The required per-feed controls apply to at least:
  - Client errors
  - Client status
  - Client network
  - Server diagnostics
  - Parser inspector output
  - Runner tail

- GET /static/<rel>
  Output: static bytes from scripts/patchhub/static/<rel>
  Rule: static path must not escape static base directory.

7.1.0 UI Layout Notes

In the main UI (templates/index.html), the Start button for launching a run
(HTML id: enqueueBtn) MUST remain on the same row as the commit message input
(HTML id: commitMsg).

Approved compact-layout allowances for the run-launch card:
- The visible card heading MAY omit the literal text "B) Start run".
- The mode dropdown (HTML id: mode) MAY use a compact fixed width and MUST
  remain left-aligned.
- The patch path input (HTML id: patchPath) MAY appear either:
  - on the same row as mode and Gate options, or
  - on a dedicated row below.
- If patchPath is placed on the mode row, Gate options MUST remain on the
  right side of that same row.
- The file-manager chooser control (HTML id: browsePatch) MAY remain wired in
  the DOM while being visually hidden from the main screen.
- Compact fixed-width variants are permitted for:
  - issueId: 50 px
  - mode: 50 px
  - patchPath: 120 px

Result badge sizing rule (UI):
- The result badge text (progress summary) MUST be approximately 2x the step header size,
  and MUST NOT dominate the right pane.

7.1.1 Shared Operator Info Pool

The main UI includes exactly one always-visible shared operator info strip for
operator-facing pooled status and hint messages.

Primary strip element (templates/index.html):
- <div id="uiStatusBar" class="statusbar" aria-live="polite"></div>

Detail modal requirement:
- The main UI MUST provide a dedicated modal for pooled operator info detail.
- The strip MUST be the only main-screen entry point for that modal.
- The main screen MUST NOT render extra status buttons, tabs, or secondary
  open controls for the shared pool.

Pooled sources:
- uploadHint
- uiDegradedBanner
- uiStatusBar recent status lines
- enqueueHint
- fsHint
- parseHint

Explicitly excluded from the shared pool:
- hdrMeta
- activeJob
- liveStreamStatus
- ampStatus
- progressSummary
- Jobs item status surfaces
- Runs item result surfaces
- Workspaces per-item state badges and meta
- /debug status and diagnostic surfaces

Behavior (static/app.js plus pool-specific UI module):
- The frontend keeps a ring buffer of recent pooled status lines (default: 20).
- The frontend pushes pooled status lines for:
  - upload (ok/failed)
  - parse_command (ok/failed)
  - enqueue/start job (ok/failed)
  - autofill scan (/api/patches/latest) when the endpoint is called
- If an API response includes status: [...], the frontend appends each line.
- If an API response is {ok:false,error:"..."}, the frontend appends:
  - ERROR: <error>
- The strip summary line MUST be deterministic:
  - if any degraded-mode note exists, the strip shows the latest degraded note
  - else if any pooled hint is currently non-empty, the strip shows the latest
    non-empty pooled hint
  - else if any pooled status line exists, the strip shows the latest pooled
    status line
  - else the strip shows: (idle)
- Clicking the strip MUST open the pooled-detail modal.
- The pooled-detail modal MUST expose:
  - the latest degraded-mode note
  - current pooled hints by source
  - the recent pooled status line history

7.1.2 Live Log Rendering

The main UI includes a live log view for the selected job.

Live view levels (main UI):
- quiet:
  - summary baseline
  - error-bearing content MUST remain visible
- normal:
  - human render
  - MUST include everything from quiet
  - MUST include concise step-flow lines derived from persisted log events
    (for example: DO, OK, FAIL, STATUS, RESULT)
- warning:
  - MUST include everything from normal
  - MUST include warning-level detail
- verbose:
  - MUST include everything from warning
  - MUST include DETAIL/INFO log events
  - MUST include live subprocess stdout/stderr content
- debug_human:
  - MUST render the same persisted event stream as a human-readable debug view
  - log events MUST render without technical prefix expansion such as
    <stage> | <kind> | <sev> | <msg>
  - non-log persisted events MUST still render deterministically as readable lines
- debug_raw:
  - MUST render the persisted SSE event stream without filtering or humanization
  - each persisted event line MUST render as one raw JSON line

Rendering rule for human-rendered levels (quiet, normal, warning, verbose,
debug_human):
- each rendered line MUST be derived deterministically from the persisted
  structured event payload for that event sequence; the UI MUST NOT be limited to
  emitting only ev.msg.
- result events MUST render as: RESULT: SUCCESS or RESULT: FAIL.
- log events with kind=SUBPROCESS_STDOUT MUST render as: [stdout] <msg>.
- log events with kind=SUBPROCESS_STDERR MUST render as: [stderr] <msg>.
- If ev.stdout is present, the UI appends a block: STDOUT:
<text>.
- If ev.stderr is present, the UI appends a block: STDERR:
<text>.
- For quiet, normal, warning, and verbose, the UI MAY synthesize a grouped
  failure-detail block from already received persisted subprocess events for the
  same stage when those subprocess lines were not directly visible at the active
  level and a later error-bearing event for that stage requires them.
- Any grouped failure-detail synthesis MUST use only already received persisted
  structured events; it MUST NOT fetch tail text or infer payload from missing
  data.
- debug_human MUST remain event-faithful: it MAY humanize field combinations, but
  it MUST still represent the same persisted event stream without raw JSON lines.

This is a UI-only rendering rule. The SSE event payload fields
(stage/kind/sev/msg/stdout/stderr) remain unchanged.

Main-screen control rules:
- The mode dropdown remains the only main-screen control for selecting:
  - patch
  - finalize_live (-f)
  - finalize_workspace (-w)
  - rerun_latest (-l)
- The same mode row MUST include a Gate options button on the right side.
- Approved compact layout MAY colocate patchPath on the same mode row while
  keeping Gate options right-aligned.
- Gate options opens a dedicated modal for transient per-run gate overrides.
- The modal MUST NOT contain a separate control for -l.
- Gate options are available only for:
  - patch
  - finalize_live
  - finalize_workspace
  - rerun_latest
- finalize_live gate overrides are transient only and MUST flow through the same
  gate_argv canonicalization and enqueue contract as the other supported modes.
- The modal renders one row per gate with exactly one visible interactive state surface:
  - This run: clickable binary switch representing RUN vs SKIP
- The modal MUST NOT render a separate Config column or passive RUN/SKIP pill.
- The UI MUST NOT expose a visible inherit state.
- The switch visual MUST use full-travel end positions so the thumb reaches the
  left edge for SKIP and the right edge for RUN.
- Gate overrides are transient for the current run only and MUST NOT write to
  AMP config.
- After successful enqueue, terminal mode reset, or autofill token change, the
  UI MUST clear transient gate overrides.

Live retention and clipboard rules:
- The live event view MUST retain at least 20000 events for the tracked job.
- The same retention minimum MUST remain available after reconnect/replay; the
  UI MUST NOT silently reconnect to a smaller history window.
- The live log toolbar MAY render an Auto-scroll toggle on the right side using
  the same switch visual family as the Gate options modal.
- If the Auto-scroll toggle is rendered and enabled, each live-log render MUST
  scroll the live log to the bottom.
- If the Auto-scroll toggle is rendered and disabled, a rerender MUST preserve
  the current manual scroll position.
- The live level dropdown MAY use a compact fixed width in the live log
  toolbar.
- The main screen MUST render Copy selection and Copy all buttons directly below
  the live log, aligned to the bottom-right.
- Copy selection copies only the current text selection inside the live log.
- Copy all copies the full currently rendered live log text.
- The main screen MUST NOT render a dedicated visible badge/label showing the
  numeric live buffer size.

7.1.3 Progress Card Rendering (Variant 2)

The main UI includes a Progress card (right sidebar) that renders per-step status
for the tracked active job.

HTML elements (templates/index.html):
- <span id="progressElapsed" class="muted hidden"></span>
- <div id="progressSteps" class="progress-steps"></div>
- <div id="progressSummary" class="progress-summary muted"></div>
- <div id="progressApplied" class="progress-applied hidden"></div>

Visible duration timer rules:
- PatchHub MUST use exactly one shared client-side visible duration controller for
  all visible duration timers in scope.
- The shared visible duration controller MUST use `performance.now()` only as a
  local render clock between authoritative updates.
- The shared visible duration controller MUST NOT use tail text or human-readable
  log lines as elapsed-time authority.
- Visible timer text MUST use one-decimal-second `floor` formatting for both
  running and terminal states, always including the trailing `.0` when needed.
- Visible timer DOM updates MUST occur only when the visible one-decimal-second
  value changes, when a timer enters/exits running state, or when tracked-job
  selection changes.

Primary parsing source (static client modules):
- During ACTIVE, the UI MUST use the persisted job event SSE stream as the canonical
  source for:
  - the live log pane,
  - the Active job surface,
  - the top-right Progress card.
- The canonical live source includes the terminal SSE trailer:
  - event: end
  - data: {"reason":"job_completed","status":"<job.status>"}
- Tail endpoints remain available only as explicit raw-log fallback/debug surfaces.
  - Tail text MUST NOT drive the Progress card.
  - Tail text MUST NOT replace structured event/state sources during ACTIVE.
  - Tail endpoints MUST NOT participate in automatic idle refresh.
- Step transitions are derived from persisted event payloads corresponding to runner
  progress markers:
  - DO: <STEP>
  - OK: <STEP>
  - FAIL: <STEP>
  - gate_<name>=SKIP (<reason>) markers emitted during that step
  - terminal end status from `event: end`

Rendering rules:
- Each discovered step is rendered in first-seen order.
- Per-step states:
  - pending: gray dot
  - running: yellow dot and a RUNNING pill
  - skip: gray dot and a SKIPPED pill that includes the skip reason
  - ok: green dot
  - fail: red dot
- Progress header overall elapsed rule:
  - The Progress card header MUST render the tracked-job overall elapsed timer on
    the right side while a tracked job with `started_utc` exists.
  - The overall elapsed timer MUST use `started_utc` and `ended_utc` as the
    authoritative start/stop timestamps.
  - While the tracked job is non-terminal, the shared visible duration controller
    MAY interpolate between authoritative updates using `performance.now()`.
  - After the tracked job becomes terminal, the header MUST render the frozen
    elapsed value derived from `ended_utc - started_utc` until a newer tracked
    job or explicit user selection replaces it.
- Per-step duration pill rule for non-skipped progress steps:
  - The Progress card MUST derive the step duration only from structured
    persisted AMP stage start/stop events and their authoritative timestamps.
  - Tail text and human-readable log lines MUST NOT start, stop, advance or
    reconstruct any step duration pill.
  - Start is the first persisted event for that stage with `kind="DO"`.
  - Stop is the first later persisted event for that stage with
    `kind="OK"` or `kind="FAIL"`.
  - A skip marker for that stage MUST suppress the duration pill and MUST
    annul any running duration for that stage.
  - While the step is running, the shared visible duration controller MAY
    interpolate between authoritative updates using `performance.now()`, but the
    visible label MUST remain `RUNNING (<elapsed>s)` with one-decimal-second
    `floor` formatting.
  - After the step reaches OK or FAIL, the UI MUST render `<elapsed>s` and
    MUST retain that frozen duration until the tracked job is replaced by a
    newer tracked job or explicit user selection.
  - After reload/reconnect, the step duration pill MUST be reconstructible from
    the persisted structured stage start/stop events without relying on any
    session-local stopwatch state.
  - A skipped step MUST render only the existing `SKIPPED (...)` pill and
    MUST NOT render a duration pill.
- A step that emitted a skip marker MUST remain visually skipped even if the
  surrounding runner wrapper later emits OK for that same step.
- Exactly one step is shown as running (the most recent DO without a later
  terminal step outcome).

Summary rule:
- During ACTIVE, `progressSummary` MUST follow the latest persisted live event state.
- If the latest step-local persisted state is a skip marker, `progressSummary`
  MUST surface that skip as: SKIP: <STEP> (<reason>).
- On receipt of terminal `event: end`, `progressSummary` MUST converge to the
  canonical structured terminal summary derived from the AMP `type="result"`
  payload and MUST NOT remain stuck on an older running step.
- The terminal structured payload is the primary authority for terminal summary
  text, stage, reason, commit, push, and NDJSON/log paths.
- Tail-derived summary is legacy fallback/resync only for artifacts that do not
  carry the canonical structured terminal payload.

Applied files rule:
- For a successful selected or just-finished job, Progress MUST render an
  Applied files block directly below RESULT: SUCCESS.
- After a tracked job reaches a terminal state, the Progress card MUST retain the
  final summary for that last tracked job until a newer tracked job or an explicit
  user selection replaces it.
- After a tracked job reaches a terminal state, the live event buffer for that last
  tracked job MUST remain visible until a newer tracked job or explicit user
  selection replaces it.
- The block is a first-glance surface; it MUST NOT require opening Preview,
  Issue detail tabs, or the log pane.
- Applied files are sourced from runner artifacts only:
  - primary: issue_<ISSUE>_diff*.zip -> manifest.txt -> FILE <repo-path>
  - fallback: FILES: section from final summary text
- For non-success results, the UI MUST render an explicit unavailable state;
  it MUST NOT fabricate applied files from the UI selection.

This is a UI-only rendering rule. Runner output format is unchanged.

7.1.4 Preview Default Visibility (HARD)

The Preview panel is collapsed by default.
The UI MUST NOT auto-expand the Preview panel after:
- Parse (parse_command)
- Enqueue/Start run

Preview visibility is controlled only by explicit user interaction
(Preview buttons).

7.1.5 Quick Actions Removal

The "Quick actions" card is not present in the main UI.
Filesystem navigation remains available via the Files panel.

7.1.6 Main UI Layout Ordering

The main UI layout is deterministic and layout-only. This section changes card
placement only; it does not change queue behavior, validation rules, or API
semantics.

Header rules (templates/index.html):
- The header MUST render only the top title/status row.
- The header MUST NOT render parseHint or enqueueHint.

Shared pool placement and local-surface rules:
- The shared operator info strip MUST render inside the Start run card below the
  start-form rows and above the Live log heading.
- The Start run card MUST NOT render separate visible rows for uiDegradedBanner
  or enqueueHint.
- The Active job card MUST NOT render a separate visible uploadHint line.
- The Active job card MUST NOT render a separate visible elapsed line; the
  canonical tracked-job elapsed surface is the Progress card header.
- The Files card MUST NOT render a separate visible fsHint line.
- The Advanced card MUST NOT render a separate visible parseHint line.
- The pooled sources listed in 7.1.1 MUST remain available through the shared
  operator info modal even when their original inline surfaces are not visible.

Left sidebar order (top to bottom):
- Active job
- Workspaces
- Stats
- Runs

Right sidebar order (top to bottom):
- Progress
- Jobs
- Preview
- Advanced

Advanced card requirements:
- The UI MUST provide a dedicated "Advanced" card in the right
  sidebar.
- The card MUST contain the canonical runner command controls:
  - rawCommand
  - parseBtn
  - previewToggle
  - parseHint
- The Advanced card MUST render below the Preview card.

This is a layout-only requirement. Existing element ids and existing client
behavior remain unchanged.

7.1.6A Sidebar Collapsible Lists (Runs, Jobs)

The main UI includes three sidebar lists that are operator convenience only:
- Workspaces list (left sidebar; above Stats and Runs)
- Runs list (left sidebar)
- Jobs list (right sidebar)

These lists MUST be collapsible and MUST be hidden by default.

HTML elements (templates/index.html):
- Workspaces:
  - toggle button: <button id="workspacesCollapse" ...>
  - wrapper: <div id="workspacesWrap" class="hidden"> ... </div>
- Runs:
  - toggle button: <button id="runsCollapse" ...>
  - wrapper: <div id="runsWrap" class="hidden"> ... </div>
- Jobs:
  - toggle button: <button id="jobsCollapse" ...>
  - wrapper: <div id="jobsWrap" class="hidden"> ... </div>

Behavior (static/app.js):
- Default visibility:
  - workspacesVisible = false
  - runsVisible = false
  - jobsVisible = false
- UI state persistence uses localStorage keys:
  - amp.ui.workspacesVisible ("1" or "0")
  - amp.ui.runsVisible ("1" or "0")
  - amp.ui.jobsVisible ("1" or "0")
- If a key is missing or invalid, the default is hidden ("0").

Button text:
- When the wrapper is hidden, the corresponding button MUST display: Show
- When the wrapper is visible, the corresponding button MUST display: Hide

Workspace list item content (UI)

The Workspaces list is an operator convenience view.
Each list item MUST provide a meaningful summary without requiring a click.

Required visible fields per item:
- issue id (rendered as "#<id>")
- state badge (DIRTY, CLEAN, or KEPT_AFTER_SUCCESS)
- commit message summary when available
- attempt when available
- allowed_union_count when available
- busy marker when the same issue currently has a queued/running job
- actions: Open, Finalize (-w), Delete

Layout requirements:
- First line MUST show: issue id and state badge.
- Commit summary MUST be on its own line when present.
- Meta line MUST include: attempt, allowed_union_count, busy marker, and last
  activity time when present.
- Actions MUST operate as follows:
  - Open: navigate the Files panel to workspace_rel_path.
  - Finalize (-w): prepare the Start form for finalize_workspace only; it MUST:
    - set mode = finalize_workspace
    - set issueId = workspace issue id
    - clear commitMsg, patchPath, and rawCommand
    - refresh preview/validation
    - MUST NOT enqueue a job and MUST NOT start processing before explicit Start
  - Delete: use the existing filesystem delete endpoint against workspace_rel_path.

Terminology rule:
- The UI label for this card MUST be "Workspaces".
- The UI MUST NOT label the card as "In-progress workspaces" or equivalent,
  because a workspace directory may exist after a successful run.

This is a UI/API behavior change. The queue model and runner authority are unchanged.

Jobs list item content (UI)

The Jobs list is an operator convenience view.
Each list item MUST provide a meaningful summary without requiring a click.

Required visible fields per item:
- issue id (rendered as "#<id>"; if missing, render "(no issue)")
- status (uppercase)
- commit message summary (single line; deterministic truncation)
- mode
- patch basename (filename only)
- duration in seconds when both started_utc and ended_utc are available
- for the tracked active job row, a client-side elapsed duration derived from
  started_utc while the job remains non-terminal

Layout requirements:
- First line MUST show: issue id and status.
- Commit summary MUST be on its own line.
- Meta line MUST include: mode, patch basename (when present), and duration
  (when present).
- The elapsed duration for the tracked active job row MUST update client-side
  without requiring an additional backend fetch cycle.
- The Jobs list tracked-row elapsed timer MUST use the same shared visible
  duration controller and the same one-decimal-second `floor` formatter as the
  Progress header overall elapsed timer.
- A quick action row MAY appear below the meta line.
- The quick action label MUST be: Use for -l

Quick action rules:
- The quick action is a Start-form preparation control, not an enqueue control.
- The UI MAY render the quick action only for list items whose visible summary is
  compatible with rerun_latest candidate selection:
  - mode is patch or rerun_latest
  - issue id is non-empty
  - commit summary is non-empty
- On click, the UI MUST fetch GET /api/jobs/<job_id> and MUST validate the detail
  record before mutating the Start form.
- If the clicked job is start-form-usable for rerun_latest, the UI MUST:
  - set mode = rerun_latest
  - set issueId, commitMsg, and patchPath from that JobRecord
  - clear rawCommand
  - refresh preview/validation
  - MUST NOT enqueue a job and MUST NOT start processing before explicit Start
- If the clicked job is not start-form-usable for rerun_latest, the UI MUST leave
  the Start form unchanged and MUST show an explicit operator-visible status.

Forbidden in visible item text:
- job_id (may exist only as an internal data attribute for selection)

7.1.6B rerun_latest Autofill Authority (UI)

Definitions:
- detail-eligible rerun job = a JobRecord that satisfies all of the following:
  - mode is patch or rerun_latest
  - issue_id is non-empty
  - commit_message is non-empty
  - patch path resolves by this algorithm:
    1) effective_patch_path when non-empty
    2) else original_patch_path when non-empty
    3) else the patch operand derived from canonical_command for patch/rerun_latest
- start-form-usable rerun job = a detail-eligible rerun job whose resolved patch
  path also exists under patches_root after PatchHub jail resolution.
- latest start-form-usable job = the first start-form-usable rerun job in jobs
  history sorted by created_utc descending.

Single source of truth:
- Global rerun_latest (-l) preparation and per-job quick action preparation MUST
  use the same authority model: JobRecord detail selected by job_id.
- The client MUST NOT derive rerun_latest autofill from:
  - /api/runs
  - tracked live fallback state
  - /api/patches/latest
  - workspace metadata
- /api/jobs list is a candidate discovery surface only.
- GET /api/jobs/<job_id> is the authoritative detail source for rerun_latest
  Start-form filling.
- Patch path existence for rerun_latest Start-form usability MUST be checked
  against PatchHub filesystem authority under patches_root with jail
  constraints; discovery/list summary alone is insufficient.

Global mode-switch behavior:
- When the operator changes the mode dropdown to rerun_latest, the UI MUST:
  - clear rawCommand
  - resolve the latest start-form-usable job from jobs history
  - fetch the authoritative JobRecord detail for the selected job_id
  - verify the resolved patch path exists under patches_root with jail
    constraints before mutating the Start form
  - fill issueId, commitMsg, and patchPath from that one JobRecord
  - refresh preview/validation
  - MUST NOT enqueue a job and MUST NOT start processing before explicit Start
- If no start-form-usable rerun job exists, the UI MUST:
  - clear issueId, commitMsg, and patchPath
  - refresh preview/validation
  - show an explicit operator-visible status indicating that no start-form-usable
    previous job exists for rerun_latest

7.1.6C Autofill Token Change Output Clearing (UI)

When autofill is enabled and the UI detects that /api/patches/latest returns a new
token value, the UI may clear output from the previous patch run.

Config gates (patchhub.toml [ui]):
- clear_output_on_autofill (default true)
  If true, on new token detection the UI clears:
  - the live log view (SSE rendered events),
  - the Tail view,
  - the Progress summary and step list.

  Because automatic idle tail polling is forbidden, the cleared output MUST remain
  cleared until structured selected/tracked data or an explicit user action replaces it.

- show_autofill_clear_status (default true)
  If true and output is cleared due to autofill, the UI status bar is set to the
  exact line: "autofill: loaded new patch, output cleared".

Job selection interaction:
- Manual job selection (click on an item in the Jobs list) shows that job via
  structured replay/state surfaces and MAY expose explicit raw-log access.
- Starting a new job (enqueue success) activates the structured live event path
  for that job.

Idle auto-select:
- If idle_auto_select_last_job is false (default), the UI does not auto-select
  the most recent job when idle.
- If idle_auto_select_last_job is true, the UI preserves the legacy behavior
  and auto-selects the most recent job when idle.

Running job exception:
- If a job is running and no job is selected, the UI selects the running job.

7.1.6D PM Validation Summary Strip and Operator Info Modal (UI)

When a patch zip is loaded through the zip-manifest flow:
- PatchHub MUST run the same `pm_validator.py` used by chat delivery for
  diagnostic parity.
- This PM validation run is load-time only. Enqueue MUST NOT trigger a second PM
  validator run and PM FAIL MUST NOT block patch job creation.
- The shared `uiStatusBar` MUST show a short PM validation summary after load.
  Required labels are:
  - `PM validation: PASS`
  - `PM validation: FAIL`
  - `PM validation: ERROR`
  - `PM validation: MISSING CONTEXT`
- PM validation summary priority in the strip is:
  1. degraded mode
  2. PM validation summary
  3. latest pooled hint
  4. recent status line
- Clicking the status bar MUST open the existing `Operator info` modal.
- The modal MUST expose a dedicated `PM validation` section containing:
  - PM status
  - effective mode
  - issue id
  - commit message
  - patch path
  - authority sources
  - supplemental files, if any
  - full raw validator output in a preformatted block
- Raw PM validator output MUST NOT be merged into `Recent status`.

Authority chain for load-time PM validation:
- Initial validation MUST derive TARGET from the basename of the workspace
  snapshot artifact explicitly selected as the authority input for that
  validation run, using the PM contract `<TARGET>-main_<OPAQUE>.zip`.
- `<OPAQUE>` MUST be ignored for TARGET derivation.
- PatchHub MUST NOT silently replace a missing or unspecified initial
  authority input with its own alternative authority hierarchy.
- If PatchHub does not have one explicit workspace snapshot authority
  input for the current initial validation run, the PM status MUST be
  `MISSING CONTEXT`.
- Repair validation MUST use the latest `patched_issue<issue>_*.zip`
  overlay as the authority input for TARGET.
- In repair mode, overlay `target.txt` is authoritative for TARGET.
- A workspace snapshot MAY be used in repair mode only for:
  - basename-versus-overlay TARGET consistency check, and
  - exact per-file supplemental authority requested by the validator via
    explicit `--supplemental-file` paths.
- Implicit bulk or full-tree fallback is forbidden.
- The `authority sources` field in Operator info MUST list exactly the
  artifact paths actually passed to the validator for that run.

7.1.7 Missing patchPath Clears Run Fields (UI) (HARD)

Rule:
- The UI MUST enforce the following invariant:
- If the file referenced by the current Run patchPath does not exist on disk,
  the UI MUST set:
  - issueId = ""
  - commitMsg = ""
  - patchPath = ""

Notes:
- This clearing is unconditional with respect to user edits, autofill, dirty flags,
  and overwrite policies.

7.1.8 Mode Reset After Terminal Job (UI) (HARD)

Rule:
- After any job reaches a terminal state (success, failed, canceled),
  the UI MUST set the mode dropdown to: patch.

Additionally, after resetting mode to patch due to a terminal job state,
  the UI MUST clear the start-form inputs: issueId, commitMsg, patchPath, rawCommand.

Additionally, after the same terminal reset, the UI MUST clear any transient
Gate options overrides for the next run.


Notes:
- This rule applies to all UI-exposed modes (patch, finalize_live, finalize_workspace, rerun_latest).
- repair is a legacy mode supported only for backward compatibility via API/parse; UI MUST NOT expose repair in the mode dropdown.

7.1.9 Autofill New Patch Token Forces Patch Mode (UI) (HARD)

Rule:
- When /api/patches/latest returns a new token (a different patch than previously
  seen), the UI MUST:
  - set mode dropdown to: patch
  - set issueId, commitMsg, patchPath from the new autofill payload
  - clear rawCommand (if present)


7.2 API routes (GET)

7.2.1 GET /api/config
Output schema (success):
{
  "meta": { "version": "<string>" },
  "server": { "host": "<string>", "port": <int> },
  "runner": {
    "command": ["<string>", ...],
    "default_verbosity": "<string>",
    "queue_enabled": <bool>,
    "runner_config_toml": "<string>",
    "success_archive_rel": "<string>"
  },
  "paths": {
    "patches_root": "<string>",
    "upload_dir": "<string>",
    "allow_crud": <bool>,
    "crud_allowlist": ["<string>", ...]
  },
  "upload": {
    "max_bytes": <int>,
    "allowed_extensions": ["<string>", ...],
    "ascii_only_names": <bool>
  },
  "issue": {
    "default_regex": "<string>",
    "allocation_start": <int>,
    "allocation_max": <int>
  },
  "indexing": {
    "log_filename_regex": "<string>",
    "stats_windows_days": [<int>, ...],
    "poll_interval_seconds": <int>
  },
  "ui": {
    "base_font_px": <int>,
    "drop_overlay_enabled": <bool>,
    "clear_output_on_autofill": <bool>,
    "show_autofill_clear_status": <bool>,
    "idle_auto_select_last_job": <bool>,
    "live_event_buffer_limit": <int>
  },
  "autofill": {
    "enabled": <bool>,
    "poll_interval_seconds": <int>,
    "overwrite_policy": "<string>",
    "fill_patch_path": <bool>,
    "fill_issue_id": <bool>,
    "fill_commit_message": <bool>,
    "scan_dir": "<string>",
    "scan_extensions": ["<string>", ...],
    "scan_ignore_filenames": ["<string>", ...],
    "scan_ignore_prefixes": ["<string>", ...],
    "choose_strategy": "<string>",
    "tiebreaker": "<string>",
    "derive_enabled": <bool>,
    "issue_regex": "<string>",
    "commit_regex": "<string>",
    "commit_replace_underscores": <bool>,
    "commit_replace_dashes": <bool>,
    "commit_collapse_spaces": <bool>,
    "commit_trim": <bool>,
    "commit_ascii_only": <bool>,
    "issue_default_if_no_match": "<string|null>",
    "commit_default_if_no_match": "<string|null>"
  },
  "targeting": {
    "options": ["<string>", ...],
    "default_target_repo": "<string>",
    "zip_target_prefill_enabled": <bool>
  }
}

Notes:
- success_archive_rel is computed by compute_success_archive_rel(repo_root, runner_config_toml, patches_root_rel).
- It reads [paths].success_archive_name from runner_config_toml (default "{repo}-{branch}.zip").
- It resolves branch via: git rev-parse --abbrev-ref HEAD (cwd=repo_root).
  If git fails, or returns "HEAD", it uses runner_config_toml [git].default_branch (fallback "main").
- It substitutes {repo} and {branch}, takes os.path.basename, and ensures a .zip suffix.
- It always returns a relative path string: <patches_root_rel>/<name>.zip.

7.2.2 GET /api/fs/stat?path=<string>
Input:
- query parameter: path (string, relative to patches jail)
Output:
{ "ok": true, "path": "<string>", "exists": <bool> }
Semantics:
- exists is true iff the referenced file exists on disk within jail constraints.
- For path == "", the endpoint MUST return exists == true.

7.2.3 GET /api/fs/list?path=<string>
Input:
- query param "path" (default empty string)
Output (success):
{
  "ok": true,
  "path": "<string>",
  "items": [
    { "name": "<string>", "is_dir": <bool>, "size": <int>, "mtime": <int> },
    ...
  ]
}
Errors:
- 400 for jail validation errors
- 404 if not a directory

7.2.4 GET /api/fs/read_text?path=<string>&tail_lines=<int>&max_bytes=<int>
Inputs:
- query "path" (required)
- query "tail_lines" (optional; if present and non-empty, tail mode is used)
- query "max_bytes" (optional; default 200000; clamped to [1, 2000000])

Outputs (success):
- Tail mode:
  { "ok": true, "path": "<string>", "text": "<string>", "truncated": false }
- Head mode:
  { "ok": true, "path": "<string>", "text": "<string>", "truncated": <bool> }

Notes:
- Head mode reads full source bytes first, then truncates in memory.
- UTF-8 decode uses errors="replace".
- `artifacts/web_jobs/...` is a PatchHub-owned virtual read-only namespace.
- In `db_primary` mode, `read_text` for `artifacts/web_jobs/...` MUST resolve
  from persisted DB-backed content.
- In `file_emergency` mode, `read_text` for `artifacts/web_jobs/...` MAY read
  the emergency file-backed web-jobs state.

Errors:
- 400 for jail validation errors
- 404 if the resolved source does not exist
- 500 if the resolved source cannot be read

7.2.5 GET /api/fs/download?path=<string>
Output:
- Raw file bytes with guessed Content-Type and Content-Length.
Errors:
- JSON error with 400/404 if jail validation or file not found.

7.2.5a GET /api/workspaces
Output schema (success):
{
  "ok": true,
  "items": [<WorkspaceListItem>, ...],
  "sig": "<string>"
}

Rules:
- The endpoint MUST derive workspace paths from runner config state, not from a
  hardcoded patches/workspaces path.
- The endpoint MUST expose workspace_rel_path relative to patches_root.
- The endpoint MUST classify state deterministically:
  - DIRTY: the workspace repository has tracked or untracked changes.
  - CLEAN: the workspace exists and the workspace repository is clean.
  - KEPT_AFTER_SUCCESS: the workspace exists and the latest known run result for
    the same issue is success.
- The endpoint MUST set busy=true when the same issue currently has a queued or
  running job in PatchHub.
- The endpoint MUST support ETag/304 using sig.

7.2.5b GET /api/patches/latest
Purpose:
- Used by UI autofill/polling to find latest matching file in scan_dir.

Defaulting:
- If scan_dir is empty, it defaults to cfg.paths.patches_root.
- If scan_dir equals patches_root, scan_dir_rel is "".

Behavior:
- If cfg.autofill.enabled is false:
  { "ok": true, "found": false, "disabled": true }
- Only supports:
  choose_strategy == "mtime_ns"
  tiebreaker == "lex_name"
  Otherwise returns error 400.

Scanning rules:
- scan_dir must be under patches_root, else 400.
- Scan is non-recursive; only direct children files.
- Files filtered by scan_extensions, scan_ignore_filenames, scan_ignore_prefixes.
- If cfg.autofill.scan_zip_require_patch is true:
  - .zip candidates are considered only if the zip contains at least one file entry
    ending with ".patch" (case-insensitive), anywhere in the zip.
  - corrupted/unreadable zips are ignored (no 500); they count as ignored_zip_no_patch.
- Best file chosen by max mtime_ns; ties broken by lexicographic name.

Status counters (additive):
- ignored_zip_no_patch=<int>
  Count of ignored .zip candidates due to missing any .patch file entry, including
  corrupted/unreadable zips.

Output (found):
{
  "ok": true,
  "found": true,
  "filename": "<string>",
  "stored_rel_path": "<string>",
  "mtime_ns": <int>,
  "token": "<mtime_ns>:<stored_rel_path>",
  "derived_issue": "<string|null>",                 (only if derive_enabled)
  "derived_commit_message": "<string|null>",        (only if derive_enabled)
  "derived_target_repo": "<string|null>"            (only for zip inputs)
}

7.2.6 GET /api/runs?issue_id=<int>&result=<string>&limit=<int>
Inputs:
- issue_id (optional): filters to that issue
- result (optional): one of "success"|"fail"|"unknown"|"canceled"
- limit (optional): default 100; clamped to [1, 500]

Data sources:
- logs-based runs from `indexing.iter_runs(patches_root, log_filename_regex)`
- plus canceled runs derived from persisted PatchHub web-jobs state for the
  active backend mode

Sorting:
- runs sorted by `(mtime_utc, issue_id)` descending
- truncated to `limit`

Output (success):
{
  "ok": true,
  "runs": [
    {
      "issue_id": <int>,
      "log_rel_path": "<string>",
      "result": "success|fail|unknown|canceled",
      "mtime_utc": "<UTC ISO Z string>",
      "artifact_refs": ["<string>", ...]
    },
    ...
  ]
}

Derivation details:
- result parsed from last 200 non-empty lines of log, after ANSI strip.
- artifact_refs is a list of existing artifact rel paths under patches_root for the issue_id:
  - archived patch: latest file in patches/successful or patches/unsuccessful containing "issue_<id>"
  - diff bundle: latest file in patches/artifacts containing "issue_<id>_diff"
  - success zip: config-derived success archive rel path when present
- missing artifacts are omitted (artifact_refs may be empty).

7.2.7 GET /api/runner/tail?lines=<int>
Input:
- query "lines" (optional; default 200; clamped in read_tail to [1, 5000])

Output (success):
{
  "ok": true,
  "path": "<string>",     (logical path: patches_root/am_patch.log)
  "tail": "<string>"      (last N lines; empty if file missing)
}

Note:
- This tails patches_root/am_patch.log, not a job-local log.
- This endpoint is raw-text only.
- PatchHub UI routes MUST NOT call it automatically during startup, idle refresh,
  visible resync, or overview refresh.
- It MUST NOT be used for liveness detection, progress rendering, selected-job
  state, or overview invalidation.

7.2.8 GET /api/jobs
Output:
{
  "ok": true,
  "jobs": [ <JobListItem JSON>, ... ]
}
Jobs are the union of:
- in-memory queue jobs, plus
- persisted PatchHub web-jobs entries from the active backend mode (up to 200)
  not present in memory
Sorted by `created_utc` descending.

7.2.9 GET /api/jobs/<job_id>
Output:
{ "ok": true, "job": <JobRecord JSON> }
Error 404 if not found in memory or in the active backend mode.

Detail-only additive fields for patch/repair jobs:
- original_patch_path: "<string|null>"
- effective_patch_path: "<string|null>"
- effective_patch_kind: "original|derived_subset|null"
- zip_target_repo: "<string|null>"
- selected_target_repo: "<string|null>"
- effective_runner_target_repo: "<string|null>"
- target_mismatch: <bool>
- selected_patch_entries: ["<zip member>", ...]
- selected_repo_paths: ["<repo path>", ...]
- applied_files: ["<repo path>", ...]
- applied_files_source: "diff_manifest|final_summary|non_success|unavailable"
- terminal_summary: {
    "terminal_status": "success|fail|canceled|null",
    "final_stage": "<string|null>",
    "final_reason": "<string|null>",
    "final_commit_sha": "<string|null>",
    "push_status": "OK|FAIL|null",
    "log_path": "<string|null>",
    "json_path": "<string|null>"
  }

GET /api/jobs remains the thin list endpoint defined elsewhere in this spec;
these fields are detail-only and MUST NOT be added to list items.

7.2.9A GET /api/patches/zip_manifest?path=<string>
Output:
{
  "ok": true,
  "manifest": <ZipPatchManifest JSON>,
  "pm_validation": <PatchPmValidation JSON>,
  "derived_target_repo": "<string|null>"
}
Error 400 if path missing, path is not a zip, or the zip cannot be resolved.

ZipPatchManifest JSON:
{
  "path": "<string>",
  "is_zip": true,
  "selectable": <bool>,
  "reason": "ok|zip_has_no_patch_entries|zip_not_pm_per_file_layout",
  "patch_entry_count": <int>,
  "entries": [
    {
      "zip_member": "<string>",
      "repo_path": "<string|null>",
      "selectable": <bool>
    }
  ],
  "root_metadata_present": ["COMMIT_MESSAGE.txt", "ISSUE_NUMBER.txt", ...]
}

PatchPmValidation JSON:
{
  "status": "pass|fail|error|missing_context",
  "effective_mode": "initial|repair-overlay-only|repair-supplemental",
  "issue_id": "<string>",
  "commit_message": "<string>",
  "patch_path": "<string>",
  "authority_sources": ["<string>", ...],
  "supplemental_files": ["<string>", ...],
  "raw_output": "<string>"
}

Rules:
- PM validation is computed exactly once for the loaded zip patch.
- The endpoint MUST use zip-derived issue/message inputs with the same autofill
  precedence used by PatchHub patch intake.
- The endpoint MUST NOT trigger enqueue or any patch execution side effects.
- Subset selection remains available only when selectable is true.

7.2.10 GET /api/jobs/<job_id>/log_tail?lines=<int>
Output:
{ "ok": true, "job_id": "<string>", "tail": "<string>" }
Source:
- active backend mode human-readable job log store (last N lines)
- In `db_primary` mode, source is the persisted DB-backed web-jobs log store.
- In `file_emergency` mode, source is the emergency file-backed `runner.log`.
If the source log is missing: tail is empty string.
Rules:
- This endpoint is raw-text only.
- PatchHub UI routes MUST NOT poll it automatically in `visible+idle`.
- It MUST NOT be used for liveness detection, overview invalidation, or Progress
  card reconstruction.
- It MAY remain available for explicit raw-log fallback/debug access.

7.2.11 GET /api/jobs/<job_id>/events
Output:
- `text/event-stream; charset=utf-8` (SSE)

Semantics (`asgi/asgi_app.py`):
- If job not found in memory and not found in the active backend mode:
  - returns 200 and immediately emits:
    event: end
    data: {"reason":"job_not_found"}
- Otherwise:
  - On enqueue (job created and queued), the server MUST ensure that persisted
    event history exists and contains at least one accepted/queued event record,
    so that clients see immediate output without waiting for the job to enter
    `running`.
  - While job status is `queued` (or `running`), the server MUST NOT emit an
    `end` event solely because persisted event history does not yet exist.
  - The server streams `data: <json line>` for each complete persisted event
    line.
  - On connection, the server SHOULD replay a recent tail of persisted event
    history (default: last 500 lines) before switching to broker live streaming.
  - Live events SHOULD appear in the UI with low latency (no polling batching).

Runner IPC event persistence robustness (HARD):
- The job event pump MUST NOT rely on `asyncio StreamReader.readline()` limits.
- The pump MUST read the IPC stream in chunks and split on `"\n"`.
- The pump MUST persist each complete JSONL line as-is (after UTF-8 decode).
- This raw capture rule includes IPC control and reply frames received on the
  job socket.
- If a single line grows beyond 64 MiB without a newline, the pump MUST drop
  the partial buffer and emit a JSON notice line with:
  `{"type":"patchhub_notice","code":"IPC_LINE_TOO_LARGE_DROPPED",...}`.
- After runner process exit, PatchHub MUST use `cfg.runner.post_exit_grace_s` as
  the shared bounded wait for both stdout tail drain and IPC shutdown-tail
  completion.
- If the shared post-exit grace expires, PatchHub MUST cancel the pending tail
  wait, record deterministic diagnostics, and continue finalization.
- Emits periodic comment pings every ~10 seconds:
  `: ping`
- Ends with:
  event: end
  data: {"reason":"job_completed","status":"<job.status>"}

Lifecycle invariants (HARD):
- The server MUST treat historical replay and broker-based streaming as
  equivalent with respect to termination semantics.
- Completion ordering MUST be:
  1) Set final job status (`success|fail|canceled`)
  2) Persist final job state to the active backend mode
  3) Close the live broker (if any)
  4) Emit SSE end trailer:
     event: end
     data: {"reason":"job_completed","status":"<job.status>"}
  The status carried in the end trailer MUST be the final persisted status.
- Silent termination (stream ends without an explicit `event: end`) is forbidden.
- Broker close MUST be deterministic:
  - Backpressure MAY drop data lines,
  - but MUST NOT drop the broker termination signal (subscriber loops MUST end).
- After successful enqueue (HTTP 200 for `POST /api/jobs/enqueue`),
  `GET /api/jobs/<job_id>/events` MUST NOT return `{"reason":"job_not_found"}`.
- A stuck post-exit tail wait MUST NOT keep a memory-resident job in
  `status="running"` indefinitely after runner exit.
- When `cfg.runner.post_exit_grace_s` expires after runner exit, PatchHub MUST:
  - stop waiting on the pending tail task,
  - preserve completion status mapping from `return_code`,
  - persist deterministic diagnostics describing the timed-out tail path, and
  - unblock the single-runner queue for subsequent jobs.

SSE source rule (HARD):
- SSE MUST NOT connect to the runner IPC socket directly.
- Live SSE streaming MUST use an in-memory job event broker fed by the job
  event pump.
- Historical replay in `db_primary` mode MUST use the persisted DB-backed event
  store only.
- Historical replay in `file_emergency` mode MAY use the persisted file-backed
  event store.

End-of-stream rule:
- If job status != `running` and no growth observed for >= 0.5 seconds, stream
  ends.

7.2.12 GET /api/debug/diagnostics
Output: JSON object (NOT envelope).
Rules:
- This endpoint is the authoritative diagnostics and telemetry payload for the
  PatchHub header debug details.
- Volatile diagnostics fields returned here MUST NOT be duplicated inside
  ui_snapshot.header.
- Volatile diagnostics fields returned here MUST NOT be included in header_sig.
- Volatile diagnostics fields returned here MUST NOT trigger overview snapshot
  invalidation.
Schema (best-effort, current implementation):
{
  "queue": { "queued": <int>, "running": <int> },
  "lock": { "path": "<string>", "held": <bool> },
  "disk": { "total": <int>, "used": <int>, "free": <int> },
  "runs": { "count": <int> },
  "stats": { "all_time": <StatsWindow>, "windows": [<StatsWindow>, ...] },
  "resources": {
    "process": { "rss_bytes": <int>, "cpu_user_seconds": <float>, "cpu_system_seconds": <float> },
    "host": {
      "loadavg_1": <float>, "loadavg_5": <float>, "loadavg_15": <float>,
      "mem_total_bytes": <int>, "mem_available_bytes": <int>,
      "net_rx_bytes_total": <int>, "net_tx_bytes_total": <int>
    }
  }
}
StatsWindow schema:
{ "days": <int>, "total": <int>, "success": <int>, "fail": <int>, "unknown": <int> }

7.2.13 GET /api/events
Output: SSE stream.
Event names:
- snapshot_state
- snapshot_changed

Event payload:
{
  "seq": <int>,
  "sigs": {
    "jobs": "<string>",
    "runs": "<string>",
    "workspaces": "<string>",
    "header": "<string>",
    "snapshot": "<string>"
  }
}

Rules:
- On connect, exactly one snapshot_state event MUST be sent first.
- Subsequent overview changes MUST emit snapshot_changed.
- No per-endpoint invalidation events are permitted on this channel.

7.2.14 GET /api/ui_snapshot_delta?since_seq=<int>
Output (success):
{
  "ok": true,
  "seq": <int>,
  "sigs": {
    "jobs": "<string>",
    "runs": "<string>",
    "workspaces": "<string>",
    "header": "<string>",
    "snapshot": "<string>"
  },
  "jobs": { "added": [...], "updated": [...], "removed": [...] },
  "runs": { "added": [...], "updated": [...], "removed": [...] },
  "workspaces": { "added": [...], "updated": [...], "removed": [...] },
  "header_changed": <bool>,
  "header": { ... }
}

Output (resync needed):
{ "ok": true, "resync_needed": true, "seq": <int> }

Rules:
- removed arrays MUST contain stable item identities only.
- header MUST be present only when header_changed is true.
- If header_changed is false, the header field MUST be omitted, not null.
- The endpoint MUST operate on the single overview seq defined in 2.10.2.

-------------------------------------------------------------------------------

7.3 API routes (POST)

7.3.1 POST /api/parse_command
Input JSON:
{ "raw": "<string>" }

Output (success):
{
  "ok": true,
  "parsed": {
    "mode": "patch|finalize_live|finalize_workspace|rerun_latest",
    "issue_id": "<string>",
    "commit_message": "<string>",
    "patch_path": "<string>"
  },
  "canonical": { "argv": ["<string>", ...] }
}

Parsing rules (command_parse.py):
- shlex.split(raw)
- must contain "scripts/am_patch.py" as an argv element
- supports finalize/rerun flags in rest (combinations are rejected):
  -f MESSAGE [gate overrides] => finalize_live
    (MESSAGE is required; stored as commit_message)
  -w ISSUE_ID => finalize_workspace (ISSUE_ID is required; digits only)
  - ISSUE_ID MESSAGE [PATCH] -l => rerun_latest
- patch mode requires exactly 3 args after scripts/am_patch.py:
  ISSUE_ID (digits), commit message (non-empty), PATCH (non-empty)
- finalize_live, finalize_workspace, rerun_latest, and patch accept canonical gate overrides:
  - --no-compile-check
  - --skip-ruff
  - --skip-pytest
  - --skip-mypy
  - --skip-js
  - --skip-docs
  - --skip-monolith
  - --override KEY=VALUE for compile_check and gates_skip_* booleans
- Canonicalization MUST normalize gate flags into deterministic argv order.

Errors:
- 400 with ok=false and error string on parse/validation failure

7.3.2 POST /api/jobs/enqueue
Input JSON fields (minimum accepted by app_api_jobs.py):
- mode: "patch" | "repair" | "finalize_live" | "finalize_workspace" | "rerun_latest"
- issue_id: "<string>"           (optional for patch/repair; auto-allocated if missing)
- commit_message: "<string>"     (required for patch/repair unless raw_command provides)
- patch_path: "<string>"         (required for patch/repair unless raw_command provides)
- raw_command: "<string>"        (optional; if provided, it is parsed and canonicalized)
- gate_argv: ["<flag>", ...]     (optional; patch/finalize_live/finalize_workspace/rerun_latest only)
- target_repo: "<string>"        (optional; structured patch/rerun_latest only)
- selected_patch_entries: ["<zip member>", ...] (optional; patch/repair zip subset only)

Behavior:
- If raw_command is present:
  - parse_runner_command(raw_command)
  - canonical argv from parsed command is used
  - missing fields may be filled from body fields as fallback
  - raw_command MUST NOT be combined with selected_patch_entries
  - raw_command MUST NOT be combined with gate_argv
  - raw_command MUST NOT be combined with target_repo
- If raw_command is absent:
  - finalize_live requires commit_message and builds:
    runner_prefix + ['-f', commit_message] + gate_argv
  - finalize_workspace requires issue_id (digits) and builds:
    runner_prefix + ['-w', issue_id] + gate_argv
  - rerun_latest requires issue_id (digits) and commit_message and builds:
    runner_prefix + [issue_id, commit_message, optional patch_path, '-l']
    + optional ['--override', 'active_target_repo_root=<target_repo>']
    + gate_argv
  - patch/repair requires commit_message and patch_path
  - patch builds: runner_prefix + [issue_id, commit_message, patch_path]
    + optional ['--override', 'active_target_repo_root=<target_repo>']
    + gate_argv
  - finalize_live and finalize_workspace MUST ignore target_repo
  - if issue_id missing, PatchHub auto-allocates it (see Section 11)
- Gate options in the main UI are transient only; they feed gate_argv for the
  current enqueue request and MUST NOT mutate AMP config.
- target_repo is operator-selected execution context only.
  PatchHub MUST read root-level target.txt from zip inputs for display and prefill,
  but MUST NOT rewrite the uploaded zip when target_repo differs.
- target mismatch between zip target.txt and target_repo is informational only.
  PatchHub MAY surface PM validation FAIL for the uploaded zip, but MUST NOT turn
  that mismatch into a new enqueue gate on its own.
- Zip subset semantics for patch/repair:
  - No-subset branch is unchanged: if selected_patch_entries is absent, empty, or
    selects all selectable entries, PatchHub runs the original zip path.
  - Subset selection is supported only for PM-compliant per-file zip layout where
    patches/per_file/<repo path encoded with __>.patch maps deterministically to a repo path.
  - The uploaded/original zip MUST NOT be modified in place.
  - When a proper subset is selected, PatchHub MAY create a derived zip under the
    root patches directory and use that derived zip as the effective runner input.
  - The derived zip preserves root metadata files used by the runner contract
    (COMMIT_MESSAGE.txt, ISSUE_NUMBER.txt, and target.txt when present).
  - selected target files and applied files are different concepts: selected_* comes
    from the UI request; applied_files comes only from runner artifacts after success.

Output (success):
{
  "ok": true,
  "job_id": "<string>",
  "job": <JobRecord JSON>
}

JobRecord JSON schema (models.JobRecord):
{
  "job_id": "<string>",
  "created_utc": "<UTC ISO Z string>",
  "mode": "patch|repair|finalize_live|finalize_workspace|rerun_latest",
  "issue_id": "<string>",
  "commit_message": "<string>",
  "commit_summary": "<string>",
  "patch_basename": "<string|null>",
  "raw_command": "<string>",
  "canonical_command": ["<string>", ...],
  "status": "queued|running|success|fail|canceled|unknown",
  "started_utc": "<UTC ISO Z string|null>",
  "ended_utc": "<UTC ISO Z string|null>",
  "return_code": <int|null>,
  "error": "<string|null>",
  "cancel_requested_utc": "<UTC ISO Z string|null>",
  "cancel_ack_utc": "<UTC ISO Z string|null>",
  "cancel_source": "socket|terminate|hard_stop|null",
  "original_patch_path": "<string|null>",
  "effective_patch_path": "<string|null>",
  "effective_patch_kind": "original|derived_subset|null",
  "selected_patch_entries": ["<string>", ...],
  "selected_repo_paths": ["<string>", ...]
}

Notes:
- created_utc/started_utc/ended_utc use format "%Y-%m-%dT%H:%M:%SZ".
- commit_message stores the full message for detail consumers.
- commit_summary is the single-line deterministic truncation used by JobListItem.

JobListItem JSON schema (used by Section 7.2.8 GET /api/jobs):
{
  "job_id": "<string>",
  "status": "queued|running|success|fail|canceled|unknown",
  "created_utc": "<UTC ISO Z string>",
  "started_utc": "<UTC ISO Z string|null>",
  "ended_utc": "<UTC ISO Z string|null>",
  "mode": "patch|repair|finalize_live|finalize_workspace|rerun_latest",
  "issue_id": "<string>",
  "commit_summary": "<string>",
  "patch_basename": "<string|null>"

}

Contract:
- GET /api/jobs MUST return JobListItem JSON objects (not JobRecord JSON).
- commit_summary MUST be a single line and use deterministic truncation consistent with Section 2.11.
- patch_basename MUST be filename-only (no directory); it MUST be null if absent.
- GET /api/jobs MUST NOT include additional keys in list items; full details are available via GET /api/jobs/<job_id>.

UI contract for zip subset controls:
- The Start run card MAY render an inline zip subset strip directly below patchPath.
- The strip is the pre-modal first-glance surface for zip subset state.
- The subset chooser MAY use a modal dialog.
- The modal MUST use draft/apply semantics:
  - checkbox changes inside the modal update draft state only
  - Apply commits the draft to the effective selected_patch_entries state
  - Cancel, Close, and backdrop close MUST discard the draft
  - the inline strip reflects committed state only
- The modal contract is:
  - title: Select target files (N)
  - subtitle: Contents of <zip basename>
  - selection control: a leading checkbox per row keyed by zip_member
  - columns: Repo path
  - footer: selection count, Cancel, Apply
- The modal card and list surfaces MUST use the PatchHub blue card theme; black-only
  modal surfaces are forbidden.
- Preview remains collapsed-by-default; zip subset selection MUST NOT require Preview
  to be opened.

7.3.3 POST /api/jobs/<job_id>/cancel
Output (success):
{ "ok": true, "job_id": "<string>" }
Error:
- 409 if cannot cancel (unknown job or job already completed)

Cancel semantics (queue.cancel):
- If job.status == "queued":
  - PatchHub sets job.status = "canceled" and sets ended_utc immediately.
- If job.status == "running":
  - Cancel is request-only for the graceful path.
  - PatchHub MUST NOT change job.status or ended_utc at request time.
  - PatchHub MUST set cancel_requested_utc when it accepts the running cancel
    request.
  - PatchHub MUST record cancel_source and cancel_ack_utc as follows:
    - "socket" when an IPC cancel reply ok is observed
    - "terminate" when PatchHub falls back to terminating the live runner
      process group after the graceful IPC path cannot be used or fails
  - Final status MUST be determined by Section 8.5 using return_code together
    with the recorded stop context.

7.3.3A POST /api/jobs/<job_id>/hard_stop
Output (success):
{ "ok": true, "job_id": "<string>" }
Error:
- 409 if cannot hard-stop (unknown job, job not running, or job already completed)

Hard-stop semantics (queue.hard_stop):
- This endpoint is permitted only when job.status == "running".
- PatchHub MUST send signals directly to the live runner process group; it MUST
  NOT use the AMP IPC cancel socket for this endpoint.
- PatchHub MUST set cancel_requested_utc when it accepts the hard-stop request.
- PatchHub MUST set cancel_source = "hard_stop" and set cancel_ack_utc when it
  has accepted the live process-group stop request.
- PatchHub MUST NOT change job.status or ended_utc at request time.
- Final status MUST be determined by Section 8.5 using return_code together
  with the recorded stop context.

7.3.4 POST /api/upload/patch (multipart/form-data)
Input:
- Content-Type must be multipart/form-data
- Must include field "file"

Validation (app_api_upload.py):
- If cfg.upload.ascii_only_names: filename must be ASCII
- size must be <= cfg.upload.max_bytes (else 413)
- extension must be in cfg.upload.allowed_extensions

Storage:
- Stored under cfg.paths.upload_dir, which must be under patches_root.
- Destination filename is os.path.basename(filename).

Output (success):
{
  "ok": true,
  "stored_rel_path": "<string>",
  "bytes": <int>,
  "derived_issue": "<string|null>",             (only if cfg.autofill.derive_enabled)
  "derived_commit_message": "<string|null>",    (only if cfg.autofill.derive_enabled)
  "derived_target_repo": "<string|null>"        (only for zip inputs)
}

7.3.5 POST /api/fs/mkdir
Input JSON:
{ "path": "<rel>" }
Output:
{ "ok": true, "path": "<rel>" }

7.3.6 POST /api/fs/rename
Input JSON:
{ "src": "<rel>", "dst": "<rel>" }
Output:
{ "ok": true, "src": "<rel>", "dst": "<rel>" }

7.3.7 POST /api/fs/delete
Input JSON:
{ "path": "<rel>" }
Output:
{ "ok": true, "path": "<rel>", "deleted": <bool> }

7.3.8 POST /api/fs/unzip
Input JSON:
{ "zip_path": "<rel>", "dest_dir": "<rel>" }
Output:
{ "ok": true, "zip_path": "<rel>", "dest_dir": "<rel>" }

IMPORTANT (current implementation limitation):
- Unzip uses ZipFile.extractall(dest) without per-member validation.
- This specification describes the current behavior. It does not claim
  additional zip-slip hardening beyond jail constraints on the destination.

7.3.9 POST /api/fs/archive
Input JSON:
{ "paths": ["<rel>", ...] }

Validation:
- paths must be a non-empty list
- each path normalized: strip whitespace, remove leading "/"
- duplicates removed; ordering is deterministic (sorted unique)

Behavior:
- Collect files for each rel path:
Timestamps:
- Zip entries preserve source file timestamps as written by zipfile.ZipFile.write().
- PatchHub does not normalize timestamps or other per-entry metadata.
- Therefore, archive bytes are stable only if file contents AND file metadata (mtime) are unchanged.

  - File paths are included as-is with arcname equal to rel
  - Directory paths are walked with os.walk:
    - dirnames and filenames sorted
    - each file included with arcname equal to relative path under patches_root
- Build zip bytes "selection.zip" using zipfile.ZIP_DEFLATED

Output:
- Content-Type: application/zip
- Content-Disposition: attachment; filename="selection.zip"
- Body: zip bytes

7.3.10 POST /api/debug/indexer/force_rescan
Purpose:
- Debug-only trigger for an immediate index rebuild (jobs, runs, ui_snapshot).

Input:
- No body.

Output (success):
{ "ok": true }

Semantics:
- The request handler MUST NOT perform filesystem scanning.
- The handler only signals the background indexer to perform a full rescan.

-------------------------------------------------------------------------------

8. Job Queue, Locking, and Override Injection

8.1 Job IDs
Job IDs are generated by uuid.uuid4().hex (32 lowercase hex characters).

8.2 Persistence

Backend modes (HARD)
- PatchHub web-jobs persistence operates in exactly one authoritative backend
  mode at a time:
  - `db_primary`
  - `file_emergency`
- Dual-write and dual-read authority are forbidden.
- Automatic fallback to files is permitted only as a mode switch from
  `db_primary` to `file_emergency`; it MUST NOT create a second concurrent
  source of truth.

Primary DB artifact
- In `db_primary` mode, PatchHub persists web-jobs state in a PatchHub-local DB
  artifact under `patches/artifacts/`.
- The DB artifact path and related tuning, retention, backup and recovery
  settings are configured by PatchHub TOML under dedicated `web_jobs_*` blocks.

Primary DB contents
- persisted job metadata
- persisted human-readable job log lines
- persisted raw NDJSON event lines captured by the job event pump
- revision and meta state needed for cheap unchanged checks and snapshots

Crash-safety contract (HARD)
- Commit-before-observe is mandatory.
- A job state, log line or event line MUST become visible to API/SSE consumers
  only after the corresponding DB transaction commits successfully.
- PatchHub MUST NOT report a final job status in user-visible APIs before that
  final status is durably persisted in the active backend mode.
- During migration, recovery or restore, source data cleanup MUST NOT occur in
  the same phase as import or restore.

Backup and recovery contract (HARD)
- PatchHub MUST support creation of a physical backup into a separate file.
- A verified backup MUST be restorable without the original runtime process.
- On detection of unclean shutdown, DB open failure, or DB integrity failure in
  `db_primary` mode, PatchHub MUST automatically attempt recovery in this order:
  1) main DB artifact
  2) latest verified backup
  3) emergency export or restore into `file_emergency` mode
- Queue processing and mutating web-jobs operations MUST remain blocked until
  exactly one authoritative backend mode is selected.

Persistence source (HARD)
- Runtime source for structured events is the runner IPC socket NDJSON stream.
- In `db_primary` mode, PatchHub MUST persist every received NDJSON line into
  the DB-backed event store.
- In `file_emergency` mode, PatchHub MAY persist NDJSON lines into the
  emergency file-backed event store.
- This includes runner events, control frames and reply frames received on the
  job socket.
- PatchHub MUST NOT rewrite NDJSON lines.
- After receiving a control frame with `event="connected"`, the job event pump
  MUST send the IPC command `ready`.
- If sending `ready` fails, or if a reply frame for `ready` is missing or
  carries `ok=false`, the pump MUST continue raw capture without aborting the
  job event stream.
- After receiving a control frame with `event="eos"` and `seq=<n>`, the job
  event pump MUST first persist that eos line and then send
  `drain_ack(seq=<n>)`.
- If sending `drain_ack` fails, or if a reply frame for `drain_ack` is missing
  or carries `ok=false`, the pump MUST continue shutdown-tail capture without
  dropping already-received lines.

Legacy file-tree status
- `patches/artifacts/web_jobs/<job_id>/job.json`, `runner.log` and
  `am_patch_issue_<issue_id>.jsonl` / `am_patch_finalize.jsonl` are legacy file
  artifacts.
- In `db_primary` mode they MUST NOT be created during normal runtime.
- In `file_emergency` mode they MAY be used as the active backend.

jobs_root naming
- `jobs_root = patches_root/artifacts/web_jobs`
- In `db_primary` mode this path is a PatchHub-owned virtual namespace for
  compatibility paths such as `artifacts/web_jobs/...`.

8.3 Single-runner rule
Only one runner execution may be active at a time.
Queue worker waits until BOTH are true:
- `executor.is_running()` is false, AND
- `is_lock_held(patches_root/am_patch.lock)` is false

8.4 Web override injection (`queue._inject_web_overrides`)
Before executing a job, PatchHub injects runner overrides into argv
deterministically and idempotently:
- `--override ipc_socket_enabled=true`
- `--override ipc_handshake_enabled=true`
- `--override ipc_handshake_wait_s=<cfg.runner.ipc_handshake_wait_s>`
  - `cfg.runner.ipc_handshake_wait_s` MUST be an integer >= 1
- `--override ipc_socket_path=/tmp/audiomason/patchhub_<job_id>.sock`
- PatchHub-run jobs MUST deterministically disable runner-side JSON file output
  into the legacy web-jobs file tree.

PatchHub MUST NOT inject a value that causes runner JSON output to become the
normal authoritative source for `web_jobs` state.

Insertion point:
- immediately after the first argv element that ends with "am_patch.py"
- if not found, append at end

Duplicate suppression:
- if an override key already exists in argv, it is not added again

8.5 Completion status mapping
After runner exits:
- return_code == 0 => job.status = "success"
- return_code == 130 (AMP cancel exit code) and cancel_source == "socket" and
  cancel_ack_utc is not null => job.status = "canceled"
- cancel_source == "terminate" and cancel_ack_utc is not null =>
  job.status = "canceled"
- cancel_source == "hard_stop" and cancel_ack_utc is not null =>
  job.status = "canceled"
- otherwise => job.status = "fail"

Status-mapping rule:
- PatchHub MUST determine final status from return_code together with the
  recorded stop context.
- Running stop requests are request-only: they MUST NOT change job.status or
  ended_utc before runner exit.
- The stop-context fields used by final mapping are:
  - cancel_source
  - cancel_ack_utc
- cancel_requested_utc is diagnostic metadata and MUST NOT by itself change the
  final status.

Post-exit grace rule:
- Expiry of cfg.runner.post_exit_grace_s MUST NOT change job.status mapping.
- Grace expiry diagnostics are additive and MUST NOT replace the completion
  mapping above.

SSE + persisted state rule:
- When Section 8.5 yields job.status = "canceled", PatchHub MUST persist the
  canceled status before closing the live broker.
- The SSE end trailer MUST carry status "canceled" when the persisted final
  status is canceled.

-------------------------------------------------------------------------------

9. Runner Observation Model (Log + Event Store)

PatchHub provides two complementary streams:
- a human-readable job log store for text viewing
- a structured persisted event store for UI updates

Runtime source:
- IPC socket NDJSON stream
- runner stdout/stderr stream

Persistence:
- In `db_primary` mode:
  - DB-backed human-readable log store
  - DB-backed structured event store (single pump per job)
- In `file_emergency` mode:
  - file-backed `runner.log`
  - file-backed PatchHub event store

SSE (`/api/jobs/<job_id>/events`) streams persisted event lines from the active
backend mode only. PatchHub does not parse or rewrite persisted NDJSON lines.
Debug live view requirements (HARD):
- `debug_human` and `debug_raw` are two representations of the same persisted
  SSE event stream.
- In `debug_raw`, the UI MUST display every persisted event line, including
  non-log IPC reply/control frames.
- In `debug_human`, the UI MUST render the same persisted events as readable
  lines and MUST provide a deterministic non-empty fallback for reply,
  control, and other non-log JSON objects.
- Persisted UI state that still stores the legacy level value `debug` MUST be
  migrated to `debug_raw`.

Bounded-growth contract (HARD)
- Raw log and event history in `db_primary` mode MUST be subject to retention
  and compaction after jobs reach terminal state.
- Long-term retention MUST preserve thin job metadata plus compact derived data
  needed for common UI reads after prune.

9.1 PatchHub TOML config blocks for web-jobs DB (HARD)

PatchHub MUST expose dedicated TOML config blocks for web-jobs DB behavior:
- `[web_jobs_db]`
- `[web_jobs_migration]`
- `[web_jobs_backup]`
- `[web_jobs_recovery]`
- `[web_jobs_fallback]`
- `[web_jobs_retention]`
- `[web_jobs_derived]`

Configurable knobs SHOULD include, where applicable:
- paths and path templates
- polling intervals and batch sizes
- timeouts and busy timeouts
- verification toggles and startup checks
- backup triggers, retention counts and restore priority knobs
- recovery thresholds, export controls and emergency fallback policy knobs
- retention windows, prune limits and compaction thresholds
- virtual-path compatibility toggles

9.1.1 `[web_jobs_backup]` trigger policy contract (HARD)

`[web_jobs_backup].trigger_policy` MUST accept at least:
- `manual`
- `startup_always`
- `startup_after_recovery`
- `interval_hours`

If `trigger_policy = "interval_hours"`, PatchHub TOML MUST also expose:
- `interval_hours` (int >= 1)
- `check_interval_minutes` (int >= 1)

Semantics:
- Backup cadence MUST be computed from `last_verified_backup_utc`, not from
  process start time.
- `last_verified_backup_utc`, `last_verified_backup_path`, and
  `last_verified_backup_status` MUST be persisted outside the DB in the
  PatchHub runtime state file under `patches/artifacts/`.
- The interval scheduler MUST run only in `db_primary` mode.
- The interval scheduler MUST NOT run in `file_emergency` mode.
- After process restart, the scheduler MUST continue from the persisted
  `last_verified_backup_utc` state and MUST NOT create a new backup solely
  because the runtime restarted.

Validation:
- Invalid `trigger_policy`, `interval_hours`, or `check_interval_minutes`
  values MUST raise a deterministic config error.
- Startup-only policies (`manual`, `startup_always`,
  `startup_after_recovery`) MUST keep their startup-only semantics and MUST
  NOT be reinterpreted as periodic scheduler policies.

The following safety invariants MUST remain non-configurable:
- single authoritative backend mode
- no dual-write authority
- commit-before-observe
- recovery attempt order
- no normal runtime write into legacy `web_jobs/<job_id>/*` files in
  `db_primary` mode

-------------------------------------------------------------------------------

10. Runs Indexing Algorithm (Historical View)

Data source:
- patches_root/logs directory

Log selection:
- files whose filename matches cfg.indexing.log_filename_regex
- issue_id extracted from group(1) of that regex

Result parsing:
- read file as UTF-8 with errors="replace"
- strip ANSI escape sequences
- consider last 200 non-empty lines
- find last line that starts with "RESULT:"
- map:
  "RESULT: SUCCESS" => success
  "RESULT: FAIL" => fail
  otherwise => unknown

Sorting:
- by (mtime_utc, issue_id) descending

-------------------------------------------------------------------------------

11. Issue Allocation (when enqueue patch/repair without issue_id)

When POST /api/jobs/enqueue is called for mode patch/repair and issue_id is empty,
PatchHub allocates issue_id by scanning patches_root for existing issue markers.

Algorithm (issue_alloc.py):
- find_existing_issue_ids scans under:
  - patches_root/logs
  - patches_root/artifacts
  - patches_root/successful
  - patches_root/unsuccessful
  using cfg.issue.default_regex and group(1) as digits
- next id = max(existing)+1 else allocation_start
- clamped to [allocation_start, allocation_max]
- if exceeds allocation_max => error

-------------------------------------------------------------------------------

12. Error Handling and Status Codes

JSON error envelope:
{ "ok": false, "error": "<string>" }

Status codes used:
- 200 success
- 400 validation/jail/config errors
- 404 not found
- 409 conflict (cannot cancel)
- 413 upload too large
- 500 internal errors (e.g., read failure, config invariant violation)

No silent failures:
- On validation/jail failure, PatchHub must not perform partial side effects
  before returning error. (Current code follows this for most endpoints.)
- UI MUST surface mutation failures to the user using the JSON error envelope
  error string. Silent no-op UI behavior is forbidden.

-------------------------------------------------------------------------------

13. AMP Settings Editor (Runner Configuration)

PatchHub MAY provide a visual editor for the AM Patch runner configuration.

Single source of truth:
- The authoritative configuration is the runner TOML file referenced by:
  cfg.runner.runner_config_toml
- PatchHub must never create or maintain a second configuration store.

API:
- GET /api/amp/schema
  - returns a deterministic schema describing editable runner policy fields
  - schema is derived from the runner Policy surface (dataclass) and is not
    duplicated in PatchHub
  - returns the runner schema export object (schema_version + policy map)
  - PatchHub UI may use label/help metadata when present (non-normative)
- GET /api/amp/config
  - returns current runner policy values (typed)
- POST /api/amp/config
  - body: { "values": {<key>: <value>, ...}, "dry_run": bool }
  - dry_run=true performs validation only and returns typed values
  - dry_run=false validates and then writes the runner TOML atomically
  - MUST reject writes when the runner lock is held (HTTP 409)
  - MUST validate by rebuilding runner Policy from the updated TOML (roundtrip)

UI:
- The AMP Settings editor is located between:
  - A) Start run
  - C) Files
- It is hidden by default (collapsed).
- Field rendering rules:
  - bool -> toggle switch
  - str -> text input
  - int -> numeric input
  - enum -> dropdown
  - list[str] -> tag/chips editor
    - From runtime version 1.12.12 onward, this editor MUST preserve list
      fidelity end-to-end.
    - Reload MUST preserve element order, duplicates, and empty-string items
      exactly as returned by GET /api/amp/config.
    - Validate and Save without user edits MUST roundtrip each list[str]
      field without dropping empty-string items, removing duplicates, or
      reordering elements.
    - Chip deletion MUST be positional; deleting one duplicate MUST NOT remove
      other equal-value items.
    - The UI MUST provide an explicit action to append an empty-string item.
    - Empty-string items MAY render as placeholder chips, but their payload
      value MUST remain "".
- Actions:
  - Reload: fetch schema + config
  - Validate: POST with dry_run=true
  - Save: POST with dry_run=false
  - Revert: restore last loaded values

-------------------------------------------------------------------------------

14. Non-Goals

PatchHub is NOT:
- A patch authoring system
- A CI/CD orchestrator
- A replacement for the AM Patch runner
- A general-purpose repository file manager

-------------------------------------------------------------------------------

END OF SPECIFICATION
