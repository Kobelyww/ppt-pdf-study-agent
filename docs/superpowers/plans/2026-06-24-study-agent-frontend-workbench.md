# Study Agent Frontend Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a frontend Study Agent workbench so authenticated users can select one or more ready documents, query `/api/study-agent/query`, and inspect grounded results, citations, confidence, and review status.

**Architecture:** Extend the existing Vite/React single-page workspace without changing the backend. Add typed Study Agent API contracts in `frontend/src/api.ts`, create focused UI components for query controls and evidence display, then integrate the panel into the existing selected-document detail stack. Keep the interface dense and operational like the current product workbench.

**Tech Stack:** Vite, React 18, TypeScript, existing browser `fetch` API, existing CSS in `frontend/src/styles.css`, backend `/api/study-agent/query`.

---

## File Structure

- Modify `frontend/src/api.ts`
  - Add Study Agent request/result types and `queryStudyAgent`.
- Create `frontend/src/components/EvidenceViewer.tsx`
  - Render citations, evidence chunks, confidence, selected mode, fallback reason, and review issues.
- Create `frontend/src/components/StudyAgentPanel.tsx`
  - Own Study Agent form state, multi-document ready-source selection, request submission, loading/error states, and result rendering.
- Modify `frontend/src/App.tsx`
  - Import `StudyAgentPanel`, pass `apiClient`, documents, selected document, and global API error handler.
- Modify `frontend/src/styles.css`
  - Add compact workbench styles for the Study Agent panel and evidence display.

Every implementation task must finish with two reviews before commit:

1. Spec review: compare the task result against `docs/superpowers/specs/2026-06-24-product-completion-roadmap-design.md`, Phase 1.
2. Quality review: inspect accessibility, responsive layout, state handling, privacy, API error mapping, and whether existing workflows remain intact.

---

### Task 1: Study Agent API Client Types

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: Preserve backend product error details**

Replace the current `parseJson` helper in `frontend/src/api.ts` with this implementation:

```ts
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
```

- [ ] **Step 2: Add Study Agent type contracts**

Append these types to `frontend/src/api.ts` after `LoginResult`:

```ts
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
  audit_metadata: Record<string, unknown>;
}
```

- [ ] **Step 3: Add the API function**

Append this function near the other exported API calls in `frontend/src/api.ts`:

```ts
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
```

- [ ] **Step 4: Run the frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 5: Spec review for Task 1**

Check manually:

- Types cover query, target, one-or-more document ids, preferred mode, budget, expected terms.
- Result type covers generated content, citations, evidence chunks, mode, confidence, fallback reason, and review status.
- API function calls exactly `/api/study-agent/query`.
- API errors preserve backend `detail` strings for missing explicit document selection, non-ready documents, unavailable evidence, and inaccessible documents.

If any item fails, fix `frontend/src/api.ts` and rerun `cd frontend && npm run build`.

- [ ] **Step 6: Quality review for Task 1**

Check manually:

- Types match backend JSON names using snake_case where backend returns snake_case.
- `queryStudyAgent` uses existing `ApiClient.headers` and `parseJson`.
- `parseJson` does not expose stack traces or raw objects; it only displays string details or validation messages.
- No auth token or identity field is manually inserted into request JSON.
- No new dependency is added.

If any item fails, fix `frontend/src/api.ts` and rerun `cd frontend && npm run build`.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add frontend/src/api.ts
git commit -m "feat: type study agent frontend api"
```

Expected: commit succeeds with only `frontend/src/api.ts` staged.

---

### Task 2: Evidence Viewer Component

**Files:**
- Create: `frontend/src/components/EvidenceViewer.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/EvidenceViewer.tsx`:

```tsx
import type { StudyAgentResult } from "../api";

interface EvidenceViewerProps {
  result: StudyAgentResult;
}

