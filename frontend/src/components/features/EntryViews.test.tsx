import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HighlightText } from './EntryViews'

describe('HighlightText', () => {
  it('命中文字染琥珀色，其余原样', () => {
    render(<HighlightText text="闭水试验至少 24 小时，试验要持续观察" query="试验" />)

    const highlighted = screen.getAllByText('试验')
    expect(highlighted).toHaveLength(2)
    for (const node of highlighted) {
      expect(node.className).toContain('text-[#b45309]')
    }
  })

  it('无查询词时原样输出', () => {
    render(<HighlightText text="闭水试验" />)
    expect(screen.getByText('闭水试验').className).toBe('')
  })

  it('大小写不敏感匹配', () => {
    render(<HighlightText text="Waterproof Test Passed" query="test" />)
    expect(screen.getByText('Test').className).toContain('text-[#b45309]')
  })
})
