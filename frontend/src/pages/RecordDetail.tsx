import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Download, Pencil, Trash2, Check, X, Plus, ScrollText, ChevronDown, Eye } from 'lucide-react'
import { api, fmt, type GradeScale, type Preview, type RecordDetail as Detail, type Subject } from '../api'
import { Confidence, EngineTag, Notice, PiiBadge, Skeleton, Stamp } from '../components/ui'
import { DocumentPreview } from '../components/DocumentPreview'

type Tab = 'subjects' | 'text' | 'document'
type SubjectDraft = Omit<Subject, 'id' | 'position'>
type Draft = {
  student_name: string
  roll_number: string
  institution: string
  program: string
  term: string
  academic_year: string
  result_status: string
  gpa: number | null
  credits_earned: number | null
  grade_scale: GradeScale | ''
  subjects: SubjectDraft[]
}

export default function RecordDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [rec, setRec] = useState<Detail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('subjects')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showSteps, setShowSteps] = useState(false)
  const [preview, setPreview] = useState<Preview | null | 'missing'>(null)
  const [showPreview, setShowPreview] = useState(false)

  useEffect(() => {
    api.get(Number(id)).then(setRec).catch((e) => setError(e.message))
  }, [id])

  useEffect(() => {
    if (!showPreview) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setShowPreview(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showPreview])

  // Fetch a fresh signed link when the document is shown, and again if it expires while open.
  useEffect(() => {
    if ((tab !== 'document' && !showPreview) || !rec) return
    let timer: number | undefined
    const load = () =>
      api
        .preview(rec.id)
        .then((p) => {
          setPreview(p)
          const ms = Math.max(30_000, p.expires_at * 1000 - Date.now() - 30_000)
          timer = window.setTimeout(load, ms)
        })
        .catch(() => setPreview('missing'))
    load()
    return () => window.clearTimeout(timer)
  }, [tab, showPreview, rec])

  const beginEdit = () => {
    if (!rec) return
    setDraft({
      student_name: rec.student_name ?? '',
      roll_number: rec.roll_number ?? '',
      institution: rec.institution ?? '',
      program: rec.program ?? '',
      term: rec.term ?? '',
      academic_year: rec.academic_year ?? '',
      result_status: rec.result_status ?? '',
      gpa: rec.gpa,
      credits_earned: rec.credits_earned,
      grade_scale: rec.grade_scale ?? '',
      subjects: rec.subjects.map(({ code, name, marks_obtained, max_marks, grade, credits, grade_points }) => ({
        code,
        name,
        marks_obtained,
        max_marks,
        grade,
        credits,
        grade_points,
      })),
    })
    setTab('subjects')
  }

  const save = async () => {
    if (!rec || !draft) return
    setSaving(true)
    setError(null)
    try {
      const empty = (v: string) => (v.trim() ? v.trim() : null)
      const updated = await api.update(rec.id, {
        student_name: empty(draft.student_name),
        roll_number: empty(draft.roll_number),
        institution: empty(draft.institution),
        program: empty(draft.program),
        term: empty(draft.term),
        academic_year: empty(draft.academic_year),
        result_status: empty(draft.result_status),
        gpa: draft.gpa,
        credits_earned: draft.credits_earned,
        grade_scale: draft.grade_scale || null,
        subjects: draft.subjects.filter((s) => s.name.trim()),
      })
      setRec(updated)
      setDraft(null)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const setStatus = async (review_status: 'verified' | 'needs_review') => {
    if (!rec) return
    try {
      setRec(await api.update(rec.id, { review_status }))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const remove = async () => {
    if (!rec) return
    try {
      await api.remove(rec.id)
      navigate('/records')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (error && !rec) return <Notice kind="error">{error}</Notice>
  if (!rec) return <Skeleton />

  const editing = draft !== null
  const subjects: SubjectDraft[] = editing ? draft.subjects : rec.subjects
  const scale = (editing ? draft.grade_scale : rec.grade_scale) || (rec.gpa !== null && rec.percentage === null ? '4.0' : 'percentage')
  const us = scale === '4.0'
  // Pass/fail, withdrawn and incomplete grades carry credits but no quality points, so they sit outside the GPA.
  const NO_POINTS = new Set(['P', 'NP', 'S', 'U', 'W', 'I', 'IP', 'CR', 'NC', 'AU', 'PASS', 'FAIL', 'AB'])
  const carriesPoints = (s: SubjectDraft) => s.grade !== null && !NO_POINTS.has(s.grade.toUpperCase()) && s.grade_points !== null
  const totalCredits = subjects.reduce((a, s) => a + (s.credits ?? 0), 0)
  const gpaCredits = subjects.filter(carriesPoints).reduce((a, s) => a + (s.credits ?? 0), 0)
  const totalPoints = subjects.filter(carriesPoints).reduce((a, s) => a + (s.grade_points ?? 0), 0)

  return (
    <div className="mx-auto max-w-6xl">
      <Link to="/records" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-ink">
        <ArrowLeft size={14} /> Records
      </Link>

      <div className="settle card relative overflow-hidden">
        <div className="absolute right-6 top-6 hidden sm:block">
          <Stamp status={rec.review_status} size="lg" />
        </div>
        <div className="border-b border-line px-6 py-6 sm:pr-48">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="eyebrow">
              {rec.file_type.toUpperCase()} · {rec.file_name}
            </span>
            <EngineTag engine={rec.extraction_method} confidence={rec.engine_confidence} model={rec.engine_model} />
            {rec.pii_redacted && <PiiBadge />}
          </div>
          {editing ? (
            <input
              className="input mt-2 max-w-md font-display text-2xl font-semibold"
              value={draft.student_name}
              placeholder="Student name"
              onChange={(e) => setDraft({ ...draft, student_name: e.target.value })}
            />
          ) : (
            <h1 className="mt-1 font-display text-[30px] font-semibold leading-tight tracking-tight text-ink">
              {rec.student_name ?? <span className="italic text-slate-400">Name not found</span>}
            </h1>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-600">
            {rec.roll_number && !editing && <span className="font-mono">{rec.roll_number}</span>}
            {rec.institution && !editing && <span>{rec.institution}</span>}
            <span className="sm:hidden">
              <Stamp status={rec.review_status} />
            </span>
          </div>
        </div>

        <div className="grid gap-x-8 gap-y-4 px-6 py-5 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Student ID" mono value={rec.roll_number} editing={editing} draft={draft?.roll_number} onChange={(v) => draft && setDraft({ ...draft, roll_number: v })} />
          <Field label="Institution" value={rec.institution} editing={editing} draft={draft?.institution} onChange={(v) => draft && setDraft({ ...draft, institution: v })} />
          <Field label="Program" value={rec.program} editing={editing} draft={draft?.program} onChange={(v) => draft && setDraft({ ...draft, program: v })} />
          <Field label="Term" value={rec.term} editing={editing} draft={draft?.term} onChange={(v) => draft && setDraft({ ...draft, term: v })} />
          <Field label="Academic year" mono value={rec.academic_year} editing={editing} draft={draft?.academic_year} onChange={(v) => draft && setDraft({ ...draft, academic_year: v })} />
          <Field label="Standing / result" value={rec.result_status} editing={editing} draft={draft?.result_status} onChange={(v) => draft && setDraft({ ...draft, result_status: v })} />

          <div>
            <div className="eyebrow">{us ? 'Cumulative GPA' : 'Aggregate'}</div>
            {editing ? (
              <div className="mt-1 flex items-center gap-2">
                <NumInput value={draft.gpa} onChange={(v) => setDraft({ ...draft, gpa: v })} placeholder="GPA" />
                <select className="input w-auto py-1" value={draft.grade_scale} onChange={(e) => setDraft({ ...draft, grade_scale: e.target.value as GradeScale | '' })} aria-label="Grade scale">
                  <option value="">Scale?</option>
                  <option value="4.0">4.0 scale</option>
                  <option value="percentage">Percentage</option>
                  <option value="other">Other</option>
                </select>
              </div>
            ) : us ? (
              <div className="mt-1 font-mono text-sm">
                <span className="text-ink">{fmt.gpa(rec.gpa)}</span>
                <span className="text-slate-500"> / 4.00</span>
                {rec.percentage !== null && <span className="text-slate-500"> · {fmt.pct(rec.percentage)}</span>}
              </div>
            ) : (
              <div className="mt-1 font-mono text-sm">
                {rec.total_marks !== null ? (
                  <>
                    {fmt.num(rec.total_marks)} / {fmt.num(rec.max_marks)} · <span className="text-ink">{fmt.pct(rec.percentage)}</span>
                  </>
                ) : (
                  fmt.pct(rec.percentage)
                )}
                {rec.gpa !== null && <span className="text-slate-500"> · GPA {fmt.gpa(rec.gpa)}</span>}
              </div>
            )}
          </div>

          <div>
            <div className="eyebrow">{us ? 'Credits earned' : 'Extraction'}</div>
            {us ? (
              editing ? (
                <div className="mt-1">
                  <NumInput value={draft.credits_earned} onChange={(v) => setDraft({ ...draft, credits_earned: v })} placeholder="Credits" />
                </div>
              ) : (
                <div className="mt-1 font-mono text-sm text-ink">{fmt.num(rec.credits_earned, 1)}</div>
              )
            ) : (
              <div className="mt-1.5 flex items-center gap-3 text-sm">
                <Confidence value={rec.confidence} />
                <span className="text-xs text-slate-500">
                  {rec.page_count} {rec.page_count === 1 ? 'page' : 'pages'}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-line bg-paper px-6 py-3">
          <button onClick={() => setShowSteps((s) => !s)} className="flex w-full items-center gap-2 text-left text-sm text-slate-600 hover:text-ink" aria-expanded={showSteps}>
            <ChevronDown size={14} className={`transition-transform ${showSteps ? 'rotate-180' : ''}`} />
            How this file was read
            <span className="ml-2 flex items-center gap-2">
              <Confidence value={rec.confidence} />
              <span className="text-xs text-slate-500">fields found</span>
            </span>
          </button>
          {showSteps && (
            <ol className="mt-3 space-y-1.5 border-l-2 border-line pl-4 text-sm text-slate-700">
              {rec.engine_notes.length === 0 && <li className="text-slate-500">No processing notes were recorded.</li>}
              {rec.engine_notes.map((n, i) => (
                <li key={i} className="flex gap-3">
                  <span className="font-mono text-xs text-slate-400">{i + 1}</span>
                  <span>{n}</span>
                </li>
              ))}
              <li className="flex gap-3 text-xs text-slate-500">
                <span className="font-mono text-slate-400">·</span>
                <span>
                  {rec.page_count} {rec.page_count === 1 ? 'page' : 'pages'}, {fmt.bytes(rec.file_size)}
                  {rec.pii_redacted && '. A Social Security number or date of birth was found and removed before storage.'}
                </span>
              </li>
            </ol>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-line bg-paper px-6 py-3">
          {editing ? (
            <>
              <button className="btn-primary" onClick={save} disabled={saving}>
                <Check size={15} /> {saving ? 'Saving…' : 'Save changes'}
              </button>
              <button className="btn-ghost" onClick={() => setDraft(null)} disabled={saving}>
                <X size={15} /> Cancel
              </button>
            </>
          ) : (
            <>
              <button className="btn-ghost" onClick={beginEdit}>
                <Pencil size={15} /> Edit
              </button>
              {rec.review_status === 'verified' ? (
                <button className="btn-ghost" onClick={() => setStatus('needs_review')}>
                  Mark as needs review
                </button>
              ) : (
                <button className="btn-ghost" onClick={() => setStatus('verified')}>
                  <Check size={15} /> Mark verified
                </button>
              )}
              <button className="btn-ghost" onClick={() => setShowPreview(true)}>
                <Eye size={15} /> Preview file
              </button>
              <a className="btn-ghost" href={api.fileUrl(rec.id)}>
                <Download size={15} /> Original file
              </a>
              <Link className="btn-ghost" to={`/audit?record=${rec.id}`}>
                <ScrollText size={15} /> Access history
              </Link>
              <div className="ml-auto flex items-center gap-2">
                {confirmDelete ? (
                  <>
                    <span className="text-sm text-slate-600">Delete this record and its file? This is logged.</span>
                    <button className="btn-danger" onClick={remove}>
                      Delete
                    </button>
                    <button className="btn-ghost" onClick={() => setConfirmDelete(false)}>
                      Keep
                    </button>
                  </>
                ) : (
                  <button className="btn-ghost text-slate-500" onClick={() => setConfirmDelete(true)}>
                    <Trash2 size={15} /> Delete
                  </button>
                )}
              </div>
            </>
          )}
          {saved && <span className="text-sm text-moss">Saved</span>}
        </div>
      </div>

      {error && (
        <div className="mt-4">
          <Notice kind="error">{error}</Notice>
        </div>
      )}

      <div className="settle settle-2 mt-6 flex items-center gap-1 border-b border-line">
        {(
          [
            ['subjects', `${us ? 'Courses' : 'Subjects'} (${subjects.length})`],
            ['document', 'Document'],
            ['text', 'Extracted text'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === key ? 'border-ink font-medium text-ink' : 'border-transparent text-slate-500 hover:text-ink'}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'subjects' && (
        <div className="settle settle-3 card mt-4 overflow-x-auto">
          {subjects.length === 0 && !editing ? (
            <div className="px-6 py-10 text-center text-sm text-slate-500">
              No course rows were recognised. Check the{' '}
              <button className="text-oxford underline" onClick={() => setTab('text')}>
                extracted text
              </button>{' '}
              to see what was read, or edit the record to add them.
            </div>
          ) : (
            <table className="w-full min-w-[720px] text-sm">
              <thead className="border-b border-line bg-paper">
                {us ? (
                  <tr>
                    <th className="th w-28">Course</th>
                    <th className="th">Title</th>
                    <th className="th w-24 text-right">Credits</th>
                    <th className="th w-20">Grade</th>
                    <th className="th w-28 text-right">Grade points</th>
                    <th className="th w-40">Points / credit</th>
                    {editing && <th className="th w-10" />}
                  </tr>
                ) : (
                  <tr>
                    <th className="th w-28">Code</th>
                    <th className="th">Subject</th>
                    <th className="th w-28 text-right">Marks</th>
                    <th className="th w-24 text-right">Max</th>
                    <th className="th w-40">Share</th>
                    <th className="th w-20">Grade</th>
                    <th className="th w-20 text-right">Credits</th>
                    {editing && <th className="th w-10" />}
                  </tr>
                )}
              </thead>
              <tbody className="divide-y divide-line">
                {subjects.map((s, i) => {
                  const upd = (patch: Partial<SubjectDraft>) =>
                    draft && setDraft({ ...draft, subjects: draft.subjects.map((x, j) => (j === i ? { ...x, ...patch } : x)) })
                  const removeRow = () => draft && setDraft({ ...draft, subjects: draft.subjects.filter((_, j) => j !== i) })
                  const perCredit = carriesPoints(s) && s.credits ? (s.grade_points ?? 0) / s.credits : null
                  const share = s.marks_obtained !== null && s.max_marks ? Math.min(100, (s.marks_obtained / s.max_marks) * 100) : null
                  return (
                    <tr key={i} className="hover:bg-paper">
                      <td className="td font-mono text-xs text-slate-600">
                        {editing ? <input className="input py-1 font-mono text-xs" value={s.code ?? ''} onChange={(e) => upd({ code: e.target.value || null })} /> : (s.code ?? '—')}
                      </td>
                      <td className="td text-ink">{editing ? <input className="input py-1" value={s.name} onChange={(e) => upd({ name: e.target.value })} /> : s.name}</td>
                      {us ? (
                        <>
                          <td className="td text-right font-mono">{editing ? <NumInput value={s.credits} onChange={(v) => upd({ credits: v })} /> : fmt.num(s.credits, 2)}</td>
                          <td className="td font-mono">{editing ? <input className="input py-1 font-mono" value={s.grade ?? ''} onChange={(e) => upd({ grade: e.target.value.toUpperCase() || null })} /> : (s.grade ?? '—')}</td>
                          <td className="td text-right font-mono text-slate-700">{editing ? <NumInput value={s.grade_points} onChange={(v) => upd({ grade_points: v })} /> : fmt.num(s.grade_points, 2)}</td>
                          <td className="td">
                            {perCredit !== null ? (
                              <div className="flex items-center gap-2">
                                <div className="markbar flex-1">
                                  <i style={{ width: `${Math.min(100, (perCredit / 4) * 100)}%` }} />
                                </div>
                                <span className="w-10 text-right font-mono text-xs text-slate-500">{perCredit.toFixed(1)}</span>
                              </div>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="td text-right font-mono">{editing ? <NumInput value={s.marks_obtained} onChange={(v) => upd({ marks_obtained: v })} /> : fmt.num(s.marks_obtained)}</td>
                          <td className="td text-right font-mono text-slate-500">{editing ? <NumInput value={s.max_marks} onChange={(v) => upd({ max_marks: v })} /> : fmt.num(s.max_marks)}</td>
                          <td className="td">
                            {share !== null ? (
                              <div className="flex items-center gap-2">
                                <div className="markbar flex-1">
                                  <i style={{ width: `${share}%` }} />
                                </div>
                                <span className="w-10 text-right font-mono text-xs text-slate-500">{share.toFixed(0)}%</span>
                              </div>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                          <td className="td font-mono">{editing ? <input className="input py-1 font-mono" value={s.grade ?? ''} onChange={(e) => upd({ grade: e.target.value || null })} /> : (s.grade ?? '—')}</td>
                          <td className="td text-right font-mono text-slate-500">{editing ? <NumInput value={s.credits} onChange={(v) => upd({ credits: v })} /> : fmt.num(s.credits)}</td>
                        </>
                      )}
                      {editing && (
                        <td className="td">
                          <button className="rounded p-1 text-slate-400 hover:bg-seal-soft hover:text-seal" aria-label="Remove row" onClick={removeRow}>
                            <X size={14} />
                          </button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
              {!editing && subjects.length > 0 && (
                <tfoot className="border-t border-line bg-paper">
                  {us ? (
                    <tr>
                      <td className="td" />
                      <td className="td font-medium text-ink">Total</td>
                      <td className="td text-right font-mono font-medium text-ink">{fmt.num(totalCredits, 2)}</td>
                      <td className="td" />
                      <td className="td text-right font-mono text-slate-700">{fmt.num(totalPoints, 2)}</td>
                      <td className="td font-mono text-xs text-slate-500">
                        GPA {gpaCredits ? (totalPoints / gpaCredits).toFixed(2) : '—'}
                        {gpaCredits !== totalCredits && gpaCredits > 0 && <span className="text-slate-400"> on {fmt.num(gpaCredits, 2)} cr</span>}
                      </td>
                    </tr>
                  ) : (
                    rec.total_marks !== null && (
                      <tr>
                        <td className="td" />
                        <td className="td font-medium text-ink">Total</td>
                        <td className="td text-right font-mono font-medium text-ink">{fmt.num(rec.total_marks)}</td>
                        <td className="td text-right font-mono text-slate-500">{fmt.num(rec.max_marks)}</td>
                        <td className="td font-mono text-xs text-slate-500">{fmt.pct(rec.percentage)}</td>
                        <td className="td" colSpan={2} />
                      </tr>
                    )
                  )}
                </tfoot>
              )}
            </table>
          )}
          {editing && (
            <div className="border-t border-line px-4 py-2">
              <button
                className="btn-ghost"
                onClick={() =>
                  draft &&
                  setDraft({
                    ...draft,
                    subjects: [
                      ...draft.subjects,
                      { code: null, name: '', marks_obtained: null, max_marks: us ? null : 100, grade: null, credits: us ? 3 : null, grade_points: null },
                    ],
                  })
                }
              >
                <Plus size={14} /> Add {us ? 'course' : 'subject'}
              </button>
            </div>
          )}
        </div>
      )}

      {tab === 'document' && (
        <DocumentPreview preview={preview} fileName={rec.file_name} downloadUrl={api.fileUrl(rec.id)} pageCount={rec.page_count} />
      )}

      {showPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-3 backdrop-blur-sm sm:p-6" role="dialog" aria-modal="true" aria-label={`Preview of ${rec.file_name}`} onClick={() => setShowPreview(false)}>
          <div className="settle flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-line bg-paper-2 shadow-lift" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="eyebrow">Original document</div>
                <div className="truncate text-sm font-medium text-ink">
                  {rec.student_name ?? 'Unnamed'} · {rec.file_name}
                </div>
              </div>
              <button className="btn-ghost" onClick={() => setShowPreview(false)} aria-label="Close preview">
                <X size={15} /> Close
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto [&>div]:mt-0 [&>div]:rounded-none [&>div]:border-0 [&>div]:shadow-none">
              <DocumentPreview preview={preview} fileName={rec.file_name} downloadUrl={api.fileUrl(rec.id)} pageCount={rec.page_count} />
            </div>
          </div>
        </div>
      )}

      {tab === 'text' && (
        <div className="settle settle-3 card mt-4">
          <div className="flex items-center justify-between border-b border-line px-4 py-2">
            <div className="eyebrow">Everything read from the file</div>
            <span className="font-mono text-xs text-slate-500">{rec.raw_text.length.toLocaleString('en-US')} characters</span>
          </div>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap px-5 py-4 font-mono text-[12.5px] leading-6 text-slate-700">{rec.raw_text || 'No text was extracted.'}</pre>
        </div>
      )}
    </div>
  )
}

function Field({
  label,
  value,
  mono,
  editing,
  draft,
  onChange,
}: {
  label: string
  value: string | null
  mono?: boolean
  editing: boolean
  draft?: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      {editing ? (
        <input className={`input mt-1 py-1.5 ${mono ? 'font-mono' : ''}`} value={draft ?? ''} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <div className={`mt-1 text-sm ${mono ? 'font-mono' : ''} ${value ? 'text-ink' : 'text-slate-400'}`}>{value ?? 'Not found'}</div>
      )}
    </div>
  )
}

function NumInput({ value, onChange, placeholder }: { value: number | null; onChange: (v: number | null) => void; placeholder?: string }) {
  return (
    <input
      type="number"
      step="any"
      placeholder={placeholder}
      className="input py-1 text-right font-mono"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
    />
  )
}
