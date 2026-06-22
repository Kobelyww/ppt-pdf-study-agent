import type { ReviewTaskSummary } from "../api";

interface ReviewTasksPageProps {
  tasks: ReviewTaskSummary[];
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
              <strong>{task.target_type}</strong>
              <span>{task.reason}</span>
              <span className={`status-badge status-${task.status}`}>{task.status}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default ReviewTasksPage;
