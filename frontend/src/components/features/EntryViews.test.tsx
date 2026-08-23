import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { EntryCard, EntryList, HighlightText } from './EntryViews'
import type { EntryPayload } from '@/lib/api'

const ENTRY: EntryPayload = {
  id: 1,
  project_id: 10,
  node_id: 20,
  node_name: '施工',
  title: '闭水试验时长',
  content: '闭水试验至少持续 24 小时',
  main_type: 'knowledge',
  info_nature: 'fact',
  applicable_condition: null,
  note: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-02T00:00:00Z',
  evidences: [],
}

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

describe('EntryCard 操作按钮', () => {
  it('渲染编辑 / AI 修订建议 / 版本历史 / 相关知识按钮并触发回调', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    const onAiRevise = vi.fn()
    const onVersionHistory = vi.fn()
    const onShowSimilar = vi.fn()
    render(
      <EntryCard
        entry={ENTRY}
        onEdit={onEdit}
        onAiRevise={onAiRevise}
        onVersionHistory={onVersionHistory}
        onShowSimilar={onShowSimilar}
      />,
    )

    await user.click(screen.getByRole('button', { name: /编辑「闭水试验时长」/ }))
    await user.click(screen.getByRole('button', { name: /AI 修订建议/ }))
    await user.click(screen.getByRole('button', { name: /版本历史/ }))
    await user.click(screen.getByRole('button', { name: '相关知识' }))

    expect(onEdit).toHaveBeenCalledWith(ENTRY)
    expect(onAiRevise).toHaveBeenCalledWith(ENTRY)
    expect(onVersionHistory).toHaveBeenCalledWith(ENTRY)
    expect(onShowSimilar).toHaveBeenCalledWith(ENTRY)
  })

  it('无回调时不渲染操作区', () => {
    const { container } = render(<EntryCard entry={ENTRY} />)
    expect(container.querySelector('button')).toBeNull()
  })
})

describe('EntryList 操作列', () => {
  it('渲染操作按钮并触发回调', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    const onAiRevise = vi.fn()
    const onVersionHistory = vi.fn()
    render(
      <EntryList
        entries={[ENTRY]}
        onEdit={onEdit}
        onAiRevise={onAiRevise}
        onVersionHistory={onVersionHistory}
      />,
    )

    await user.click(screen.getByRole('button', { name: /编辑「闭水试验时长」/ }))
    await user.click(screen.getByRole('button', { name: /AI 修订建议/ }))
    await user.click(screen.getByRole('button', { name: /版本历史/ }))

    expect(onEdit).toHaveBeenCalledWith(ENTRY)
    expect(onAiRevise).toHaveBeenCalledWith(ENTRY)
    expect(onVersionHistory).toHaveBeenCalledWith(ENTRY)
  })
})
