import type { ContentVersion, ExportJob } from "../api";

interface QuestionsPageProps {
  exportJobs: ExportJob[];
  version?: ContentVersion;
  onCreateExport: (version: ContentVersion, format: string) => Promise<void>;
  onSubmitFeedback: (
    targetType: string,
    targetId: string,
    rating: number,
    reason: string,
    comment: string,
  ) => Promise<void>;
}

function latestExportFor(exportJobs: ExportJob[], version?: ContentVersion) {
  if (!version) return undefined;
  return exportJobs.find((job) => job.version_id === version.id);
}

function questionBlocks(content: string) {
  return content
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);
}

function QuestionsPage({ exportJobs, version, onCreateExport, onSubmitFeedback }: QuestionsPageProps) {
  const exportJob = latestExportFor(exportJobs, version);
  const blocks = version ? questionBlocks(version.content) : [];

  return (
    <section className="questions-panel" aria-labelledby="questions-title">
      <div className="panel-header compact">
        <div>
          <h2 id="questions-title">Questions</h2>
          <p>Latest generated question set with answer content.</p>
        </div>
      </div>

      {version ? (
        <>
          <div className="action-row">
            <button type="button" className="secondary-action" onClick={() => onCreateExport(version, "markdown")}>
              Export Markdown
            </button>
            <button
              type="button"
              className="secondary-action"
              onClick={() => onSubmitFeedback("question_set", version.id, 1, "needs_revision", "Question set needs review.")}
            >
              Flag questions
            </button>
          </div>

          {exportJob ? (
            <p className="muted">Export {exportJob.id}: {exportJob.status}</p>
          ) : null}

          <div className="question-list">
            {blocks.map((block, index) => (
              <article className="question-item" key={`${version.id}-${index}`}>
                <pre className="content-block">{block}</pre>
              </article>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state">
          <strong>No questions available</strong>
          <span>Question generation starts after processing creates a question-set version.</span>
        </div>
      )}
    </section>
  );
}

export default QuestionsPage;