function formatPercent(value: number) {
  if (!Number.isFinite(value)) return "0%";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function metadataLabel(metadata: Record<string, unknown>) {
  const title = typeof metadata.document_title === "string" ? metadata.document_title : "";
  const chunkIndex =
    typeof metadata.chunk_index === "number" ? `chunk ${metadata.chunk_index + 1}` : "";
  const documentId = typeof metadata.document_id === "string" ? metadata.document_id : "";
  return [title, chunkIndex, documentId].filter(Boolean).join(" · ") || "Evidence";
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
          {result.verification.issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      ) : null}

      <div className="citation-list" aria-label="Citations">
        {result.draft.citations.length > 0 ? (
          result.draft.citations.map((citation) => (
            <span className="citation-pill" key={citation}>
              {citation}
            </span>
          ))
        ) : (
          <span className="muted">No citations returned.</span>
        )}
      </div>

      <div className="evidence-list">
        {result.evidence.chunks.length > 0 ? (
          result.evidence.chunks.map((chunk) => (
            <article className="evidence-item" key={chunk.source}>
              <div className="evidence-heading">
                <strong>{metadataLabel(chunk.metadata)}</strong>
                <span>{formatPercent(chunk.score)}</span>
              </div>
              <p>{chunk.content}</p>
              <code>{chunk.source}</code>
            </article>
          ))
        ) : (
          <div className="empty-state">
            <strong>No evidence chunks</strong>
            <span>The agent could not recover supporting chunks for this query.</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default EvidenceViewer;
```

- [ ] **Step 2: Run the frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 3: Spec review for Task 2**

Check manually:

- Component displays citations.
- Component displays evidence chunks or an empty evidence state.
- Component displays mode, confidence, review status, and fallback reason.

If any item fails, fix `frontend/src/components/EvidenceViewer.tsx` and rerun `cd frontend && npm run build`.

- [ ] **Step 4: Quality review for Task 2**

Check manually:

- Component is display-only and has no API side effects.
- Long source ids and chunk content can wrap.
- It does not render raw metadata objects directly.
- It uses existing visual language: compact trace, pills, evidence list.

If any item fails, fix component and rerun `cd frontend && npm run build`.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add frontend/src/components/EvidenceViewer.tsx
git commit -m "feat: render study agent evidence"
```

Expected: commit succeeds with only `EvidenceViewer.tsx` staged.

---

### Task 3: Study Agent Panel Component

**Files:**
- Create: `frontend/src/components/StudyAgentPanel.tsx`

- [ ] **Step 1: Create the panel component**

Create `frontend/src/components/StudyAgentPanel.tsx`:

```tsx
import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
  ApiClient,
  ApiError,
  type ApiDocument,
  type StudyAgentQueryPayload,
  type StudyAgentResult,
  type StudyBudget,
  type StudyRetrievalMode,
  type StudyTarget,
  queryStudyAgent,
} from "../api";
import EvidenceViewer from "./EvidenceViewer";

interface StudyAgentPanelProps {
  apiClient: ApiClient;
  documents: ApiDocument[];
  selectedDocumentId: string;
  onSelectDocument: (documentId: string) => void;
  onAuthExpired: () => void;
}

const targetOptions: Array<{ value: StudyTarget; label: string }> = [
  { value: "answer", label: "Answer" },
  { value: "question", label: "Practice question" },
  { value: "outline_fragment", label: "Study notes" },
];

const budgetOptions: Array<{ value: StudyBudget; label: string }> = [
  { value: "balanced", label: "Balanced" },
  { value: "low", label: "Low" },
  { value: "high", label: "High" },
];

const modeOptions: Array<{ value: ""; label: string } | { value: StudyRetrievalMode; label: string }> = [
  { value: "", label: "Auto" },
  { value: "simple_rag", label: "Simple" },
  { value: "graph_rag_lite", label: "Graph" },
  { value: "agentic_rag", label: "Agentic" },
];

function readyDocuments(documents: ApiDocument[]) {
  return documents.filter((document) => document.status === "ready");
}

function parseExpectedTerms(value: string) {
  return value
    .split(",")
    .map((term) => term.trim())
    .filter(Boolean);
}

function initialDocumentIds(documents: ApiDocument[], selectedDocumentId: string) {
  const ready = readyDocuments(documents);
  if (selectedDocumentId && ready.some((document) => document.id === selectedDocumentId)) {
    return [selectedDocumentId];
  }
  return ready[0]?.id ? [ready[0].id] : [];
}

function StudyAgentPanel({
  apiClient,
  documents,
  selectedDocumentId,
  onSelectDocument,
  onAuthExpired,
}: StudyAgentPanelProps) {
  const ready = useMemo(() => readyDocuments(documents), [documents]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>(() =>
    initialDocumentIds(documents, selectedDocumentId),
  );
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<StudyTarget>("answer");
  const [budget, setBudget] = useState<StudyBudget>("balanced");
  const [preferredMode, setPreferredMode] = useState<StudyRetrievalMode | "">("");
  const [expectedTerms, setExpectedTerms] = useState("");
  const [result, setResult] = useState<StudyAgentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const readyIds = useMemo(() => new Set(ready.map((document) => document.id)), [ready]);
  const validSelectedIds = useMemo(
    () => selectedDocumentIds.filter((documentId) => readyIds.has(documentId)),
    [readyIds, selectedDocumentIds],
  );
  const hasReadySource = validSelectedIds.length > 0;
  const hasNonReadyDocuments = documents.some((document) => document.status !== "ready");

  useEffect(() => {
    setSelectedDocumentIds((current) => {
      const filtered = current.filter((documentId) => readyIds.has(documentId));
      if (filtered.length > 0) {
        return filtered.length === current.length ? current : filtered;
      }
      const nextDocumentId =
        selectedDocumentId && readyIds.has(selectedDocumentId) ? selectedDocumentId : ready[0]?.id;
      return nextDocumentId ? [nextDocumentId] : [];
    });
  }, [ready, readyIds, selectedDocumentId]);

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((current) => {
      const existing = current.filter((item) => readyIds.has(item));
      const next = existing.includes(documentId)
        ? existing.filter((item) => item !== documentId)
        : [...existing, documentId];
      return next;
    });
    onSelectDocument(documentId);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const documentIds = validSelectedIds;
    if (documentIds.length === 0) {
      setError("Select at least one ready document before asking the Study Agent.");
      return;
    }
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      setError("Enter a study question before running the agent.");
      return;
    }

    const payload: StudyAgentQueryPayload = {
      query: trimmedQuery,
      target,
      document_ids: documentIds,
      budget,
    };
    if (preferredMode) payload.preferred_mode = preferredMode;
    const terms = parseExpectedTerms(expectedTerms);
    if (terms.length > 0) payload.expected_terms = terms;

    setIsSubmitting(true);
    try {
      setResult(await queryStudyAgent(apiClient, payload));
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        onAuthExpired();
      }
      setError(caught instanceof Error ? caught.message : "Failed to query Study Agent");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="study-agent-panel" aria-labelledby="study-agent-title">
      <div className="panel-header compact">
        <div>
          <h2 id="study-agent-title">Study Agent</h2>
          <p>Ask grounded questions against processed documents.</p>
        </div>
        {hasReadySource ? (
          <span className="status-badge status-ready">{validSelectedIds.length} source</span>
        ) : (
          <span className="status-badge status-idle">No ready source</span>
        )}
      </div>

      {ready.length === 0 ? (
        <div className="empty-state">
          <strong>No ready documents</strong>
          <span>
            {hasNonReadyDocuments
              ? "Wait for processing to finish before asking the Study Agent."
              : "Upload and process a PDF or PPTX before asking the Study Agent."}
          </span>
        </div>
      ) : (
        <form className="study-agent-form" onSubmit={handleSubmit}>
          <fieldset className="document-checklist">
            <legend>Ready documents</legend>
            <div>
              {ready.map((document) => (
                <label key={document.id}>
                  <input
                    type="checkbox"
                    checked={validSelectedIds.includes(document.id)}
                    onChange={() => toggleDocument(document.id)}
                  />
                  <span>{document.title}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <label htmlFor="study-agent-query">
            <span>Question</span>
            <textarea
              id="study-agent-query"
              value={query}
              rows={4}
              placeholder="Ask what this document explains, request a practice question, or ask for review notes."
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>

          <div className="agent-control-grid">
            <label htmlFor="study-agent-target">
              <span>Target</span>
              <select
                id="study-agent-target"
                value={target}
                onChange={(event) => setTarget(event.target.value as StudyTarget)}
              >
                {targetOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label htmlFor="study-agent-budget">
              <span>Budget</span>
              <select
                id="study-agent-budget"
                value={budget}
                onChange={(event) => setBudget(event.target.value as StudyBudget)}
              >
                {budgetOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label htmlFor="study-agent-mode">
              <span>Mode</span>
              <select
                id="study-agent-mode"
                value={preferredMode}
                onChange={(event) =>
                  setPreferredMode(event.target.value as StudyRetrievalMode | "")
                }
              >
                {modeOptions.map((option) => (
                  <option key={option.value || "auto"} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label htmlFor="study-agent-terms">
            <span>Expected terms</span>
            <input
              id="study-agent-terms"
              type="text"
              value={expectedTerms}
              placeholder="Optional, comma separated"
              onChange={(event) => setExpectedTerms(event.target.value)}
            />
          </label>

          {error ? (
            <div className="error-banner compact" role="alert">
              {error}
            </div>
          ) : null}

          <div className="action-row">
            <button className="primary-action" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Running" : "Run Study Agent"}
            </button>
          </div>
        </form>
      )}

      {result ? (
        <div className="study-agent-result">
          <div className="panel-header compact">
            <div>
              <h3>Result</h3>
              <p>{result.verification.needs_review ? "Review recommended" : "Grounded response"}</p>
            </div>
            <span className={`status-badge ${result.verification.needs_review ? "status-failed" : "status-ready"}`}>
              {result.verification.needs_review ? "Needs review" : "Passed"}
            </span>
          </div>
          <pre className="content-block agent-answer">{result.draft.content}</pre>
          <EvidenceViewer result={result} />
        </div>
      ) : null}
    </section>
  );
}

export default StudyAgentPanel;
```

- [ ] **Step 2: Run the frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 3: Spec review for Task 3**

Check manually:

- Panel lets users select one or more ready documents.
- Panel supports query, target, preferred mode, budget, and expected terms.
- Panel blocks submit when no ready document is selected or blank query is available.
- Panel renders generated content, review status, and evidence viewer.
- Panel maps auth expiration to `onAuthExpired`.

If any item fails, fix `frontend/src/components/StudyAgentPanel.tsx` and rerun `cd frontend && npm run build`.

- [ ] **Step 4: Quality review for Task 3**

Check manually:

- Component owns only Study Agent UI state.
- Component sends only selected ready document ids in this phase.
- Toggling a document keeps the existing app-level selected document synchronized for Job, Outline, and Questions views.
- Component does not trust or send user identity fields.
- Long answers and source text use existing `content-block` wrapping.
- Empty-ready state is clear for both no documents and processing documents.

If any item fails, fix component and rerun `cd frontend && npm run build`.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add frontend/src/components/StudyAgentPanel.tsx
git commit -m "feat: add study agent workbench panel"
```

Expected: commit succeeds with only `StudyAgentPanel.tsx` staged.

---

### Task 4: App Integration

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Import the panel**

Add this import to `frontend/src/App.tsx`:

```ts
import StudyAgentPanel from "./components/StudyAgentPanel";
```

- [ ] **Step 2: Render the panel in the selected document detail stack**

In `frontend/src/App.tsx`, render `StudyAgentPanel` after `JobDetailPage` and before the existing `study-columns` block:

```tsx
          <StudyAgentPanel
            apiClient={apiClient}
            documents={documents}
            selectedDocumentId={selectedDocumentId}
            onSelectDocument={setSelectedDocumentId}
            onAuthExpired={handleLogout}
          />
```

The surrounding section should remain:

```tsx
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
```

- [ ] **Step 3: Run the frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 4: Spec review for Task 4**

Check manually:

- Study Agent panel appears in the existing authenticated workspace.
- Existing Documents, Job, Outline, Questions, and Review Tasks flows remain present.
- Panel receives authenticated `ApiClient` from existing app state.

If any item fails, fix `frontend/src/App.tsx` and rerun `cd frontend && npm run build`.

- [ ] **Step 5: Quality review for Task 4**

Check manually:

- App integration does not duplicate API state or auth state.
- Logout/session behavior remains centralized in `handleLogout`.
- No existing workflow props are removed.

If any item fails, fix `frontend/src/App.tsx` and rerun `cd frontend && npm run build`.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add frontend/src/App.tsx
git commit -m "feat: surface study agent in workspace"
```

Expected: commit succeeds with only `App.tsx` staged.

---

### Task 5: Styling, Verification, And Docs Sync

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `README.md`
- Modify: `SPEC.md`

- [ ] **Step 1: Add Study Agent styles**

Append these styles to `frontend/src/styles.css` before the media queries:

```css
.study-agent-panel {
  border: 1px solid #d9e0ea;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgb(20 32 48 / 5%);
  padding: 18px;
}

.study-agent-form {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

.study-agent-form label {
  display: grid;
  gap: 7px;
  color: #344256;
  font-size: 0.88rem;
  font-weight: 700;
}

.study-agent-form input,
.study-agent-form select,
.study-agent-form textarea {
  min-width: 0;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  color: #18212f;
}

.study-agent-form textarea {
  resize: vertical;
  line-height: 1.5;
}

.document-checklist {
  min-width: 0;
  margin: 0;
  padding: 12px;
  border: 1px solid #e1e7ef;
  border-radius: 8px;
}

.document-checklist legend {
  padding: 0 6px;
  color: #344256;
  font-size: 0.88rem;
  font-weight: 800;
}

.document-checklist > div {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.document-checklist label {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 1px solid #edf1f6;
  border-radius: 6px;
  background: #f8fafc;
}

.document-checklist input[type="checkbox"] {
  width: auto;
  min-width: 16px;
}

.document-checklist span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.agent-control-grid,
.agent-trace {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.study-agent-result {
  display: grid;
  gap: 12px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #edf1f6;
}

.agent-answer {
  padding: 12px;
  border: 1px solid #e1e7ef;
  border-radius: 8px;
  background: #f8fafc;
}

.evidence-viewer {
  display: grid;
  gap: 12px;
}

.agent-trace {
  margin: 0;
}

.agent-trace div {
  min-width: 0;
  padding: 10px;
  border: 1px solid #e1e7ef;
  border-radius: 8px;
  background: #f8fafc;
}

.agent-reason,
.agent-issues {
  display: grid;
  gap: 6px;
  margin: 0;
  color: #344256;
  line-height: 1.45;
}

.agent-reason span,
.agent-issues li {
  color: #5b6678;
}

.agent-issues {
  padding-left: 18px;
}

.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.citation-pill {
  display: inline-flex;
  max-width: 100%;
  min-height: 26px;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf1f6;
  color: #344256;
  font-size: 0.78rem;
  font-weight: 800;
  overflow-wrap: anywhere;
}

.evidence-list {
  display: grid;
  gap: 10px;
}

.evidence-item {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid #e1e7ef;
  border-radius: 8px;
  background: #ffffff;
}

.evidence-heading {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #263548;
}

.evidence-item p,
.evidence-item code {
  margin: 0;
  overflow-wrap: anywhere;
  line-height: 1.45;
}

.evidence-item p {
  color: #4d596b;
}

.evidence-item code {
  color: #5b6678;
  font-size: 0.78rem;
}
```

Inside the existing `@media (max-width: 720px)` block, add `.document-checklist > div`, `.agent-control-grid`, and `.agent-trace` to the one-column rule:

```css
  .upload-controls,
  .upload-row,
  .stage-item,
  .review-list li,
  .document-checklist > div,
  .agent-control-grid,
  .agent-trace {
    grid-template-columns: 1fr;
  }
```

- [ ] **Step 2: Update README**

In `README.md`, under the current Study Agent status note, add:

```markdown
The frontend workbench includes a Study Agent panel for one or more ready documents, grounded answer/question/note generation, citation display, confidence, and review status.
```

- [ ] **Step 3: Update SPEC**

In `SPEC.md`, near the Study Agent document evidence bullet, add:

```markdown
- Study Agent frontend workbench: authenticated users can select one or more ready documents, query the Study Agent, and inspect generated content, citations, evidence, retrieval mode, confidence, and review status from the web UI.
```

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 5: Run focused backend API tests**

Run:

```bash
pytest tests/test_study_agent_api.py tests/test_study_agent_runtime.py -q
```

Expected: PASS.

- [ ] **Step 6: Final spec review**

Check Phase 1 acceptance criteria:

- A signed-in user can select one or more ready documents and ask from the frontend.
- UI shows answer content, citations, mode, confidence, and review status.
- Product errors are shown as user-facing error messages.
- Existing document upload, job status, outline, questions, feedback, export, and review tasks remain in `App.tsx`.
- `cd frontend && npm run build` passes.

If any criterion lacks code evidence, fix the relevant frontend file and rerun Steps 4 and 5.

- [ ] **Step 7: Final quality review**

Check manually:

- UI remains workbench-like and compact.
- Text wraps in buttons, citations, evidence snippets, and mobile layouts.
- Ready-document checkboxes stay compact and do not inherit full-width text-input sizing.
- No nested cards are introduced beyond existing panel/tool surfaces.
- No new dependency is added.
- API client still uses authenticated headers and does not send identity fields.

If any item fails, fix and rerun Steps 4 and 5.

- [ ] **Step 8: Commit Task 5**

Run:

```bash
git add frontend/src/styles.css README.md SPEC.md
git commit -m "docs: document study agent frontend workbench"
```

Expected: commit succeeds with only styles and docs staged.

---

## Completion Criteria

The Phase 1 implementation is complete only when all of these are true:

- Every task checkbox is complete.
- Each task has passed both spec review and quality review.
- `cd frontend && npm run build` passes.
- `pytest tests/test_study_agent_api.py tests/test_study_agent_runtime.py -q` passes.
- Existing upload, job, outline, questions, feedback, export, and review task UI remain present in `frontend/src/App.tsx`.
- The Study Agent panel sends no identity fields in JSON and relies on `ApiClient` auth headers.
- The working tree contains only intended Phase 1 changes before final landing.
