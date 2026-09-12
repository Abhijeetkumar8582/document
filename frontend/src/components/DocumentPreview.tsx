import { Download, ExternalLink, FileWarning, Loader2 } from 'lucide-react'
import { absolute, type Preview } from '../api'

/**
 * Shows the original upload inline from a short-lived signed link.
 * PDFs use the browser's own viewer; images render directly; anything else offers the download.
 */
export function DocumentPreview({
  preview,
  fileName,
  downloadUrl,
  pageCount,
}: {
  preview: Preview | null | 'missing'
  fileName: string
  downloadUrl: string
  pageCount: number
}) {
  if (preview === null) {
    return (
      <div className="settle settle-3 card mt-4 flex items-center justify-center gap-2 px-6 py-16 text-sm text-slate-500">
        <Loader2 size={15} className="animate-spin" /> Getting a signed link to the document…
      </div>
    )
  }
  if (preview === 'missing') {
    return (
      <div className="settle settle-3 card mt-4 flex items-start gap-3 px-6 py-8 text-sm">
        <FileWarning size={18} className="mt-0.5 shrink-0 text-seal" />
        <div>
          <div className="font-medium text-ink">The original file is no longer in storage.</div>
          <div className="text-slate-500">The extracted data is still here, but the document itself cannot be shown or downloaded.</div>
        </div>
      </div>
    )
  }

  const expires = new Date(preview.expires_at * 1000)
  return (
    <div className="settle settle-3 card mt-4 overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-2">
        <div className="eyebrow">Original document</div>
        <span className="truncate font-mono text-xs text-slate-500">{fileName}</span>
        {preview.kind === 'pdf' && pageCount > 0 && (
          <span className="font-mono text-xs text-slate-500">
            {pageCount} {pageCount === 1 ? 'page' : 'pages'}
          </span>
        )}
        <span className="ml-auto font-mono text-[11px] text-slate-400" title={`Signed link valid until ${expires.toLocaleTimeString('en-US')}`}>
          {preview.backend === 's3' ? 'served from bucket' : 'served locally'} · link renews automatically
        </span>
        <a href={absolute(preview.url)} target="_blank" rel="noreferrer" className="btn-ghost px-2 py-1 text-xs">
          <ExternalLink size={13} /> Open
        </a>
        <a href={downloadUrl} className="btn-ghost px-2 py-1 text-xs">
          <Download size={13} /> Download
        </a>
      </div>

      {preview.kind === 'pdf' && (
        <iframe
          key={preview.url}
          src={`${absolute(preview.url)}#toolbar=1&view=FitH`}
          title={`Preview of ${fileName}`}
          className="block h-[78vh] w-full bg-slate-100"
        />
      )}
      {preview.kind === 'image' && (
        <div className="flex justify-center bg-slate-100 p-4">
          <img key={preview.url} src={absolute(preview.url)} alt={`Scan: ${fileName}`} className="max-h-[78vh] w-auto max-w-full rounded shadow-lift" />
        </div>
      )}
      {preview.kind === 'other' && (
        <div className="px-6 py-10 text-center text-sm text-slate-500">
          Word and text files have no inline preview. Use <span className="font-medium text-ink">Download</span> to open the original, or read the
          extracted text tab.
        </div>
      )}
    </div>
  )
}
