import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiClient,
  ApiError,
  type AuthenticatedUser,
  type ApiDocument,
  type ApiJob,
  type ContentVersion,
  type ExportJob,
  type ReviewTaskSummary,
  createExport,
  getJob,
  login,
  listDocuments,
  listReviewTasks,
  listVersions,
  me,
  retryJob,
  submitFeedback,
  uploadDocument,
} from "./api";
import StudyAgentPanel from "./components/StudyAgentPanel";
import DocumentsPage from "./pages/DocumentsPage";
import JobDetailPage from "./pages/JobDetailPage";
import LoginPage from "./pages/LoginPage";
import OutlinePage from "./pages/OutlinePage";
import QuestionsPage from "./pages/QuestionsPage";
import ReviewTasksPage from "./pages/ReviewTasksPage";

const TOKEN_STORAGE_KEY = "ppt-pdf-study-agent-token";
const DEV_USER_STORAGE_KEY = "ppt-pdf-study-agent-dev-user";
const ALLOW_DEV_USER_SWITCHER =
  (import.meta as ImportMeta & { env?: { VITE_ALLOW_DEV_USER_SWITCHER?: string } }).env
    ?.VITE_ALLOW_DEV_USER_SWITCHER === "true";

function latestVersion(versions: ContentVersion[], targetType: string) {
  return versions
    .filter((version) => version.target_type === targetType)
    .sort((first, second) => second.version - first.version)[0];
}

