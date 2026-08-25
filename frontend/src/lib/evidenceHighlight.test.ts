import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  findEvidenceRanges,
  highlightEvidence,
  highlightEvidenceAll,
  normalizeText,
} from './evidenceHighlight'

describe('evidenceHighlight', () => {
  it('归一化忽略空白与标点符号', () => {
    expect(normalizeText('3 净水器:\n1) 水槽')).toBe('3净水器1水槽')
  })

  it('归一化忽略全角标点与装饰符号', () => {
    expect(normalizeText('：（）☞✨✅')).toBe('')
  })

  it('归一化英文转小写', () => {
    expect(normalizeText('ABC Water')).toBe('abcwater')
  })

  it('换行差异仍能匹配并映射回原文', () => {
    const text = '3 净水器\n1)水槽下面至少留2个插座'
    const quote = '3 净水器 1)水槽下面至少留2个插座'
    const ranges = findEvidenceRanges(text, quote)
    expect(ranges).toHaveLength(1)
    expect(text.slice(ranges[0].start, ranges[0].end)).toContain('净水器')
  })

  it('全角标点与空格差异可匹配', () => {
    const text = '烟机灶具：分体/集成灶'
    const quote = '烟机灶具: 分体/集成灶'
    expect(findEvidenceRanges(text, quote)).toHaveLength(1)
  })

  it('英文大小写差异可匹配', () => {
    const text = '净水器 Water Filter'
    const quote = 'water filter'
    expect(findEvidenceRanges(text, quote)).toHaveLength(1)
  })

  it('无匹配返回 null', () => {
    expect(findEvidenceRanges('完全没有相关内容', '不存在的引用')).toEqual([])
  })

  it('引用去掉行首装饰符号仍可匹配', () => {
    const text = '☞每层层板后缩2cm，不妨碍放鞋子，但是鞋柜内空气可以流通起来'
    const quote = '每层层板后缩2cm，不妨碍放鞋子，但是鞋柜内空气可以流通起来'
    const ranges = findEvidenceRanges(text, quote)
    expect(ranges).toHaveLength(1)
    expect(text.slice(ranges[0].start, ranges[0].end)).toContain('每层层板后缩')
  })

  it('省略号摘要引用按段匹配并分别高亮', () => {
    const text =
      '厨房灯光 推荐4000k 厨房是食材处理、烹饪操作的功能区，洗菜、切菜需要光线。4000K 色温光线通透明亮'
    const quote = '厨房灯光 推荐4000k 厨房是食材处理…4000K 色温光线通透明亮'
    const ranges = findEvidenceRanges(text, quote)
    expect(ranges).toHaveLength(2)
    expect(text.slice(ranges[0].start, ranges[0].end)).toContain('厨房是食材处理')
    expect(text.slice(ranges[1].start, ranges[1].end)).toContain('4000K 色温')
  })

  it('省略号首段未命中则整体失败', () => {
    expect(
      findEvidenceRanges('完全不相关的内容', '不存在的引用…后面也不存在'),
    ).toEqual([])
  })

  it('highlightEvidence 输出带定位标记的 mark', () => {
    const html = renderToStaticMarkup(highlightEvidence('abc 净水器 xyz', '净水器'))
    expect(html).toContain('<mark')
    expect(html).toContain('data-evidence-highlight')
  })

  it('无引用时返回原文', () => {
    expect(renderToStaticMarkup(highlightEvidence('abc', undefined))).toBe('abc')
  })

  it('多证据引用全部高亮并合并重叠', () => {
    const text = 'A 欧派 ENF 级。B 39800 套餐。C 结束'
    const quotes = ['欧派 ENF 级', 'ENF 级。B 39800']
    const html = renderToStaticMarkup(highlightEvidenceAll(text, quotes))
    expect(html).toContain('<mark')
    expect(html).toContain('data-evidence-highlight')
  })
})
