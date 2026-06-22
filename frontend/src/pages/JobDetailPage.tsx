import type { ProcessingStageStatus, StudyDocument } from "../App";

interface JobDetailPageProps {
  document: StudyDocument;
}

const stageLabels: Record<ProcessingStageStatus, string> = {
  done: "Done",
  active: "Active",
  pending: "Pending",
  blocked: "Blocked"
};

function JobDetailPage({ document }: JobDetailPageProps) {
  return (
    <section className="job-panel" aria-labelledby="job-title">
      <div className="panel-header">
        <div>
          <h2 id="job-title">Job Status</h2>
          <p>{document.summary}</p>
        </div>
        <span className={`status-badge status-${document.status}`}>{document.status}</span>
      </div>

      <div className="job-progress">
        <div className="progress-copy">
          <span>{document.activePhase}</span>
          <strong>{document.progress}%</strong>
        </div>
        <div className="progress-track" aria-label={`${document.progress}% complete`}>
          <span style={{ width: `${document.progress}%` }} />
        </div>
      </div>

      <ol className="stage-list">
        {document.stages.map((stage) => (
          <li className={`stage-item stage-${stage.status}`} key={stage.id}>
            <span className="stage-marker" aria-hidden="true" />
            <span className="stage-copy">
              <span className="stage-title">{stage.label}</span>
              <span className="stage-detail">{stage.detail}</span>
            </span>
            <span className="stage-status">{stageLabels[stage.status]}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default JobDetailPage;