function App() {
  const [authToken, setAuthToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? "");
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null);
  const [devUserId, setDevUserId] = useState(
    () => localStorage.getItem(DEV_USER_STORAGE_KEY) ?? "demo-user",
  );
  const [documents, setDocuments] = useState<ApiDocument[]>([]);
  const [jobsByDocumentId, setJobsByDocumentId] = useState<Record<string, ApiJob>>({});
  const [versions, setVersions] = useState<ContentVersion[]>([]);
  const [reviewTasks, setReviewTasks] = useState<ReviewTaskSummary[]>([]);
  const [exports, setExports] = useState<ExportJob[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isRestoringSession, setIsRestoringSession] = useState(Boolean(authToken));
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const apiClient = useMemo(
    () =>
      authToken
        ? new ApiClient(authToken, ALLOW_DEV_USER_SWITCHER ? devUserId : null)
        : null,
    [authToken, devUserId],
  );

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

  const handleLogout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setAuthToken("");
    setCurrentUser(null);
    setDocuments([]);
    setJobsByDocumentId({});
    setVersions([]);
    setReviewTasks([]);
    setExports([]);
    setSelectedDocumentId("");
    setError(null);
  }, []);

  const handleApiError = useCallback(
    (caught: unknown, fallback: string) => {
      if (caught instanceof ApiError && caught.status === 401) {
        handleLogout();
      }
      return caught instanceof Error ? caught.message : fallback;
    },
    [handleLogout],
  );

  const handleLogin = useCallback(async (email: string, password: string) => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const result = await login(email, password);
      const nextClient = new ApiClient(result.access_token);
      const user = await me(nextClient);
      localStorage.setItem(TOKEN_STORAGE_KEY, result.access_token);
      setAuthToken(result.access_token);
      setCurrentUser(user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to log in");
    } finally {
      setIsLoggingIn(false);
    }
  }, []);

  const refreshDocuments = useCallback(async () => {
    if (!apiClient) return;
    setIsLoading(true);
    setError(null);
    try {
      const nextDocuments = await listDocuments(apiClient);
      setDocuments(nextDocuments);
      setSelectedDocumentId((current) => {
        if (nextDocuments.length === 0) return "";
        if (current && nextDocuments.some((document) => document.id === current)) return current;
        return nextDocuments[0].id;
      });
    } catch (caught) {
      setDocuments([]);
      setSelectedDocumentId("");
      setError(handleApiError(caught, "Failed to load documents"));
    } finally {
      setIsLoading(false);
    }
  }, [apiClient, handleApiError]);

  const refreshReviewTasks = useCallback(async () => {
    if (!apiClient) return;
    try {
      setReviewTasks(await listReviewTasks(apiClient));
    } catch (caught) {
      setError(handleApiError(caught, "Failed to load review tasks"));
    }
  }, [apiClient, handleApiError]);

  useEffect(() => {
    if (!apiClient) {
      setIsRestoringSession(false);
      return;
    }
    let isCurrent = true;
    async function restoreSession() {
      setIsRestoringSession(true);
      try {
        const user = await me(apiClient as ApiClient);
        if (isCurrent) setCurrentUser(user);
      } catch (caught) {
        if (isCurrent) {
          setError(handleApiError(caught, "Failed to restore session"));
        }
      } finally {
        if (isCurrent) setIsRestoringSession(false);
      }
    }
    void restoreSession();
    return () => {
      isCurrent = false;
    };
  }, [apiClient, handleApiError]);

  useEffect(() => {
    if (!currentUser) return;
    void refreshDocuments();
    void refreshReviewTasks();
  }, [currentUser, refreshDocuments, refreshReviewTasks]);

  useEffect(() => {
    localStorage.setItem(DEV_USER_STORAGE_KEY, devUserId);
    setJobsByDocumentId({});
    setVersions([]);
    setExports([]);
  }, [devUserId]);

  useEffect(() => {
    if (!selectedDocumentId || !apiClient) {
      setVersions([]);
      return;
    }

    let isCurrent = true;
    const client = apiClient;
    async function loadSelectedDocumentData() {
      setError(null);
      try {
        const loadedVersions = await listVersions(client, selectedDocumentId);
        if (isCurrent) setVersions(loadedVersions);
      } catch (caught) {
        if (isCurrent) {
          setVersions([]);
          setError(handleApiError(caught, "Failed to load versions"));
        }
      }
    }

    void loadSelectedDocumentData();
    return () => {
      isCurrent = false;
    };
  }, [apiClient, handleApiError, selectedDocumentId]);

  async function handleUpload(file: File) {
    if (!apiClient) return;
    setIsUploading(true);
    setError(null);
    try {
      const result = await uploadDocument(apiClient, file);
      setDocuments((current) => [
        result.document,
        ...current.filter((item) => item.id !== result.document.id),
      ]);
      setJobsByDocumentId((current) => ({ ...current, [result.document.id]: result.job }));
      setSelectedDocumentId(result.document.id);
      await refreshReviewTasks();
    } catch (caught) {
      setError(handleApiError(caught, "Failed to upload document"));
    } finally {
      setIsUploading(false);
    }
  }

  async function handleRefreshJob(jobId: string) {
    if (!apiClient) return;
    setError(null);
    try {
      const job = await getJob(apiClient, jobId);
      setJobsByDocumentId((current) => ({ ...current, [job.document_id]: job }));
    } catch (caught) {
      setError(handleApiError(caught, "Failed to load job"));
    }
  }

  async function handleRetry(jobId: string) {
    if (!apiClient) return;
    setError(null);
    try {
      const job = await retryJob(apiClient, jobId);
      setJobsByDocumentId((current) => ({ ...current, [job.document_id]: job }));
      await refreshDocuments();
    } catch (caught) {
      setError(handleApiError(caught, "Failed to retry job"));
    }
  }

  async function handleCreateExport(version: ContentVersion, format: string) {
    if (!selectedDocument || !apiClient) return;
    setError(null);
    try {
      const job = await createExport(apiClient, selectedDocument.id, version.id, format);
      setExports((current) => [job, ...current.filter((item) => item.id !== job.id)]);
    } catch (caught) {
      setError(handleApiError(caught, "Failed to create export"));
    }
  }

  async function handleSubmitFeedback(
    targetType: string,
    targetId: string,
    rating: number,
    reason: string,
    comment: string,
  ) {
    if (!apiClient) return;
    setError(null);
    try {
      await submitFeedback(apiClient, targetType, targetId, rating, reason, comment);
      await refreshReviewTasks();
    } catch (caught) {
      setError(handleApiError(caught, "Failed to submit feedback"));
    }
  }

  if (!authToken || !currentUser || !apiClient) {
    return (
      <LoginPage
        error={error}
        isLoading={isLoggingIn || isRestoringSession}
        onLogin={handleLogin}
      />
    );
  }

  return (
    <main className="app-shell">
      <section className="workspace-header" aria-labelledby="workspace-title">
        <div>
          <p className="eyebrow">Internal Beta Workspace</p>
          <h1 id="workspace-title">PPT PDF Study Agent</h1>
          <p className="workspace-summary">Upload study materials, track processing, review generated content, and export usable study artifacts.</p>
        </div>
        <div className="session-box">
          <span>{currentUser.email}</span>
          <button className="secondary-action" type="button" onClick={handleLogout}>
            Logout
          </button>
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
          allowDevUserSwitcher={ALLOW_DEV_USER_SWITCHER}
          devUserId={devUserId}
          onSelectDocument={setSelectedDocumentId}
          onUpload={handleUpload}
          onDevUserIdChange={setDevUserId}
        />

        <section className="detail-stack" aria-label="Selected document study workspace">
          <JobDetailPage
            document={selectedDocument}
            job={selectedJob}
            onRefreshJob={handleRefreshJob}
            onRetry={handleRetry}
          />
          <StudyAgentPanel
            apiClient={apiClient}
            documents={documents}
            selectedDocumentId={selectedDocumentId}
            onSelectDocument={setSelectedDocumentId}
            onAuthExpired={handleLogout}
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
