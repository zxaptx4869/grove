import { render, screen } from '@testing-library/react'
import { toast } from 'sonner'
import { describe, expect, it } from 'vitest'
import { Toaster } from './sonner'

describe('Toaster（sonner 基座）', () => {
  it('可渲染且能显示提示', async () => {
    render(<Toaster />)

    expect(screen.getByLabelText(/Notifications/)).toBeInTheDocument()

    toast.success('基座提示测试')
    expect(await screen.findByText('基座提示测试')).toBeInTheDocument()
  })
})
