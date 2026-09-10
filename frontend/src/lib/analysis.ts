/**
 * Analysis sessions live outside React so they keep running when the overlay is closed or the route changes.
 *
 * A session: upload every file straight to storage (presigned POST) -> create a batch from the keys ->
 * poll the batch until every job is terminal. The server does the reading, so even a full page reload
 * loses nothing: sessions with a batch id are remembered in sessionStorage and resume polling on load.
 */
import { api, type Job, type Mode, type RecordDetail } from '../api'

export type Phase = 'uploading' | 'queuing' | 'processing' | 'done' | 'error'

export interface FileTask {
  id: string
  name: string
  size: number
  type: string
  uploadPct: number
  key?: string
  uploadError?: string
  job?: Job
  record?: RecordDetail
}

export interface Session {
  id: string
  name: string
  mode: Mode
  startedAt: number
  phase: Phase
  batchId?: number
  files: FileTask[]
  error?: string
}

type Listener = () => void

const STORAGE_KEY = 'registrar.analysis.sessions'
const POLL_MS = 1500
const UPLOAD_PARALLEL = 3

let sessions: Session[] = []
let overlaySession: string | null = null
const listeners = new Set<Listener>()
const pollers = new Map<string, number>()
const recordCache = new Map<number, RecordDetail>()

function emit() {
  for (const l of listeners) l()
  persist()
}

function persist() {
  try {
    const slim = sessions
      .filter((s) => s.batchId && s.phase !== 'done' && s.phase !== 'error')
      .map((s) => ({ id: s.id, name: s.name, mode: s.mode, startedAt: s.startedAt, batchId: s.batchId }))
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(slim))
  } catch {
    /* storage unavailable */
  }
}

function update(id: string, patch: Partial<Session>) {
  sessions = sessions.map((s) => (s.id === id ? { ...s, ...patch } : s))
  emit()
}

function updateFile(sessionId: string, fileId: string, patch: Partial<FileTask>) {
  sessions = sessions.map((s) => (s.id === sessionId ? { ...s, files: s.files.map((f) => (f.id === fileId ? { ...f, ...patch } : f)) } : s))
  emit()
}

export const analysis = {
  subscribe(fn: Listener) {
    listeners.add(fn)
    return () => {
      listeners.delete(fn)
    }
  },
  getSessions: () => sessions,
  getOverlay: () => overlaySession,
  openOverlay(id: string) {
    overlaySession = id
    emit()
  },
  closeOverlay() {
    overlaySession = null
    emit()
  },
  dismiss(id: string) {
    sessions = sessions.filter((s) => s.id !== id)
    if (overlaySession === id) overlaySession = null
    stopPolling(id)
    emit()
  },
  activeCount: () => sessions.filter((s) => s.phase === 'uploading' || s.phase === 'queuing' || s.phase === 'processing').length,
  activeFileCount: () =>
    sessions
      .filter((s) => s.phase === 'uploading' || s.phase === 'queuing' || s.phase === 'processing')
      .reduce((n, s) => n + s.files.filter((f) => !isTerminal(f)).length, 0),

  async start(files: File[], mode: Mode, name = ''): Promise<string> {
    const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
    const session: Session = {
      id,
      name: name || (files.length === 1 ? files[0].name : `${files.length} documents`),
      mode,
      startedAt: Date.now(),
      phase: 'uploading',
      files: files.map((f, i) => ({ id: `${id}-${i}`, name: f.name, size: f.size, type: f.type, uploadPct: 0 })),
    }
    sessions = [session, ...sessions]
    overlaySession = id
    emit()

    // ZIP archives are unpacked on the server, so a session containing one goes through the batch endpoint;
    // the server puts every member straight into storage and the file list is replaced by the real jobs.
    if (files.some((f) => f.name.toLowerCase().endsWith('.zip'))) {
      try {
        const batch = await api.createBatch(files, mode, session.name, (pct) => {
          sessions = sessions.map((s) => (s.id === id ? { ...s, files: s.files.map((f) => ({ ...f, uploadPct: pct })) } : s))
          emit()
        })
        const jobs = await api.batchJobs(batch.id, { page_size: 500 })
        update(id, {
          phase: 'processing',
          batchId: batch.id,
          files: jobs.items.map((j) => ({ id: `${id}-${j.id}`, name: j.file_name, size: j.file_size, type: '', uploadPct: 100, key: 'server', job: j })),
        })
        startPolling(id)
      } catch (e) {
        update(id, { phase: 'error', error: (e as Error).message })
      }
      return id
    }

    // Upload straight to storage, a few at a time.
    const queue = files.map((file, i) => ({ file, task: session.files[i] }))
    const workers = Array.from({ length: Math.min(UPLOAD_PARALLEL, queue.length) }, async () => {
      while (queue.length) {
        const { file, task } = queue.shift()!
        try {
          const presigned = await api.presign(file)
          await api.uploadToStorage(presigned, file, (pct) => updateFile(id, task.id, { uploadPct: pct }))
          // Folder drops carry a relative path; keep it so the batch shows where each file came from.
          const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath
          updateFile(id, task.id, { uploadPct: 100, key: presigned.key, name: rel || file.name })
        } catch (e) {
          updateFile(id, task.id, { uploadError: (e as Error).message })
        }
      }
    })
    await Promise.all(workers)

    const current = sessions.find((s) => s.id === id)!
    const uploaded = current.files.filter((f) => f.key)
    if (uploaded.length === 0) {
      update(id, { phase: 'error', error: 'None of the files could be uploaded.' })
      return id
    }
    update(id, { phase: 'queuing' })
    try {
      const batch = await api.createBatchFromKeys(
        uploaded.map((f) => ({ key: f.key!, file_name: f.name, content_type: f.type || null, size: f.size })),
        mode,
        current.name,
      )
      update(id, { phase: 'processing', batchId: batch.id })
      startPolling(id)
    } catch (e) {
      update(id, { phase: 'error', error: (e as Error).message })
    }
    return id
  },
}

