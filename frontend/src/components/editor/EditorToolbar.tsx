import React from 'react';
import {
  Check, FileSpreadsheet, FoldVertical, History, Loader2, Maximize2, Minimize2, Plus,
  Redo2, Search, Trash2, Undo2, X,
} from 'lucide-react';
import { DraftState, EditorTab } from '../../stores/documentEditor';
import Hint from './Hint';

interface Props {
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
  /** Одинаковые позиции показаны одной строкой с общим объёмом. */
  collapsed: boolean;
  /** Есть ли по чему сворачивать: в файле может не быть наименования. */
  canCollapse: boolean;
  /** Сколько групп свернулось — иначе непонятно, есть ли в документе дубли. */
  groupCount: number;
  onToggleCollapsed: () => void;
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
  onExport: () => void;
}

const DRAFT_LABEL: Record<DraftState, string> = {
  idle: '',
  saving: 'Сохраняю черновик…',
  saved: 'Черновик сохранён',
  error: 'Черновик не сохранён',
};

/** Вкладки — тоже действие, и тоже объясняются при наведении. */
const TAB_HINT: Record<EditorTab, string> = {
  all: 'Показать все строки документа — и работы, и материалы',
  works: 'Оставить в таблице только работы',
  materials: 'Оставить в таблице только материалы',
};

export const EditorToolbar: React.FC<Props> = ({
  totalCount, workCount, materialCount, showTabs, tab, search,
  selectedCount, canWrite, isDirty, applying, draftState, canUndo, canRedo,
  fullscreen, historyOpen, collapsed, canCollapse, groupCount,
  onToggleCollapsed, onTabChange, onSearchChange, onUndo, onRedo,
  onApply, onDiscard, onAddRow, onDeleteSelected, onToggleFullscreen, onToggleHistory,
  onExport,
}) => (
  <div className="de-toolbar">
    <div className="de-toolbar-row">
      {showTabs && (
        <div className="de-tabs" role="tablist">
          {([
            { id: 'all' as const, label: 'Все', count: totalCount },
            { id: 'works' as const, label: 'Работы', count: workCount },
            { id: 'materials' as const, label: 'Материалы', count: materialCount },
          ]).map(({ id, label, count }) => (
            <Hint key={id} text={TAB_HINT[id]} align="start">
              <button
                role="tab"
                aria-selected={tab === id}
                className={`de-tab${tab === id ? ' de-tab-active' : ''}`}
                onClick={() => onTabChange(id)}
              >
                {label}
                {count > 0 && <span className="de-tab-count">{count}</span>}
              </button>
            </Hint>
          ))}
        </div>
      )}

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
            <Hint text="Добавить пустую строку после выделенной, а без выделения — в конец таблицы">
              <button className="de-icon-btn" onClick={onAddRow} aria-label="Добавить строку">
                <Plus size={14} />
              </button>
            </Hint>
            <Hint
              text={selectedCount === 0
                ? 'Удалить строки: сначала отметьте их галочками слева'
                : `Удалить отмеченные строки (${selectedCount}) вместе с их материалами`}
            >
              <button
                className="de-icon-btn de-icon-btn-danger"
                onClick={onDeleteSelected}
                disabled={selectedCount === 0}
                aria-label="Удалить выбранные строки"
              >
                <Trash2 size={14} />
              </button>
            </Hint>
            <span className="de-divider" />
            <Hint
              text={canUndo
                ? 'Отменить последнюю правку в таблице (Ctrl+Z)'
                : 'Отменять нечего: правок в таблице не было'}
            >
              <button className="de-icon-btn" onClick={onUndo} disabled={!canUndo} aria-label="Отменить (Ctrl+Z)">
                <Undo2 size={14} />
              </button>
            </Hint>
            <Hint
              text={canRedo
                ? 'Вернуть отменённую правку (Ctrl+Y)'
                : 'Возвращать нечего: отменённых правок нет'}
            >
              <button className="de-icon-btn" onClick={onRedo} disabled={!canRedo} aria-label="Повторить (Ctrl+Y)">
                <Redo2 size={14} />
              </button>
            </Hint>
          </>
        )}

        {/* Свёртка одинаковых позиций: общий объём одной строкой, правка
            разъезжается по всем позициям сразу. Режим показа — документ от
            неё не меняется. */}
        <Hint
          align="end"
          text={canCollapse
            ? (collapsed
              ? 'Показать все позиции по отдельности, как они лежат в документе'
              : 'Собрать одинаковые работы и материалы в одну строку с общим объёмом. Документ не меняется — это только вид таблицы')
            : 'В этом документе нет колонки с наименованием — сворачивать не по чему'}
        >
          <button
            className={`de-btn${collapsed ? ' de-btn-active' : ''}`}
            onClick={onToggleCollapsed}
            disabled={!canCollapse}
          >
            <FoldVertical size={14} />
            Свернуть дубли
            {collapsed && groupCount > 0 && <span className="de-tab-count">{groupCount}</span>}
          </button>
        </Hint>

        <Hint align="end" text="Собрать ведомость: выбрать колонки и строки и скачать файл Excel">
          <button className="de-btn" onClick={onExport}>
            <FileSpreadsheet size={14} />
            Выгрузка
          </button>
        </Hint>

        <Hint align="end" text="История правок: кто и что менял в документе, с возможностью откатить">
          <button
            className={`de-icon-btn${historyOpen ? ' de-icon-btn-active' : ''}`}
            onClick={onToggleHistory}
            aria-label="История правок"
          >
            <History size={14} />
          </button>
        </Hint>
        <Hint
          align="end"
          text={fullscreen
            ? 'Вернуть таблице обычную высоту'
            : 'Растянуть таблицу на всю высоту окна — видно больше строк'}
        >
          <button
            className="de-icon-btn"
            onClick={onToggleFullscreen}
            aria-label={fullscreen ? 'Свернуть таблицу' : 'Растянуть таблицу на всю высоту окна'}
          >
            {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </Hint>

        {canWrite && (
          <>
            {draftState !== 'idle' && (
              <span className={`de-draft-state de-draft-${draftState}`}>
                {DRAFT_LABEL[draftState]}
              </span>
            )}
            {isDirty && (
              <Hint align="end" text="Вернуть таблицу к последнему применённому виду: непринятые правки пропадут">
                <button className="de-btn-ghost" onClick={onDiscard} disabled={applying}>
                  Отменить правки
                </button>
              </Hint>
            )}
            <Hint
              align="end"
              text={!isDirty
                ? 'Нет непринятых правок — применять нечего'
                : 'Записать правки в документ: они попадут в файл и в смету задачи'}
            >
              <button
                className="de-btn-primary"
                onClick={onApply}
                disabled={!isDirty || applying}
              >
                {applying
                  ? <><Loader2 size={14} className="de-spin" /> Применяю…</>
                  : <><Check size={14} /> Применить</>}
              </button>
            </Hint>
          </>
        )}
      </div>
    </div>
  </div>
);

export default EditorToolbar;
