import { useCallback, useState } from 'react';

import { DocumentMeta } from '../../api/documents';
import { getVersion } from '../../api/estimateVersions';
import {
  EstimateVersionFull,
  OptimizationProposal,
  OptimizationStep,
} from '../../types';
import OptimizationToolbar, { AbcBreakdown } from '../estimate/OptimizationToolbar';
import OptimizationProposalsPanel from '../estimate/OptimizationProposalsPanel';
import { toVersionSummary } from './EditorVersionPanel';

/**
 * Шаги оптимизации и предложения ИИ — внутри редактора.
 *
 * Раньше жили на отдельной странице и были не видны, когда смету открывали из
 * карточки. Теперь идут вместе с таблицей: шаг создаёт новую версию, редактор
 * сразу на неё переключается, а предложения показываются рядом со строками,
 * к которым относятся.
 */

interface Props {
  meta: DocumentMeta;
  /** Перечитать документ на указанной версии — после шага или применения. */
  onVersionCreated: (versionId: string) => void;
}

interface PanelState {
  proposals: OptimizationProposal[];
  step: OptimizationStep;
  versionId: string;
  abcBreakdown?: AbcBreakdown;
  autoApplied?: boolean;
}

interface StepBanner {
  step: OptimizationStep;
  count: number;
}

function bannerText({ step, count }: StepBanner): string {
  if (step === 'fill_prices') {
    return count > 0
      ? `Цены проставлены для ${count} позиций.`
      : 'По всем позициям цены проставлены. Дополнительного поиска не требуется.';
  }
  return count > 0
    ? `${count} предложений применено автоматически. Добавленные позиции выделены цветом в смете.`
    : 'Смета соответствует нормативам, предложений нет.';
}

export const OptimizationPanel: React.FC<Props> = ({ meta, onVersionCreated }) => {
  const [panel, setPanel] = useState<PanelState | null>(null);
  const [banner, setBanner] = useState<StepBanner | null>(null);

  const versions = meta.versions
    .filter((v) => !v.is_rolled_back)
    .map((v) => toVersionSummary(meta, v));

  const handleStepComplete = useCallback(
    (
      newVersionId: string,
      proposals: OptimizationProposal[],
      step: OptimizationStep,
      _abc?: AbcBreakdown,
    ) => {
      setPanel(null);
      setBanner({ step, count: proposals.length });
      onVersionCreated(newVersionId);
    },
    [onVersionCreated],
  );

  const handleViewStep = useCallback(
    async (versionId: string, step: OptimizationStep) => {
      onVersionCreated(versionId);
      if (step === 'fill_prices') return;
      try {
        const full = await getVersion(meta.task_id, versionId);
        setPanel({
          proposals: full.optimization_proposals ?? [],
          step, versionId, autoApplied: true,
        });
      } catch {
        // Предложения — справка к шагу: без них версия всё равно открылась.
      }
    },
    [meta.task_id, onVersionCreated],
  );

  const handleProposalsApplied = useCallback(
    (newVersion: EstimateVersionFull) => {
      setPanel(null);
      onVersionCreated(newVersion.id);
    },
    [onVersionCreated],
  );

  return (
    <div className="de-optimization">
      <OptimizationToolbar
        taskId={meta.task_id}
        versions={versions}
        onStepComplete={handleStepComplete}
        onViewStep={handleViewStep}
      />

      {banner && (
        <div className="de-step-banner">
          <span>
            <strong>✓ Шаг завершён</strong> — {bannerText(banner)}
          </span>
          <button className="de-step-banner-close" onClick={() => setBanner(null)}>✕</button>
        </div>
      )}

      {panel && (
        <OptimizationProposalsPanel
          proposals={panel.proposals}
          step={panel.step}
          taskId={meta.task_id}
          versionId={panel.versionId}
          abcBreakdown={panel.abcBreakdown}
          autoApplied={panel.autoApplied}
          onProposalsApplied={handleProposalsApplied}
          onDismiss={() => setPanel(null)}
        />
      )}
    </div>
  );
};

export default OptimizationPanel;
