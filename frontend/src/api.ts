export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "canceled";

export interface StudyIndexStatus {
  document_id: string;
  status: "indexed" | "missing" | "stale" | "fallback_available";
  artifact_id?: string | null;
  expected_chunk_count?: number | null;
  indexed_artifact_id?: string | null;
  latest_artifact_id?: string | null;
  chunk_count: number;
  indexed_at?: string | null;
  fallback_reason?: string | null;
}

export interface ApiDocument {
  id: string;
  owner_id: string;
  title: string;
  source_type: string;
  storage_uri?: string;
  content_hash?: string;
  original_filename?: string | null;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
  study_index?: StudyIndexStatus | null;
}

export interface ApiJob {
  id?: string;
  job_id?: string;
  document_id: string;
  owner_id?: string;
  job_type?: string;
  status: JobStatus;
  progress?: number;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ContentVersion {
  id: string;
  document_id?: string;
  target_type: string;
  target_id: string;
  version: number;
  content: string;
  created_by: string;
  created_at?: string | null;
  change_summary: string;
  content_metadata?: Record<string, unknown>;
}

export interface ExportJob {
  id: string;
  document_id: string;
  version_id: string;
  format: string;
  status: string;
  storage_uri?: string | null;
  error_message?: string | null;
}

export interface ReviewTaskSummary {
  id: string;
  owner_id?: string;
  target_type: string;
  target_id: string;
  status: string;
  reason: string;
  decision?: string | null;
  comment?: string | null;
}

export interface AuthenticatedUser {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
}

export type StudyTarget = "answer" | "question" | "outline_fragment";
export type StudyBudget = "low" | "balanced" | "high";
export type StudyRetrievalMode = "simple_rag" | "graph_rag_lite" | "agentic_rag";

export interface StudyAgentQueryPayload {
  query: string;
  target: StudyTarget;
  document_ids: string[];
  preferred_mode?: StudyRetrievalMode;
  budget?: StudyBudget;
  expected_terms?: string[];
}

export interface StudyAgentChunk {
  content: string;
  source: string;
  metadata: Record<string, unknown>;
  score: number;
}

export interface StudyAgentTraceSummary {
  trace_id: string;
  request_id?: string | null;
  selected_mode?: StudyRetrievalMode | null;
  route_reason?: string | null;
  chunk_source?: "persisted" | "fallback" | null;
  fallback_reason?: string | null;
  document_count: number;
  source_count: number;
  used_chunk_count: number;
  confidence: number;
  source_recall: number;
  answer_term_recall: number;
  needs_review: boolean;
  latency_ms: number;
}

export interface StudyAgentPolicyDiagnostic {
  policy_version?: string | null;
  router_mode?: StudyRetrievalMode | null;
  selected_mode?: StudyRetrievalMode | null;
  category?: string | null;
  status?: string | null;
  readiness_status?: string | null;
  blocked_reason?: string | null;
  experiment_enabled?: boolean | null;
}

export interface StudyAgentResult {
  request: {
    query: string;
    target: StudyTarget;
    document_ids: string[];
    preferred_mode?: StudyRetrievalMode | null;
    budget: StudyBudget;
    expected_terms: string[];
    authenticated_user_id?: string | null;
    request_id?: string | null;
  };
  plan: {
    mode: StudyRetrievalMode;
    reason: string;
    steps: string[];
    estimated_cost: string;
    fallbacks: StudyRetrievalMode[];
  };
  evidence: {
    mode: StudyRetrievalMode;
    chunks: StudyAgentChunk[];
    sources: string[];
    concept_ids: string[];
    confidence: number;
    reason: string;
    fallback_reason?: string | null;
  };
  draft: {
    target: StudyTarget;
    content: string;
    citations: string[];
    used_chunk_count: number;
    metadata: Record<string, unknown>;
  };
  verification: {
    passed: boolean;
    needs_review: boolean;
    confidence: number;
    issues: string[];
    source_recall: number;
    answer_term_recall: number;
  };
  trace?: StudyAgentTraceSummary;
  policy?: StudyAgentPolicyDiagnostic | null;
  audit_metadata?: Record<string, unknown>;
}

const API_BASE =
  (import.meta as ImportMeta & { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE ??
  "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export class ApiClient {
  private token: string;
  private devUserId: string | null;

  constructor(token: string, devUserId: string | null = null) {
    this.token = token;
    this.devUserId = devUserId;
  }

  headers(extra?: HeadersInit): HeadersInit {
    const base: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
    };
    if (this.devUserId) base["x-user-id"] = this.devUserId;
    return { ...base, ...extra };
  }
}

function apiDetailMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = "detail" in body ? (body as { detail?: unknown }).detail : null;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const message = (item as { msg?: unknown }).msg;
          return typeof message === "string" ? message : null;
        }
        return null;
      })
      .filter((message): message is string => Boolean(message));
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}

