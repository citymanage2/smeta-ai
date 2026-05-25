import React, { useRef, useState, useEffect, lazy, Suspense } from 'react';
import * as xlsx from 'xlsx';
import { xlsxWorkbookToFortune, fortuneToXlsxWorkbook, workbookHasFormulas } from '../../utils/fortuneSheetConverter';

const Workbook = lazy(() =>
  import('@fortune-sheet/react').then((m) => ({ default: m.Workbook }))
);

const TODAY = () => new Date().toISOString().slice(0, 10);

export function SpreadsheetTestEditor() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [sheets, setSheets] = useState<unknown[]>([]);
  const [loadedFileName, setLoadedFileName] = useState<string | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFormulasWarning, setShowFormulasWarning] = useState(false);

  // Dynamically attach/detach Fortune-Sheet CSS to avoid polluting other tabs
  useEffect(() => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.id = 'fortune-sheet-css';
    link.href = new URL(
      '../../node_modules/@fortune-sheet/react/dist/index.css',
      import.meta.url
    ).href;
    // Fallback: try CDN or bundled path
    link.onerror = () => {
      // Try the bundled asset path via Vite
      link.href = '/node_modules/@fortune-sheet/react/dist/index.css';
    };
    document.head.appendChild(link);
    return () => {
      document.getElementById('fortune-sheet-css')?.remove();
    };
  }, []);

  // Warn before leaving with unsaved changes
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasUnsavedChanges]);

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFileLoad(file);
    e.target.value = '';
  }

  async function handleFileLoad(file: File) {
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (ext !== 'xlsx' && ext !== 'xls') {
      setError('Поддерживаются только файлы .xlsx и .xls');
      return;
    }

    setIsLoading(true);
    setError(null);
    setShowFormulasWarning(false);

    const timeoutId = setTimeout(() => {
      setIsLoading(false);
      setError('Загрузка заняла слишком долго. Попробуйте файл меньшего размера.');
    }, 30000);

    try {
      const buffer = await file.arrayBuffer();
      const wb = xlsx.read(buffer, { type: 'array', cellStyles: true });

      if (workbookHasFormulas(wb)) {
        setShowFormulasWarning(true);
      }

      const fortuneData = xlsxWorkbookToFortune(wb);
      setSheets(fortuneData);
      setLoadedFileName(file.name.replace(/\.xlsx?$/i, ''));
      setHasUnsavedChanges(false);
    } catch (err) {
      setError(`Ошибка при чтении файла: ${err instanceof Error ? err.message : 'неизвестная ошибка'}`);
    } finally {
      clearTimeout(timeoutId);
      setIsLoading(false);
    }
  }

  function handleDownload() {
    const wb = fortuneToXlsxWorkbook(sheets);
    const data = xlsx.write(wb, { type: 'array', bookType: 'xlsx' });
    const blob = new Blob([data], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${loadedFileName ?? 'export'}_${TODAY()}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    setHasUnsavedChanges(false);
  }

  function handleReset() {
    setSheets([]);
    setLoadedFileName(null);
    setError(null);
    setHasUnsavedChanges(false);
    setShowFormulasWarning(false);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function handleSheetChange(data: any) {
    setSheets(data);
    setHasUnsavedChanges(true);
  }

  const hasSheets = sheets.length > 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          flexWrap: 'wrap',
          padding: '12px 16px',
          backgroundColor: '#f8fafc',
          borderRadius: '10px',
          border: '1px solid #e2e8f0',
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls"
          style={{ display: 'none' }}
          onChange={handleFileInputChange}
        />

        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={isLoading}
          style={{
            padding: '8px 16px',
            backgroundColor: '#2563eb',
            color: '#ffffff',
            border: 'none',
            borderRadius: '8px',
            cursor: isLoading ? 'not-allowed' : 'pointer',
            fontSize: '14px',
            fontWeight: 600,
            opacity: isLoading ? 0.6 : 1,
          }}
        >
          Загрузить xlsx
        </button>

        {loadedFileName && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '14px', color: '#334155', fontWeight: 500 }}>
              {loadedFileName}.xlsx
              {hasUnsavedChanges && (
                <span style={{ color: '#f59e0b', marginLeft: '4px' }} title="Есть несохранённые изменения">
                  *
                </span>
              )}
            </span>
            <button
              onClick={handleReset}
              title="Закрыть файл"
              style={{
                padding: '2px 8px',
                backgroundColor: '#f1f5f9',
                color: '#64748b',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '12px',
              }}
            >
              ✕
            </button>
          </div>
        )}

        {showFormulasWarning && (
          <span
            style={{
              fontSize: '13px',
              color: '#92400e',
              backgroundColor: '#fef3c7',
              padding: '4px 10px',
              borderRadius: '6px',
              border: '1px solid #fcd34d',
            }}
          >
            ⚠ Формулы заменены на значения
          </span>
        )}

        <div style={{ marginLeft: 'auto' }}>
          <button
            onClick={handleDownload}
            disabled={!hasSheets}
            style={{
              padding: '8px 16px',
              backgroundColor: hasSheets ? '#16a34a' : '#94a3b8',
              color: '#ffffff',
              border: 'none',
              borderRadius: '8px',
              cursor: hasSheets ? 'pointer' : 'not-allowed',
              fontSize: '14px',
              fontWeight: 600,
            }}
          >
            Скачать xlsx
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '8px',
            color: '#dc2626',
            fontSize: '14px',
          }}
        >
          {error}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div style={{ textAlign: 'center', padding: '40px', color: '#64748b', fontSize: '14px' }}>
          Загрузка файла...
        </div>
      )}

      {/* Empty state */}
      {!hasSheets && !isLoading && !error && (
        <div
          style={{
            textAlign: 'center',
            padding: '60px 20px',
            backgroundColor: '#f8fafc',
            borderRadius: '10px',
            border: '1px dashed #cbd5e1',
          }}
        >
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>📊</div>
          <h3 style={{ margin: '0 0 8px', fontSize: '18px', fontWeight: 600, color: '#334155' }}>
            Редактор таблиц
          </h3>
          <p style={{ margin: '0 0 20px', fontSize: '14px', color: '#64748b' }}>
            Загрузите смету в формате .xlsx или .xls
          </p>
          <button
            onClick={() => fileInputRef.current?.click()}
            style={{
              padding: '10px 24px',
              backgroundColor: '#2563eb',
              color: '#ffffff',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 600,
            }}
          >
            Загрузить файл
          </button>
        </div>
      )}

      {/* Fortune-Sheet editor */}
      {hasSheets && !isLoading && (
        <div style={{ height: 'calc(100vh - 220px)', minHeight: '400px' }}>
          <Suspense fallback={<div style={{ padding: '20px', color: '#64748b' }}>Загрузка редактора...</div>}>
            <Workbook
              data={sheets as Parameters<typeof Workbook>[0]['data']}
              onChange={handleSheetChange}
            />
          </Suspense>
        </div>
      )}
    </div>
  );
}
