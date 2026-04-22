import { useState } from 'react';
import { Icon } from './Icon';
import { api } from '../../api/client';
import type { TaskResult, TaskResultFile } from '../../types';

interface Props {
  primary: TaskResult;
}

type ExportFormat = 'docx' | 'pptx';

function formatSize(bytes?: number | null): string | null {
  if (!bytes || bytes <= 0) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function durationLabel(ms?: number): string | null {
  if (!ms || ms <= 0) return null;
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Phase 5 — render a persisted report artifact (HTML / DOCX / PPTX / MD).
 *
 * Contract: the task's `data` must be a TaskResultFile with an
 * `artifact_id` referencing a row in `report_artifacts`. If
 * `artifact_id` is null the artifact failed to persist — surface a
 * degraded card with no download, just the format badge.
 */
export function FileResultCard({ primary }: Props) {
  const file = (primary.data as TaskResultFile | null) ?? null;
  const artifactId = file?.artifact_id ?? null;
  const format = (file?.format ?? 'FILE').toUpperCase();
  const title = file?.title || primary.name;

  // On-demand conversion state: only exposed for HTML source artifacts.
  const [converting, setConverting] = useState<ExportFormat | null>(null);
  const [converted, setConverted] = useState<Record<ExportFormat, string | undefined>>({
    docx: undefined,
    pptx: undefined,
  });
  const [convertError, setConvertError] = useState<string | null>(null);

  // HTML / MD can preview inline; binary formats (DOCX/PPTX) must
  // download through the browser native viewer.
  const canPreview = format === 'HTML' || format === 'MD' || format === 'MARKDOWN';
  const canConvert = format === 'HTML' && !!artifactId;

  const metaBits: string[] = [];
  metaBits.push(format);
  const size = formatSize(file?.size_bytes);
  if (size) metaBits.push(size);
  const duration = durationLabel(primary.duration_ms);
  if (duration) metaBits.push(duration);
  if (primary.skill) metaBits.push(primary.skill);

  const downloadUrl = artifactId ? `/api/reports/${artifactId}/download` : null;
  const previewUrl = artifactId ? `/api/reports/${artifactId}/preview` : null;

  const handleDownload = () => {
    if (!downloadUrl) return;
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.target = '_blank';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handlePreview = () => {
    if (!previewUrl) return;
    window.open(previewUrl, '_blank', 'noopener');
  };

  const handleConvert = async (fmt: ExportFormat) => {
    if (!artifactId || converting) return;
    setConvertError(null);
    setConverting(fmt);
    try {
      const { artifact_id: newId } = await api.convertReport(artifactId, fmt);
      setConverted((m) => ({ ...m, [fmt]: newId }));
      // Immediately trigger download — that's the user's intent.
      const a = document.createElement('a');
      a.href = `/api/reports/${newId}/download`;
      a.target = '_blank';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setConvertError(msg);
    } finally {
      setConverting(null);
    }
  };

  const handleDownloadConverted = (fmt: ExportFormat) => {
    const id = converted[fmt];
    if (!id) return;
    const a = document.createElement('a');
    a.href = `/api/reports/${id}/download`;
    a.target = '_blank';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className="an-result-card">
      <div className="an-result-head">
        <div className="an-result-title">
          <div className="an-result-name" title={title}>{title}</div>
          <div className="an-result-meta">
            {metaBits.map((bit, i) => (
              <span
                key={i}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                {i > 0 && <span className="sep" />}
                <span>{bit}</span>
              </span>
            ))}
          </div>
        </div>
        <span className={`an-file-badge fmt-${format.toLowerCase()}`}>
          {format}
        </span>
      </div>

      <div className="an-result-body">
        {artifactId ? (
          <div className="an-file-hint">
            已生成 <strong>{format}</strong> 文件
            {size ? `，${size}` : ''}。
            {canConvert
              ? '可直接预览、下载，或按需生成 DOCX / PPTX 版本。'
              : canPreview
                ? '可直接预览或下载到本地。'
                : '请下载后使用 Office / 浏览器打开。'}
            {convertError && (
              <div
                style={{
                  marginTop: 8,
                  color: 'var(--an-err)',
                  fontSize: 11,
                  fontFamily: 'var(--an-font-mono)',
                }}
              >
                转换失败：{convertError}
              </div>
            )}
          </div>
        ) : (
          <div className="an-file-hint an-file-hint-error">
            文件已生成但未能持久化到存储卷，无法下载。请检查后端日志。
          </div>
        )}
      </div>

      {artifactId && (
        <div className="an-result-footer">
          {canPreview && (
            <button type="button" className="an-btn ghost" onClick={handlePreview}>
              <Icon name="panel-left" size={12} />
              预览
            </button>
          )}
          <button type="button" className="an-btn primary" onClick={handleDownload}>
            <Icon name="check" size={12} />
            下载 {format}
          </button>

          {canConvert && (
            <>
              <span
                aria-hidden
                style={{
                  width: 1,
                  alignSelf: 'stretch',
                  background: 'var(--an-border)',
                  margin: '0 2px',
                }}
              />
              {(['docx', 'pptx'] as const).map((fmt) => {
                const label = fmt.toUpperCase();
                const already = converted[fmt];
                const busy = converting === fmt;
                if (already) {
                  return (
                    <button
                      key={fmt}
                      type="button"
                      className="an-btn"
                      onClick={() => handleDownloadConverted(fmt)}
                      title={`再次下载 ${label}`}
                    >
                      <Icon name="check" size={12} />
                      再次下载 {label}
                    </button>
                  );
                }
                return (
                  <button
                    key={fmt}
                    type="button"
                    className="an-btn"
                    onClick={() => handleConvert(fmt)}
                    disabled={busy || converting !== null}
                    title={`生成并下载 ${label}`}
                  >
                    {busy ? (
                      <span className="an-spinner" style={{ width: 10, height: 10 }} />
                    ) : null}
                    {busy ? `生成中…` : `生成 ${label}`}
                  </button>
                );
              })}
            </>
          )}
        </div>
      )}
    </div>
  );
}
