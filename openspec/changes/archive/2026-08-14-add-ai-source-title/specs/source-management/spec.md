## MODIFIED Requirements

### Requirement: 标题自动生成
系统 MUST 在采集时生成初始标题：图片 Source 取第一个图片附件的文件名，文字 Source 取正文首行；处理成功后 MUST 用 Organizing Agent 生成的非空标题更新 Source 标题；采集阶段 MUST NOT 依赖 AI 生成标题。

#### Scenario: 图片标题
- **WHEN** 用户上传图片创建 Source
- **THEN** Source 初始标题为第一个图片文件名

#### Scenario: 文字标题
- **WHEN** 用户粘贴文字创建 Source
- **THEN** Source 初始标题为正文首行

#### Scenario: 处理完成后更新 AI 标题
- **WHEN** Source 处理成功且 Agent 生成了非空标题
- **THEN** Source 标题更新为该 AI 标题
