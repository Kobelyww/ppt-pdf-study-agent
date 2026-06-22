import type { Difficulty, StudyDocument } from "../App";

interface QuestionsPageProps {
  document: StudyDocument;
}

const difficultyLabels: Record<Difficulty, string> = {
  Easy: "Easy",
  Medium: "Medium",
  Hard: "Hard"
};

function QuestionsPage({ document }: QuestionsPageProps) {
  return (
    <section className="questions-panel" aria-labelledby="questions-title">
      <div className="panel-header compact">
        <div>
          <h2 id="questions-title">Questions</h2>
          <p>Review prompts with answers, explanations, and difficulty labels.</p>
        </div>
      </div>

      {document.questions.length === 0 ? (
        <div className="empty-state">
          <strong>No questions available</strong>
          <span>Question generation starts after parsing and outline generation complete.</span>
        </div>
      ) : (
        <div className="question-list">
          {document.questions.map((question) => (
            <article className="question-item" key={question.id}>
              <div className="question-heading">
                <h3>{question.prompt}</h3>
                <span className={`difficulty difficulty-${question.difficulty.toLowerCase()}`}>
                  {difficultyLabels[question.difficulty]}
                </span>
              </div>
              <dl>
                <div>
                  <dt>Answer</dt>
                  <dd>{question.answer}</dd>
                </div>
                <div>
                  <dt>Explanation</dt>
                  <dd>{question.explanation}</dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>{question.source}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export default QuestionsPage;
