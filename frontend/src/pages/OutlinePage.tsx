import type { StudyDocument } from "../App";

interface OutlinePageProps {
  document: StudyDocument;
}

function classifyLine(line: string) {
  if (line.startsWith("# ")) {
    return "outline-heading outline-heading-top";
  }

  if (line.startsWith("## ")) {
    return "outline-heading";
  }

  return "outline-bullet";
}

function cleanLine(line: string) {
  return line.replace(/^#{1,2}\s*/, "").replace(/^-\s*/, "");
}

function OutlinePage({ document }: OutlinePageProps) {
  return (
    <section className="outline-panel" aria-labelledby="outline-title">
      <div className="panel-header compact">
        <div>
          <h2 id="outline-title">Outline</h2>
          <p>Generated Markdown-style structure with source-aware sections.</p>
        </div>
      </div>

      <div className="outline-content">
        {document.outline.map((line, index) => (
          <p className={classifyLine(line)} key={`${document.id}-${index}`}>
            {cleanLine(line)}
          </p>
        ))}
      </div>
    </section>
  );
}

export default OutlinePage;
