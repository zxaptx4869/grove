/** 来源库派生口径：状态徽标、done 副状态、时间、重试与两个操作的阻断判定。 */

import {
  attachmentCacheFileName,
  candidateDirectoryLine,
  deleteBlockedReason,
  deleteConfirmCopy,
  deleteFailureNotice,
  failureLine,
  formatSourceTime,
  hasActiveSources,
  isDeleteConflict,
  isProcessingNotStarted,
  moveBlockedReason,
  needsProcessingRetry,
  nextImageIndex,
  retryLabel,
  shouldPollSources,
  sourceMaterialSummary,
  sourceStatusBadge,
  sourceSubStatus,
  SOURCE_POLL_INTERVAL_MS,
} from "@/src/sources/state";
import type { CandidateOut, SourceOut } from "@/src/sources/types";

function source(overrides: Partial<SourceOut> = {}): SourceOut {
  return {
    id: 1,
    title: "厨房插座位置确认",
    note: null,
    project_id: null,
    status: "waiting",
    created_at: "2026-09-24T02:12:00.000Z",
    updated_at: "2026-09-24T02:12:00.000Z",
    attachments: [{ id: 1, kind: "image", position: 0, mime_type: "image/jpeg", file_name: "a.jpg", text_content: null, ocr_text: null }],
    failure_reason: null,
    retry_count: 0,
    has_processing_task: true,
    project_locked: false,
    evidence_entry_count: 0,
    pending_candidate_count: 0,
    candidate_count: 0,
    ...overrides,
  };
}

test("状态徽标覆盖四态，并单独识别处理未启动", () => {
  expect(sourceStatusBadge(source({ status: "waiting", has_processing_task: true })).label).toBe("等待处理");
  expect(sourceStatusBadge(source({ status: "waiting", has_processing_task: false })).label).toBe("处理未启动");
  expect(sourceStatusBadge(source({ status: "processing" })).label).toBe("处理中");
  expect(sourceStatusBadge(source({ status: "done" })).label).toBe("提取完成");
  expect(sourceStatusBadge(source({ status: "failed" })).label).toBe("处理失败");
});

test("处理未启动只由状态与任务存在性判定，不使用等待时长", () => {
  expect(isProcessingNotStarted(source({ status: "waiting", has_processing_task: false }))).toBe(true);
  expect(isProcessingNotStarted(source({ status: "waiting", has_processing_task: true }))).toBe(false);
  expect(isProcessingNotStarted(source({ status: "processing", has_processing_task: false }))).toBe(false);
});

test("done 副状态按待确认与正式知识组合派生", () => {
  expect(
    sourceSubStatus(source({ status: "done", pending_candidate_count: 2, evidence_entry_count: 0 }))?.label,
  ).toBe("待确认 2 条");
  expect(
    sourceSubStatus(source({ status: "done", pending_candidate_count: 1, evidence_entry_count: 2 }))?.label,
  ).toBe("部分确认 · 2 条正式知识");
  expect(
    sourceSubStatus(source({ status: "done", pending_candidate_count: 0, evidence_entry_count: 3 }))?.label,
  ).toBe("3 条正式知识");
  expect(
    sourceSubStatus(source({ status: "done", pending_candidate_count: 0, evidence_entry_count: 0 }))?.label,
  ).toBe("还没有候选");
});

test("非完成态不显示副状态，即使计数非零", () => {
  expect(sourceSubStatus(source({ status: "processing", pending_candidate_count: 3 }))).toBeNull();
  expect(sourceSubStatus(source({ status: "failed", evidence_entry_count: 1 }))).toBeNull();
});

test("类型与附件摘要按是否含文字附件派生", () => {
  expect(sourceMaterialSummary(source())).toBe("1 张图片");
  expect(
    sourceMaterialSummary(
      source({ attachments: [{ id: 1, kind: "text", position: 0, mime_type: null, file_name: null, text_content: "正文", ocr_text: null }] }),
    ),
  ).toBe("文字");
});

test("创建时间文案区分今天、昨天、同年与跨年", () => {
  const now = new Date(2026, 8, 24, 20, 0);
  expect(formatSourceTime(new Date(2026, 8, 24, 10, 12).toISOString(), now)).toBe("今天 10:12");
  expect(formatSourceTime(new Date(2026, 8, 23, 18, 5).toISOString(), now)).toBe("昨天 18:05");
  expect(formatSourceTime(new Date(2026, 8, 20, 15, 20).toISOString(), now)).toBe("9 月 20 日 15:20");
  expect(formatSourceTime(new Date(2025, 8, 20, 15, 20).toISOString(), now)).toBe("2025 年 9 月 20 日");
});

