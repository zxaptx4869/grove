/**
 * 服务端时间解析口径（Web 唯一实现）。
 *
 * 后端统一输出 UTC 带偏移的时间串；历史裸串（旧数据或直接读库的调试路径）不带时区，
 * 按 UTC 解释才不会整体差一个时区（东八区下差 8 小时）。已带偏移的串直接按原偏移解析，
 * 不二次偏移。展示格式由各调用点自己决定，本模块只负责「解析成时间点」。
 */

const OFFSET_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/

/** 把服务端时间串解析为时间点；无法解析时返回 Invalid Date，由调用方给兜底文案。 */
export function parseServerTime(value: string): Date {
  return new Date(OFFSET_PATTERN.test(value) ? value : `${value}Z`)
}

/**
 * 按传入的 Intl 选项格式化服务端时间串。
 *
 * @param value 服务端时间串（允许 null/undefined，走 fallback）
 * @param options Intl.DateTimeFormat 选项，由调用点决定显示格式
 * @param fallback 空值或无法解析时的兜底文案
 */
export function formatServerTime(
  value: string | null | undefined,
  options: Intl.DateTimeFormatOptions,
  fallback = '',
): string {
  if (!value) return fallback
  const date = parseServerTime(value)
  if (Number.isNaN(date.getTime())) return fallback
  return new Intl.DateTimeFormat('zh-CN', options).format(date)
}
