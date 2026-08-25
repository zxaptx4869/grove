## 1. OpenSpec 工件

- [x] 1.1 创建 change `refine-evidence-highlight` 并编写 proposal / specs / design / tasks
- [x] 1.2 `openspec validate --all --strict` 通过

## 2. 前端实现

- [x] 2.1 新增 `lib/evidenceHighlight.tsx`：归一化匹配与高亮工具（去空白、标点统一、大小写统一、区间映射）
- [x] 2.2 `ReviewPage`：`highlightQuote` 替换为归一化高亮；切换候选 effect 自动滚动到高亮（无命中不滚动）
- [x] 2.3 `SourceCandidatesDialog`：增加来源原文区（附件 OCR/正文）、选中候选状态与高亮定位，布局调整为原文 + 候选

## 3. 验证与收尾

- [x] 3.1 前端测试：高亮工具单元测试（换行/空格/全角标点/大小写）；相关组件测试通过
- [x] 3.2 `npm run lint`、`npm run test`、`npm run build` 通过
- [x] 3.3 `openspec validate --all --strict` 通过后归档同步主规格
- [x] 3.4 本地提交（不 push、不 merge）
