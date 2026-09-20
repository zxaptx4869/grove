/** 下一条消息仅允许覆盖正式 Agent 已支持的上下文行为。 */

import type { ContextMode } from "@/src/knowledge-agent/types";

export interface ModeSelection {
  contextMode: ContextMode;
}

export const DEFAULT_MODES: ModeSelection = { contextMode: "auto" };

export function hasModeOverrides(modes: ModeSelection): boolean {
  return modes.contextMode !== DEFAULT_MODES.contextMode;
}

export function resetModes(_modes: ModeSelection): ModeSelection {
  return { ...DEFAULT_MODES };
}

export function withContextMode(
  modes: ModeSelection,
  contextMode: ContextMode,
): ModeSelection {
  return { ...modes, contextMode };
}
