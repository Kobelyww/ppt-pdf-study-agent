export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "canceled";

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

async function parseJson<T>(response: Response, message: string): Promise<T> {
  if (!response.ok) {
    const authMessage =
      response.status === 401
        ? "Authentication required"
        : response.status === 403
          ? "You do not have access to this resource"
          : message;
    throw new ApiError(`${authMessage}: ${response.status}`, response.status);
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
