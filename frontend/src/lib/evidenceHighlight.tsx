// 证据高亮工具：归一化匹配 + 高亮片段（含 JSX，故用 .tsx）
import type { ReactNode } from 'react'

export interface EvidenceRange {
  start: number
  end: number
}

/** 归一化：去全部空白、全角标点转半角、英文转小写。 */
export function normalizeText(text: string): string {
  return text
    .replace(/\s+/g, '')
    .replace(/[\uFF01-\uFF5E]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0xfee0))
    .toLowerCase()
}

/** 构建「归一化字符位置 → 原文索引」映射（跳过原文空白）。 */
function buildIndexMap(text: string): number[] {
  const map: number[] = []
  let normalizedPosition = 0
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i])) continue
    map[normalizedPosition] = i
    normalizedPosition += 1
  }
  return map
}

/** 归一化匹配引用，返回命中区间的原文索引；无命中返回 null。 */
export function findEvidenceRange(text: string, quote: string): EvidenceRange | null {
  if (!quote) return null
  const normalizedText = normalizeText(text)
  const normalizedQuote = normalizeText(quote)
  if (!normalizedQuote) return null
  const index = normalizedText.indexOf(normalizedQuote)
  if (index < 0) return null
  const map = buildIndexMap(text)
  const start = map[index]
  const last = map[index + normalizedQuote.length - 1]
  if (start == null || last == null) return null
  return { start, end: last + 1 }
}

/** 原文中高亮证据引用（命中区间包 <mark>，带定位标记）。 */
export function highlightEvidence(text: string, quote?: string): ReactNode {
  const range = quote ? findEvidenceRange(text, quote) : null
  if (!range) return text
  return (
    <>
      {text.slice(0, range.start)}
      <mark
        data-evidence-highlight
        className="rounded bg-amber-100 text-foreground"
      >
        {text.slice(range.start, range.end)}
      </mark>
      {text.slice(range.end)}
    </>
  )
}
