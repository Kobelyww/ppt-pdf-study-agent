import type { ContentVersion, ExportJob } from "../api";

interface OutlinePageProps {
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

function classifyLine(line: string) {
  if (line.startsWith("# ")) {
    return "outline-heading outline-heading-top";
  }

  if (line.startsWith("## ")) {
    return "outline-heading";
  }

  return "outline-bullet";
}

function cleanLine(line: string) {
  return line.replace(/^#{1,2}\s*/, "").replace(/^-\s*/, "");
}

function latestExportFor(exportJobs: ExportJob[], version?: ContentVersion) {
  if (!version) return undefined;
  return exportJobs.find((job) => job.version_id === version.id);
}

function OutlinePage({ exportJobs, version, onCreateExport, onSubmitFeedback }: OutlinePageProps) {
  const exportJob = latestExportFor(exportJobs, version);
  const lines = version?.content.split("\n").filter((line) => line.trim().length > 0) ?? [];

  return (
    <section className="outline-panel" aria-labelledby="outline-title">
      <div className="panel-header compact">
        <div>
          <h2 id="outline-title">Outline</h2>
          <p>Latest generated outline version.</p>
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
              onClick={() => onSubmitFeedback("outline", version.id, 1, "needs_revision", "Outline needs review.")}
            >
              Flag outline
            </button>
          </div>

          {exportJob ? (
            <p className="muted">Export {exportJob.id}: {exportJob.status}</p>
          ) : null}

          <div className="outline-content">
            {lines.map((line, index) => (
              <p className={classifyLine(line)} key={`${version.id}-${index}`}>
                {cleanLine(line)}
              </p>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state">
          <strong>No outline available</strong>
          <span>Run document processing before exporting or reviewing an outline.</span>
        </div>
      )}
    </section>
  );
}

export default OutlinePage;
