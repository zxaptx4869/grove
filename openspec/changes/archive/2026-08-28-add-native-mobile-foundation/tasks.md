## 1. OpenSpec 与技术决策

- [x] 1.1 完成移动基础、移动会话与用户认证 delta 规格，并运行 `openspec validate --all --strict`
- [x] 1.2 在端侧边界专题中锁定 Expo 原生端技术栈与本 change 的产品边界

## 2. 后端移动认证

- [x] 2.1 新增移动注册、登录、登出 schemas 与 API，复用 Session 哈希存储
- [x] 2.2 扩展认证依赖以支持严格 Bearer 优先级，同时保留 Cookie 行为
- [x] 2.3 增加移动认证、登出、失效会话、冲突凭据和 Workspace 隔离测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_auth.py`

## 3. 原生移动工程

- [x] 3.1 建立独立 Expo Router TypeScript npm 工程、环境变量示例、ESLint、Jest 与开发说明
- [x] 3.2 实现 SecureStore 认证恢复、统一 API 客户端、超时、401 清理和真实项目查询
- [x] 3.3 实现登录/注册、四栏导航、原创 SVG 图标、键盘与安全区壳层及未接入状态
- [x] 3.4 运行 `cd mobile && npm run lint && npm run typecheck && npm test -- --runInBand`

## 4. 验证与收尾

- [x] 4.1 运行后端完整测试与 `cd backend && .venv/bin/ruff check app tests`
- [x] 4.2 记录 API 验证、认证恢复、项目加载、范围切换、401、登出及可用平台的正式结果
- [x] 4.3 执行手动走查后归档 change、同步主规格并完成仅本地提交
