/// <reference path="../../../types/am2-globals.d.ts" />
/**
 * @typedef {PatchhubJob & {
 *   rollback_scope_manifest_rel_path?: string,
 *   rollback_scope_manifest_hash?: string,
 *   rollback_authority_kind?: string,
 *   rollback_authority_source_ref?: string,
 *   rollback_available?: boolean,
 * }} RollbackAwareJob
 * @typedef {{
 *   call?: (name: string, ...args: unknown[]) => unknown,
 *   register?: (name: string, exportsObj: Record<string, unknown>) => void,
 * }} JobsRevertRuntime
 * @typedef {Window & typeof globalThis & { PH?: JobsRevertRuntime | null }} JobsRevertWindow
 */
var jobsRevertWindow = /** @type {JobsRevertWindow} */ (window);
var jobsRevertPh = /** @type {JobsRevertRuntime | null} */ (
	jobsRevertWindow.PH || null
);
var jobsRevertDetailCache =
	/** @type {Record<string, RollbackAwareJob | null>} */ (Object.create(null));
var jobsRevertDetailSig = /** @type {Record<string, string>} */ (
	Object.create(null)
);
var jobsRevertInflight =
	/** @type {Record<string, Promise<RollbackAwareJob | null>>} */ (
		Object.create(null)
	);
var jobsRevertInflightSig = /** @type {Record<string, string>} */ (
	Object.create(null)
);
var jobsRevertSeq = /** @type {Record<string, number>} */ (Object.create(null));
var jobsRevertRender = /** @type {(() => void) | null} */ (null);
var jobsRevertRenderQueued = false;

/** @param {string} name @param {...unknown} args @returns {unknown} */
function jobsRevertPhCall(name, ...args) {
	if (!jobsRevertPh || typeof jobsRevertPh.call !== "function")
		return undefined;
	return jobsRevertPh.call(name, ...args);
}

/** @param {PatchhubJob | null | undefined} job @returns {string} */
function jobsRevertSummarySig(job) {
	return [
		String((job && job.status) || "").trim(),
		String((job && job.ended_utc) || "").trim(),
	].join("|");
}

/** @param {RollbackAwareJob | null | undefined} detail @returns {boolean} */
function rollbackRequiredAuthorityPresent(detail) {
	return !!(
		String((detail && detail.effective_runner_target_repo) || "").trim() &&
		String((detail && detail.run_start_sha) || "").trim() &&
		String((detail && detail.run_end_sha) || "").trim() &&
		detail &&
		detail.rollback_available === true
	);
}

/** @param {string} jobId @returns {void} */
function jobsRevertDrop(jobId) {
	delete jobsRevertDetailCache[jobId];
	delete jobsRevertDetailSig[jobId];
	delete jobsRevertInflight[jobId];
	delete jobsRevertInflightSig[jobId];
}

/** @param {PatchhubJob[] | null | undefined} jobs @returns {void} */
function jobsRevertPrune(jobs) {
	var keep = /** @type {Record<string, boolean>} */ (Object.create(null));
	(jobs || []).forEach((job) => {
		var jobId = String((job && job.job_id) || "").trim();
		if (jobId) keep[jobId] = true;
	});
	Object.keys(jobsRevertDetailCache).forEach((jobId) => {
		if (!keep[jobId]) jobsRevertDrop(jobId);
	});
}

/** @returns {void} */
function jobsRevertScheduleRender() {
	if (jobsRevertRenderQueued) return;
	jobsRevertRenderQueued = true;
	Promise.resolve().then(() => {
		jobsRevertRenderQueued = false;
		if (typeof jobsRevertRender === "function") jobsRevertRender();
		jobsRevertPhCall("syncRollbackUiFromInputs");
	});
}

/** @param {RollbackAwareJob | null | undefined} job @returns {void} */
function rememberRollbackSourceJobDetail(job) {
	var jobId = String((job && job.job_id) || "").trim();
	if (!jobId) return;
	jobsRevertDetailCache[jobId] = job || null;
	jobsRevertDetailSig[jobId] = jobsRevertSummarySig(job);
	jobsRevertScheduleRender();
}

/** @param {PatchhubJob | null | undefined} job @returns {Promise<RollbackAwareJob | null>} */
function jobsRevertLoadDetail(job) {
	var jobId = String((job && job.job_id) || "").trim();
	var sig = jobsRevertSummarySig(job);
	var seq = 0;
	if (!jobId) return Promise.resolve(null);
	if (jobsRevertDetailSig[jobId] !== sig) jobsRevertDrop(jobId);
	if (Object.hasOwn(jobsRevertDetailCache, jobId)) {
		jobsRevertDetailSig[jobId] = sig;
		return Promise.resolve(jobsRevertDetailCache[jobId]);
	}
	if (
		Object.hasOwn(jobsRevertInflight, jobId) &&
		jobsRevertInflightSig[jobId] === sig
	) {
		return jobsRevertInflight[jobId];
	}
	seq = Number(jobsRevertSeq[jobId] || 0) + 1;
	jobsRevertSeq[jobId] = seq;
	jobsRevertInflightSig[jobId] = sig;
	jobsRevertInflight[jobId] = /** @type {Promise<JobDetailResponse>} */ (
		apiGet("/api/jobs/" + encodeURIComponent(jobId))
	)
		.then((resp) => {
			if (Number(jobsRevertSeq[jobId] || 0) !== seq) return null;
			jobsRevertDetailSig[jobId] = sig;
			jobsRevertDetailCache[jobId] =
				resp && resp.ok !== false && resp.job ? resp.job : null;
			jobsRevertScheduleRender();
			return jobsRevertDetailCache[jobId];
		})
		.catch(
			/** @returns {RollbackAwareJob | null} */ () => {
				if (Number(jobsRevertSeq[jobId] || 0) !== seq) return null;
				jobsRevertDetailSig[jobId] = sig;
				jobsRevertDetailCache[jobId] = null;
				jobsRevertScheduleRender();
				return null;
			},
		)
		.finally(() => {
			if (Number(jobsRevertSeq[jobId] || 0) !== seq) return;
			delete jobsRevertInflight[jobId];
			delete jobsRevertInflightSig[jobId];
		});
	return jobsRevertInflight[jobId];
}

/**
 * @param {PatchhubJob[] | null | undefined} jobs
 * @param {(() => void) | null | undefined} renderFn
 * @returns {boolean}
 */
function syncJobsRevertState(jobs, renderFn) {
	jobsRevertRender =
		typeof renderFn === "function" ? renderFn : jobsRevertRender;
	jobsRevertPrune(jobs);
	(jobs || []).forEach((job) => {
		jobsRevertLoadDetail(job);
	});
	jobsRevertScheduleRender();
	return true;
}

/** @param {PatchhubJob | null | undefined} job @returns {boolean} */
function shouldShowJobsRevert(job) {
	var jobId = String((job && job.job_id) || "").trim();
	var sig = jobsRevertSummarySig(job);
	if (!jobId) return false;
	if (jobsRevertDetailSig[jobId] !== sig) return false;
	return rollbackRequiredAuthorityPresent(jobsRevertDetailCache[jobId]);
}

if (jobsRevertPh && typeof jobsRevertPh.register === "function") {
	jobsRevertPh.register("app_part_jobs_revert", {
		syncJobsRevertState,
		shouldShowJobsRevert,
		rememberRollbackSourceJobDetail,
	});
}
