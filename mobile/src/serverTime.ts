/**
 * 服务端时间解析口径（原生端唯一实现）。
 *
 * 后端统一输出 UTC 带偏移的时间串；历史裸串（旧数据或直接读库的调试路径）不带时区，
 * 按 UTC 解释才不会整体差一个时区（东八区下差 8 小时，真机走查：几分钟前采集的显示成 7:23，
 * 刚结束的对话显示成 8 小时前）。已带偏移的串按原偏移解析，不二次偏移。
 */

const OFFSET_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/;

/** 把服务端时间串解析为时间点；无法解析时返回 Invalid Date，由调用方给兜底文案。 */
export function parseServerTime(value: string): Date {
  return new Date(OFFSET_PATTERN.test(value) ? value : `${value}Z`);
}
