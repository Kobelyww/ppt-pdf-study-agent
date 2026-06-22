import { useMemo, useState } from "react";
import DocumentsPage from "./pages/DocumentsPage";
import JobDetailPage from "./pages/JobDetailPage";
import OutlinePage from "./pages/OutlinePage";
import QuestionsPage from "./pages/QuestionsPage";

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ProcessingStageStatus = "done" | "active" | "pending" | "blocked";
export type Difficulty = "Easy" | "Medium" | "Hard";

export interface ProcessingStage {
  id: string;
  label: string;
  status: ProcessingStageStatus;
  detail: string;
}

export interface StudyQuestion {
  id: string;
  prompt: string;
  answer: string;
  explanation: string;
  difficulty: Difficulty;
  source: string;
}

export interface StudyDocument {
  id: string;
  title: string;
  type: "PDF" | "PPTX";
  pages: number;
  uploadedAt: string;
  owner: string;
  status: JobStatus;
  progress: number;
  activePhase: string;
  summary: string;
  outline: string[];
  stages: ProcessingStage[];
  questions: StudyQuestion[];
}

const documents: StudyDocument[] = [
  {
    id: "doc-transformers",
    title: "Transformer Architecture Seminar.pdf",
    type: "PDF",
    pages: 42,
    uploadedAt: "2026-06-15 09:24",
    owner: "Study Group A",
    status: "running",
    progress: 68,
    activePhase: "Generating retrieval-grounded questions",
    summary: "Lecture notes covering attention, positional encodings, encoder-decoder stacks, and training dynamics.",
    outline: [
      "# Transformer Architecture Seminar",
      "## 1. Motivation",
      "- Replaces recurrent sequence processing with parallel attention.",
      "- Improves long-range dependency modeling for translation and summarization.",
      "## 2. Scaled Dot-Product Attention",
      "- Query, key, and value projections are compared with normalized dot products.",
      "- Multi-head attention lets the model track syntax, position, and entity relations.",
      "## 3. Positional Encoding",
      "- Fixed sinusoidal features inject token order without recurrence.",
      "- Learned embeddings can adapt position signals to task-specific corpora.",
      "## 4. Encoder and Decoder Blocks",
      "- Residual connections stabilize deep stacked layers.",
      "- Masked self-attention prevents leakage during autoregressive decoding."
    ],
    stages: [
      { id: "parse", label: "Parse document", status: "done", detail: "Extracted text, slide titles, and figure captions." },
      { id: "understand", label: "Understand content", status: "done", detail: "Identified 18 concepts and 31 supporting claims." },
      { id: "outline", label: "Build outline", status: "done", detail: "Created section hierarchy with source page anchors." },
      { id: "questions", label: "Generate questions", status: "active", detail: "Drafting mixed difficulty questions from the attention chapter." },
      { id: "review", label: "Quality review", status: "pending", detail: "Awaiting answer consistency and citation checks." }
    ],
    questions: [
      {
        id: "q1",
        prompt: "Why does scaled dot-product attention divide by the square root of the key dimension?",
        answer: "It keeps attention logits in a stable range as vector dimensions grow.",
        explanation: "Without scaling, large dot products can push softmax into saturated regions, making gradients small and training less stable.",
        difficulty: "Medium",
        source: "Section 2"
      },
      {
        id: "q2",
        prompt: "What problem does masked self-attention solve in a decoder?",
        answer: "It prevents the decoder from attending to future tokens during training.",
        explanation: "The model must generate one token at a time, so masking preserves the same information boundary used at inference.",
        difficulty: "Easy",
        source: "Section 4"
      }
    ]
  },
  {
    id: "doc-rag",
    title: "RAG Evaluation Workshop.pptx",
    type: "PPTX",
    pages: 28,
    uploadedAt: "2026-06-14 17:10",
    owner: "Research Ops",
    status: "completed",
    progress: 100,
    activePhase: "Ready for study",
    summary: "Workshop deck about retrieval metrics, judge calibration, answer faithfulness, and regression sets.",
    outline: [
      "# RAG Evaluation Workshop",
      "## 1. Retrieval Quality",
      "- Recall@k measures whether the right evidence entered the context window.",
      "- MRR rewards systems that rank useful passages earlier.",
      "## 2. Generation Quality",
      "- Faithfulness checks whether answers are supported by retrieved evidence.",
      "- Completeness checks whether the answer covers required facts.",
      "## 3. Regression Practice",
      "- Fixed eval sets catch model and prompt drift.",
      "- Human spot checks remain necessary for ambiguous failures."
    ],
    stages: [
      { id: "parse", label: "Parse document", status: "done", detail: "Read 28 slides and presenter notes." },
      { id: "understand", label: "Understand content", status: "done", detail: "Mapped evaluation concepts into a compact knowledge graph." },
      { id: "outline", label: "Build outline", status: "done", detail: "Created three-section study outline." },
      { id: "questions", label: "Generate questions", status: "done", detail: "Generated 14 review questions." },
      { id: "review", label: "Quality review", status: "done", detail: "All answers include evidence references." }
    ],
    questions: [
      {
        id: "q3",
        prompt: "How are Recall@k and MRR different?",
        answer: "Recall@k asks whether relevant evidence appears in the top k results; MRR also rewards placing it earlier.",
        explanation: "A system can have good recall but still bury the best passage. MRR captures that ranking quality.",
        difficulty: "Medium",
        source: "Slide 8"
      },
      {
        id: "q4",
        prompt: "Why should RAG systems use fixed regression sets?",
        answer: "They make quality drift visible after model, prompt, or retrieval changes.",
        explanation: "A fixed set gives repeatable comparisons, so teams can distinguish real improvements from random variation.",
        difficulty: "Easy",
        source: "Slide 21"
      }
    ]
  },
  {
    id: "doc-failed",
    title: "Scanned Lecture Notes.pdf",
    type: "PDF",
    pages: 16,
    uploadedAt: "2026-06-13 11:02",
    owner: "Personal",
    status: "failed",
    progress: 32,
    activePhase: "OCR extraction failed",
    summary: "Low-resolution scanned notes need a cleaner source before outline and question generation.",
    outline: ["# Scanned Lecture Notes", "## Extraction unavailable", "- Upload a higher quality PDF or image set to continue."],
    stages: [
      { id: "parse", label: "Parse document", status: "blocked", detail: "OCR confidence fell below the minimum threshold." },
      { id: "understand", label: "Understand content", status: "pending", detail: "Waiting for readable source text." },
      { id: "outline", label: "Build outline", status: "pending", detail: "Not started." },
      { id: "questions", label: "Generate questions", status: "pending", detail: "Not started." }
    ],
    questions: []
  }
];

