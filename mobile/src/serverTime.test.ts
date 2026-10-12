import { parseServerTime } from "@/src/serverTime";

const UTC = "2026-09-29T07:23:51";

test("不带时区的服务端时间按 UTC 解析", () => {
  expect(parseServerTime(UTC).getTime()).toBe(Date.parse(`${UTC}Z`));
});

test("带 Z 与 +00:00 的串不重复偏移", () => {
  expect(parseServerTime(`${UTC}Z`).getTime()).toBe(parseServerTime(UTC).getTime());
  expect(parseServerTime(`${UTC}+00:00`).getTime()).toBe(parseServerTime(UTC).getTime());
});

test("带非零偏移的串按原偏移解析为同一时刻", () => {
  expect(parseServerTime("2026-09-29T15:23:51+08:00").getTime()).toBe(
    parseServerTime(UTC).getTime(),
  );
});

test("东八区下 07:23 渲染为 15:23", () => {
  const rendered = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(parseServerTime(UTC));

  expect(rendered).toBe("15:23");
});

test("无法解析时返回 Invalid Date，由调用方兜底", () => {
  expect(Number.isNaN(parseServerTime("不是时间").getTime())).toBe(true);
});
