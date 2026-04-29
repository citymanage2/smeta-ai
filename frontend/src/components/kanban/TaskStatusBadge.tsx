import { TaskBrief } from '../../types/workflow'
import { LumaSpin } from '../ui/LumaSpin'

interface Props {
  task: TaskBrief | null
}

export function TaskStatusBadge({ task }: Props) {
  if (!task) {
    return <span style={{ color: '#94a3b8', fontSize: '13px' }}>● Не запущено</span>
  }
  switch (task.status) {
    case 'completed':
      return <span style={{ color: '#15803d', fontSize: '13px' }}>● Готово</span>
    case 'processing':
      return (
        <span style={{ color: '#d97706', fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          ● Обрабатывается <LumaSpin size="sm" color="#d97706" />
        </span>
      )
    case 'pending':
      return <span style={{ color: '#94a3b8', fontSize: '13px' }}>● Ожидает запуска</span>
    case 'failed':
      return <span style={{ color: '#dc2626', fontSize: '13px' }}>● Ошибка</span>
    case 'cancelled':
      return <span style={{ color: '#94a3b8', fontSize: '13px' }}>● Остановлено</span>
    default:
      return <span style={{ color: '#94a3b8', fontSize: '13px' }}>● Неизвестно</span>
  }
}
