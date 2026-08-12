import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { BasicsPage } from './BasicsPage'

describe('BasicsPage', () => {
  it('渲染基座示例页且无报错', () => {
    render(
      <MemoryRouter>
        <BasicsPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '组件基座示例' })).toBeInTheDocument()
    expect(screen.getByText('设计令牌')).toBeInTheDocument()
    expect(screen.getByText('AI 候选')).toBeInTheDocument()
  })
})
