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

const API_BASE =
  (import.meta as ImportMeta & { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE ??
  "http://localhost:8000";

function headers(userId: string): HeadersInit {
  return { "x-user-id": userId };
}

async function parseJson<T>(response: Response, message: string): Promise<T> {
  if (!response.ok) {
    throw new Error(`${message}: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listDocuments(userId: string): Promise<ApiDocument[]> {
  const response = await fetch(`${API_BASE}/api/documents`, { headers: headers(userId) });
  return parseJson<ApiDocument[]>(response, "Failed to load documents");
}

export async function uploadDocument(
  userId: string,
  file: File,
): Promise<{ document: ApiDocument; job: ApiJob }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/documents`, {
    method: "POST",
    headers: headers(userId),
    body: form,
  });
  return parseJson<{ document: ApiDocument; job: ApiJob }>(response, "Failed to upload document");
}

export async function getJob(userId: string, jobId: string): Promise<ApiJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, { headers: headers(userId) });
  return parseJson<ApiJob>(response, "Failed to load job");
}

export async function retryJob(userId: string, jobId: string): Promise<ApiJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/retry`, {
    method: "POST",
    headers: headers(userId),
  });
  return parseJson<ApiJob>(response, "Failed to retry job");
}

export async function listVersions(
  userId: string,
  documentId: string,
): Promise<ContentVersion[]> {
  const response = await fetch(`${API_BASE}/api/documents/${documentId}/versions`, {
    headers: headers(userId),
  });
  return parseJson<ContentVersion[]>(response, "Failed to load versions");
}

export async function createExport(
  userId: string,
  documentId: string,
  versionId: string,
  format: string,
): Promise<ExportJob> {
  const response = await fetch(`${API_BASE}/api/exports/${documentId}`, {
    method: "POST",
    headers: { ...headers(userId), "content-type": "application/json" },
    body: JSON.stringify({ version_id: versionId, format }),
  });
  return parseJson<ExportJob>(response, "Failed to create export");
}

export async function submitFeedback(
  userId: string,
  targetType: string,
  targetId: string,
  rating: number,
  reason: string,
  comment: string,
): Promise<{ id: string; rating: number; target_id: string }> {
  const response = await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: { ...headers(userId), "content-type": "application/json" },
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

export async function listReviewTasks(userId: string): Promise<ReviewTaskSummary[]> {
  const response = await fetch(`${API_BASE}/api/review-tasks`, { headers: headers(userId) });
  return parseJson<ReviewTaskSummary[]>(response, "Failed to load review tasks");
}