export function isTerminal(f: FileTask): boolean {
  if (f.uploadError) return true
  const s = f.job?.status
  return s === 'done' || s === 'skipped' || s === 'dead' || s === 'cancelled'
}

function stopPolling(id: string) {
  const t = pollers.get(id)
  if (t) window.clearTimeout(t)
  pollers.delete(id)
}

function startPolling(id: string) {
  stopPolling(id)
  const tick = async () => {
    const s = sessions.find((x) => x.id === id)
    if (!s || !s.batchId) return
    try {
      const [batch, jobs] = await Promise.all([api.batch(s.batchId), api.batchJobs(s.batchId, { page_size: 500 })])
      // Match jobs to file tasks by name (order is preserved by the server), or append unknown ones.
      let files = s.files.map((f) => {
        const job = jobs.items.find((j) => j.file_name === f.name && !s.files.some((o) => o !== f && o.job?.id === j.id)) ?? f.job
        return job ? { ...f, job } : f
      })
      // Records for newly filed jobs.
      const need = files.filter((f) => f.job?.record_id && !f.record)
      if (need.length) {
        const fetched = await Promise.all(
          need.map(async (f) => {
            const rid = f.job!.record_id!
            if (!recordCache.has(rid)) recordCache.set(rid, await api.get(rid))
            return [f.id, recordCache.get(rid)!] as const
          }),
        )
        const byId = new Map(fetched)
        files = files.map((f) => (byId.has(f.id) ? { ...f, record: byId.get(f.id) } : f))
      }
      const finished = batch.status !== 'running' && batch.status !== 'queued'
      update(id, { files, phase: finished ? 'done' : 'processing' })
      if (finished) {
        stopPolling(id)
        return
      }
    } catch {
      /* transient; try again next tick */
    }
    pollers.set(id, window.setTimeout(tick, POLL_MS))
  }
  tick()
}

// Resume sessions that were mid-flight before a reload.
try {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (raw) {
    const saved = JSON.parse(raw) as { id: string; name: string; mode: Mode; startedAt: number; batchId: number }[]
    for (const s of saved) {
      sessions.push({ ...s, phase: 'processing', files: [] })
      api.batchJobs(s.batchId, { page_size: 500 }).then((jobs) => {
        update(s.id, {
          files: jobs.items.map((j) => ({ id: `${s.id}-${j.id}`, name: j.file_name, size: j.file_size, type: '', uploadPct: 100, key: 'resumed', job: j })),
        })
        startPolling(s.id)
      })
    }
  }
} catch {
  /* ignore */
}
