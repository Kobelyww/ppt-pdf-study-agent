import type { StudyAgentResult } from "../api";

interface EvidenceViewerProps {
  result: StudyAgentResult;
}

function formatPercent(value: number) {
  if (!Number.isFinite(value)) return "Unknown";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function stringValue(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function numberValue(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function positionLabel(metadata: Record<string, unknown>) {
  const pageNumber = numberValue(metadata, "page_number");
  const pageIndex = numberValue(metadata, "page_index");
  const slideNumber = numberValue(metadata, "slide_number");
  const slideIndex = numberValue(metadata, "slide_index");
  const chunkIndex = numberValue(metadata, "chunk_index");

  if (pageNumber !== null) return `page ${pageNumber}`;
  if (pageIndex !== null) return `page ${pageIndex + 1}`;
  if (slideNumber !== null) return `slide ${slideNumber}`;
  if (slideIndex !== null) return `slide ${slideIndex + 1}`;
  if (chunkIndex !== null) return `chunk ${chunkIndex + 1}`;
  return "";
}

function metadataLabel(metadata: Record<string, unknown>, index: number) {
  const title = stringValue(metadata, "document_title");
  const section = stringValue(metadata, "section_title") || stringValue(metadata, "heading");
  const position = positionLabel(metadata);
  return [title, section, position].filter(Boolean).join(" · ") || `Evidence ${index + 1}`;
}

function EvidenceViewer({ result }: EvidenceViewerProps) {
  return (
    <div className="evidence-viewer" aria-label="Study Agent evidence">
      <dl className="agent-trace">
        <div>
          <dt>Mode</dt>
          <dd>{result.plan.mode}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{formatPercent(result.verification.confidence)}</dd>
        </div>
        <div>
          <dt>Review</dt>
          <dd>{result.verification.needs_review ? "Needs review" : "Passed"}</dd>
        </div>
        <div>
          <dt>Sources</dt>
          <dd>{result.evidence.sources.length}</dd>
        </div>
      </dl>

      <div className="agent-reason">
        <strong>{result.plan.reason}</strong>
        {result.evidence.fallback_reason ? (
          <span>Fallback: {result.evidence.fallback_reason}</span>
        ) : null}
      </div>

      {result.verification.issues.length > 0 ? (
        <ul className="agent-issues" aria-label="Verification issues">
          {result.verification.issues.map((issue, index) => (
            <li key={`issue-${index}-${issue}`}>{issue}</li>
          ))}
        </ul>
      ) : null}

      <div className="citation-list" aria-label="Citations" role="list">
        {result.draft.citations.length > 0 ? (
          result.draft.citations.map((citation, index) => (
            <span className="citation-pill" key={`citation-${index}-${citation}`} role="listitem">
              {citation}
            </span>
          ))
        ) : (
          <span className="muted" role="listitem">
            No citations returned.
          </span>
        )}
      </div>

      <div className="evidence-list" aria-label="Evidence chunks" role="list">
        {result.evidence.chunks.length > 0 ? (
          result.evidence.chunks.map((chunk, index) => (
            <article
              className="evidence-item"
              key={`chunk-${index}-${chunk.source}-${metadataLabel(chunk.metadata, index)}`}
              role="listitem"
            >
              <div className="evidence-heading">
                <strong>{metadataLabel(chunk.metadata, index)}</strong>
                <span>{formatPercent(chunk.score)}</span>
              </div>
              <p>{chunk.content}</p>
            </article>
          ))
        ) : (
          <div className="empty-state" role="listitem">
            <strong>No evidence chunks</strong>
            <span>The agent could not recover supporting chunks for this query.</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default EvidenceViewer;
