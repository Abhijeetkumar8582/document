export type ReviewStatus = 'verified' | 'needs_review'
export type Engine = 'text' | 'google_docai' | 'llm_vision' | 'ocr'
export type Mode = 'auto' | Engine
export type GradeScale = '4.0' | 'percentage' | 'other'

export interface Subject {
  id: number
  position: number
  code: string | null
  name: string
  marks_obtained: number | null
  max_marks: number | null
  grade: string | null
  credits: number | null
  grade_points: number | null
}

export interface RecordSummary {
  id: number
  file_name: string
  file_type: string
  file_size: number
  page_count: number
  extraction_method: Engine
  engine_confidence: number | null
  engine_model: string | null
  student_name: string | null
  roll_number: string | null
  institution: string | null
  program: string | null
  term: string | null
  academic_year: string | null
  result_status: string | null
  total_marks: number | null
  max_marks: number | null
  percentage: number | null
  gpa: number | null
  credits_earned: number | null
  grade_scale: GradeScale | null
  confidence: number
  review_status: ReviewStatus
  pii_redacted: boolean
  subject_count: number
  created_at: string
}

export interface RecordDetail extends RecordSummary {
  engine_notes: string[]
  raw_text: string
  subjects: Subject[]
}

export interface RecordPage {
  items: RecordSummary[]
  total: number
  page: number
  page_size: number
}

export interface Stats {
  total_records: number
  verified: number
  needs_review: number
  average_percentage: number | null
  average_gpa: number | null
  institutions: number
  by_engine: Partial<Record<Engine, number>>
  recent: RecordSummary[]
}

export interface NamedCount {
  key: string
  label: string
  count: number
}

export interface Dashboard {
  total_records: number
  verified: number
  needs_review: number
  added_last_7: number
  added_prev_7: number
  average_gpa: number | null
  average_percentage: number | null
  average_confidence: number | null
  institutions: number
  pii_redacted: number
  by_day: { date: string; count: number }[]
  by_engine: NamedCount[]
  by_status: NamedCount[]
  by_scale: NamedCount[]
  gpa_buckets: { label: string; lo: number; hi: number; count: number }[]
  top_institutions: NamedCount[]
  queue: QueueSummary
  recent_activity: AuditEvent[]
}

export interface Presigned {
  key: string
  method: 'POST'
  url: string
  fields: Record<string, string>
  expires_at: number
  max_bytes: number
  backend: 'local' | 's3'
}

export interface Preview {
  url: string
  expires_at: number
  content_type: string | null
  kind: 'pdf' | 'image' | 'other'
  file_name: string
  backend: 'local' | 's3'
}

export interface StorageStatus {
  backend: 'local' | 's3'
  bucket: string | null
  presign_expires: number
  max_bytes: number
}

export interface EngineStatus {
  text: { label: string; ready: boolean }
  google_docai: { label: string; ready: boolean; threshold: number }
  llm_vision: { label: string; ready: boolean; model: string }
  ocr: { label: string; ready: boolean }
}

export interface AuditEvent {
  id: number
  record_id: number | null
  action: string
  detail: string
  actor: string
  client_ip: string | null
  created_at: string
}

export interface AuditPage {
  items: AuditEvent[]
  total: number
  page: number
  page_size: number
}

export type JobStatus = 'queued' | 'processing' | 'failed' | 'done' | 'skipped' | 'dead' | 'cancelled'
export type BatchStatus = 'queued' | 'running' | 'completed' | 'attention' | 'cancelled'

export interface JobCounts {
  queued: number
  processing: number
  failed: number
  done: number
  skipped: number
  dead: number
  cancelled: number
}

