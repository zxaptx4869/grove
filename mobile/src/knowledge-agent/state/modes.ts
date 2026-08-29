/** 一次性模式覆盖：理解方式与回答方式只作用于下一条消息。 */

import type { AnswerMode, ContextMode } from "@/src/knowledge-agent/types";

export interface ModeSelection {
  contextMode: ContextMode;
  answerMode: AnswerMode;
}

export const DEFAULT_MODES: ModeSelection = {
  contextMode: "auto",
  answerMode: "auto",
};

export function hasModeOverrides(modes: ModeSelection): boolean {
  return (
    modes.contextMode !== DEFAULT_MODES.contextMode ||
    modes.answerMode !== DEFAULT_MODES.answerMode
  );
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

export function withAnswerMode(
  modes: ModeSelection,
  answerMode: AnswerMode,
): ModeSelection {
  return { ...modes, answerMode };
}
