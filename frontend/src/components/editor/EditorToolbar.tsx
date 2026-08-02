import React from 'react';
import {
  Check, History, Loader2, Maximize2, Minimize2, Plus, Redo2, Search, Trash2, Undo2, X,
} from 'lucide-react';
import { DraftState, EditorTab } from '../../stores/documentEditor';

interface Props {
  rowCount: number;
  totalCount: number;
  workCount: number;
  materialCount: number;
  showTabs: boolean;
  tab: EditorTab;
  search: string;
  selectedCount: number;
  canWrite: boolean;
  isDirty: boolean;
  applying: boolean;
  draftState: DraftState;
  canUndo: boolean;
  canRedo: boolean;
  fullscreen: boolean;
  historyOpen: boolean;
  onTabChange: (tab: EditorTab) => void;
  onSearchChange: (value: string) => void;
  onUndo: () => void;
  onRedo: () => void;
  onApply: () => void;
  onDiscard: () => void;
  onAddRow: () => void;
  onDeleteSelected: () => void;
  onToggleFullscreen: () => void;
  onToggleHistory: () => void;
}

const DRAFT_LABEL: Record<DraftState, string> = {
  idle: '',
  saving: 'Сохраняю черновик…',
  saved: 'Черновик сохранён',
  error: 'Черновик не сохранён',
};

export const EditorToolbar: React.FC<Props> = ({
  rowCount, totalCount, workCount, materialCount, showTabs, tab, search,
  selectedCount, canWrite, isDirty, applying, draftState, canUndo, canRedo,
  fullscreen, historyOpen, onTabChange, onSearchChange, onUndo, onRedo,
  onApply, onDiscard, onAddRow, onDeleteSelected, onToggleFullscreen, onToggleHistory,
}) => (
  <div className="de-toolbar">
    {showTabs && (
      <div className="de-tabs" role="tablist">
        {([
          { id: 'all' as const, label: 'Все', count: totalCount },
          { id: 'works' as const, label: 'Работы', count: workCount },
          { id: 'materials' as const, label: 'Материалы', count: materialCount },
        ]).map(({ id, label, count }) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={`de-tab${tab === id ? ' de-tab-active' : ''}`}
            onClick={() => onTabChange(id)}
          >
            {label}
            {count > 0 && <span className="de-tab-count">{count}</span>}
          </button>
        ))}
      </div>
    )}

    <div className="de-toolbar-row">
      <span className="de-row-count">Строк: {rowCount}</span>

      <div className="de-search">
        <Search size={14} className="de-search-icon" />
        <input
          className="de-search-input"
          placeholder="Поиск по наименованию…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        {search && (
          <button className="de-search-clear" onClick={() => onSearchChange('')} title="Очистить">
            <X size={12} />
          </button>
        )}
      </div>

      <div className="de-toolbar-actions">
        {selectedCount > 0 && (
          <span className="de-selected-count">Выбрано: {selectedCount}</span>
        )}

        {canWrite && (
          <>
            <button
              className="de-icon-btn" onClick={onAddRow} title="Добавить строку"
            >
              <Plus size={14} />
            </button>
            <button
              className="de-icon-btn de-icon-btn-danger"
              onClick={onDeleteSelected}
              disabled={selectedCount === 0}
              title="Удалить выбранные строки"
            >
              <Trash2 size={14} />
            </button>
            <span className="de-divider" />
            <button className="de-icon-btn" onClick={onUndo} disabled={!canUndo} title="Отменить (Ctrl+Z)">
              <Undo2 size={14} />
            </button>
            <button className="de-icon-btn" onClick={onRedo} disabled={!canRedo} title="Повторить (Ctrl+Y)">
              <Redo2 size={14} />
            </button>
          </>
        )}

        <button
          className={`de-icon-btn${historyOpen ? ' de-icon-btn-active' : ''}`}
          onClick={onToggleHistory}
          title="История правок"
        >
          <History size={14} />
        </button>
        <button
          className="de-icon-btn"
          onClick={onToggleFullscreen}
          title={fullscreen ? 'Свернуть' : 'Открыть на весь экран'}
        >
          {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>

        {canWrite && (
          <>
            {draftState !== 'idle' && (
              <span className={`de-draft-state de-draft-${draftState}`}>
                {DRAFT_LABEL[draftState]}
              </span>
            )}
            {isDirty && (
              <button className="de-btn-ghost" onClick={onDiscard} disabled={applying}>
                Отменить правки
              </button>
            )}
            <button
              className="de-btn-primary"
              onClick={onApply}
              disabled={!isDirty || applying}
              title={!isDirty ? 'Нет непринятых правок' : 'Записать правки в документ'}
            >
              {applying
                ? <><Loader2 size={14} className="de-spin" /> Применяю…</>
                : <><Check size={14} /> Применить</>}
            </button>
          </>
        )}
      </div>
    </div>
  </div>
);

export default EditorToolbar;
