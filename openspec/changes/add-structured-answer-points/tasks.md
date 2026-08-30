## 1. 实施前基线与契约核对

- [x] 1.1 重新阅读本 change 的 proposal/design/specs，并读取 `docs/产品蓝图.md` 索引路由到的「Agent架构与AI边界」「技术与端侧边界」与原型 `grove-mobile-agent-prototype.html` 的 `answer-points` 视觉基线；核对 `grove-ui-conventions`，确认要点卡样式、触控与读屏约束。
- [x] 1.2 盘点 `KnowledgeAnswerDraft`/`KnowledgeAnswerOut`/`build_validated_answer`、回答 prompt v2、移动端 `AnswerCard`/`cleanAnswerText`/`CitationStrip` 的当前契约，确认 Web ReaderView、草稿 seed 与历史回答的兼容基线。
- [x] 1.3 运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_evidence.py -W error` 与 `cd mobile && npm test -- --runInBand && npm run lint && npx tsc --noEmit`，记录实施前结果。

## 2. 后端：结构化要点协议与生成

- [x] 2.1 扩展 `KnowledgeAnswerDraft`（`lead` + `points`，每条含 `section`/`text`/`evidence_handles`）与 `KnowledgeAnswerOut`（可选 `points`，每条含 `section`/`text`/逐条 `citations`），历史 JSON 缺省为空不破坏解析。
- [x] 2.2 升级回答 prompt 至 v3（`ANSWER_PROMPT_VERSION`）：模型输出 `lead` + `points`，每个关键事实一个 point 且至少挂一个句柄，`section` 用于分组，`text` 禁止句柄/编号/括号标记；不要求模型再写扁平 markdown 正文。
- [x] 2.3 扩展 `build_validated_answer`：`points` 存在时逐条重验句柄，无有效句柄的 point 丢弃并计入 `discarded_count`（触发 `partial`）；最终扁平 `citations` 由有效 points 按序去重派生并并入 conflicts 句柄；`answer` 由 `lead` + points 确定性拼接（`**分组**` + `- 列表` 格式）并经 `sanitize_answer_text` 清洗。
- [x] 2.4 保持兼容路径：模型未返回 `points` 时沿用现有 `answer` 文本与扁平 `citations` 逻辑；`coverage`/`gaps`/`conflicts`/`status` 判定不引入新语义。
- [x] 2.5 补充后端单测：points 解析/逐条校验/部分失效 partial/全部失效 insufficient/服务端拼接/句柄清洗/无 points 兼容；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_evidence.py -W error && .venv/bin/ruff check app tests`，通过后本地提交。

## 3. 移动端：要点卡渲染与回退

- [x] 3.1 扩展 `KnowledgeAnswer` 类型与 `KnowledgeAnswerPoint`（`section`/`text`/`citations`），API 解析保持旧响应兼容。
- [x] 3.2 在 `AnswerCard` 实现要点卡渲染：`section` 变化时显示分组标题（加粗 + 前缀符号）、全回答连续编号、要点正文；每条要点下方提供来源 chip（`minHeight 44`、复用 `onCitationPress` → CitationSheet、`accessibilityLabel="查看引用：{entryTitle}"`）。
- [x] 3.3 保留无 `points` 回退路径（`cleanAnswerText` + 底部 `CitationStrip`）与有 `points` 时的底部「全部来源速览」；不出现空要点区或伪富文本。
- [x] 3.4 补充组件测试：要点渲染（分组/编号/chip）、无 points 回退、引用点击、读屏标签与 44 触控目标；运行 `cd mobile && npm test -- --runInBand && npm run lint && npx tsc --noEmit`，通过后本地提交。

## 4. 验证与记录

- [ ] 4.1 运行后端全量 `cd backend && .venv/bin/python -m pytest -W error` 与 `cd backend && .venv/bin/ruff check app tests`，确认全量通过。
- [ ] 4.2 运行移动端全量 `cd mobile && npm test -- --runInBand && npm run lint && npx tsc --noEmit`，并执行 `cd mobile && npx expo export --platform ios` 与 `npx expo export --platform android`。
- [ ] 4.3 运行 `openspec validate add-structured-answer-points --strict`、`openspec validate --all --strict` 与 `git diff --check`。
- [ ] 4.4 真机验证要点卡在 390×844 主视口（并检查 360×800 / 412×915）的层级、间距、编号、来源 chip 与滚动；若无法真机验证，在 validation 中如实记录，不宣称已验收。
- [ ] 4.5 将真实测试数量、真机/截图结果与未验证项写入 `validation/validation.md`，完成本地提交，停留当前特性分支等待确认。
