import type { ApiDocument, ApiJob } from "../api";

interface JobDetailPageProps {
  document?: ApiDocument;
  job?: ApiJob;
  onRefreshJob: (jobId: string) => Promise<void>;
  onRetry: (jobId: string) => Promise<void>;
}

function progressFor(document?: ApiDocument, job?: ApiJob) {
  if (typeof job?.progress === "number") return job.progress;
  if (document?.status === "ready" || document?.status === "completed") return 100;
  if (document?.status === "failed") return 100;
  if (document?.status === "processing" || document?.status === "running") return 50;
  return 0;
}

function phaseFor(document?: ApiDocument, job?: ApiJob) {
  if (!document) return "Select or upload a document to begin.";
  if (job?.error_message) return job.error_message;
  if (job?.status === "queued") return "Waiting for processing worker.";
  if (job?.status === "running") return "Processing document into study artifacts.";
  if (job?.status === "completed" || document.status === "ready") return "Generated study content is ready.";
  if (job?.status === "failed" || document.status === "failed") return "Processing failed. Retry when the source is ready.";
  return `Document status: ${document.status}`;
}

function displayStatus(document?: ApiDocument, job?: ApiJob) {
  return job?.status ?? document?.status ?? "idle";
}

function JobDetailPage({ document, job, onRefreshJob, onRetry }: JobDetailPageProps) {
  const progress = progressFor(document, job);
  const status = displayStatus(document, job);
  const jobId = job?.job_id ?? job?.id;
  const canRetry = jobId && (job?.status === "failed" || document?.status === "failed");

  return (
    <section className="job-panel" aria-labelledby="job-title">
      <div className="panel-header">
        <div>
          <h2 id="job-title">Job Status</h2>
          <p>{phaseFor(document, job)}</p>
        </div>
        <span className={`status-badge status-${status}`}>{status}</span>
      </div>

      {document ? (
        <>
          <div className="job-progress">
            <div className="progress-copy">
              <span>{document.title}</span>
              <strong>{progress}%</strong>
            </div>
            <div className="progress-track" aria-label={`${progress}% complete`}>
              <span style={{ width: `${progress}%` }} />
            </div>
          </div>

          <div className="action-row">
            {jobId ? (
              <button type="button" className="secondary-action" onClick={() => onRefreshJob(jobId)}>
                Refresh job
              </button>
            ) : null}
            {canRetry ? (
              <button type="button" className="primary-action" onClick={() => onRetry(jobId)}>
                Retry
              </button>
            ) : null}
          </div>

          <dl className="version-list">
            <div>
              <dt>Document id</dt>
              <dd>{document.id}</dd>
            </div>
            <div>
              <dt>Job id</dt>
              <dd>{jobId ?? "No job loaded"}</dd>
            </div>
            <div>
              <dt>Owner</dt>
              <dd>{document.owner_id}</dd>
            </div>
          </dl>
        </>
      ) : (
        <div className="empty-state">
          <strong>No document selected</strong>
          <span>Upload or select a document to see processing status.</span>
        </div>
      )}
    </section>
  );
}

export default JobDetailPage;
