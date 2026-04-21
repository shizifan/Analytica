import { useTweakStore } from '../../lib/tweaks';
import type { TweakAccent, TweakDensity, TweakLayout, TweakTheme } from '../../lib/tweaks';

interface Props {
  open: boolean;
  onClose(): void;
}

const THEMES: TweakTheme[] = ['light', 'dark'];
const DENSITIES: TweakDensity[] = ['compact', 'comfortable', 'spacious'];
const ACCENTS: TweakAccent[] = ['teal', 'violet', 'amber', 'green'];
const LAYOUTS: TweakLayout[] = ['three-pane', 'two-pane', 'focus'];

const LABEL: Record<string, string> = {
  light: '浅色',
  dark: '深色',
  compact: '紧凑',
  comfortable: '常规',
  spacious: '宽松',
  teal: '青',
  violet: '紫',
  amber: '琥珀',
  green: '绿',
  'three-pane': '三栏',
  'two-pane': '双栏',
  focus: '专注',
};

function Group<T extends string>({
  label,
  choices,
  current,
  onChange,
}: {
  label: string;
  choices: readonly T[];
  current: T;
  onChange(v: T): void;
}) {
  return (
    <div className="an-tweaks-group">
      <h4>{label}</h4>
      <div className="an-tweaks-choices">
        {choices.map((c) => (
          <button
            key={c}
            type="button"
            className={`an-tweaks-choice${c === current ? ' active' : ''}`}
            onClick={() => onChange(c)}
          >
            {LABEL[c] ?? c}
          </button>
        ))}
      </div>
    </div>
  );
}

export function TweaksPanel({ open, onClose }: Props) {
  const { theme, density, accent, layout, setTheme, setDensity, setAccent, setLayout } =
    useTweakStore();
  if (!open) return null;
  return (
    <>
      <div className="an-tweaks-overlay" onClick={onClose} aria-hidden />
      <div className="an-tweaks-panel" role="dialog" aria-label="视觉设置">
        <Group label="主题" choices={THEMES} current={theme} onChange={setTheme} />
        <Group label="密度" choices={DENSITIES} current={density} onChange={setDensity} />
        <Group label="强调色" choices={ACCENTS} current={accent} onChange={setAccent} />
        <Group label="布局" choices={LAYOUTS} current={layout} onChange={setLayout} />
      </div>
    </>
  );
}
