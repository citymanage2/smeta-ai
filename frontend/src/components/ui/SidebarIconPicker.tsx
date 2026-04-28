import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactDOM from 'react-dom';
import { DynamicIcon, iconNames, type IconName } from 'lucide-react/dynamic';
import { Search, X } from 'lucide-react';

interface SidebarIconPickerProps {
  anchorRect: DOMRect;
  selectedIcon: IconName;
  onSelect: (icon: IconName) => void;
  onClose: () => void;
}

const PAGE = 100;

export const SidebarIconPicker: React.FC<SidebarIconPickerProps> = ({
  anchorRect,
  selectedIcon,
  onSelect,
  onClose,
}) => {
  const [search, setSearch] = useState('');
  const [visibleCount, setVisibleCount] = useState(PAGE);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = search.trim()
    ? iconNames.filter(n => n.includes(search.toLowerCase().trim()))
    : iconNames;

  const visible = filtered.slice(0, visibleCount);

  useEffect(() => {
    setVisibleCount(PAGE);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [search]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) {
      setVisibleCount(prev => Math.min(prev + PAGE, filtered.length));
    }
  }, [filtered.length]);

  // close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (scrollRef.current && !scrollRef.current.closest('[data-icon-picker]')?.contains(target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  // close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const left = anchorRect.right + 6;
  const top = Math.min(anchorRect.top, window.innerHeight - 340);

  return ReactDOM.createPortal(
    <div
      data-icon-picker=""
      style={{
        position: 'fixed',
        left,
        top,
        width: 280,
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: 10,
        boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '8px 10px', borderBottom: '1px solid #f1f5f9',
      }}>
        <Search size={13} color="#94a3b8" />
        <input
          ref={inputRef}
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Поиск иконки..."
          style={{
            flex: 1, border: 'none', outline: 'none', fontSize: 12,
            color: '#1e293b', backgroundColor: 'transparent',
          }}
        />
        <button
          onClick={onClose}
          style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 2, color: '#94a3b8', display: 'flex' }}
        >
          <X size={13} />
        </button>
      </div>

      {/* Label */}
      <div style={{ padding: '4px 10px 2px', fontSize: 10, color: '#94a3b8', fontWeight: 600, letterSpacing: '0.4px' }}>
        ИКОНКА КНОПКИ РАЗВЕРНУТЬ
      </div>

      {/* Grid */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{ overflowY: 'auto', maxHeight: 272, padding: '4px 6px 6px' }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2 }}>
          {visible.map(name => (
            <button
              key={name}
              title={name}
              onClick={() => { onSelect(name); onClose(); }}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: '100%', aspectRatio: '1', border: 'none', borderRadius: 6,
                cursor: 'pointer', padding: 0,
                backgroundColor: selectedIcon === name ? '#eff6ff' : 'transparent',
                outline: selectedIcon === name ? '2px solid #2563eb' : 'none',
                outlineOffset: -2,
                transition: 'background-color 0.1s',
              }}
              onMouseEnter={e => { if (selectedIcon !== name) (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#f8fafc'; }}
              onMouseLeave={e => { if (selectedIcon !== name) (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent'; }}
            >
              <DynamicIcon
                name={name}
                size={14}
                color={selectedIcon === name ? '#2563eb' : '#64748b'}
              />
            </button>
          ))}
        </div>
        {visibleCount < filtered.length && (
          <div style={{ textAlign: 'center', padding: '6px 0', fontSize: 11, color: '#cbd5e1' }}>
            ещё {filtered.length - visibleCount} иконок...
          </div>
        )}
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: '20px 0', fontSize: 12, color: '#cbd5e1' }}>
            Иконки не найдены
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
};
