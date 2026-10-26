import type { ReactNode } from 'react'

// A small, safe Markdown renderer for what the agents write (proposals, memos, chat replies).
// It builds React elements, never raw HTML, so model output cannot inject scripts or markup.
// Supports: # headings, paragraphs, - and 1. lists, | tables |, > quotes, ``` code blocks ```,
// **bold**, *italic*, `code`, and links to https://, mailto: or in-app pages (#/deals/...).

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*)/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    const k = `${keyBase}-${i++}`
    if (tok.startsWith('**')) out.push(<strong key={k}>{tok.slice(2, -2)}</strong>)
    else if (tok.startsWith('`')) out.push(<code key={k}>{tok.slice(1, -1)}</code>)
    else if (tok.startsWith('[')) {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok)
      const label = lm?.[1] ?? tok
      const href = lm?.[2] ?? ''
      if (/^#\//.test(href)) out.push(<a key={k} href={href}>{label}</a>)
      else if (/^(https?:|mailto:)/i.test(href))
        out.push(<a key={k} href={href} target="_blank" rel="noreferrer noopener">{label}</a>)
      else out.push(label)
    } else out.push(<em key={k}>{tok.slice(1, -1)}</em>)
    last = m.index + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const isTableRow = (l: string) => /^\s*\|.*\|\s*$/.test(l)
const isSep = (l: string) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(l)
const cells = (l: string) => l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())
const BULLET = /^\s*[-*•]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/
const BLOCK_START = /^(#{1,4}\s|\s*[-*•]\s+|\s*\d+[.)]\s+|\s*>|\s*\||\s*```)/

export function Markdown({ text, dark, variant = 'doc' }: { text: string; dark?: boolean; variant?: 'doc' | 'chat' }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let k = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i++
      continue
    }
    if (/^\s*```/.test(line)) {
      const code: string[] = []
      i++
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++])
      i++
      blocks.push(<pre key={k++}><code>{code.join('\n')}</code></pre>)
      continue
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) {
      const level = h[1].length
      const content = inline(h[2], `h${k}`)
      blocks.push(level === 1 ? <h1 key={k++}>{content}</h1> : level === 2 ? <h2 key={k++}>{content}</h2> : <h3 key={k++}>{content}</h3>)
      i++
      continue
    }
    if (isTableRow(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
      const head = cells(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && isTableRow(lines[i])) rows.push(cells(lines[i++]))
      blocks.push(
        <table key={k++}>
          <thead>
            <tr>{head.map((c, j) => <th key={j}>{inline(c, `th${k}-${j}`)}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `td${k}-${ri}-${j}`)}</td>)}</tr>
            ))}
          </tbody>
        </table>,
      )
      continue
    }
    if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line)
      const re = ordered ? NUMBERED : BULLET
      const items: string[] = []
      while (i < lines.length && re.test(lines[i])) items.push(lines[i++].replace(re, ''))
      const lis = items.map((it, j) => <li key={j}>{inline(it, `li${k}-${j}`)}</li>)
      blocks.push(ordered ? <ol key={k++}>{lis}</ol> : <ul key={k++}>{lis}</ul>)
      continue
    }
    if (/^\s*>/.test(line)) {
      const q: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ''))
      blocks.push(<blockquote key={k++}>{inline(q.join(' '), `q${k}`)}</blockquote>)
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !BLOCK_START.test(lines[i])) para.push(lines[i++])
    if (para.length === 0) para.push(lines[i++])
    blocks.push(<p key={k++}>{inline(para.join(' '), `p${k}`)}</p>)
  }
  if (variant === 'chat') return <div className="md">{blocks}</div>
  return <div className={`doc ${dark ? 'dark' : ''}`}>{blocks}</div>
}

// Standalone HTML for download/print. Escapes everything, then applies the same small subset.
export function markdownToHtml(md: string, title: string): string {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  const inl = (s: string) =>
    esc(s)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const l = lines[i]
    if (!l.trim()) { i++; continue }
    const h = /^(#{1,4})\s+(.*)$/.exec(l)
    if (h) { const n = Math.min(3, h[1].length); out.push(`<h${n}>${inl(h[2])}</h${n}>`); i++; continue }
    if (isTableRow(l) && i + 1 < lines.length && isSep(lines[i + 1])) {
      const head = cells(l); i += 2
      const rows: string[] = []
      while (i < lines.length && isTableRow(lines[i])) rows.push('<tr>' + cells(lines[i++]).map((c) => `<td>${inl(c)}</td>`).join('') + '</tr>')
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inl(c)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`)
      continue
    }
    if (BULLET.test(l)) {
      const items: string[] = []
      while (i < lines.length && BULLET.test(lines[i])) items.push(`<li>${inl(lines[i++].replace(BULLET, ''))}</li>`)
      out.push(`<ul>${items.join('')}</ul>`); continue
    }
    if (/^\s*>/.test(l)) {
      const q: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ''))
      out.push(`<blockquote>${inl(q.join(' '))}</blockquote>`); continue
    }
    const p: string[] = []
    while (i < lines.length && lines[i].trim() && !BLOCK_START.test(lines[i])) p.push(lines[i++])
    if (!p.length) p.push(lines[i++])
    out.push(`<p>${inl(p.join(' '))}</p>`)
  }
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title><style>
body{font:14px/1.6 "Libre Franklin","Segoe UI",system-ui,sans-serif;color:#18233a;max-width:860px;margin:40px auto;padding:0 24px}
h1{color:#0a2463;font-size:26px}h2{color:#0a2463;border-bottom:2px solid #dbe8fb;padding-bottom:4px;margin-top:28px;font-size:18px}
h3{color:#0d3482}table{border-collapse:collapse;width:100%;margin:10px 0 14px;font-size:13px}
th{background:#eef4fd;text-align:left;padding:7px 9px;border:1px solid #d5e2f5}td{padding:7px 9px;border:1px solid #e1e9f4;vertical-align:top}
blockquote{border-left:4px solid #e0a52d;background:#fff6e2;padding:8px 12px;margin:8px 0}
</style></head><body>${out.join('\n')}</body></html>`
}
