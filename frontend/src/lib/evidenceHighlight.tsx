// 证据高亮工具：归一化匹配 + 高亮片段（含 JSX，故用 .tsx）
import type { ReactNode } from 'react'

export interface EvidenceRange {
  start: number
  end: number
}

/** 归一化：仅保留字母/数字/CJK，其余符号（空白、标点、装饰符号等）全部忽略，英文转小写。 */
export function normalizeText(text: string): string {
  return text.replace(/[^\p{L}\p{N}]/gu, '').toLowerCase()
}

/** 构建「归一化字符位置 → 原文索引」映射（跳过原文中非字母/数字字符）。 */
function buildIndexMap(text: string): number[] {
  const map: number[] = []
  let normalizedPosition = 0
  for (let i = 0; i < text.length; i++) {
    if (!/[\p{L}\p{N}]/u.test(text[i])) continue
    map[normalizedPosition] = i
    normalizedPosition += 1
  }
  return map
}

/** 引用按省略号拆段（AI 生成的摘要式引用会跳过原文内容）。 */
const QUOTE_SEGMENT_SPLIT = /…|\.{2,}/

/**
 * 分段归一化匹配引用，返回全部命中区间的原文索引。
 * 引用按省略号拆成多段，逐段在原文中顺序查找；第一段未命中视为整体失败。
 */
export function findEvidenceRanges(text: string, quote: string): EvidenceRange[] {
  if (!quote) return []
  const segments = quote
    .split(QUOTE_SEGMENT_SPLIT)
    .map(normalizeText)
    .filter(Boolean)
  if (segments.length === 0) return []
  const normalizedText = normalizeText(text)
  const map = buildIndexMap(text)
  const ranges: EvidenceRange[] = []
  let cursor = 0
  for (let i = 0; i < segments.length; i++) {
    const index = normalizedText.indexOf(segments[i], cursor)
    if (index < 0) {
      if (i === 0) return []
      continue
    }
    const start = map[index]
    const last = map[index + segments[i].length - 1]
    if (start == null || last == null) return []
    ranges.push({ start, end: last + 1 })
    cursor = index + segments[i].length
  }
  return ranges
}

/** 原文中高亮证据引用（多段命中均高亮，带定位标记）。 */
export function highlightEvidence(text: string, quote?: string): ReactNode {
  const ranges = quote ? findEvidenceRanges(text, quote) : []
  if (ranges.length === 0) return text
  const nodes: ReactNode[] = []
  let cursor = 0
  ranges.forEach((range, index) => {
    nodes.push(text.slice(cursor, range.start))
    nodes.push(
      <mark key={index} data-evidence-highlight className="rounded bg-amber-100 text-foreground">
        {text.slice(range.start, range.end)}
      </mark>,
    )
    cursor = range.end
  })
  nodes.push(text.slice(cursor))
  return nodes
}

/** 高亮同一附件的多条证据引用（区间合并去重后统一渲染）。 */
export function highlightEvidenceAll(text: string, quotes: string[]): ReactNode {
  const collected = quotes.flatMap((quote) => findEvidenceRanges(text, quote))
  if (collected.length === 0) return text
  const merged = collected
    .sort((a, b) => a.start - b.start)
    .reduce<EvidenceRange[]>((acc, range) => {
      const last = acc[acc.length - 1]
      if (last && range.start <= last.end) {
        last.end = Math.max(last.end, range.end)
      } else {
        acc.push({ ...range })
      }
      return acc
    }, [])
  const nodes: ReactNode[] = []
  let cursor = 0
  merged.forEach((range, index) => {
    nodes.push(text.slice(cursor, range.start))
    nodes.push(
      <mark key={index} data-evidence-highlight className="rounded bg-amber-100 text-foreground">
        {text.slice(range.start, range.end)}
      </mark>,
    )
    cursor = range.end
  })
  nodes.push(text.slice(cursor))
  return nodes
}
