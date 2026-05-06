/** ContextSummaryCard — compact summary shown above the first user message
 * of a 'continue' turn, summarizing what was learned in the previous turn.
 */

interface Props {
  previousTurnIndex: number;
  keyFindings: string[];
}

export default function ContextSummaryCard({ previousTurnIndex, keyFindings }: Props) {
  if (!keyFindings.length) return null;

  return (
    <div className="an-context-card">
      <div className="an-context-head">
        基于 R{previousTurnIndex} 分析
      </div>
      <ul className="an-context-items">
        {keyFindings.slice(0, 3).map((f, i) => (
          <li key={i}>{f}</li>
        ))}
      </ul>
    </div>
  );
}
