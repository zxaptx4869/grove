## 1. OpenSpec 工件

- [x] 1.1 创建 change `refine-evidence-quote-normalization` 并编写 proposal / specs / design / tasks
- [x] 1.2 `openspec validate --all --strict` 通过

## 2. 后端实现

- [x] 2.1 新增 `normalize_evidence_quote` 服务（归一化 + 滑动窗口 difflib 匹配 + 原文索引映射，阈值 0.75）
- [x] 2.2 `save_success_extraction` 落库前按附件原文规范化每条证据引用（省略号拆段、全失败保留原值）
- [x] 2.3 后端测试：符号差异、省略号拆分、全失败保留、附件原文缺失跳过

## 3. 前端实现

- [x] 3.1 `findEvidenceRanges` 精确失败时滑动窗口相似度模糊兜底（阈值 0.75）
- [x] 3.2 前端测试：模糊匹配命中、低于阈值不高亮、原有用例回归

## 4. 验证与收尾

- [x] 4.1 后端 `pytest` + `ruff`；前端 `npm run lint`、`npm run test`、`npm run build` 通过
- [x] 4.2 `openspec validate --all --strict` 通过后归档同步主规格
- [x] 4.3 本地提交（不 push、不 merge）
