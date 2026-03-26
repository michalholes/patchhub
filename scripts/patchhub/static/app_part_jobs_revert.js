var jobsRevertWindow = /** @type {JobsWindow} */ (window);
var jobsRevertPh = /** @type {JobsRuntime | null} */ (
	jobsRevertWindow.PH || null
);
var jobsRevertDetailCache = /** @type {Record<string, PatchhubJob | null>} */ (
	Object.create(null)
);
var jobsRevertDetailSig = /** @type {Record<string, string>} */ (
	Object.create(null)
);
var jobsRevertInflight =
	/** @type {Record<string, Promise<PatchhubJob | null>>} */ (
		Object.create(null)
	);
var jobsRevertInflightSig = /** @type {Record<string, string>} */ (
	Object.create(null)
);
var jobsRevertSeq = /** @type {Record<string, number>} */ (Object.create(null));
var jobsRevertRender = /** @type {(() => void) | null} */ (null);
var jobsRevertRenderQueued = false;

function jobsRevertOwn(
	/** @type {Record<string, unknown>} */ obj,
	/** @type {string} */ key,
) {
	return Object.prototype.hasOwnProperty.call(obj, key);
}

function jobsRevertSummarySig(
	/** @type {PatchhubJob | null | undefined} */ job,
) {
	return [
		String((job && job.status) || "").trim(),
		String((job && job.ended_utc) || "").trim(),
	].join("|");
}

function jobsRevertHasFields(
	/** @type {PatchhubJob | null | undefined} */ detail,
) {
	return !!(
		String((detail && detail.effective_runner_target_repo) || "").trim() &&
		String((detail && detail.run_start_sha) || "").trim() &&
		String((detail && detail.run_end_sha) || "").trim()
	);
}

function jobsRevertDrop(/** @type {string} */ jobId) {
	delete jobsRevertDetailCache[jobId];
	delete jobsRevertDetailSig[jobId];
	delete jobsRevertInflight[jobId];
	delete jobsRevertInflightSig[jobId];
}

function jobsRevertPrune(/** @type {PatchhubJob[] | null | undefined} */ jobs) {
	var keep = Object.create(null);
	(jobs || []).forEach((job) => {
		var jobId = String((job && job.job_id) || "").trim();
		if (jobId) keep[jobId] = true;
	});
	Object.keys(jobsRevertDetailCache).forEach((jobId) => {
		if (!keep[jobId]) jobsRevertDrop(jobId);
	});
}

function jobsRevertScheduleRender() {
	if (jobsRevertRenderQueued) return;
	jobsRevertRenderQueued = true;
	Promise.resolve().then(() => {
		jobsRevertRenderQueued = false;
		if (typeof jobsRevertRender === "function") jobsRevertRender();
	});
}

function jobsRevertLoadDetail(
	/** @type {PatchhubJob | null | undefined} */ job,
) {
	var jobId = String((job && job.job_id) || "").trim();
	var sig = jobsRevertSummarySig(job);
	var seq = 0;
	if (!jobId) return Promise.resolve(null);
	if (jobsRevertDetailSig[jobId] !== sig) jobsRevertDrop(jobId);
	if (jobsRevertOwn(jobsRevertDetailCache, jobId)) {
		jobsRevertDetailSig[jobId] = sig;
		return Promise.resolve(jobsRevertDetailCache[jobId]);
	}
	if (jobsRevertInflight[jobId] && jobsRevertInflightSig[jobId] === sig) {
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
			/** @returns {PatchhubJob | null} */ () => {
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

function syncJobsRevertState(
	/** @type {PatchhubJob[] | null | undefined} */ jobs,
	/** @type {(() => void) | null | undefined} */ renderFn,
) {
	jobsRevertRender =
		typeof renderFn === "function" ? renderFn : jobsRevertRender;
	jobsRevertPrune(jobs);
	(jobs || []).forEach((job) => {
		jobsRevertLoadDetail(job);
	});
	return true;
}

function shouldShowJobsRevert(
	/** @type {PatchhubJob | null | undefined} */ job,
) {
	var jobId = String((job && job.job_id) || "").trim();
	var sig = jobsRevertSummarySig(job);
	if (!jobId) return false;
	if (jobsRevertDetailSig[jobId] !== sig) return false;
	return jobsRevertHasFields(jobsRevertDetailCache[jobId]);
}

if (jobsRevertPh && typeof jobsRevertPh.register === "function") {
	jobsRevertPh.register("app_part_jobs_revert", {
		syncJobsRevertState,
		shouldShowJobsRevert,
	});
}
