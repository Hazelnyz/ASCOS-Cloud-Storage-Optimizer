import { File, FileArchive, FileAudio, FileCode, FileImage, FileSpreadsheet, FileText, FileVideo } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

type Kind = 'image' | 'video' | 'audio' | 'archive' | 'code' | 'sheet' | 'doc' | 'other'

const EXTENSIONS: Record<Exclude<Kind, 'other'>, string[]> = {
  image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'heic'],
  video: ['mp4', 'mov', 'mkv', 'avi', 'webm'],
  audio: ['mp3', 'wav', 'flac', 'm4a', 'ogg'],
  archive: ['zip', 'tar', 'gz', 'tgz', '7z', 'rar'],
  code: ['js', 'ts', 'tsx', 'jsx', 'py', 'java', 'c', 'cpp', 'go', 'rs', 'json', 'html', 'css', 'sh', 'yml', 'yaml', 'tf'],
  sheet: ['xls', 'xlsx', 'csv', 'tsv'],
  doc: ['pdf', 'doc', 'docx', 'txt', 'md', 'rtf', 'ppt', 'pptx'],
}

const ICONS: Record<Kind, LucideIcon> = {
  image: FileImage,
  video: FileVideo,
  audio: FileAudio,
  archive: FileArchive,
  code: FileCode,
  sheet: FileSpreadsheet,
  doc: FileText,
  other: File,
}

function kindOf(filename: string | null): Kind {
  if (!filename) return 'other'
  const dot = filename.lastIndexOf('.')
  if (dot < 0) return 'other'
  const ext = filename.slice(dot + 1).toLowerCase()
  for (const kind of Object.keys(EXTENSIONS) as Array<Exclude<Kind, 'other'>>) {
    if (EXTENSIONS[kind].includes(ext)) return kind
  }
  return 'other'
}

const KIND_LABEL: Record<Kind, string> = {
  image: 'Image', video: 'Video', audio: 'Audio', archive: 'Archive', code: 'Code', sheet: 'Spreadsheet', doc: 'Document', other: 'File',
}

/** Short type description derived from the extension, e.g. "PDF · Document" (not a stored category). */
export function fileKindLabel(filename: string | null): string {
  if (!filename) return 'Unknown type'
  const dot = filename.lastIndexOf('.')
  const ext = dot > 0 && dot < filename.length - 1 ? filename.slice(dot + 1).toUpperCase() : null
  const kind = KIND_LABEL[kindOf(filename)]
  return ext ? `${ext} · ${kind}` : kind
}

/** Decorative icon chip chosen from the filename's extension (purely visual; the name is the accessible label). */
export function FileTypeIcon({ filename }: { filename: string | null }) {
  const Icon = ICONS[kindOf(filename)]
  return (
    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-surface-border bg-white/[0.03] text-slate-400" aria-hidden="true">
      <Icon className="h-4 w-4" />
    </span>
  )
}
