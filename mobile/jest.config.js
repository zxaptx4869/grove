module.exports = {
  preset: "jest-expo",
  testMatch: ["**/*.test.ts", "**/*.test.tsx"],
  // RNTL v14 与 TanStack Query 的假定时器/GC 句柄会让 jest 正常结束阶段挂起；
  // 测试本身全部通过，forceExit 只跳过“等待句柄”这一步。
  forceExit: true,
};
