/** 一次性模式覆盖：理解方式、回答方式与结果形式只作用于下一条消息。 */

import type {
  AnswerMode,
  ContextMode,
  ResultMode,
} from "@/src/knowledge-agent/types";

export interface ModeSelection {
  contextMode: ContextMode;
  answerMode: AnswerMode;
  resultMode: ResultMode;
}

export const DEFAULT_MODES: ModeSelection = {
  contextMode: "auto",
  answerMode: "auto",
  resultMode: "auto",
};

export function hasModeOverrides(modes: ModeSelection): boolean {
  return (
    modes.contextMode !== DEFAULT_MODES.contextMode ||
    modes.answerMode !== DEFAULT_MODES.answerMode ||
    modes.resultMode !== DEFAULT_MODES.resultMode
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

export function withResultMode(
  modes: ModeSelection,
  resultMode: ResultMode,
): ModeSelection {
  return { ...modes, resultMode };
}
