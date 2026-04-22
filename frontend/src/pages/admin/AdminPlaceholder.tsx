import { AdminListShell } from '../../components/ui/admin/AdminListShell';

interface Props {
  title: string;
  hint?: string;
}

/** Stub for admin modules 6b–6f that haven't landed yet. */
export function AdminPlaceholder({ title, hint }: Props) {
  return (
    <AdminListShell title={title}>
      <div className="an-thinking-empty" style={{ padding: '48px 24px' }}>
        该模块尚未接入。
        {hint && (
          <>
            <br />
            <span className="an-mono" style={{ fontSize: 11, color: 'var(--an-ink-5)' }}>
              {hint}
            </span>
          </>
        )}
      </div>
    </AdminListShell>
  );
}
