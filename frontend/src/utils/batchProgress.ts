/**
 * Parse a batch progress message from the backend.
 *
 * Expected format: "Обработка батча N из M ..."
 * Returns { current, total } or null if the message doesn't match.
 */
export interface BatchProgress {
  current: number;
  total: number;
}

const BATCH_RE = /батч[аa]?\s+(\d+)\s+из\s+(\d+)/i;

export function parseBatchProgress(message: string): BatchProgress | null {
  const match = BATCH_RE.exec(message);
  if (!match) return null;
  return {
    current: parseInt(match[1], 10),
    total: parseInt(match[2], 10),
  };
}
