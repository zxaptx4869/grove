import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { WorkbenchApp } from './WorkbenchApp'
import '../../index.css'
import './workbench.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider>
      <WorkbenchApp />
      <Toaster position="top-center" richColors />
    </TooltipProvider>
  </StrictMode>,
)
