import React from 'react';
import { TaskType, TASK_TYPE_LABELS } from '../types';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from './ui/Select';

interface TaskTypeSelectorProps {
  value: TaskType;
  onChange: (value: TaskType) => void;
  disabled?: boolean;
}

const TASK_TYPES: TaskType[] = [
  'LIST_FROM_GRAND',
  'LIST_FROM_PROJECT',
  'ESTIMATE_FROM_LIST',
  'ESTIMATE_OPTIMIZATION',
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
      <Select value={value} onValueChange={(v) => onChange(v as TaskType)} disabled={disabled} size="lg">
        <SelectTrigger style={{ width: '100%' }}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {TASK_TYPES.map((type) => (
            <SelectItem key={type} value={type}>
              {TASK_TYPE_LABELS[type]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

export default TaskTypeSelector;
