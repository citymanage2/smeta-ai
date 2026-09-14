import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  PromptRule, createPromptRule, deletePromptRule, getPromptRules, setPromptRuleEnabled,
} from '../../api/promptRules';

/**
 * Правила для промпта из повторяющихся правок.
 *
 * План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 8.
 *
 * Новое правило создаётся выключенным: включение — отдельное решение, потому
 * что правило меняет все будущие расчёты и в результате его не видно.
 */

const SCOPES: { value: string; label: string }[] = [
  { value: 'ALL', label: 'Все стадии' },
  { value: 'LIST_FROM_GRAND', label: 'Перечень из Гранд-сметы' },
  { value: 'LIST_FROM_PROJECT', label: 'Перечень из проекта' },
  { value: 'CHECK_LIST_COMPLETENESS', label: 'Проверка полноты перечня' },
  { value: 'CHECK_PROJECT_COMPLETENESS', label: 'Проверка полноты (по проекту)' },
  { value: 'ESTIMATE_FROM_LIST', label: 'Смета из перечня' },
];

const scopeLabel = (scope: string) =>
  SCOPES.find((s) => s.value === scope)?.label ?? scope;

const cardStyle: React.CSSProperties = {
  background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '8px',
  padding: '16px', marginBottom: '16px',
};

const btn: React.CSSProperties = {
  padding: '6px 12px', borderRadius: '7px', border: '1px solid #e2e8f0',
  background: '#ffffff', color: '#334155', fontSize: '12.5px', fontWeight: 600,
  cursor: 'pointer',
};

const PromptRulesCard: React.FC = () => {
  const [rules, setRules] = useState<PromptRule[]>([]);
  const [text, setText] = useState('');
  const [scope, setScope] = useState('ALL');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRules(await getPromptRules());
    } catch {
      toast.error('Не удалось загрузить правила');
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await createPromptRule(text.trim(), scope);
      setText('');
      await load();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Не удалось сохранить правило');
    } finally {
      setBusy(false);
    }
  };

  const handleToggle = async (rule: PromptRule) => {
    try {
      await setPromptRuleEnabled(rule.id, !rule.enabled);
      await load();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Не удалось изменить правило');
    }
  };

  const handleDelete = async (rule: PromptRule) => {
    try {
      await deletePromptRule(rule.id);
      await load();
    } catch {
      toast.error('Не удалось удалить правило');
    }
  };

  return (
    <div style={cardStyle}>
      <div style={{ fontSize: '15px', fontWeight: 600, color: '#0f172a', marginBottom: '4px' }}>
        Правила для ИИ
      </div>
      <div style={{ fontSize: '12.5px', color: '#64748b', marginBottom: '12px' }}>
        Если правки повторяются, сформулируйте правило — ИИ будет учитывать его в
        новых расчётах перечня, полноты и сметы. Правило начинает действовать
        только после «Включить» и не касается уже идущих расчётов, оптимизации и
        поиска аналогов. Не больше 20 включённых правил: лишние указания
        ухудшают ответ.
      </div>

      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '12px' }}>
        <textarea
          aria-label="Текст правила"
          value={text}
          maxLength={500}
          onChange={(e) => setText(e.target.value)}
          placeholder="Например: «Демонтаж кабеля» считай в метрах, а не в штуках"
          style={{
            flex: '1 1 320px', minHeight: '56px', padding: '8px 10px', fontSize: '13px',
            border: '1px solid #e2e8f0', borderRadius: '8px', fontFamily: 'inherit',
          }}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <select
            aria-label="Где действует"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            style={{ padding: '6px 8px', fontSize: '13px', borderRadius: '7px', border: '1px solid #e2e8f0' }}
          >
            {SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <button style={btn} disabled={busy || !text.trim()} onClick={handleCreate}>
            Добавить правило
          </button>
        </div>
      </div>

      {rules.length === 0 && (
        <div style={{ fontSize: '13px', color: '#94a3b8' }}>Правил пока нет.</div>
      )}

      {rules.map((rule) => (
        <div
          key={rule.id}
          style={{
            display: 'flex', gap: '12px', alignItems: 'flex-start', flexWrap: 'wrap',
            padding: '10px 0', borderTop: '1px solid #eef2f7',
          }}
        >
          <div style={{ flex: '1 1 320px' }}>
            <div style={{ fontSize: '13.5px', color: '#0f172a' }}>{rule.text}</div>
            <div style={{ fontSize: '11.5px', color: '#94a3b8', marginTop: '2px' }}>
              {scopeLabel(rule.scope)}
              {rule.enabled && rule.enabled_by
                ? ` · включил ${rule.enabled_by}${rule.enabled_at
                  ? ' ' + new Date(rule.enabled_at).toLocaleDateString('ru-RU') : ''}`
                : ' · выключено'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              style={{
                ...btn,
                ...(rule.enabled ? {} : { background: '#2563eb', color: '#ffffff', border: 'none' }),
              }}
              onClick={() => handleToggle(rule)}
            >
              {rule.enabled ? 'Выключить' : 'Включить'}
            </button>
            <button style={btn} onClick={() => handleDelete(rule)}>Удалить</button>
          </div>
        </div>
      ))}
    </div>
  );
};

export default PromptRulesCard;
