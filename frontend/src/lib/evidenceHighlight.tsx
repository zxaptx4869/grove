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
const FUZZY_THRESHOLD = 0.75

/** 字符多重集相似度：两个字符串的公共字符比例（0~1）。 */
function charSimilarity(a: string, b: string): number {
  const counts = new Map<string, number>()
  for (const ch of b) {
    counts.set(ch, (counts.get(ch) ?? 0) + 1)
  }
  let matched = 0
  for (const ch of a) {
    const count = counts.get(ch)
    if (count && count > 0) {
      counts.set(ch, count - 1)
      matched += 1
    }
  }
  return matched / Math.max(a.length, b.length, 1)
}

/** 模糊定位：前缀锚点 + 附近滑动窗口取相似度最高的区间。 */
function fuzzyFind(
  normalizedText: string,
  segment: string,
): { start: number; size: number } | null {
  let start = -1
  const prefixLen = Math.min(segment.length, 12)
  for (let len = prefixLen; len >= 6; len--) {
    const index = normalizedText.indexOf(segment.slice(0, len))
    if (index >= 0) {
      start = index
      break
    }
  }
  if (start < 0) return null
  const segmentLen = segment.length
  const windowMin = Math.max(1, Math.floor(segmentLen * 0.85))
  const windowMax = segmentLen + Math.max(5, Math.floor(segmentLen * 0.15))
  const searchStart = Math.max(0, start - windowMax)
  const searchEnd = Math.min(normalizedText.length, start + windowMax + segmentLen)
  let bestRatio = 0
  let bestStart = -1
  let bestSize = 0
  for (let size = windowMin; size <= windowMax; size++) {
    for (let windowStart = searchStart; windowStart <= searchEnd - size; windowStart++) {
      const ratio = charSimilarity(
        normalizedText.slice(windowStart, windowStart + size),
        segment,
      )
      if (ratio > bestRatio) {
        bestRatio = ratio
        bestStart = windowStart
        bestSize = size
      }
    }
  }
  if (bestRatio < FUZZY_THRESHOLD || bestStart < 0) return null
  return { start: bestStart, size: bestSize }
}

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
    let index = normalizedText.indexOf(segments[i], cursor)
    let size = segments[i].length
    if (index < 0) {
      const fuzzy = fuzzyFind(normalizedText, segments[i])
      if (!fuzzy) {
        if (i === 0) return []
        continue
      }
      index = fuzzy.start
      size = fuzzy.size
    }
    const start = map[index]
    const last = map[index + size - 1]
    if (start == null || last == null) return []
    ranges.push({ start, end: last + 1 })
    cursor = index + size
  }
  return ranges
}

/** 按区间渲染高亮片段（多段命中均高亮，带定位标记）。 */
function renderHighlightedRanges(text: string, ranges: EvidenceRange[]): ReactNode {
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

/** 原文中高亮单条证据引用。 */
export function highlightEvidence(text: string, quote?: string): ReactNode {
  const ranges = quote ? findEvidenceRanges(text, quote) : []
  return renderHighlightedRanges(text, ranges)
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
  return renderHighlightedRanges(text, merged)
}
