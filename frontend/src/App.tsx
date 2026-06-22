import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type ApiDocument,
  type ApiJob,
  type ContentVersion,
  type ExportJob,
  type ReviewTaskSummary,
  createExport,
  getJob,
  listDocuments,
  listReviewTasks,
  listVersions,
  retryJob,
  submitFeedback,
  uploadDocument,
} from "./api";
import DocumentsPage from "./pages/DocumentsPage";
import JobDetailPage from "./pages/JobDetailPage";
import OutlinePage from "./pages/OutlinePage";
import QuestionsPage from "./pages/QuestionsPage";
import ReviewTasksPage from "./pages/ReviewTasksPage";

function latestVersion(versions: ContentVersion[], targetType: string) {
  return versions
    .filter((version) => version.target_type === targetType)
    .sort((first, second) => second.version - first.version)[0];
}

function App() {
  const [userId, setUserId] = useState("demo-user");
  const [documents, setDocuments] = useState<ApiDocument[]>([]);
  const [jobsByDocumentId, setJobsByDocumentId] = useState<Record<string, ApiJob>>({});
  const [versions, setVersions] = useState<ContentVersion[]>([]);
  const [reviewTasks, setReviewTasks] = useState<ReviewTaskSummary[]>([]);
  const [exports, setExports] = useState<ExportJob[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedDocument = useMemo(
    () => documents.find((document) => document.id === selectedDocumentId),
    [documents, selectedDocumentId],
  );
  const selectedJob = selectedDocument ? jobsByDocumentId[selectedDocument.id] : undefined;
  const latestOutline = useMemo(() => latestVersion(versions, "outline"), [versions]);
  const latestQuestions = useMemo(() => latestVersion(versions, "question_set"), [versions]);
  const runningCount = documents.filter((document) =>
    ["queued", "running", "uploaded", "processing"].includes(document.status),
  ).length;

  const refreshDocuments = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const nextDocuments = await listDocuments(userId);
      setDocuments(nextDocuments);
      setSelectedDocumentId((current) => {
        if (nextDocuments.length === 0) return "";
        if (current && nextDocuments.some((document) => document.id === current)) return current;
        return nextDocuments[0].id;
      });
    } catch (caught) {
      setDocuments([]);
      setSelectedDocumentId("");
      setError(caught instanceof Error ? caught.message : "Failed to load documents");
    } finally {
      setIsLoading(false);
    }
  }, [userId]);

  const refreshReviewTasks = useCallback(async () => {
    try {
      setReviewTasks(await listReviewTasks(userId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load review tasks");
    }
  }, [userId]);

  useEffect(() => {
    void refreshDocuments();
    void refreshReviewTasks();
  }, [refreshDocuments, refreshReviewTasks]);

  useEffect(() => {
    setJobsByDocumentId({});
    setVersions([]);
    setExports([]);
  }, [userId]);

  useEffect(() => {
    if (!selectedDocumentId) {
      setVersions([]);
      return;
    }

    let isCurrent = true;
    async function loadSelectedDocumentData() {
      setError(null);
      try {
        const loadedVersions = await listVersions(userId, selectedDocumentId);
        if (isCurrent) setVersions(loadedVersions);
      } catch (caught) {
        if (isCurrent) {
          setVersions([]);
          setError(caught instanceof Error ? caught.message : "Failed to load versions");
        }
      }
    }

    void loadSelectedDocumentData();
    return () => {
      isCurrent = false;
    };
  }, [selectedDocumentId, userId]);

  async function handleUpload(file: File) {
    setIsUploading(true);
    setError(null);
    try {
      const result = await uploadDocument(userId, file);
      setDocuments((current) => [
        result.document,
        ...current.filter((item) => item.id !== result.document.id),
      ]);
      setJobsByDocumentId((current) => ({ ...current, [result.document.id]: result.job }));
      setSelectedDocumentId(result.document.id);
      await refreshReviewTasks();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to upload document");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleRefreshJob(jobId: string) {
    setError(null);
    try {
      const job = await getJob(userId, jobId);
      setJobsByDocumentId((current) => ({ ...current, [job.document_id]: job }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load job");
    }
  }

  async function handleRetry(jobId: string) {
    setError(null);
    try {
      const job = await retryJob(userId, jobId);
      setJobsByDocumentId((current) => ({ ...current, [job.document_id]: job }));
      await refreshDocuments();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to retry job");
    }
  }

  async function handleCreateExport(version: ContentVersion, format: string) {
    if (!selectedDocument) return;
    setError(null);
    try {
      const job = await createExport(userId, selectedDocument.id, version.id, format);
      setExports((current) => [job, ...current.filter((item) => item.id !== job.id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to create export");
    }
  }

  async function handleSubmitFeedback(
    targetType: string,
    targetId: string,
    rating: number,
    reason: string,
    comment: string,
  ) {
    setError(null);
    try {
      await submitFeedback(userId, targetType, targetId, rating, reason, comment);
      await refreshReviewTasks();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to submit feedback");
    }
  }

  return (
    <main className="app-shell">
      <section className="workspace-header" aria-labelledby="workspace-title">
        <div>
          <p className="eyebrow">Internal Beta Workspace</p>
          <h1 id="workspace-title">PPT PDF Study Agent</h1>
          <p className="workspace-summary">Upload study materials, track processing, review generated content, and export usable study artifacts.</p>
        </div>
        <div className="workspace-metrics" aria-label="Workspace metrics">
          <span><strong>{documents.length}</strong> documents</span>
          <span><strong>{runningCount}</strong> active</span>
          <span><strong>{reviewTasks.length}</strong> review tasks</span>
        </div>
      </section>

      {error ? <div className="error-banner" role="alert">{error}</div> : null}

      <div className="workspace-grid">
        <DocumentsPage
          documents={documents}
          isLoading={isLoading}
          isUploading={isUploading}
          selectedDocumentId={selectedDocumentId}
          userId={userId}
          onSelectDocument={setSelectedDocumentId}
          onUpload={handleUpload}
          onUserIdChange={setUserId}
        />

        <section className="detail-stack" aria-label="Selected document study workspace">
          <JobDetailPage
            document={selectedDocument}
            job={selectedJob}
            onRefreshJob={handleRefreshJob}
            onRetry={handleRetry}
          />
          <div className="study-columns">
            <OutlinePage
              exportJobs={exports}
              version={latestOutline}
              onCreateExport={handleCreateExport}
              onSubmitFeedback={handleSubmitFeedback}
            />
            <QuestionsPage
              exportJobs={exports}
              version={latestQuestions}
              onCreateExport={handleCreateExport}
              onSubmitFeedback={handleSubmitFeedback}
            />
          </div>
          <ReviewTasksPage tasks={reviewTasks} />
        </section>
      </div>
    </main>
  );
}

export default App;