async function parseJson<T>(response: Response, message: string): Promise<T> {
  if (!response.ok) {
    let detailMessage: string | null = null;
    try {
      detailMessage = apiDetailMessage(await response.clone().json());
    } catch {
      detailMessage = null;
    }
    const authMessage =
      response.status === 401
        ? "Authentication required"
        : response.status === 403
          ? "You do not have access to this resource"
          : message;
    throw new ApiError(`${detailMessage ?? authMessage}: ${response.status}`, response.status);
  }
  return response.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<LoginResult> {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return parseJson<LoginResult>(response, "Failed to log in");
}

export async function me(apiClient: ApiClient): Promise<AuthenticatedUser> {
  const response = await fetch(`${API_BASE}/api/auth/me`, {
    headers: apiClient.headers(),
  });
  return parseJson<AuthenticatedUser>(response, "Failed to load current user");
}

export async function listDocuments(apiClient: ApiClient): Promise<ApiDocument[]> {
  const response = await fetch(`${API_BASE}/api/documents`, { headers: apiClient.headers() });
  return parseJson<ApiDocument[]>(response, "Failed to load documents");
}

export async function uploadDocument(
  apiClient: ApiClient,
  file: File,
): Promise<{ document: ApiDocument; job: ApiJob }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/documents`, {
    method: "POST",
    headers: apiClient.headers(),
    body: form,
  });
  return parseJson<{ document: ApiDocument; job: ApiJob }>(response, "Failed to upload document");
}

export async function getJob(apiClient: ApiClient, jobId: string): Promise<ApiJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, {
    headers: apiClient.headers(),
  });
  return parseJson<ApiJob>(response, "Failed to load job");
}

export async function retryJob(apiClient: ApiClient, jobId: string): Promise<ApiJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/retry`, {
    method: "POST",
    headers: apiClient.headers(),
  });
  return parseJson<ApiJob>(response, "Failed to retry job");
}

export async function listVersions(
  apiClient: ApiClient,
  documentId: string,
): Promise<ContentVersion[]> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/versions`, {
    headers: apiClient.headers(),
  });
  return parseJson<ContentVersion[]>(response, "Failed to load versions");
}

export async function createExport(
  apiClient: ApiClient,
  documentId: string,
  versionId: string,
  format: string,
): Promise<ExportJob> {
  const response = await fetch(`${API_BASE}/api/exports/${documentId}`, {
    method: "POST",
    headers: apiClient.headers({ "content-type": "application/json" }),
    body: JSON.stringify({ version_id: versionId, format }),
  });
  return parseJson<ExportJob>(response, "Failed to create export");
}

export async function queryStudyAgent(
  apiClient: ApiClient,
  payload: StudyAgentQueryPayload,
): Promise<StudyAgentResult> {
  const response = await fetch(`${API_BASE}/api/study-agent/query`, {
    method: "POST",
    headers: apiClient.headers({ "content-type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return parseJson<StudyAgentResult>(response, "Failed to query Study Agent");
}

export async function submitFeedback(
  apiClient: ApiClient,
  targetType: string,
  targetId: string,
  rating: number,
  reason: string,
  comment: string,
): Promise<{ id: string; rating: number; target_id: string }> {
  const response = await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: apiClient.headers({ "content-type": "application/json" }),
    body: JSON.stringify({
      target_type: targetType,
      target_id: targetId,
      rating,
      reason,
      comment,
    }),
  });
  return parseJson<{ id: string; rating: number; target_id: string }>(
    response,
    "Failed to submit feedback",
  );
}

export async function listReviewTasks(apiClient: ApiClient): Promise<ReviewTaskSummary[]> {
  const response = await fetch(`${API_BASE}/api/review-tasks`, {
    headers: apiClient.headers(),
  });
  return parseJson<ReviewTaskSummary[]>(response, "Failed to load review tasks");
}
