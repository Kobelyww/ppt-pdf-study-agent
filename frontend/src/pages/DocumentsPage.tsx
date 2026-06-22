import type { StudyDocument } from "../App";

interface DocumentsPageProps {
  documents: StudyDocument[];
  selectedDocumentId: string;
  onSelectDocument: (documentId: string) => void;
}

const statusLabels: Record<StudyDocument["status"], string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled"
};

function DocumentsPage({ documents, selectedDocumentId, onSelectDocument }: DocumentsPageProps) {
  return (
    <aside className="documents-panel" aria-labelledby="documents-title">
      <div className="panel-header">
        <div>
          <h2 id="documents-title">Documents</h2>
          <p>Upload source files and monitor generated study assets.</p>
        </div>
        <button className="primary-action" type="button">Upload</button>
      </div>

      <form className="upload-strip" aria-label="Upload document placeholder">
        <label htmlFor="document-upload">Add PDF or PPTX</label>
        <div className="upload-controls">
          <input id="document-upload" type="file" accept=".pdf,.ppt,.pptx" />
          <button type="button">Queue job</button>
        </div>
      </form>

      <div className="document-list" role="list">
        {documents.map((document) => (
          <button
            className={`document-row ${document.id === selectedDocumentId ? "is-selected" : ""}`}
            key={document.id}
            type="button"
            onClick={() => onSelectDocument(document.id)}
          >
            <span className="document-row-main">
              <span className="document-title">{document.title}</span>
              <span className="document-meta">
                {document.type} · {document.pages} pages · {document.uploadedAt}
              </span>
            </span>
            <span className={`status-badge status-${document.status}`}>{statusLabels[document.status]}</span>
            <span className="document-progress" aria-label={`${document.progress}% complete`}>
              <span style={{ width: `${document.progress}%` }} />
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

export default DocumentsPage;