function App() {
  const [selectedDocumentId, setSelectedDocumentId] = useState(documents[0].id);
  const selectedDocument = useMemo(
    () => documents.find((document) => document.id === selectedDocumentId) ?? documents[0],
    [selectedDocumentId]
  );
  const runningCount = documents.filter((document) => document.status === "running").length;
  const questionCount = documents.reduce((total, document) => total + document.questions.length, 0);

  return (
    <main className="app-shell">
      <section className="workspace-header" aria-labelledby="workspace-title">
        <div>
          <p className="eyebrow">Document Workspace</p>
          <h1 id="workspace-title">PPT PDF Study Agent</h1>
          <p className="workspace-summary">Convert study materials into outlines, progress-tracked jobs, and review questions.</p>
        </div>
        <div className="workspace-metrics" aria-label="Workspace metrics">
          <span><strong>{documents.length}</strong> documents</span>
          <span><strong>{runningCount}</strong> running</span>
          <span><strong>{questionCount}</strong> questions</span>
        </div>
      </section>

      <div className="workspace-grid">
        <DocumentsPage
          documents={documents}
          selectedDocumentId={selectedDocument.id}
          onSelectDocument={setSelectedDocumentId}
        />

        <section className="detail-stack" aria-label="Selected document study workspace">
          <JobDetailPage document={selectedDocument} />
          <div className="study-columns">
            <OutlinePage document={selectedDocument} />
            <QuestionsPage document={selectedDocument} />
          </div>
        </section>
      </div>
    </main>
  );
}

export default App;