test("不带时区的服务端时间按 UTC 解析，不再整体差一个时区", () => {
  const now = new Date();
  const aware = "2026-09-29T07:23:51Z";
  // 真机走查：几分钟前采集的显示成 7:23，正是把 UTC 串当成本地时间解析
  expect(formatSourceTime("2026-09-29T07:23:51", now)).toBe(formatSourceTime(aware, now));
  // 已带偏移的串保持原样解析
  expect(formatSourceTime("2026-09-29T15:23:51+08:00", now)).toBe(formatSourceTime(aware, now));
  // 解析不了的串原样返回，不显示 Invalid Date
  expect(formatSourceTime("不是时间", now)).toBe("不是时间");
});

test("附件图片缓存名带上版本串，库重置后不会复用上一代的同号文件", () => {
  const base = { sourceId: 138, attachmentId: 154, fileName: "88452349-2a41.jpg" };
  const first = attachmentCacheFileName({ ...base, cacheVersion: "2026-09-29T07:23:51" });
  const second = attachmentCacheFileName({ ...base, cacheVersion: "2026-08-01T02:00:00" });
  expect(first).toMatch(/^grove-source-138-154-.*\.jpg$/);
  expect(first).not.toBe(second);
  // 同一版本的重复渲染复用同一个文件名
  expect(attachmentCacheFileName({ ...base, cacheVersion: "2026-09-29T07:23:51" })).toBe(first);
  // 没有版本串时退回原始文件名，仍然不会和上一代撞名
  expect(attachmentCacheFileName(base)).toContain("884523492a41");
});

test("失败原因只对处理失败来源给出原文，重试口径覆盖失败与未启动", () => {
  expect(failureLine(source({ status: "failed", failure_reason: "模型调用失败" }))).toBe("模型调用失败");
  expect(failureLine(source({ status: "done", failure_reason: "模型调用失败" }))).toBeNull();

  expect(needsProcessingRetry(source({ status: "failed" }))).toBe(true);
  expect(needsProcessingRetry(source({ status: "waiting", has_processing_task: false }))).toBe(true);
  expect(needsProcessingRetry(source({ status: "waiting", has_processing_task: true }))).toBe(false);
  expect(needsProcessingRetry(source({ status: "processing" }))).toBe(false);
  expect(needsProcessingRetry(source({ status: "done" }))).toBe(false);

  expect(retryLabel(source({ status: "failed" }))).toBe("重试");
  expect(retryLabel(source({ status: "waiting", has_processing_task: false }))).toBe("重试处理");
});

test("改归属预判：锁定与处理中给出阻断，其余放行", () => {
  expect(moveBlockedReason(source({ project_locked: true }))?.detail).toContain("已被正式知识引用");
  expect(moveBlockedReason(source({ status: "processing" }))?.detail).toContain("正在处理中");
  expect(moveBlockedReason(source({ status: "done" }))).toBeNull();
});

test("删除阻止覆盖锁定与处理中，待确认候选单独走二次确认", () => {
  expect(deleteBlockedReason(source({ project_locked: true }))?.detail).toContain("不能删除");
  expect(deleteBlockedReason(source({ status: "processing" }))?.detail).toContain("正在处理中");
  expect(deleteBlockedReason(source({ status: "done" }))).toBeNull();

  expect(deleteConfirmCopy(source({ pending_candidate_count: 0 })).detail).toContain("无法恢复");
  expect(deleteConfirmCopy(source({ pending_candidate_count: 3 })).detail).toContain(
    "将一并移除这些候选",
  );
});

