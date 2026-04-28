import React, { useRef, useState, useEffect } from 'react';
import { EstimateVersionSummary } from '../../types';
import { rollbackVersion, renameVersion, exportVersion } from '../../api/estimateVersions';

interface VersionTabsProps {
  taskId: string;
  versions: EstimateVersionSummary[];
  activeVersionId: string | null;
  activeView: 'version' | 'comparison';
  isOptimizationRunning: boolean;
  onSelectVersion: (versionId: string) => void;
  onSelectComparison: () => void;
  onVersionsChange: () => void; // reload after rollback/rename
}

const MAX_VISIBLE_TABS = 5;

const VersionTabs: React.FC<VersionTabsProps> = ({
  taskId,
  versions,
  activeVersionId,
  activeView,
  isOptimizationRunning,
  onSelectVersion,
  onSelectComparison,
  onVersionsChange,
}) => {
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [confirmRollbackId, setConfirmRollbackId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const overflowRef = useRef<HTMLDivElement | null>(null);

  // Close menus on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenId(null);
      }
      if (overflowRef.current && !overflowRef.current.contains(e.target as Node)) {
        setOverflowOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const visible = versions.slice(0, MAX_VISIBLE_TABS);
  const overflow = versions.slice(MAX_VISIBLE_TABS);

  const handleRename = async (versionId: string) => {
    if (!renameValue.trim()) return;
    await renameVersion(taskId, versionId, renameValue.trim());
    setRenamingId(null);
    setRenameValue('');
    onVersionsChange();
  };

  const handleRollback = async (versionId: string) => {
    await rollbackVersion(taskId, versionId);
    setConfirmRollbackId(null);
    setMenuOpenId(null);
    onVersionsChange();
  };

  const openRename = (v: EstimateVersionSummary) => {
    setMenuOpenId(null);
    setRenamingId(v.id);
    setRenameValue(v.version_display_name);
  };

  const renderTab = (v: EstimateVersionSummary, isOverflow = false) => {
    const isActive = !isOverflow && activeVersionId === v.id && activeView === 'version';
    const isLast = versions.indexOf(v) === versions.length - 1;

    return (
      <div
        key={v.id}
        style={{
          position: 'relative',
          display: 'inline-flex',
          alignItems: 'center',
        }}
      >
        {renamingId === v.id ? (
          <input
            autoFocus
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleRename(v.id);
              if (e.key === 'Escape') setRenamingId(null);
            }}
            onBlur={() => setRenamingId(null)}
            style={{
              padding: '4px 8px',
              fontSize: '13px',
              border: '2px solid #2563eb',
              borderRadius: '6px',
              outline: 'none',
              width: '160px',
            }}
          />
        ) : (
          <>
            <button
              onClick={() => {
                if (isOverflow) setOverflowOpen(false);
                onSelectVersion(v.id);
              }}
              style={{
                padding: '6px 10px',
                fontSize: '13px',
                fontWeight: isActive ? 600 : 400,
                borderRadius: '6px 0 0 6px',
                border: isActive ? '2px solid #2563eb' : '1px solid #e2e8f0',
                borderRight: 'none',
                background: isActive ? '#eff6ff' : '#fff',
                color: isActive ? '#2563eb' : '#374151',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                maxWidth: '160px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
              title={v.version_display_name}
            >
              {v.version_display_name}
            </button>
            <button
              onClick={(e) => {
                if (menuOpenId === v.id) {
                  setMenuOpenId(null);
                } else {
                  const rect = (e.currentTarget as HTMLButtonElement).getBoundingClientRect();
                  setMenuPos({ top: rect.bottom + 2, left: rect.left });
                  setMenuOpenId(v.id);
                }
              }}
              style={{
                padding: '6px 6px',
                fontSize: '12px',
                fontWeight: 400,
                borderRadius: '0 6px 6px 0',
                border: isActive ? '2px solid #2563eb' : '1px solid #e2e8f0',
                borderLeft: isActive ? '1px solid #93c5fd' : '1px solid #e2e8f0',
                background: isActive ? '#eff6ff' : '#fff',
                color: '#94a3b8',
                cursor: 'pointer',
              }}
              title="Действия"
            >
              ⋯
            </button>
          </>
        )}

        {/* Context menu */}
        {menuOpenId === v.id && (
          <div
            ref={menuRef}
            style={{
              position: 'fixed',
              top: menuPos.top,
              left: menuPos.left,
              zIndex: 1000,
              background: '#fff',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
              minWidth: '210px',
              padding: '4px 0',
            }}
          >
            <button
              onClick={() => openRename(v)}
              style={menuItemStyle}
            >
              Переименовать версию
            </button>
            <button
              onClick={() => {
                setMenuOpenId(null);
                exportVersion(taskId, v.id, v.version_display_name).catch(() => {
                  alert('Не удалось скачать файл. Попробуйте ещё раз.');
                });
              }}
              style={menuItemStyle}
            >
              ⬇ Скачать .xlsx
            </button>
            {!isLast && (
              <button
                onClick={() => {
                  setMenuOpenId(null);
                  setConfirmRollbackId(v.id);
                }}
                disabled={isOptimizationRunning}
                style={{
                  ...menuItemStyle,
                  color: isOptimizationRunning ? '#94a3b8' : '#dc2626',
                  cursor: isOptimizationRunning ? 'not-allowed' : 'pointer',
                }}
                title={isOptimizationRunning ? 'Дождитесь завершения оптимизации' : undefined}
              >
                Откатиться к этой версии
              </button>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      <div
        style={{
          display: 'flex',
          gap: '4px',
          marginBottom: '16px',
          flexWrap: 'nowrap',
          alignItems: 'center',
          overflowX: 'auto',
          paddingBottom: '2px',
        }}
      >
        {visible.map((v) => renderTab(v))}

        {/* Overflow dropdown */}
        {overflow.length > 0 && (
          <div style={{ position: 'relative' }} ref={overflowRef}>
            <button
              onClick={() => setOverflowOpen(!overflowOpen)}
              style={{
                padding: '6px 12px',
                fontSize: '13px',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
                background: '#fff',
                color: '#374151',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              Ещё... ({overflow.length})
            </button>
            {overflowOpen && (
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  zIndex: 200,
                  background: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                  minWidth: '200px',
                  padding: '4px 0',
                  marginTop: '2px',
                }}
              >
                {overflow.map((v) => (
                  <div key={v.id} style={{ padding: '2px 4px' }}>
                    {renderTab(v, true)}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Separator */}
        {versions.length > 0 && (
          <div style={{ width: '1px', height: '24px', background: '#e2e8f0', margin: '0 4px' }} />
        )}

        {/* Comparison tab — always last */}
        <button
          onClick={onSelectComparison}
          style={{
            padding: '6px 14px',
            fontSize: '13px',
            fontWeight: activeView === 'comparison' ? 600 : 400,
            borderRadius: '6px',
            border: activeView === 'comparison' ? '2px solid #7c3aed' : '1px solid #e2e8f0',
            background: activeView === 'comparison' ? '#f5f3ff' : '#fff',
            color: activeView === 'comparison' ? '#7c3aed' : '#374151',
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          Сравнение
        </button>
      </div>

      {/* Rollback confirmation dialog */}
      {confirmRollbackId && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.4)',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={() => setConfirmRollbackId(null)}
        >
          <div
            style={{
              background: '#fff',
              borderRadius: '12px',
              padding: '24px',
              maxWidth: '420px',
              width: '100%',
              boxShadow: '0 20px 60px rgba(0,0,0,0.15)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: '0 0 12px', fontSize: '17px', color: '#0f172a' }}>
              Откатиться к версии?
            </h3>
            <p style={{ margin: '0 0 20px', fontSize: '14px', color: '#475569', lineHeight: 1.5 }}>
              Все версии после «
              {versions.find((v) => v.id === confirmRollbackId)?.version_display_name}
              » будут скрыты. Они сохранятся в истории, но не будут отображаться. Продолжить?
            </p>
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setConfirmRollbackId(null)}
                style={cancelBtnStyle}
              >
                Отмена
              </button>
              <button
                onClick={() => handleRollback(confirmRollbackId)}
                style={dangerBtnStyle}
              >
                Откатиться
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

const menuItemStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  padding: '8px 14px',
  fontSize: '13px',
  background: 'transparent',
  border: 'none',
  textAlign: 'left',
  cursor: 'pointer',
  color: '#374151',
};

const cancelBtnStyle: React.CSSProperties = {
  padding: '8px 18px',
  fontSize: '13px',
  borderRadius: '6px',
  border: '1px solid #e2e8f0',
  background: '#fff',
  color: '#374151',
  cursor: 'pointer',
};

const dangerBtnStyle: React.CSSProperties = {
  padding: '8px 18px',
  fontSize: '13px',
  borderRadius: '6px',
  border: 'none',
  background: '#dc2626',
  color: '#fff',
  cursor: 'pointer',
  fontWeight: 600,
};

export default VersionTabs;
