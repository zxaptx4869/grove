import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DirectoryTreeSelect } from './DirectoryTreeSelect'

const nodes = [
  {
    id: 1,
    name: '空间规划',
    description: null,
    position: 0,
    entry_count: 1,
    children: [
      {
        id: 2,
        name: '客厅',
        description: null,
        position: 0,
        entry_count: 3,
        children: [],
      },
    ],
  },
  {
    id: 3,
    name: '施工',
    description: null,
    position: 1,
    entry_count: 0,
    children: [],
  },
]

describe('DirectoryTreeSelect', () => {
  it('展开子目录并选择节点', async () => {
    const onSelect = vi.fn()
    render(
      <DirectoryTreeSelect nodes={nodes} value={null} ariaLabel="目录" onSelect={onSelect} />,
    )

    await userEvent.click(screen.getByRole('button', { name: '目录' }))
    await userEvent.click(screen.getByRole('button', { name: '展开「空间规划」' }))
    await userEvent.click(screen.getByRole('option', { name: /客厅/ }))

    expect(onSelect).toHaveBeenCalledWith(2)
    expect(screen.queryByRole('option', { name: /客厅/ })).not.toBeInTheDocument()
  })

  it('搜索按名称过滤并展示祖先', async () => {
    const onSelect = vi.fn()
    render(
      <DirectoryTreeSelect nodes={nodes} value={null} ariaLabel="目录" onSelect={onSelect} />,
    )

    await userEvent.click(screen.getByRole('button', { name: '目录' }))
    await userEvent.type(screen.getByLabelText('搜索目录'), '客厅')

    expect(screen.getByRole('option', { name: /空间规划/ })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /客厅/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /施工/ })).not.toBeInTheDocument()
    expect(document.body.querySelector('span.text-ai-candidate')?.textContent).toBe('客厅')
  })

  it('允许选择根目录', async () => {
    const onSelect = vi.fn()
    render(
      <DirectoryTreeSelect
        nodes={nodes}
        value={null}
        allowRoot
        ariaLabel="目录"
        onSelect={onSelect}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: '目录' }))
    await userEvent.click(screen.getByRole('option', { name: '根目录' }))

    expect(onSelect).toHaveBeenCalledWith(null)
  })
})
