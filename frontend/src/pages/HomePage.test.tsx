import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { HomePage } from './HomePage'

describe('HomePage', () => {
  it('渲染 Grove 标题与产品定位', () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '知林 Grove' })).toBeInTheDocument()
    expect(screen.getByText(/个人知识管家/)).toBeInTheDocument()
  })
})
