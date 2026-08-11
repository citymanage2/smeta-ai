import React, { useState, useEffect, useRef, useCallback } from 'react';
import Layout from '../components/Layout';
import { ReviewItem, RetrainStats, TrainJobStatus } from '../types/retraining';
import {
  parseFiles,
  savePair,
  getStats,
  startTraining,
  getJobStatus,
} from '../api/retraining';

const MIN_POSITIVE_TO_TRAIN = 200;

const JOB_STATUS_LABELS: Record<string, string> = {
  pending: 'В очереди',
  running: 'Обучение...',
  completed: 'Завершено',
  failed: 'Ошибка',
};

const JOB_STATUS_COLORS: Record<string, { color: string; bg: string; border: string }> = {
  pending:   { color: '#854d0e', bg: '#fef9c3', border: '#fde047' },
  running:   { color: '#1d4ed8', bg: '#eff6ff', border: '#93c5fd' },
  completed: { color: '#15803d', bg: '#f0fdf4', border: '#86efac' },
  failed:    { color: '#dc2626', bg: '#fef2f2', border: '#fca5a5' },
};

function fmtScore(score: number): string {
  return `${Math.round(score * 100)}%`;
}

const RetrainingPage: React.FC = () => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Stats
  const [stats, setStats] = useState<RetrainStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  // File selection
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  // Parsing
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState('');

  // Review queue
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [savedCount, setSavedCount] = useState(0);
  const [savingPair, setSavingPair] = useState(false);
  const [showAlts, setShowAlts] = useState(false); // show alt candidates after ❌

  // Training job
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<TrainJobStatus | null>(null);
  const [trainLoading, setTrainLoading] = useState(false);
  const [trainError, setTrainError] = useState('');

  const loadStats = useCallback(async () => {
    try {
      const s = await getStats();
      setStats(s);
    } catch {
      // non-critical
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // Poll job status while running
  useEffect(() => {
    if (!jobId) return;
    if (jobStatus?.status === 'completed' || jobStatus?.status === 'failed') return;

    const timer = setInterval(async () => {
      try {
        const s = await getJobStatus(jobId);
        setJobStatus(s);
        if (s.status === 'completed' || s.status === 'failed') {
          clearInterval(timer);
          loadStats();
        }
      } catch {
        clearInterval(timer);
      }
    }, 3000);

    return () => clearInterval(timer);
  }, [jobId, jobStatus?.status, loadStats]);

  const handleFilesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    setSelectedFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...files.filter((f) => !names.has(f.name))];
    });
    e.target.value = '';
  };

  const removeFile = (name: string) => {
    setSelectedFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const handleParse = async () => {
    if (!selectedFiles.length) return;
    setParsing(true);
    setParseError('');
    setItems([]);
    setCurrentIndex(0);
    setSavedCount(0);
    setShowAlts(false);
    try {
      const result = await parseFiles(selectedFiles);
      if (result.items.length === 0) {
        setParseError('Позиции не найдены. Убедитесь, что файл содержит данные.');
      } else {
        setItems(result.items);
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setParseError(e.response?.data?.detail ?? 'Ошибка при разборе файлов.');
    } finally {
      setParsing(false);
    }
  };

  const currentItem = items[currentIndex] ?? null;
  const isQueueDone = items.length > 0 && currentIndex >= items.length;

  const advance = () => {
    setCurrentIndex((i) => i + 1);
    setShowAlts(false);
  };

  const handleVote = async (candidateIndex: number, isPositive: boolean) => {
    if (!currentItem || savingPair) return;
    const candidate = currentItem.candidates[candidateIndex];
    if (!candidate) return;

    setSavingPair(true);
    try {
      await savePair({
        anchor_text: currentItem.anchor,
        candidate_text: candidate.text,
        candidate_type: candidate.type,
        is_positive: isPositive,
        similarity_score: candidate.score,
        source_file: currentItem.source_file,
      });
      setSavedCount((c) => c + 1);
      // Refresh stats every 10 saves
      if ((savedCount + 1) % 10 === 0) loadStats();
    } catch {
      // non-critical: still advance
    } finally {
      setSavingPair(false);
      advance();
    }
  };

  const handleSkip = () => advance();

  const handleTrain = async () => {
    setTrainLoading(true);
    setTrainError('');
    try {
      const result = await startTraining();
      setJobId(result.job_id);
      setJobStatus({
        job_id: result.job_id,
        status: 'pending',
        progress_pct: 0,
        progress_message: null,
        error: null,
        model_path: null,
      });
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setTrainError(e.response?.data?.detail ?? 'Не удалось запустить обучение.');
    } finally {
      setTrainLoading(false);
    }
  };

  // Обучение закрыто предохранителем на сервере: обученная модель живёт во
  // временной папке и пропадает при перезапуске, а эмбеддинги прайса к тому
  // моменту уже пересчитаны под неё — поиск цен начал бы ошибаться незаметно.
  // Пары размечать при этом можно: они копятся и не пропадут.
  const trainingAllowed = stats?.retraining_enabled ?? false;
  const canTrain =
    trainingAllowed && (stats?.positive_pairs ?? 0) >= MIN_POSITIVE_TO_TRAIN;
  const isTraining = jobStatus?.status === 'pending' || jobStatus?.status === 'running';

  return (
    <Layout>
      <div style={{ maxWidth: '720px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
          <h2 style={{ margin: 0, fontSize: '26px', fontWeight: 700, color: '#0f172a' }}>
            Дообучение модели
          </h2>
          <button
            onClick={handleTrain}
            disabled={!canTrain || trainLoading || isTraining}
            style={{
              padding: '10px 20px',
              fontSize: '14px',
              fontWeight: 600,
              backgroundColor: canTrain && !isTraining ? '#7c3aed' : '#e2e8f0',
              color: canTrain && !isTraining ? '#ffffff' : '#94a3b8',
              border: 'none',
              borderRadius: '8px',
              cursor: canTrain && !isTraining ? 'pointer' : 'not-allowed',
              transition: 'background-color 0.15s',
            }}
          >
            {trainLoading ? 'Запуск...' : isTraining ? 'Обучение...' : 'Обучить модель →'}
          </button>
        </div>

        {/* Предохранитель: объясняем закрытую кнопку, иначе она читается как поломка. */}
        {!statsLoading && !trainingAllowed && (
          <div
            style={{
              backgroundColor: '#fffbeb',
              border: '1px solid #fde047',
              borderRadius: '12px',
              padding: '16px 20px',
              marginBottom: '20px',
              fontSize: '13px',
              color: '#854d0e',
              lineHeight: 1.6,
            }}
          >
            <strong>Обучение временно закрыто.</strong> Обученная модель сохраняется
            во временную папку и пропадает при перезапуске сервиса, а цены прайса
            к тому моменту уже пересчитаны под неё — поиск цен начал бы ошибаться,
            никак этого не показывая. Размечать пары можно: они копятся и не
            пропадут, обучение запустим, когда модель будет храниться постоянно.
          </div>
        )}

        {/* Stats panel */}
        <div
          style={{
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '12px',
            padding: '20px 24px',
            marginBottom: '20px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          }}
        >
          {statsLoading ? (
            <div style={{ color: '#94a3b8', fontSize: '14px' }}>Загрузка статистики...</div>
          ) : stats ? (
            <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
                  Всего пар
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#0f172a' }}>
                  {stats.total_pairs}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
                  Верных
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#15803d' }}>
                  {stats.positive_pairs}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
                  Неверных
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: '#dc2626' }}>
                  {stats.negative_pairs}
                </div>
              </div>
              {!canTrain && trainingAllowed && (
                <div style={{ fontSize: '13px', color: '#64748b', fontStyle: 'italic' }}>
                  Нужно {MIN_POSITIVE_TO_TRAIN - (stats.positive_pairs)} ещё верных пар для обучения
                </div>
              )}
              {stats.last_job_status && (() => {
                const c = JOB_STATUS_COLORS[stats.last_job_status] ?? JOB_STATUS_COLORS['failed'];
                return (
                  <div style={{ marginLeft: 'auto' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
                      Последнее обучение
                    </div>
                    <span style={{
                      display: 'inline-block',
                      padding: '4px 12px',
                      backgroundColor: c.bg,
                      border: `1px solid ${c.border}`,
                      borderRadius: '20px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: c.color,
                    }}>
                      {JOB_STATUS_LABELS[stats.last_job_status] ?? stats.last_job_status}
                    </span>
                  </div>
                );
              })()}
            </div>
          ) : (
            <div style={{ color: '#94a3b8', fontSize: '14px' }}>Нет данных</div>
          )}
        </div>

        {/* Train error */}
        {trainError && (
          <div style={{ padding: '10px 14px', backgroundColor: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '8px', marginBottom: '16px', fontSize: '14px', color: '#dc2626' }}>
            {trainError}
          </div>
        )}

        {/* Training job progress */}
        {jobStatus && (
          <div
            style={{
              backgroundColor: '#ffffff',
              border: `1px solid ${JOB_STATUS_COLORS[jobStatus.status]?.border ?? '#e2e8f0'}`,
              borderRadius: '12px',
              padding: '18px 24px',
              marginBottom: '20px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: jobStatus.progress_pct > 0 ? '12px' : 0 }}>
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#0f172a' }}>
                {JOB_STATUS_LABELS[jobStatus.status] ?? jobStatus.status}
                {jobStatus.progress_message && ` — ${jobStatus.progress_message}`}
              </span>
              <span style={{ fontSize: '13px', color: '#64748b' }}>{jobStatus.progress_pct}%</span>
            </div>
            {isTraining && (
              <div style={{ height: '6px', backgroundColor: '#e2e8f0', borderRadius: '3px', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${jobStatus.progress_pct}%`,
                    backgroundColor: '#7c3aed',
                    borderRadius: '3px',
                    transition: 'width 0.3s ease',
                    minWidth: jobStatus.progress_pct === 0 ? '40%' : undefined,
                    animation: jobStatus.progress_pct === 0 ? 'rtProgressSlide 1.4s ease-in-out infinite' : undefined,
                  }}
                />
              </div>
            )}
            {jobStatus.status === 'failed' && jobStatus.error && (
              <div style={{ marginTop: '10px', fontSize: '13px', color: '#dc2626' }}>
                Ошибка: {jobStatus.error}
              </div>
            )}
          </div>
        )}

        {/* File upload section */}
        {!isQueueDone && items.length === 0 && (
          <div
            style={{
              backgroundColor: '#ffffff',
              border: '1px solid #e2e8f0',
              borderRadius: '12px',
              padding: '24px',
              marginBottom: '20px',
              boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
            }}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: 700, color: '#0f172a' }}>
              Загрузить сметы для оценки
            </h3>

            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx"
              multiple
              style={{ display: 'none' }}
              onChange={handleFilesChange}
            />

            <button
              onClick={() => fileInputRef.current?.click()}
              style={{
                width: '100%',
                padding: '14px',
                fontSize: '14px',
                fontWeight: 500,
                backgroundColor: '#f8fafc',
                color: '#475569',
                border: '1.5px dashed #cbd5e1',
                borderRadius: '8px',
                cursor: 'pointer',
                marginBottom: selectedFiles.length ? '12px' : '0',
                textAlign: 'center',
              }}
            >
              Выбрать файлы xlsx
            </button>

            {selectedFiles.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                {selectedFiles.map((f) => (
                  <div
                    key={f.name}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '8px 12px',
                      backgroundColor: '#f0fdf4',
                      border: '1px solid #86efac',
                      borderRadius: '7px',
                    }}
                  >
                    <span style={{ fontSize: '13px', color: '#15803d', fontWeight: 500 }}>{f.name}</span>
                    <button
                      onClick={() => removeFile(f.name)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', fontSize: '16px', lineHeight: 1, padding: '0 4px' }}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}

            {parseError && (
              <div style={{ padding: '10px 14px', backgroundColor: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '7px', marginBottom: '12px', fontSize: '13px', color: '#dc2626' }}>
                {parseError}
              </div>
            )}

            <button
              onClick={handleParse}
              disabled={!selectedFiles.length || parsing}
              style={{
                width: '100%',
                padding: '12px',
                fontSize: '14px',
                fontWeight: 600,
                backgroundColor: selectedFiles.length && !parsing ? '#2563eb' : '#93c5fd',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                cursor: selectedFiles.length && !parsing ? 'pointer' : 'not-allowed',
                transition: 'background-color 0.15s',
              }}
            >
              {parsing ? 'Разбор файлов...' : 'Начать оценку →'}
            </button>
          </div>
        )}

        {/* Queue done message */}
        {isQueueDone && (
          <div
            style={{
              backgroundColor: '#f0fdf4',
              border: '1px solid #86efac',
              borderRadius: '12px',
              padding: '28px 24px',
              textAlign: 'center',
              marginBottom: '20px',
            }}
          >
            <div style={{ fontSize: '32px', marginBottom: '8px' }}>✅</div>
            <div style={{ fontSize: '18px', fontWeight: 700, color: '#15803d', marginBottom: '6px' }}>
              Очередь завершена
            </div>
            <div style={{ fontSize: '14px', color: '#64748b', marginBottom: '20px' }}>
              Оценено {savedCount} из {items.length} позиций
            </div>
            <button
              onClick={() => {
                setItems([]);
                setCurrentIndex(0);
                setSavedCount(0);
                setSelectedFiles([]);
                setParseError('');
                loadStats();
              }}
              style={{
                padding: '10px 24px',
                fontSize: '14px',
                fontWeight: 600,
                backgroundColor: '#2563eb',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
              }}
            >
              Загрузить ещё сметы
            </button>
          </div>
        )}

        {/* Review card */}
        {currentItem && !isQueueDone && (
          <div
            style={{
              backgroundColor: '#ffffff',
              border: '1px solid #e2e8f0',
              borderRadius: '12px',
              padding: '24px',
              boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
            }}
          >
            {/* Progress bar */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <span style={{ fontSize: '13px', color: '#64748b' }}>
                Позиция {currentIndex + 1} из {items.length}
              </span>
              <span style={{ fontSize: '13px', color: '#64748b' }}>
                Сохранено: {savedCount}
              </span>
            </div>
            <div style={{ height: '6px', backgroundColor: '#e2e8f0', borderRadius: '3px', overflow: 'hidden', marginBottom: '20px' }}>
              <div
                style={{
                  height: '100%',
                  width: `${Math.round((currentIndex / items.length) * 100)}%`,
                  backgroundColor: '#2563eb',
                  borderRadius: '3px',
                  transition: 'width 0.3s ease',
                }}
              />
            </div>

            {/* Anchor */}
            <div style={{ marginBottom: '20px' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
                Из сметы:
              </div>
              <div
                style={{
                  padding: '14px 16px',
                  backgroundColor: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  fontSize: '16px',
                  fontWeight: 600,
                  color: '#0f172a',
                }}
              >
                {currentItem.anchor}
              </div>
            </div>

            {/* No candidates fallback */}
            {!currentItem.candidates[0] && !showAlts && (
              <>
                <div style={{ padding: '14px 16px', backgroundColor: '#fef9c3', border: '1px solid #fde047', borderRadius: '8px', marginBottom: '20px', fontSize: '14px', color: '#854d0e' }}>
                  Совпадений в прайсе не найдено
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                    onClick={handleSkip}
                    disabled={savingPair}
                    title="Это раздел или заголовок — не учитывать в обучении"
                    style={{
                      padding: '12px 14px',
                      fontSize: '13px',
                      fontWeight: 600,
                      backgroundColor: '#f3f0ff',
                      color: '#7c3aed',
                      border: '1.5px solid #c4b5fd',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    🏷 Раздел
                  </button>
                  <button
                    onClick={handleSkip}
                    disabled={savingPair}
                    style={{
                      flex: 1,
                      padding: '12px 14px',
                      fontSize: '14px',
                      fontWeight: 500,
                      backgroundColor: '#f1f5f9',
                      color: '#64748b',
                      border: '1.5px solid #e2e8f0',
                      borderRadius: '8px',
                      cursor: 'pointer',
                    }}
                  >
                    → Пропустить
                  </button>
                </div>
              </>
            )}

            {/* Top-1 candidate (always shown) */}
            {currentItem.candidates[0] && !showAlts && (
              <>
                <div style={{ marginBottom: '20px' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
                    Найдено в прайсе ({fmtScore(currentItem.candidates[0].score)}):
                  </div>
                  <div
                    style={{
                      padding: '14px 16px',
                      backgroundColor: '#eff6ff',
                      border: '1px solid #bfdbfe',
                      borderRadius: '8px',
                      fontSize: '15px',
                      fontWeight: 500,
                      color: '#1e3a8a',
                    }}
                  >
                    {currentItem.candidates[0].text}
                    {currentItem.candidates[0].min_price != null && (
                      <span style={{ marginLeft: '12px', fontSize: '13px', color: '#64748b', fontWeight: 400 }}>
                        от {currentItem.candidates[0].min_price.toLocaleString('ru-RU')} ₽/{currentItem.candidates[0].unit ?? 'ед.'}
                      </span>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                    onClick={() => handleVote(0, true)}
                    disabled={savingPair}
                    style={{
                      flex: 1,
                      padding: '12px',
                      fontSize: '14px',
                      fontWeight: 600,
                      backgroundColor: savingPair ? '#e2e8f0' : '#dcfce7',
                      color: savingPair ? '#94a3b8' : '#15803d',
                      border: '1.5px solid #86efac',
                      borderRadius: '8px',
                      cursor: savingPair ? 'not-allowed' : 'pointer',
                      transition: 'background-color 0.15s',
                    }}
                  >
                    ✅ Да, это одно и то же
                  </button>
                  <button
                    onClick={() => setShowAlts(true)}
                    disabled={savingPair}
                    style={{
                      flex: 1,
                      padding: '12px',
                      fontSize: '14px',
                      fontWeight: 600,
                      backgroundColor: '#fee2e2',
                      color: '#dc2626',
                      border: '1.5px solid #fca5a5',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      transition: 'background-color 0.15s',
                    }}
                  >
                    ❌ Нет
                  </button>
                  <button
                    onClick={handleSkip}
                    disabled={savingPair}
                    title="Это раздел или заголовок — не учитывать в обучении"
                    style={{
                      padding: '12px 14px',
                      fontSize: '13px',
                      fontWeight: 600,
                      backgroundColor: '#f3f0ff',
                      color: '#7c3aed',
                      border: '1.5px solid #c4b5fd',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    🏷 Раздел
                  </button>
                  <button
                    onClick={handleSkip}
                    disabled={savingPair}
                    style={{
                      padding: '12px 14px',
                      fontSize: '14px',
                      fontWeight: 500,
                      backgroundColor: '#f1f5f9',
                      color: '#64748b',
                      border: '1.5px solid #e2e8f0',
                      borderRadius: '8px',
                      cursor: 'pointer',
                    }}
                  >
                    → Пропуск
                  </button>
                </div>
              </>
            )}

            {/* Alt candidates (shown after ❌) */}
            {showAlts && (
              <div>
                <div style={{ fontSize: '13px', color: '#64748b', marginBottom: '12px' }}>
                  Выберите правильный вариант или пропустите:
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '12px' }}>
                  {currentItem.candidates.map((c, i) => (
                    <button
                      key={i}
                      onClick={() => handleVote(i, i === 0 ? false : true)}
                      disabled={savingPair}
                      style={{
                        padding: '12px 16px',
                        textAlign: 'left',
                        backgroundColor: '#f8fafc',
                        border: '1.5px solid #e2e8f0',
                        borderRadius: '8px',
                        cursor: savingPair ? 'not-allowed' : 'pointer',
                        fontSize: '14px',
                        color: '#1e293b',
                        transition: 'border-color 0.15s, background-color 0.15s',
                      }}
                      onMouseEnter={(e) => {
                        if (!savingPair) {
                          (e.currentTarget as HTMLButtonElement).style.borderColor = '#2563eb';
                          (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#eff6ff';
                        }
                      }}
                      onMouseLeave={(e) => {
                        (e.currentTarget as HTMLButtonElement).style.borderColor = '#e2e8f0';
                        (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#f8fafc';
                      }}
                    >
                      <span style={{ fontWeight: 600 }}>{c.text}</span>
                      <span style={{ marginLeft: '10px', fontSize: '12px', color: '#94a3b8' }}>
                        {fmtScore(c.score)} · {c.type === 'work' ? 'Работа' : 'Материал'}
                        {c.min_price != null ? ` · от ${c.min_price.toLocaleString('ru-RU')} ₽` : ''}
                      </span>
                    </button>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={handleSkip}
                    title="Это раздел или заголовок — не учитывать в обучении"
                    style={{
                      padding: '10px 16px',
                      fontSize: '13px',
                      fontWeight: 600,
                      backgroundColor: '#f3f0ff',
                      color: '#7c3aed',
                      border: '1px solid #c4b5fd',
                      borderRadius: '7px',
                      cursor: 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    🏷 Раздел
                  </button>
                  <button
                    onClick={handleSkip}
                    style={{
                      flex: 1,
                      padding: '10px',
                      fontSize: '13px',
                      fontWeight: 500,
                      backgroundColor: '#f1f5f9',
                      color: '#64748b',
                      border: '1px solid #e2e8f0',
                      borderRadius: '7px',
                      cursor: 'pointer',
                    }}
                  >
                    → Нет подходящего варианта, пропустить
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <style>{`
        @keyframes rtProgressSlide {
          0%   { transform: translateX(-150%); }
          100% { transform: translateX(350%); }
        }
      `}</style>
    </Layout>
  );
};

export default RetrainingPage;