export interface Batch {
  id: number
  name: string
  mode: Mode
  actor: string
  status: BatchStatus
  total_jobs: number
  total_bytes: number
  counts: JobCounts
  finished_jobs: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Job {
  id: number
  batch_id: number
  file_name: string
  file_size: number
  sha256: string
  source: 'incoming' | 'storage'
  mode: Mode
  status: JobStatus
  attempts: number
  max_attempts: number
  next_attempt_at: string | null
  worker_id: string | null
  progress_done: number
  progress_total: number
  stage: string
  error: string | null
  record_id: number | null
  duplicate_of: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface QueueSummary {
  queued: number
  processing: number
  dead: number
  running_batches: number
  workers: number
}

export interface RecordUpdate {
  student_name?: string | null
  roll_number?: string | null
  institution?: string | null
  program?: string | null
  term?: string | null
  academic_year?: string | null
  result_status?: string | null
  gpa?: number | null
  credits_earned?: number | null
  grade_scale?: GradeScale | null
  review_status?: ReviewStatus
  subjects?: Omit<Subject, 'id' | 'position'>[]
}

export const ENGINE_LABEL: Record<Engine, string> = {
  text: 'Text layer',
  google_docai: 'Google Document AI',
  llm_vision: 'Gemini vision',
  ocr: 'Local OCR',
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/**
 * Backend origin. Empty in development (Vite proxies /api to port 8000).
 * In production set VITE_API_BASE in frontend/.env before `npm run build`, e.g. https://api.example.com
 */
export const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/+$/, '')

/** Absolute URL for an API path. */
export function url(path: string): string {
  return `${API_BASE}${path}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url(path), init)
  const type = res.headers.get('content-type') ?? ''
  if (type.includes('text/html')) {
    throw new ApiError(
      res.status,
      API_BASE
        ? `The API at ${API_BASE} answered with a web page, not JSON. Check VITE_API_BASE points at the backend.`
        : 'The request reached the web server instead of the API. Set VITE_API_BASE to the backend address and rebuild the frontend.',
    )
  }
  if (!res.ok) {
    let message = res.statusText
    try {
      const body = await res.json()
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* no body */
    }
    throw new ApiError(res.status, message)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

function qs(params: Record<string, string | number | undefined>) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') q.set(k, String(v))
  return q.toString()
}

export const api = {
  stats: () => request<Stats>('/api/records/stats'),
  dashboard: (days = 30) => request<Dashboard>(`/api/dashboard?days=${days}`),
  engines: () => request<EngineStatus>('/api/engines'),
  list: (params: Record<string, string | number | undefined>) => request<RecordPage>(`/api/records?${qs(params)}`),
  get: (id: number) => request<RecordDetail>(`/api/records/${id}`),
  update: (id: number, body: RecordUpdate) =>
    request<RecordDetail>(`/api/records/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  remove: (id: number) => request<void>(`/api/records/${id}`, { method: 'DELETE' }),
  removeMany: (ids: number[]) =>
    request<{ deleted: number; missing: number[] }>('/api/records/bulk-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }),
  audit: (params: Record<string, string | number | undefined>) => request<AuditPage>(`/api/audit?${qs(params)}`),
  /** Three steps: ask for a presigned POST, send the bytes straight to storage, then ask the API to file the object. */
  upload: async (file: File, mode: Mode, onProgress?: (pct: number) => void) => {
    const presigned = await api.presign(file)
    await api.uploadToStorage(presigned, file, onProgress)
    return api.fromUpload(presigned.key, file, mode)
  },
  presign: (file: File) =>
    request<Presigned>('/api/uploads/presign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_name: file.name, content_type: file.type || null, size: file.size }),
    }),
  fromUpload: (key: string, file: File, mode: Mode) =>
    request<RecordDetail>('/api/records/from-upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, file_name: file.name, content_type: file.type || null, mode }),
    }),
  storage: () => request<StorageStatus>('/api/storage'),
  preview: (id: number) => request<Preview>(`/api/records/${id}/preview`),
  /** POST the file to a presigned URL (S3 form fields first, file last, as S3 requires). */
  uploadToStorage: (presigned: Presigned, file: File, onProgress?: (pct: number) => void) =>
    new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', presigned.url)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve()
        else {
          let message = `Storage rejected the upload (${xhr.status})`
          try {
            const body = JSON.parse(xhr.responseText)
            if (body.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
          } catch {
            const m = /<Message>(.*?)<\/Message>/.exec(xhr.responseText || '')
            if (m) message = m[1]
          }
          reject(new ApiError(xhr.status, message))
        }
      }
      xhr.onerror = () => reject(new ApiError(0, presigned.backend === 's3' ? 'The bucket refused the upload. Check its CORS rules allow POST from this origin.' : 'The server could not be reached.'))
      const form = new FormData()
      for (const [k, v] of Object.entries(presigned.fields)) form.append(k, v)
      form.append('file', file)
      xhr.send(form)
    }),
  /** Legacy single-request upload through the API. Kept for scripts; the UI uses `upload`. */
  uploadDirect: (file: File, mode: Mode, onProgress?: (pct: number) => void) =>
    new Promise<RecordDetail>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', url(`/api/records/upload?mode=${mode}`))
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText))
        } else {
          let message = xhr.statusText || 'Upload failed'
          try {
            const body = JSON.parse(xhr.responseText)
            if (body.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
          } catch {
            /* ignore */
          }
          reject(new ApiError(xhr.status, message))
        }
      }
      xhr.onerror = () => reject(new ApiError(0, 'The server could not be reached. Is the backend running on port 8000?'))
      const form = new FormData()
      form.append('file', file)
      xhr.send(form)
    }),
  fileUrl: (id: number) => url(`/api/records/${id}/file`),
  exportUrl: () => url('/api/records/export.csv'),

  // Bulk upload
  batches: (params: Record<string, string | number | undefined>) => request<Page<Batch>>(`/api/batches?${qs(params)}`),
  batch: (id: number) => request<Batch>(`/api/batches/${id}`),
  batchJobs: (id: number, params: Record<string, string | number | undefined> = {}) =>
    request<Page<Job>>(`/api/batches/${id}/jobs?${qs(params)}`),
  queueSummary: () => request<QueueSummary>('/api/batches/summary'),
  retryBatch: (id: number) => request<Batch>(`/api/batches/${id}/retry`, { method: 'POST' }),
  cancelBatch: (id: number) => request<Batch>(`/api/batches/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: number) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),
  /** Batch over objects already uploaded with presigned POSTs. Workers process them in the background. */
  createBatchFromKeys: (items: { key: string; file_name: string; content_type: string | null; size: number }[], mode: Mode, name = '') =>
    request<Batch>('/api/batches/from-keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items, mode, name }),
    }),
  createBatch: (files: File[], mode: Mode, name: string, onProgress?: (pct: number) => void) =>
    new Promise<Batch>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', url(`/api/batches?mode=${mode}&name=${encodeURIComponent(name)}`))
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText))
        else {
          let message = xhr.statusText || 'Upload failed'
          try {
            const body = JSON.parse(xhr.responseText)
            if (body.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
          } catch {
            /* ignore */
          }
          reject(new ApiError(xhr.status, message))
        }
      }
      xhr.onerror = () => reject(new ApiError(0, 'The server could not be reached. Is the backend running on port 8000?'))
      const form = new FormData()
      for (const f of files) form.append('files', f)
      xhr.send(form)
    }),
}

const US = 'en-US'
const utc = (iso: string) => new Date(iso.endsWith('Z') ? iso : iso + 'Z')

export const fmt = {
  date: (iso: string) => utc(iso).toLocaleDateString(US, { month: '2-digit', day: '2-digit', year: 'numeric' }),
  dateTime: (iso: string) =>
    utc(iso).toLocaleString(US, { month: '2-digit', day: '2-digit', year: 'numeric', hour: 'numeric', minute: '2-digit' }),
  bytes: (n: number) => (n < 1024 * 1024 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`),
  num: (n: number | null | undefined, digits = 0) =>
    n === null || n === undefined ? '—' : Number.isInteger(n) && !digits ? String(n) : n.toFixed(digits || 2),
  pct: (n: number | null | undefined) => (n === null || n === undefined ? '—' : `${n.toFixed(n % 1 ? 2 : 0)}%`),
  gpa: (n: number | null | undefined) => (n === null || n === undefined ? '—' : n.toFixed(2)),
  /** 1,284 / 12.9K / 4.2M for headline tiles. */
  compact: (n: number) => (n < 10_000 ? n.toLocaleString(US) : n < 1_000_000 ? `${(n / 1000).toFixed(1)}K` : `${(n / 1_000_000).toFixed(1)}M`),
  timeAgo: (iso: string) => {
    const s = Math.max(0, (Date.now() - utc(iso).getTime()) / 1000)
    if (s < 60) return 'just now'
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    if (s < 86_400) return `${Math.floor(s / 3600)}h ago`
    if (s < 7 * 86_400) return `${Math.floor(s / 86_400)}d ago`
    return utc(iso).toLocaleDateString(US, { month: 'short', day: 'numeric' })
  },
  /** Headline score for a record: GPA on 4.0-scale transcripts, percentage otherwise. */
  score: (r: { grade_scale: GradeScale | null; gpa: number | null; percentage: number | null }) =>
    r.grade_scale === '4.0' && r.gpa !== null ? `${r.gpa.toFixed(2)} GPA` : r.percentage !== null ? `${r.percentage.toFixed(r.percentage % 1 ? 2 : 0)}%` : r.gpa !== null ? `${r.gpa.toFixed(2)} GPA` : '—',
}
