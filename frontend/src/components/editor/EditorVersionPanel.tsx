import { useCallback, useMemo } from 'react';

import { DocumentMeta } from '../../api/documents';
import { EstimateVersionSummary } from '../../types';
import VersionTabs from '../estimate/VersionTabs';
import EstimateComparison from '../estimate/EstimateComparison';

/**
 * Вкладки версий и сравнение — внутри редактора, а не вокруг него.
 *
 * Раньше вкладки жили на отдельной странице оптимизации и прятались, когда
 * редактор открывали из карточки: человек не видел, что версий несколько, и
 * правил не ту (решение пользователя 11 — «видны всегда»).
 *
 * Сами вкладки переиспользуются как есть: переименование, откат и выгрузка
 * версии там уже написаны и работают.
 */

interface Props {
  meta: DocumentMeta;
  /** Открытая версия; отличается от активной, когда переключились вкладкой. */
  versionId: string | null;
  comparing: boolean;
  /** Правки не приняты — переключение версии их бы спрятало, спрашиваем. */
  isDirty: boolean;
  onSelectVersion: (versionId: string) => void;
  onToggleComparison: (comparing: boolean) => void;
  onVersionsChange: () => void;
}

const SWITCH_WARNING =
  'Есть непринятые правки. Они сохранены как черновик этой версии и не потеряются, '
  + 'но на другой вкладке вы их не увидите. Переключить версию?';

/** Метаданные версии редактора → форма, которую понимают вкладки и сравнение. */
export function toVersionSummary(
  meta: DocumentMeta, version: DocumentMeta['versions'][number],
): EstimateVersionSummary {
  return {
    id: version.id,
    task_id: meta.task_id,
    version_number: version.version_number,
    version_label: version.version_label,
    version_display_name: version.version_display_name,
    overhead_pct: version.overhead_pct,
    transport_pct: version.transport_pct,
    contingency_pct: version.contingency_pct,
    expenses_overridden: version.expenses_overridden,
    is_rolled_back: version.is_rolled_back,
    created_at: version.created_at,
  };
}

export const EditorVersionPanel: React.FC<Props> = ({
  meta, versionId, comparing, isDirty,
  onSelectVersion, onToggleComparison, onVersionsChange,
}) => {
  const versions = useMemo(
    () => meta.versions.filter((v) => !v.is_rolled_back).map((v) => toVersionSummary(meta, v)),
    [meta],
  );

  const guarded = useCallback((action: () => void) => {
    if (isDirty && !window.confirm(SWITCH_WARNING)) return;
    action();
  }, [isDirty]);

  if (versions.length < 2) return null;

  return (
    <div className="de-versions" data-testid="editor-version-tabs">
      <VersionTabs
        taskId={meta.task_id}
        cardId={meta.card_id}
        versions={versions}
        activeVersionId={versionId}
        activeView={comparing ? 'comparison' : 'version'}
        isOptimizationRunning={!meta.can_write}
        onSelectVersion={(id) => guarded(() => {
          onToggleComparison(false);
          onSelectVersion(id);
        })}
        onSelectComparison={() => guarded(() => onToggleComparison(true))}
        onVersionsChange={onVersionsChange}
      />
    </div>
  );
};

interface ComparisonProps {
  meta: DocumentMeta;
}

export const EditorComparison: React.FC<ComparisonProps> = ({ meta }) => {
  const versions = useMemo(
    () => meta.versions.filter((v) => !v.is_rolled_back).map((v) => toVersionSummary(meta, v)),
    [meta],
  );

  return (
    <div className="de-comparison">
      <h3 className="de-comparison-title">Сравнение версий сметы</h3>
      <EstimateComparison taskId={meta.task_id} versions={versions} />
    </div>
  );
};

export default EditorVersionPanel;
