export interface Candidate {
  text: string;
  score: number;
  type: 'work' | 'material';
  unit?: string;
  min_price?: number;
}

export interface ReviewItem {
  anchor: string;
  candidates: Candidate[];
  source_file?: string;
}

export interface RetrainStats {
  total_pairs: number;
  positive_pairs: number;
  negative_pairs: number;
  last_job_status: string | null;
  model_loaded: boolean;
}

export interface TrainJobStatus {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress_pct: number;
  progress_message: string | null;
  error: string | null;
  model_path: string | null;
}
