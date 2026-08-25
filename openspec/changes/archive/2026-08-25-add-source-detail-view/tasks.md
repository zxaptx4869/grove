## 1. OpenSpec 工件

- [x] 1.1 创建 change `add-source-detail-view` 并编写 proposal / specs / design / tasks
- [x] 1.2 `openspec validate --all --strict` 通过

## 2. 前端实现

- [x] 2.1 `SourceCandidatesDialog` 重命名为 `SourceDetailDialog`：标题「来源详情」，头部元信息区（说明、状态、项目、候选/正式知识数、创建时间）
- [x] 2.2 详情内图片点击放大（全屏遮罩 + Esc/点击关闭）
- [x] 2.3 `SourceList`：「候选」按钮改为「查看」且所有来源显示；点击来源标题打开详情
- [x] 2.4 更新测试：重命名、元信息、无候选空状态、标题点击入口

## 3. 验证与收尾

- [x] 3.1 `npm run lint`、`npm run test`、`npm run build` 通过
- [x] 3.2 `openspec validate --all --strict` 通过后归档同步主规格
- [x] 3.3 本地提交（不 push、不 merge）
