# add-structured-answer-points 实施与验收记录

日期：2026-08-30
分支：`codex/add-structured-answer-points`

## 实施范围

回答协议新增可选 `points` 结构化字段（`section` / `text` / 逐条 `citations`），回答模型
升级为输出 `lead` + `points`，服务端逐条重验句柄并确定性拼接 `answer` 文本；原生回答卡
在有 `points` 时渲染「分组标题 + 正文行内上标序号 + 底部按序号来源区」要点卡，无 `points`
的历史回答回退到现有纯文本 + 底部来源条。不改变草稿/确认协议、正式 Entry 语义与 Web
展示。

## 真机反馈后的展示修订（2026-08-30，两轮）

- 第一版「每条要点下方一个来源 chip」：真机反馈在「一条要点 = 一条 Entry」时来源标题与
  要点内容高度重复、显得多余；
- 第二版「行内上标 + 底部按序号来源区」：真机反馈来源全部铺开太长，且用户希望保留每条
  要点左侧的连续编号圆点；
- 最终方案：分组标题 + 每条要点左侧连续编号圆点 + 正文，要点内不展示任何来源；底部统一
  保留 `CitationStrip`「全部来源速览」（有 `points` 与无 `points` 一致）；逐条绑定只保留
  在数据层。相应更新 `design.md` 决策 5 与 `native-knowledge-agent-answer` delta spec。

## 真实命令与结果

### 实施前基线（任务 1.3）

```bash
cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_evidence.py -W error
# 28 passed

cd mobile && npm test -- --runInBand && npm run lint && npx tsc --noEmit
# 10 suites / 71 tests passed；lint 与 typecheck 通过
```

### 后端

```bash
cd backend && .venv/bin/python -m pytest -W error
# 全部通过（原有 432 + 新增 4 项 points 单测）

cd backend && .venv/bin/ruff check app tests
# All checks passed!
```

新增单测（`tests/test_knowledge_agent_evidence.py`）：

- `test_build_validated_answer_points_compose_and_validate`：lead + 分组要点拼接、逐条
  citations 派生、句柄清洗；
- `test_build_validated_answer_points_drop_invalid_marks_partial`：无有效句柄要点丢弃并
  标记 partial；
- `test_build_validated_answer_points_all_invalid_insufficient`：全部要点失效返回
  insufficient；
- `test_build_validated_answer_legacy_without_points`：无 points 旧草稿兼容，points 为空。

### 移动端

```bash
cd mobile && npm test -- --runInBand
# 10 suites / 73 tests passed（新增要点渲染与回退 2 项；含编号/来源条最终形态修订）

cd mobile && npm run lint
# 通过

cd mobile && npx tsc --noEmit
# 通过

cd mobile && npx expo export --platform ios
# ios bundles 导出成功

cd mobile && npx expo export --platform android
# android bundles 导出成功
```

### OpenSpec 与 diff 检查

```bash
openspec validate add-structured-answer-points --strict
# Change 'add-structured-answer-points' is valid

openspec validate --all --strict
# 46 passed, 0 failed

git diff --check
# 干净
```

## 设备验证状态

- 本次未执行 iOS/Android 真机或模拟器视觉验收（无设备操作权限），不宣称已验收；
- 需用户在真机确认：要点卡在 390×844 主视口（并检查 360×800 / 412×915）的分组标题、
  编号、间距、来源 chip 触控与长正文滚动；
- 回答模型 prompt 已升级为 v3（输出 `lead` + `points`），需真机实测确认模型输出稳定性
  与拼接正文观感；若模型降级/未输出 points，移动端会自动回退到纯文本 + 来源条。

## 遗留观察项

- `answer` 文本由服务端从 `lead` + `points` 拼接，Web ReaderView 显示的文本风格与旧版
  基本一致（`**分组**` + `- 列表`），无需改动；
- 同一条 Evidence 被多条要点引用时，扁平 `citations` 与底部来源条按证据去重展示。
