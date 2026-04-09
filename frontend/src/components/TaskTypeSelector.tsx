import React from 'react';
import { TaskType, TASK_TYPE_LABELS } from '../types';

interface TaskTypeSelectorProps {
  value: TaskType;
  onChange: (value: TaskType) => void;
  disabled?: boolean;
}

const TASK_TYPES: TaskType[] = [
  'LIST_FROM_GRAND',
];

const TaskTypeSelector: React.FC<TaskTypeSelectorProps> = ({ value, onChange, disabled }) => {
  return (
    <div>
      <label
        style={{
          display: 'block',
          fontSize: '14px',
          fontWeight: 600,
          color: '#374151',
          marginBottom: '8px',
        }}
      >
        Тип задачи
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as TaskType)}
        disabled={disabled}
        style={{
          width: '100%',
          padding: '10px 14px',
          fontSize: '15px',
          color: '#1e293b',
          backgroundColor: disabled ? '#f1f5f9' : '#ffffff',
          border: '1.5px solid #e2e8f0',
          borderRadius: '8px',
          outline: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          appearance: 'none',
          backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E")`,
          backgroundRepeat: 'no-repeat',
          backgroundPosition: 'right 12px center',
          paddingRight: '40px',
          transition: 'border-color 0.15s',
        }}
        onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
        onBlur={(e) => { e.target.style.borderColor = '#e2e8f0'; }}
      >
        {TASK_TYPES.map((type) => (
          <option key={type} value={type}>
            {TASK_TYPE_LABELS[type]}
          </option>
        ))}
      </select>
    </div>
  );
};

export default TaskTypeSelector;
