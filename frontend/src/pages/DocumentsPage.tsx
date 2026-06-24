import { type FormEvent, useState } from "react";
import type { ApiDocument } from "../api";

interface DocumentsPageProps {
  documents: ApiDocument[];
  isLoading: boolean;
  isUploading: boolean;
  selectedDocumentId: string;
  allowDevUserSwitcher: boolean;
  devUserId: string;
  onSelectDocument: (documentId: string) => void;
  onUpload: (file: File) => Promise<void>;
  onDevUserIdChange: (userId: string) => void;
}

const statusLabels: Record<string, string> = {
  queued: "Queued",
  uploaded: "Uploaded",
  processing: "Processing",
  running: "Running",
  ready: "Ready",
  completed: "Completed",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
  canceled: "Canceled",
};

function formatDate(value?: string | null) {
  if (!value) return "No timestamp";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function documentType(document: ApiDocument) {
  return document.source_type?.toUpperCase() || "FILE";
}

function DocumentsPage({
  documents,
  isLoading,
  isUploading,
  selectedDocumentId,
  allowDevUserSwitcher,
  devUserId,
  onSelectDocument,
  onUpload,
  onDevUserIdChange,
}: DocumentsPageProps) {
  const [file, setFile] = useState<File | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    await onUpload(file);
    setFile(null);
    event.currentTarget.reset();
  }

  return (
    <aside className="documents-panel" aria-labelledby="documents-title">
      <div className="panel-header">
        <div>
          <h2 id="documents-title">Documents</h2>
          <p>Upload source files and monitor generated study assets.</p>
        </div>
      </div>

      {allowDevUserSwitcher ? (
        <label className="user-switcher" htmlFor="user-id">
          <span>Development user override</span>
          <input
            id="user-id"
            type="text"
            value={devUserId}
            onChange={(event) => onDevUserIdChange(event.target.value || "demo-user")}
          />
        </label>
      ) : null}

      <form className="upload-strip" aria-label="Upload document" onSubmit={handleSubmit}>
        <label htmlFor="document-upload">Add PDF or PPTX</label>
        <div className="upload-row">
          <input
            id="document-upload"
            type="file"
            accept=".pdf,.ppt,.pptx"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <button type="submit" disabled={!file || isUploading}>
            {isUploading ? "Uploading" : "Queue job"}
          </button>
        </div>
      </form>

      <div className="document-list" role="list">
        {isLoading ? (
          <div className="empty-state">
            <strong>Loading documents</strong>
            <span>Fetching the current user's workspace.</span>
          </div>
        ) : documents.length === 0 ? (
          <div className="empty-state">
            <strong>No documents</strong>
            <span>Upload a PDF or PPTX to start the product loop.</span>
          </div>
        ) : (
          documents.map((document) => {
            const status = document.status || "queued";
            return (
              <button
                className={`document-row ${document.id === selectedDocumentId ? "is-selected" : ""}`}
                key={document.id}
                type="button"
                onClick={() => onSelectDocument(document.id)}
              >
                <span className="document-row-main">
                  <span className="document-title">{document.title}</span>
                  <span className="document-meta">
                    {documentType(document)} · {formatDate(document.created_at)}
                  </span>
                </span>
                <span className={`status-badge status-${status}`}>
                  {statusLabels[status] ?? status}
                </span>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}

export default DocumentsPage;
