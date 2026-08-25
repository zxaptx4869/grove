import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { findEvidenceRange, highlightEvidence, normalizeText } from './evidenceHighlight'

describe('evidenceHighlight', () => {
  it('归一化去除全部空白', () => {
    expect(normalizeText('3 净水器:\n1) 水槽')).toBe('3净水器:1)水槽')
  })

  it('归一化全角转半角', () => {
    expect(normalizeText('：（）')).toBe(':()')
  })

  it('归一化英文转小写', () => {
    expect(normalizeText('ABC Water')).toBe('abcwater')
  })

  it('换行差异仍能匹配并映射回原文', () => {
    const text = '3 净水器\n1)水槽下面至少留2个插座'
    const quote = '3 净水器 1)水槽下面至少留2个插座'
    const range = findEvidenceRange(text, quote)
    expect(range).not.toBeNull()
    expect(text.slice(range!.start, range!.end)).toContain('净水器')
  })

  it('全角标点与空格差异可匹配', () => {
    const text = '烟机灶具：分体/集成灶'
    const quote = '烟机灶具: 分体/集成灶'
    expect(findEvidenceRange(text, quote)).not.toBeNull()
  })

  it('英文大小写差异可匹配', () => {
    const text = '净水器 Water Filter'
    const quote = 'water filter'
    expect(findEvidenceRange(text, quote)).not.toBeNull()
  })

  it('无匹配返回 null', () => {
    expect(findEvidenceRange('完全没有相关内容', '不存在的引用')).toBeNull()
  })

  it('highlightEvidence 输出带定位标记的 mark', () => {
    const html = renderToStaticMarkup(highlightEvidence('abc 净水器 xyz', '净水器'))
    expect(html).toContain('<mark')
    expect(html).toContain('data-evidence-highlight')
  })

  it('无引用时返回原文', () => {
    expect(renderToStaticMarkup(highlightEvidence('abc', undefined))).toBe('abc')
  })
})
