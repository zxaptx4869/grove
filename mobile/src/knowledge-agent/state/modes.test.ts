import {
  DEFAULT_MODES,
  hasModeOverrides,
  resetModes,
  withContextMode,
} from "@/src/knowledge-agent/state/modes";

test("提问设置只保留上下文覆盖", () => {
  expect(DEFAULT_MODES).toEqual({ contextMode: "auto" });
  const next = withContextMode(DEFAULT_MODES, "new_topic");
  expect(hasModeOverrides(next)).toBe(true);
  expect(resetModes(next)).toEqual({ contextMode: "auto" });
});
