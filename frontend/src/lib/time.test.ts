import { describe, expect, it } from 'vitest'

import { formatServerTime, parseServerTime } from './time'

const UTC = '2026-09-29T07:23:51'

describe('parseServerTime', () => {
  it('不带时区的串按 UTC 解析', () => {
    expect(parseServerTime(UTC).getTime()).toBe(Date.parse(`${UTC}Z`))
  })

  it('带 Z 或 +00:00 的串不重复偏移', () => {
    expect(parseServerTime(`${UTC}Z`).getTime()).toBe(parseServerTime(UTC).getTime())
    expect(parseServerTime(`${UTC}+00:00`).getTime()).toBe(parseServerTime(UTC).getTime())
  })

  it('东八区下 07:23 渲染为 15:23', () => {
    const rendered = new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'Asia/Shanghai',
    }).format(parseServerTime(UTC))

    expect(rendered).toBe('15:23')
  })

  it('带非零偏移的串按原偏移解析', () => {
    expect(parseServerTime('2026-09-29T15:23:51+08:00').getTime()).toBe(
      parseServerTime(UTC).getTime(),
    )
  })

  it('无法解析时返回 Invalid Date', () => {
    expect(Number.isNaN(parseServerTime('不是时间').getTime())).toBe(true)
    expect(formatServerTime('不是时间', { hour: '2-digit' }, '—')).toBe('—')
  })
})

describe('formatServerTime', () => {
  it('空值走兜底文案', () => {
    expect(formatServerTime(null, { year: 'numeric' }, '—')).toBe('—')
    expect(formatServerTime(undefined, { year: 'numeric' }, '—')).toBe('—')
  })

  it('裸串与带 Z 的串渲染一致', () => {
    const options: Intl.DateTimeFormatOptions = {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }

    expect(formatServerTime(UTC, options)).toBe(formatServerTime(`${UTC}Z`, options))
  })
})