test("轮询开关：处理中与「等待处理且有任务」才轮询，处理未启动不轮询", () => {
  const waitingWithTask = [source({ status: "waiting", has_processing_task: true })];
  const waitingWithoutTask = [source({ status: "waiting", has_processing_task: false })];
  const processing = [source({ status: "processing", has_processing_task: true })];
  const settled = [source({ status: "done" }), source({ id: 2, status: "failed" })];

  expect(hasActiveSources(waitingWithTask)).toBe(true);
  expect(hasActiveSources(processing)).toBe(true);
  // 处理未启动：没有处理任务，状态不会自己变，前台不该一直轮询
  expect(hasActiveSources(waitingWithoutTask)).toBe(false);
  expect(hasActiveSources(settled)).toBe(false);
  expect(hasActiveSources(undefined)).toBe(false);

  expect(shouldPollSources(waitingWithTask, true)).toBe(SOURCE_POLL_INTERVAL_MS);
  expect(shouldPollSources(processing, true)).toBe(SOURCE_POLL_INTERVAL_MS);
  expect(shouldPollSources(waitingWithoutTask, true)).toBe(false);
  expect(shouldPollSources(settled, true)).toBe(false);
  expect(shouldPollSources(waitingWithTask, false)).toBe(false);
  expect(shouldPollSources(undefined, true)).toBe(false);
  // 处理未启动的条目混在列表里也不会把轮询打开
  expect(shouldPollSources([...waitingWithoutTask, ...settled], true)).toBe(false);
});

test("删除提示口径：预判与 409 是只读阻断，其余失败给重试入口", () => {
  const blocked = deleteBlockedReason(source({ project_locked: true }));
  expect(deleteFailureNotice(blocked, null)).toEqual({
    title: "不能删除",
    detail: "该来源已被正式知识引用，不能删除；请先处理关联 Entry",
    hint: "请先在桌面工作台处理关联的正式知识。",
    retryable: false,
  });
  // 服务端 409：用服务端原文，但不给重试
  expect(
    deleteFailureNotice(null, { message: "该来源已被正式知识引用，不能删除", conflict: true }),
  ).toEqual({ title: "不能删除", detail: "该来源已被正式知识引用，不能删除", hint: null, retryable: false });
  // 本地预判命中时以预判为准，即使同时带着失败信息
  expect(deleteFailureNotice(blocked, { message: "网络连接中断，请检查网络后重试。", conflict: false })?.retryable).toBe(false);
  // 网络 / 5xx：标题「删除失败」并保留重试
  expect(
    deleteFailureNotice(null, { message: "网络连接中断，请检查网络后重试。", conflict: false }),
  ).toEqual({
    title: "删除失败",
    detail: "网络连接中断，请检查网络后重试。",
    hint: null,
    retryable: true,
  });
  expect(deleteFailureNotice(null, null)).toBeNull();
});

test("删除冲突判定只看 409", () => {
  expect(isDeleteConflict(Object.assign(new Error("冲突"), { status: 409 }))).toBe(true);
  expect(isDeleteConflict(Object.assign(new Error("挂了"), { status: 500 }))).toBe(false);
  expect(isDeleteConflict(new Error("网络错误"))).toBe(false);
  expect(isDeleteConflict(null)).toBe(false);
});

test("切换图片：只前后移动一位，到头停住不做环绕", () => {
  expect(nextImageIndex(0, 3, 1)).toBe(1);
  expect(nextImageIndex(1, 3, -1)).toBe(0);
  // 首尾边界停住
  expect(nextImageIndex(2, 3, 1)).toBe(2);
  expect(nextImageIndex(0, 3, -1)).toBe(0);
  // 不在放大状态或没有图片时保持原值
  expect(nextImageIndex(null, 3, 1)).toBeNull();
  expect(nextImageIndex(0, 0, 1)).toBe(0);
});

test("候选目录建议只展示可读内容", () => {
  function candidate(overrides: Partial<CandidateOut> = {}): CandidateOut {
    return {
      id: 1,
      candidate_kind: "entry",
      title: "标题",
      content: "内容",
      main_type: "事实",
      note: null,
      reason: "理由",
      status: "pending",
      recommended_node_id: null,
      node_reason: null,
      routing_status: "done",
      relation_status: "done",
      new_node_suggestion: null,
      node_alternatives: [],
      ...overrides,
    };
  }

  expect(
    candidateDirectoryLine(candidate({ new_node_suggestion: { name: "防水施工", parent_id: 1, reason: null } })),
  ).toBe("建议新增节点：防水施工");
  expect(candidateDirectoryLine(candidate({ recommended_node_id: 7 }))).toContain("编号 7");
  expect(candidateDirectoryLine(candidate())).toBe("这次没有给出目录建议");
});
