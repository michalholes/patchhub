from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "patchhub" / "static" / "patchhub_shell.js"
HTML_PATH = REPO_ROOT / "scripts" / "patchhub" / "templates" / "index.html"


def _module_src() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


def _run_node(script: str) -> dict[str, object]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    proc = subprocess.run(
        [node, "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def _prelude() -> str:
    module = json.dumps(_module_src())
    return f"""
const moduleSrc = {module};
class Node {{
  constructor(tag) {{
    this.tagName = String(tag || 'div').toLowerCase();
    this.children = [];
    this.parentElement = null;
    this.attributes = Object.create(null);
    this.className = '';
    this.textContent = '';
    this.id = '';
  }}
  appendChild(child) {{
    if (!child) return child;
    child.parentElement = this;
    this.children.push(child);
    return child;
  }}
  removeChild(child) {{
    const idx = this.children.indexOf(child);
    if (idx >= 0) this.children.splice(idx, 1);
    if (child) child.parentElement = null;
    return child;
  }}
  remove() {{
    if (this.parentElement) this.parentElement.removeChild(this);
  }}
  setAttribute(name, value) {{
    const key = String(name || '');
    const text = String(value || '');
    this.attributes[key] = text;
    if (key === 'class') this.className = text;
    if (key === 'id') this.id = text;
  }}
  getAttribute(name) {{
    const key = String(name || '');
    if (key === 'class') return this.className || null;
    if (key === 'id') return this.id || null;
    return Object.prototype.hasOwnProperty.call(this.attributes, key)
      ? this.attributes[key]
      : null;
  }}
}}
function esc(text) {{
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}}
function render(node) {{
  if (!node) return '';
  const attrs = [];
  if (node.id) attrs.push(`id="${{esc(node.id)}}"`);
  if (node.className) attrs.push(`class="${{esc(node.className)}}"`);
  Object.keys(node.attributes).forEach((key) => {{
    if (key === 'id' || key === 'class') return;
    attrs.push(`${{key}}="${{esc(node.attributes[key])}}"`);
  }});
  const open = `<${{node.tagName}}${{attrs.length ? ' ' + attrs.join(' ') : ''}}>`;
  const body = node.children.length
    ? node.children.map((child) => render(child)).join('')
    : esc(node.textContent || '');
  return `${{open}}${{body}}</${{node.tagName}}>`;
}}
function makeJobRow(job, selectedJobId) {{
  const host = new Node('div');
  host.className = 'item job-item' +
    (selectedJobId && String(selectedJobId) === String(job.job_id || '')
      ? ' selected'
      : '');
  const name = new Node('div');
  name.className = 'name job-name';
  name.setAttribute('data-jobid', String(job.job_id || ''));
  const lines = new Node('div');
  lines.className = 'job-lines';
  const top = new Node('div');
  top.className = 'job-top';
  const issue = new Node('span');
  issue.className = 'job-issue';
  issue.textContent = String(job.issue_id || '');
  const status = new Node('span');
  status.className = 'job-status';
  status.textContent = String(job.status || '');
  top.appendChild(issue);
  top.appendChild(status);
  lines.appendChild(top);
  if (job.show_rerun) {{
    const actions = new Node('div');
    actions.className = 'actions job-actions';
    const btn = new Node('button');
    btn.className = 'btn btn-small jobUseForRerun';
    btn.setAttribute('type', 'button');
    btn.setAttribute('data-rerun-jobid', String(job.job_id || ''));
    btn.textContent = 'Use for -l';
    actions.appendChild(btn);
    lines.appendChild(actions);
  }}
  name.appendChild(lines);
  host.appendChild(name);
  return host;
}}
const elements = new Map();
const jobsList = new Node('div');
jobsList.id = 'jobsList';
elements.set('jobsList', jobsList);
const document = {{
  getElementById(id) {{
    return elements.get(String(id || '')) || null;
  }},
  createElement(tag) {{
    return new Node(tag);
  }},
}};
const registry = new Map();
const runtime = {{
  register(name, exportsObj) {{
    registry.set(String(name || ''), exportsObj || {{}});
  }},
}};
global.document = document;
global.window = {{ PH_RT: runtime, PH: runtime }};
global.apiGet = (path) => Promise.resolve({{ ok: true, job: null, path }});
global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;
eval(moduleSrc);
const jobsExports = {{
  renderJobsFromResponse(resp) {{
    jobsList.children = [];
    (resp && Array.isArray(resp.jobs) ? resp.jobs : []).forEach((job) => {{
      jobsList.appendChild(makeJobRow(job, global.selectedJobId || ''));
    }});
  }},
  triggerRevertJob(jobId) {{
    return '/api/jobs/' + encodeURIComponent(String(jobId || '')) + '/revert';
  }},
}};
runtime.register('app_part_jobs', jobsExports);
const appPartJobs = registry.get('app_part_jobs');
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
"""


def test_jobs_revert_module_exists() -> None:
    src = _module_src()
    assert "function syncJobs(" in src
    assert 'apiGetFn("/api/jobs/" + encodeURIComponent(jobId))' in src


def test_index_loads_revert_module_before_bootstrap() -> None:
    src = HTML_PATH.read_text(encoding="utf-8")
    revert_idx = src.index("/static/patchhub_shell.js")
    boot_idx = src.index("/static/patchhub_bootstrap.js")
    assert revert_idx < boot_idx


def test_non_selected_job_gets_revert_after_detail_resolution() -> None:
    script = (
        _prelude()
        + """
global.selectedJobId = 'job-selected';
global.apiGet = (path) => Promise.resolve(
  String(path || '') === '/api/jobs/job-eligible'
    ? {
        ok: true,
        job: {
          job_id: 'job-eligible',
          effective_runner_target_repo: 'patchhub',
          run_start_sha: 'aaa111',
          run_end_sha: 'bbb222',
        },
        path,
      }
    : { ok: true, job: { job_id: 'job-selected' }, path }
);
appPartJobs.renderJobsFromResponse({ jobs: [
  { job_id: 'job-selected', status: 'success', issue_id: '380' },
  {
    job_id: 'job-eligible',
    status: 'success',
    ended_utc: '2026-03-25T09:15:00Z',
    issue_id: '381',
  },
] });
flush().then(() => flush()).then(() => {
  console.log(JSON.stringify({ html: render(jobsList) }));
});
"""
    )
    result = _run_node(script)
    html = str(result["html"])
    assert 'data-revert-jobid="job-eligible"' in html
    assert 'data-revert-jobid="job-selected"' not in html


def test_revalidates_when_summary_state_changes() -> None:
    script = (
        _prelude()
        + """
let fetchCount = 0;
global.apiGet = (path) => {
  fetchCount += 1;
  if (fetchCount === 1) {
    return Promise.resolve({ ok: true, job: { job_id: 'job-eligible' }, path });
  }
  return Promise.resolve({
    ok: true,
    job: {
      job_id: 'job-eligible',
      effective_runner_target_repo: 'patchhub',
      run_start_sha: 'aaa111',
      run_end_sha: 'bbb222',
    },
    path,
  });
};
appPartJobs.renderJobsFromResponse({ jobs: [
  { job_id: 'job-eligible', status: 'running', issue_id: '383' },
] });
flush().then(() => flush()).then(() => {
  const firstHtml = render(jobsList);
  appPartJobs.renderJobsFromResponse({ jobs: [
    {
      job_id: 'job-eligible',
      status: 'success',
      ended_utc: '2026-03-25T09:15:00Z',
      issue_id: '383',
    },
  ] });
  return flush().then(() => flush()).then(() => {
    console.log(JSON.stringify({
      fetchCount,
      firstHtml,
      secondHtml: render(jobsList),
    }));
  });
});
"""
    )
    result = _run_node(script)
    assert result["fetchCount"] == 2
    assert 'data-revert-jobid="job-eligible"' not in str(result["firstHtml"])
    assert 'data-revert-jobid="job-eligible"' in str(result["secondHtml"])


def test_missing_required_fields_keeps_revert_hidden() -> None:
    script = (
        _prelude()
        + """
global.apiGet = (path) => Promise.resolve({
  ok: true,
  job: {
    job_id: 'job-no-revert',
    effective_runner_target_repo: 'patchhub',
    run_start_sha: 'aaa111',
  },
  path,
});
appPartJobs.renderJobsFromResponse({ jobs: [
  {
    job_id: 'job-no-revert',
    status: 'success',
    ended_utc: '2026-03-25T09:16:00Z',
    issue_id: '384',
  },
] });
flush().then(() => flush()).then(() => {
  console.log(JSON.stringify({ html: render(jobsList) }));
});
"""
    )
    result = _run_node(script)
    assert 'data-revert-jobid="job-no-revert"' not in str(result["html"])
