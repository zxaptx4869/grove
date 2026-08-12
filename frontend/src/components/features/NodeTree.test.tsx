import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { NodeTree, type NodeTreeCallbacks } from './NodeTree'

const NODES = [
  { id: 1, name: '节点1', description: null, position: 0, children: [] },
  { id: 2, name: '节点2', description: null, position: 1, children: [] },
]

describe('NodeTree', () => {
  it('点击下移触发排序回调', async () => {
    const callbacks: NodeTreeCallbacks = {
      onAddChild: vi.fn(),
      onRename: vi.fn(),
      onDelete: vi.fn(),
      onReorder: vi.fn(),
    }
    render(<NodeTree nodes={NODES} callbacks={callbacks} />)

    await userEvent.click(screen.getByRole('button', { name: '下移 节点1' }))

    expect(callbacks.onReorder).toHaveBeenCalledWith(null, [2, 1])
  })

  it('渲染空目录提示', () => {
    render(<NodeTree nodes={[]} callbacks={{ onAddChild: vi.fn(), onRename: vi.fn(), onDelete: vi.fn(), onReorder: vi.fn() }} />)

    expect(screen.getByText(/目录为空/)).toBeInTheDocument()
  })
})
