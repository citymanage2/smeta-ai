import React, { useRef, useState, useCallback } from 'react';

interface FileUploadProps {
  files: File[];
  onChange: (files: File[]) => void;
  maxFiles?: number;
  maxSizeMB?: number;
  accept?: string;
  onValidateFile?: (file: File) => string | null;
  hint?: string;
}

const MAX_FILES = 10;
const MAX_SIZE_MB = 20;
const ACCEPTED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png', '.xlsx', '.xls', '.xml'];

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

const FileUpload: React.FC<FileUploadProps> = ({
  files,
  onChange,
  maxFiles = MAX_FILES,
  maxSizeMB = MAX_SIZE_MB,
  accept = ACCEPTED_EXTENSIONS.join(','),
  onValidateFile,
  hint,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const validateAndAdd = useCallback(
    (newFiles: FileList | null) => {
      if (!newFiles) return;
      const validationErrors: string[] = [];
      const validated: File[] = [];

      Array.from(newFiles).forEach((file) => {
        const ext = '.' + file.name.split('.').pop()?.toLowerCase();
        if (!ACCEPTED_EXTENSIONS.includes(ext)) {
          validationErrors.push(`«${file.name}»: неподдерживаемый формат (${ext})`);
          return;
        }
        if (file.size > maxSizeMB * 1024 * 1024) {
          validationErrors.push(`«${file.name}»: файл превышает ${maxSizeMB} МБ`);
          return;
        }
        if (onValidateFile) {
          const customError = onValidateFile(file);
          if (customError) {
            validationErrors.push(`«${file.name}»: ${customError}`);
            return;
          }
        }
        validated.push(file);
      });

      const combined = [...files, ...validated];
      if (combined.length > maxFiles) {
        validationErrors.push(`Можно загрузить не более ${maxFiles} файлов`);
        onChange(combined.slice(0, maxFiles));
      } else {
        onChange(combined);
      }

      setErrors(validationErrors);
    },
    [files, onChange, maxFiles, maxSizeMB]
  );

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    validateAndAdd(e.dataTransfer.files);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => setIsDragging(false);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    validateAndAdd(e.target.files);
    // Reset input value so the same file can be re-added after removal
    e.target.value = '';
  };

  const removeFile = (index: number) => {
    const updated = files.filter((_, i) => i !== index);
    onChange(updated);
    setErrors([]);
  };

  return (
    <div>
      <label style={{ display: 'block', fontSize: '14px', fontWeight: 600, color: '#374151', marginBottom: '8px' }}>
        Файлы
      </label>

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => inputRef.current?.click()}
        style={{
          border: `2px dashed ${isDragging ? '#2563eb' : '#cbd5e1'}`,
          borderRadius: '10px',
          padding: '32px 24px',
          textAlign: 'center',
          cursor: 'pointer',
          backgroundColor: isDragging ? '#eff6ff' : '#f8fafc',
          transition: 'all 0.15s',
        }}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          onChange={handleInputChange}
          style={{ display: 'none' }}
        />
        <div style={{ fontSize: '36px', marginBottom: '8px' }}>📁</div>
        <p style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: '#334155' }}>
          Перетащите файлы сюда или нажмите для выбора
        </p>
        <p style={{ margin: '6px 0 0', fontSize: '13px', color: '#94a3b8' }}>
          {hint ?? `${ACCEPTED_EXTENSIONS.join(', ')} · Макс. ${maxFiles} файлов · Макс. ${maxSizeMB} МБ каждый`}
        </p>
        <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#f59e0b' }}>
          Формат .gsn не поддерживается
        </p>
      </div>

      {/* Validation errors */}
      {errors.length > 0 && (
        <div
          style={{
            marginTop: '10px',
            padding: '10px 14px',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '8px',
          }}
        >
          {errors.map((err, i) => (
            <p key={i} style={{ margin: 0, fontSize: '13px', color: '#dc2626' }}>
              {err}
            </p>
          ))}
        </div>
      )}

      {/* File list */}
      {files.length > 0 && (
        <ul style={{ listStyle: 'none', margin: '12px 0 0', padding: 0, display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {files.map((file, index) => (
            <li
              key={index}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 12px',
                backgroundColor: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                <span style={{ fontSize: '16px' }}>📄</span>
                <span
                  style={{
                    fontSize: '14px',
                    color: '#1e293b',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    maxWidth: '400px',
                  }}
                >
                  {file.name}
                </span>
                <span style={{ fontSize: '12px', color: '#94a3b8', flexShrink: 0 }}>
                  {formatFileSize(file.size)}
                </span>
              </div>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); removeFile(index); }}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: '#ef4444',
                  fontSize: '18px',
                  lineHeight: 1,
                  padding: '0 4px',
                  flexShrink: 0,
                }}
                title="Удалить"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default FileUpload;
