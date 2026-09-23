/** 批次标识：一次采集动作一个 UUID，提交单元的键与批次内序号组合。 */

import { randomUUID } from "expo-crypto";

export function newBatchId(): string {
  return randomUUID();
}
