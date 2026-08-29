module.exports = {
  preset: "jest-expo",
  testMatch: ["**/*.test.ts", "**/*.test.tsx"],
  // 已知工程债：RNTL v14 + TanStack Query 在假定时器测试后遗留句柄，
  // 测试全部通过但 jest 正常结束阶段会挂起；gcTime=0 与 client.clear() 均不能
  // 消除该句柄，暂以 forceExit 兜底，后续定位到具体句柄来源后再移除。
  forceExit: true,
};
