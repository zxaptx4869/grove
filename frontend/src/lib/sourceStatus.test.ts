import { describe, expect, it } from 'vitest'

import {
  isProcessingNotStarted,
  needsProcessingRetry,
  processingRetryLabel,
  sourceStatusClass,
  sourceStatusLabel,
} from './sourceStatus'

describe('来源处理状态口径', () => {
  it('等待处理但没有处理任务才算处理未启动', () => {
    expect(isProcessingNotStarted({ status: 'waiting', has_processing_task: false })).toBe(true)
    expect(isProcessingNotStarted({ status: 'waiting', has_processing_task: true })).toBe(false)
    expect(isProcessingNotStarted({ status: 'processing', has_processing_task: false })).toBe(false)
  })

  it('状态文案区分未启动、等待处理、处理中、提取完成与失败', () => {
    expect(sourceStatusLabel({ status: 'waiting', has_processing_task: false })).toBe('处理未启动')
    expect(sourceStatusLabel({ status: 'waiting', has_processing_task: true })).toBe('等待处理')
    expect(sourceStatusLabel({ status: 'processing', has_processing_task: true })).toBe('处理中')
    expect(sourceStatusLabel({ status: 'done', has_processing_task: true })).toBe('提取完成')
    expect(sourceStatusLabel({ status: 'failed', has_processing_task: true })).toBe('失败')
  })

  it('未启动用警告色，与移动端 risk 同色', () => {
    expect(sourceStatusClass({ status: 'waiting', has_processing_task: false })).toBe(
      'bg-warning-soft text-warning',
    )
  })

  it('只有失败与未启动提供重试入口，且文案区分', () => {
    expect(needsProcessingRetry({ status: 'failed', has_processing_task: true })).toBe(true)
    expect(needsProcessingRetry({ status: 'waiting', has_processing_task: false })).toBe(true)
    expect(needsProcessingRetry({ status: 'waiting', has_processing_task: true })).toBe(false)
    expect(needsProcessingRetry({ status: 'processing', has_processing_task: true })).toBe(false)
    expect(needsProcessingRetry({ status: 'done', has_processing_task: true })).toBe(false)

    expect(processingRetryLabel({ status: 'failed', has_processing_task: true })).toBe('重试')
    expect(processingRetryLabel({ status: 'waiting', has_processing_task: false })).toBe('重试处理')
  })
})
