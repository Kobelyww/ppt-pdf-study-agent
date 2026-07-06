import type { ReviewTaskSummary } from "../api";

interface ReviewTasksPageProps {
  tasks: ReviewTaskSummary[];
}

function safeMetadataItems(task: ReviewTaskSummary) {
  const metadata = task.metadata ?? task.task_metadata;
  if (!metadata) return [];
  const items: Array<[string, string]> = [];
  const pushString = (key: string, label: string) => {
    const value = metadata[key];
    if (typeof value === "string" && value.trim()) items.push([label, value]);
  };
  const pushNumber = (key: string, label: string) => {
    const value = metadata[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      items.push([label, String(value)]);
    }
  };
  pushString("workflow_id", "Workflow");
  pushString("selected_mode", "Mode");
  const reviewReasons = metadata.review_reasons;
  if (Array.isArray(reviewReasons)) {
    const safeReasons = reviewReasons.filter(
      (reason): reason is string => typeof reason === "string" && reason.trim().length > 0,
    );
    if (safeReasons.length > 0) items.push(["Reasons", safeReasons.join(", ")]);
  }
  pushNumber("source_count", "Sources");
  pushNumber("chunk_count", "Chunks");
  pushNumber("citation_count", "Citations");
  pushNumber("issue_count", "Issues");
  return items;
}

function ReviewTaskMetadata({ task }: { task: ReviewTaskSummary }) {
  const items = safeMetadataItems(task);
  if (items.length === 0) return null;
  return (
    <div className="review-task-metadata">
      {items.map(([label, value]) => (
        <span key={`${task.id}-${label}`}>
          <strong>{label}</strong> {value}
        </span>
      ))}
    </div>
  );
}

function ReviewTasksPage({ tasks }: ReviewTasksPageProps) {
  return (
    <section className="review-panel" aria-labelledby="review-title">
      <div className="panel-header compact">
        <div>
          <h2 id="review-title">Review tasks</h2>
          <p>Low-rated generated content that needs product review.</p>
        </div>
      </div>
      {tasks.length === 0 ? (
        <p className="muted">No open review tasks.</p>
      ) : (
        <ul className="review-list">
          {tasks.map((task) => (
            <li key={task.id}>
              <div>
                <strong>{task.target_type}</strong>
                <span>{task.target_id}</span>
              </div>
              <div>
                <span>{task.reason}</span>
                <ReviewTaskMetadata task={task} />
              </div>
              <span className={`status-badge status-${task.status}`}>{task.status}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default ReviewTasksPage;
