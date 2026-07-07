import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiClient,
  ApiError,
  type ApiDocument,
  type StudyAgentQueryPayload,
  type StudyAgentResult,
  type StudyAgentSkillPerformanceItem,
  type StudyBudget,
  type StudyRetrievalMode,
  type StudyTarget,
  getStudyAgentSkillPerformance,
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

const modeOptions: Array<
  { value: ""; label: string } | { value: StudyRetrievalMode; label: string }
> = [
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

function workflowStatusMarkerClass(status: string | null | undefined) {
  switch (status) {
    case "passed":
    case "completed":
      return "study-agent-workflow-marker-completed";
    case "pending":
      return "study-agent-workflow-marker-pending";
    case "failed":
    case "skipped":
    case "running":
      return `study-agent-workflow-marker-${status}`;
    case "needs_review":
      return "study-agent-workflow-marker-needs-review";
    default:
      return "study-agent-workflow-marker-default";
  }
}

function WorkflowTimeline({ workflow }: { workflow: StudyAgentResult["workflow"] }) {
  if (!workflow) return null;
  return (
    <div className="study-agent-workflow">
      <div className="study-agent-workflow-header">
        <span>Workflow: {workflow.status ?? "unknown"}</span>
        <span>Stage: {workflow.current_stage ?? "unknown"}</span>
        {workflow.needs_review ? (
          <span className="study-agent-policy-warning">Review</span>
        ) : null}
      </div>
      <ol>
        {workflow.stages.map((stage, index) => (
          <li key={`${stage.stage}-${stage.status}-${index}`}>
            <span
              className={`study-agent-workflow-marker ${workflowStatusMarkerClass(stage.status)}`}
              aria-hidden="true"
            />
            <span>{stage.stage}</span>
            <span>{stage.status}</span>
            {typeof stage.duration_ms === "number" ? (
              <span>{Math.round(stage.duration_ms)}ms</span>
            ) : null}
            {stage.review_reason ? <span>{stage.review_reason}</span> : null}
            {stage.error_code ? <span>{stage.error_code}</span> : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

function ReviewTaskStatus({ task }: { task: StudyAgentResult["review_task"] }) {
  if (!task) return null;
  return (
    <div className="study-agent-review-task" aria-label="Study Agent review task">
      <span>
        <strong>Review task</strong> {task.id}
      </span>
      <span>
        <strong>Status</strong> {task.status}
      </span>
      <span>
        <strong>Reason</strong> {task.reason}
      </span>
    </div>
  );
}

function SkillStatus({ skill }: { skill: StudyAgentResult["skill"] }) {
  if (!skill?.skill_name) return null;
  return (
    <div className="study-agent-skill" aria-label="Study Agent skill">
      <span>
        <strong>Skill</strong> {skill.skill_name}
      </span>
      <span>
        <strong>Version</strong> {skill.skill_version ?? "unknown"}
      </span>
    </div>
  );
}

function ExpertStatus({ expert }: { expert?: StudyAgentResult["expert"] }) {
  if (!expert) return null;
  return (
    <div className="study-agent-expert" aria-label="Study Agent expert diagnostics">
      <span>
        <strong>Experts</strong> {expert.enabled ? "enabled" : "skipped"}
      </span>
      <span>
        <strong>Branches</strong> {expert.branch_count ?? 0}
      </span>
      <span>
        <strong>Timeouts</strong> {expert.timeout_count ?? 0}
      </span>
      {expert.fallback_reason ? (
        <span className="study-agent-policy-warning">{expert.fallback_reason}</span>
      ) : null}
    </div>
  );
}

function SkillPerformanceStatus({
  item,
}: {
  item?: StudyAgentSkillPerformanceItem | null;
}) {
  if (!item) return null;
  return (
    <div className="study-agent-skill-performance" aria-label="Study Agent skill performance">
      <span>
        <strong>Review rate</strong> {Math.round(item.review_rate * 100)}%
      </span>
      <span>
        <strong>Fallback rate</strong> {Math.round(item.fallback_rate * 100)}%
      </span>
      <span>
        <strong>Expert runs</strong> {item.expert_run_count}
      </span>
    </div>
  );
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
  const [skillPerformance, setSkillPerformance] =
    useState<StudyAgentSkillPerformanceItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const hasUserEditedSelection = useRef(false);
  const readyIds = useMemo(() => new Set(ready.map((document) => document.id)), [ready]);
  const validSelectedIds = useMemo(
    () => selectedDocumentIds.filter((documentId) => readyIds.has(documentId)),
    [readyIds, selectedDocumentIds],
  );
  const hasReadySource = validSelectedIds.length > 0;
  const hasNonReadyDocuments = documents.some((document) => document.status !== "ready");
  const canSubmit = hasReadySource && query.trim().length > 0 && !isSubmitting;

  useEffect(() => {
    setSelectedDocumentIds((current) => {
      const filtered = current.filter((documentId) => readyIds.has(documentId));
      if (
        selectedDocumentId &&
        readyIds.has(selectedDocumentId) &&
        !filtered.includes(selectedDocumentId)
      ) {
        return [...filtered, selectedDocumentId];
      }
      if (filtered.length > 0) {
        return filtered.length === current.length ? current : filtered;
      }
      const nextDocumentId = hasUserEditedSelection.current ? null : ready[0]?.id;
      return nextDocumentId ? [nextDocumentId] : [];
    });
  }, [ready, readyIds, selectedDocumentId]);

  function toggleDocument(documentId: string) {
    hasUserEditedSelection.current = true;
    const isSelected = validSelectedIds.includes(documentId);
    const nextSelectedIds = isSelected
      ? validSelectedIds.filter((item) => item !== documentId)
      : [...validSelectedIds, documentId];

    setSelectedDocumentIds((current) => {
      const existing = current.filter((item) => readyIds.has(item));
      return isSelected
        ? existing.filter((item) => item !== documentId)
        : [...existing, documentId];
    });

    if (!isSelected) {
      onSelectDocument(documentId);
      return;
    }

    if (selectedDocumentId === documentId) {
      const fallbackDocumentId =
        nextSelectedIds[0] ?? ready.find((document) => document.id !== documentId)?.id ?? "";
      onSelectDocument(fallbackDocumentId);
    }
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
      const data = await queryStudyAgent(apiClient, payload);
      setResult(data);
      setSkillPerformance(null);
      const skill = data.skill ?? data.trace?.skill;
      if (skill?.skill_name) {
        try {
          const performance = await getStudyAgentSkillPerformance(
            apiClient,
            skill.skill_name,
            skill.skill_version ?? undefined,
          );
          setSkillPerformance(performance.skills[0] ?? null);
        } catch (caught) {
          if (caught instanceof ApiError && caught.status === 401) {
            onAuthExpired();
          }
          setSkillPerformance(null);
        }
      } else {
        setSkillPerformance(null);
      }
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
          <span className="status-badge status-ready">
            {validSelectedIds.length} {validSelectedIds.length === 1 ? "source" : "sources"}
          </span>
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
            <button className="primary-action" type="submit" disabled={!canSubmit}>
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
            <span
              className={`status-badge ${
                result.verification.needs_review ? "status-failed" : "status-ready"
              }`}
            >
              {result.verification.needs_review ? "Needs review" : "Passed"}
            </span>
          </div>
          {result.trace ? (
            <div className="trace-diagnostics" aria-label="Study Agent diagnostics">
              <span>
                <strong>Trace</strong> {result.trace.trace_id}
              </span>
              <span>
                <strong>Mode</strong> {result.trace.selected_mode ?? result.plan.mode}
              </span>
              <span>
                <strong>Evidence</strong> {result.trace.chunk_source ?? "unknown"}
              </span>
              <span>
                <strong>Confidence</strong> {Math.round(result.trace.confidence * 100)}%
              </span>
              <span>
                <strong>Recall</strong>{" "}
                {Math.round(result.trace.answer_term_recall * 100)}%
              </span>
              <span>
                <strong>Latency</strong> {Math.round(result.trace.latency_ms)}ms
              </span>
            </div>
          ) : null}
          {result.policy ? (
            <div className="study-agent-policy" aria-label="Study Agent policy diagnostics">
              <span>
                <strong>Policy status</strong> {result.policy.status ?? "unknown"}
              </span>
              <span>
                <strong>Mode</strong> {result.policy.selected_mode ?? "unknown"}
              </span>
              {result.policy.category ? (
                <span>
                  <strong>Category</strong> {result.policy.category}
                </span>
              ) : null}
              {result.policy.blocked_reason ? (
                <span className="study-agent-policy-warning">
                  {result.policy.blocked_reason}
                </span>
              ) : null}
            </div>
          ) : null}
          <SkillStatus skill={result.skill ?? result.trace?.skill} />
          <ExpertStatus expert={result.expert ?? result.trace?.expert} />
          <SkillPerformanceStatus item={skillPerformance} />
          {result.trace?.fallback_reason ? (
            <div className="warning-banner compact" role="status">
              Evidence index fallback: {result.trace.fallback_reason}
            </div>
          ) : null}
          <ReviewTaskStatus task={result.review_task} />
          <WorkflowTimeline workflow={result.workflow ?? result.trace?.workflow} />
          <pre className="content-block agent-answer">{result.draft.content}</pre>
          <EvidenceViewer result={result} />
        </div>
      ) : null}
    </section>
  );
}

export default StudyAgentPanel;
