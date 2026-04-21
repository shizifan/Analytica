import { Icon } from './Icon';
import type { EmployeeSummary } from '../../types';
import type { FAQ } from '../../data/employeeFaq';

interface Props {
  employee: EmployeeSummary | null;
  faqs: FAQ[];
  onPick(question: string): void;
  disabled?: boolean;
}

function initials(name: string): string {
  if (!name) return 'AN';
  const trimmed = name.trim();
  if (!trimmed) return 'AN';
  // Chinese names: take first 2 chars; otherwise take up to 2 uppercase letters.
  if (/[\u4e00-\u9fa5]/.test(trimmed)) return trimmed.slice(0, 2);
  const words = trimmed.split(/\s+/).slice(0, 2);
  return words.map((w) => w[0]?.toUpperCase() ?? '').join('') || 'AN';
}

export function EmptyHero({ employee, faqs, onPick, disabled }: Props) {
  const halo = employee ? initials(employee.name) : 'AN';
  return (
    <div className="an-empty-hero">
      <div className="an-halo">{halo}</div>
      <h2>{employee?.name ?? 'Analytica · 多维能动决策智能体'}</h2>
      <p>
        {employee?.description ??
          '输入分析需求，或从下方常见问题开始。感知、规划、执行、反思全流程在右侧 Agent Inspector 实时可视。'}
      </p>
      {faqs.length > 0 && (
        <div className="an-faq-section">
          <div className="an-faq-label">
            <span className="an-left">
              <Icon name="sparkles" size={12} /> 常见问题 · FAQ
            </span>
            <span className="an-mono" style={{ fontSize: 10 }}>
              {faqs.length} 个问题
            </span>
          </div>
          <div className="an-faq-grid">
            {faqs.map((faq) => (
              <button
                key={faq.id}
                type="button"
                className="an-faq-card"
                onClick={() => onPick(faq.question)}
                disabled={disabled}
              >
                <span className="an-faq-q">{faq.question}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
