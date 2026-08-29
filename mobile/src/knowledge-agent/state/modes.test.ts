import {
  DEFAULT_MODES,
  hasModeOverrides,
  resetModes,
  withAnswerMode,
  withContextMode,
} from "@/src/knowledge-agent/state/modes";

test("默认模式无覆盖；非默认值可见", () => {
  expect(hasModeOverrides(DEFAULT_MODES)).toBe(false);
  expect(hasModeOverrides(withContextMode(DEFAULT_MODES, "new_topic"))).toBe(true);
  expect(hasModeOverrides(withAnswerMode(DEFAULT_MODES, "investigate"))).toBe(true);
});

test("成功提交后恢复 auto，不影响下一次发送", () => {
  const overridden = withContextMode(
    withAnswerMode(DEFAULT_MODES, "quick"),
    "continue",
  );
  expect(resetModes(overridden)).toEqual(DEFAULT_MODES);
  expect(resetModes(overridden)).not.toBe(DEFAULT_MODES);
});

test("模式覆盖只作用于下一条消息", () => {
  const next = withAnswerMode(DEFAULT_MODES, "investigate");
  const afterSend = resetModes(next);
  expect(afterSend.answerMode).toBe("auto");
  expect(afterSend.contextMode).toBe("auto");
});
