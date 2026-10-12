/**
 * 来源详情：全屏只读层（元信息 / 原始材料 / OCR / AI 候选）与底部「改归属 / 删除」操作条。
 *
 * 候选只读：这里不提供任何确认、拒绝、写入或归档入口，候选落地仍回桌面 Web 或回对话讨论。
 */

import { useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import type { Project } from "@/src/api";
import { AppButton, Badge, Card, CardBody, Sheet } from "@/src/knowledge-agent/components/ui";
import { sourceErrorMessage } from "@/src/sources/api";
import { SourceIcon } from "@/src/sources/components/SourceIcon";
import { SourceImage } from "@/src/sources/components/SourceImage";
import { ZoomableImage } from "@/src/sources/components/ZoomableImage";
import {
  candidateDirectoryLine,
  deleteBlockedReason,
  deleteConfirmCopy,
  deleteFailureNotice,
  formatSourceTime,
  imageAttachments,
  isDeleteConflict,
  isProcessingNotStarted,
  moveBlockedReason,
  nextImageIndex,
  ocrText,
  sourceKind,
  sourceProjectLabel,
  sourceStatusBadge,
  sourceSubStatus,
  textContent,
} from "@/src/sources/state";
import type { CandidateOut, SourceOut } from "@/src/sources/types";
import { theme } from "@/src/theme";

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue}>{value}</Text>
    </View>
  );
}

function ocrHint(source: SourceOut): string {
  if (sourceKind(source) === "text") return "文字来源不需要 OCR 识别。";
  if (source.status === "failed") return "本次处理没有产生 OCR 文本。";
  if (isProcessingNotStarted(source) || source.status === "waiting") {
    return "材料还没开始处理，暂时没有 OCR 文本。";
  }
  if (source.status === "processing") return "材料还在处理中，还没有 OCR 文本。";
  return "本次处理没有产生 OCR 文本。";
}

function candidateHint(source: SourceOut): string {
  if (source.status === "failed") return "处理失败，这条来源还没有候选。";
  if (isProcessingNotStarted(source)) return "处理还没启动，可以在列表里点「重试处理」。";
  if (source.status === "waiting" || source.status === "processing") {
    return "处理完成后才会出现 AI 候选。";
  }
  return "这次处理没有产生候选。";
}

export function SourceDetailOverlay({
  source,
  candidates,
  projects,
  loading,
  error,
  candidatesError,
  moving,
  onClose,
  onRetryLoad,
  onMove,
  onDelete,
}: {
  source: SourceOut | null;
  candidates: CandidateOut[];
  projects: Project[];
  loading: boolean;
  error: string | null;
  candidatesError: string | null;
  moving: boolean;
  onClose: () => void;
  onRetryLoad: () => void;
  onMove: (projectId: number | null) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [zoomIndex, setZoomIndex] = useState<number | null>(null);
  // 原图尺寸（按附件缓存）：拿到后放大视图按宽度铺满渲染，缩放时更清晰
  const [zoomImageSizes, setZoomImageSizes] = useState<
    Record<number, { width: number; height: number }>
  >({});
  const [moveOpen, setMoveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [moveError, setMoveError] = useState("");
  // 删除失败留原文，弹层里按「业务阻断 / 可重试失败」两种口径展示
  const [deleteFailure, setDeleteFailure] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);

  const images = source ? imageAttachments(source) : [];
  const badge = source ? sourceStatusBadge(source) : null;
  const subStatus = source ? sourceSubStatus(source) : null;
  const moveBlocked = source ? moveBlockedReason(source) : null;
  const deleteBlocked = source ? deleteBlockedReason(source) : null;

  function openMoveSheet() {
    setMoveError("");
    setSelectedProjectId(source?.project_id ?? null);
    setMoveOpen(true);
  }

  function openDeleteSheet() {
    // 每次打开都从确认态开始：上一次的失败提示不带到下一次
    setDeleteFailure(null);
    setDeleteOpen(true);
  }

  async function submitMove() {
    setMoveError("");
    setBusy(true);
    try {
      await onMove(selectedProjectId);
      setMoveOpen(false);
    } catch (moveFailure) {
      // 失败保留弹层与当前选择，原样展示服务端文案
      setMoveError(sourceErrorMessage(moveFailure));
    } finally {
      setBusy(false);
    }
  }

  async function submitDelete() {
    setBusy(true);
    try {
      await onDelete();
      setDeleteOpen(false);
    } catch (failure) {
      setDeleteFailure(failure);
    } finally {
      setBusy(false);
    }
  }

  const confirm = source ? deleteConfirmCopy(source) : null;
  const deleteNotice = deleteFailureNotice(
    deleteBlocked,
    deleteFailure === null
      ? null
      : { message: sourceErrorMessage(deleteFailure), conflict: isDeleteConflict(deleteFailure) },
  );

  return (
    <Modal
      visible
      animationType="slide"
      statusBarTranslucent
      navigationBarTranslucent
      onRequestClose={onClose}
      accessibilityViewIsModal
    >
      <SafeAreaView style={styles.page} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="返回收集列表"
            onPress={onClose}
            style={({ pressed }) => [styles.headerIcon, pressed && styles.pressed]}
          >
            <SourceIcon name="back" size={22} color={theme.ink} />
          </Pressable>
          <Text style={styles.headerTitle}>来源详情</Text>
          <View style={styles.headerIcon} />
        </View>

        <ScrollView
          style={styles.fill}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          {loading && !source ? (
            <Card>
              <CardBody>
                <View style={styles.loading}>
                  <ActivityIndicator color={theme.green} />
                  <Text style={styles.stateText}>正在读取来源…</Text>
                </View>
              </CardBody>
            </Card>
          ) : null}

          {error && !source ? (
            <Card accent="risk">
              <CardBody>
                <View style={styles.stateBody}>
                  <SourceIcon name="cloudOff" size={22} color={theme.error} />
                  <Text style={styles.stateTitle}>来源详情加载失败</Text>
                  <Text style={styles.stateText}>{error}</Text>
                  <AppButton label="重新加载" onPress={onRetryLoad} />
                </View>
              </CardBody>
            </Card>
          ) : null}

          {source ? (
            <>
              <Card>
                <CardBody>
                  <View style={styles.badges}>
                    {badge ? <Badge tone={badge.tone}>{badge.label}</Badge> : null}
                    {subStatus ? <Badge tone={subStatus.tone}>{subStatus.label}</Badge> : null}
                  </View>
                  <Text style={styles.title}>{source.title}</Text>
                  <View style={styles.meta}>
                    <MetaRow
                      label="类型"
                      value={
                        sourceKind(source) === "text" ? "文字" : `图片 · ${images.length} 张`
                      }
                    />
                    <MetaRow label="创建时间" value={formatSourceTime(source.created_at)} />
                    <MetaRow
                      label="项目归属"
                      value={
                        source.project_locked
                          ? `${sourceProjectLabel(source, projects)}（已被正式知识引用，不能改归属或删除）`
                          : sourceProjectLabel(source, projects)
                      }
                    />
                    <MetaRow label="补充说明" value={source.note?.trim() || "未填写"} />
                  </View>
                </CardBody>
              </Card>

              {source.status === "failed" && source.failure_reason ? (
                <Card accent="risk">
                  <CardBody>
                    <Text style={styles.noticeTitle}>处理失败</Text>
                    <Text style={styles.noticeBody}>{source.failure_reason}</Text>
                    <Text style={styles.noticeHint}>可以在列表里对这条来源重试处理。</Text>
                  </CardBody>
                </Card>
              ) : null}

              {isProcessingNotStarted(source) ? (
                <Card accent="risk">
                  <CardBody>
                    <Text style={styles.noticeTitle}>处理未启动</Text>
                    <Text style={styles.noticeBody}>
                      这条来源没有处理任务，不会被自动处理。
                    </Text>
                    <Text style={styles.noticeHint}>回到列表点「重试处理」即可重新排队。</Text>
                  </CardBody>
                </Card>
              ) : null}

              <Text style={styles.sectionTitle}>
                原始材料
                <Text style={styles.sectionMeta}>
                  {sourceKind(source) === "text" ? "文字正文" : `${images.length} 张图片`}
                </Text>
              </Text>
              {sourceKind(source) === "text" ? (
                <View style={styles.quote}>
                  <Text style={styles.quoteText}>{textContent(source)}</Text>
                </View>
              ) : (
                <View style={styles.grid}>
                  {images.map((item, index) => (
                    <Pressable
                      key={item.id}
                      accessibilityRole="button"
                      accessibilityLabel={`放大查看第 ${index + 1} 张：${item.file_name ?? "图片"}`}
                      onPress={() => setZoomIndex(index)}
                      style={({ pressed }) => [styles.photo, pressed && styles.pressed]}
                    >
                      <SourceImage
                        sourceId={source.id}
                        attachmentId={item.id}
                        fileName={item.file_name}
                        cacheVersion={source.created_at}
                        style={styles.photoImage}
                      />
                      <View style={styles.zoomHint}>
                        <SourceIcon name="zoom" size={12} color={theme.ink} />
                        <Text style={styles.zoomHintText}>放大</Text>
                      </View>
                    </Pressable>
                  ))}
                </View>
              )}

              <Text style={styles.sectionTitle}>
                OCR 文本
                <Text style={styles.sectionMeta}>只读</Text>
              </Text>
              {ocrText(source) ? (
                <>
                  <View style={styles.quote}>
                    <Text style={styles.quoteText}>{ocrText(source)}</Text>
                  </View>
                  <Text style={styles.hint}>
                    机器识别结果，可能与原图存在差异；正式知识以人工确认为准。
                  </Text>
                </>
              ) : (
                <Text style={styles.hint}>{ocrHint(source)}</Text>
              )}

              <Text style={styles.sectionTitle}>
                AI 候选
                <Text style={styles.sectionMeta}>共 {candidates.length} 条 · 未应用</Text>
              </Text>
              {candidatesError ? (
                <Card accent="risk">
                  <CardBody>
                    <Text style={styles.noticeBody}>{candidatesError}</Text>
                    <Text style={styles.noticeHint}>重新打开详情或稍后重试。</Text>
                  </CardBody>
                </Card>
              ) : candidates.length === 0 ? (
                <Text style={styles.hint}>{candidateHint(source)}</Text>
              ) : (
                candidates.map((item) => (
                  <Card key={item.id} accent="ai">
                    <CardBody>
                      <View style={styles.badges}>
                        <Badge tone="ai">AI 候选</Badge>
                        <Badge tone="neutral">未应用</Badge>
                      </View>
                      <Text style={styles.candidateTitle}>{item.content || item.title}</Text>
                      <Text style={styles.candidateLine}>{candidateDirectoryLine(item)}</Text>
                      {item.reason ? (
                        <Text style={styles.candidateLine}>理由：{item.reason}</Text>
                      ) : null}
                      {item.node_reason ? (
                        <Text style={styles.candidateLine}>目录理由：{item.node_reason}</Text>
                      ) : null}
                    </CardBody>
                  </Card>
                ))
              )}
              <Text style={styles.hint}>
                候选的确认、拒绝与写入在桌面工作台或对话里完成，这里只读。
              </Text>
            </>
          ) : null}
        </ScrollView>

        {source ? (
          <View style={styles.footer}>
            <View style={styles.footerButton}>
              <AppButton
                label={moving ? "更换中…" : "改归属"}
                disabled={moving}
                onPress={openMoveSheet}
              />
            </View>
            <View style={styles.footerButton}>
              <AppButton label="删除" variant="danger" onPress={openDeleteSheet} />
            </View>
          </View>
        ) : null}
      </SafeAreaView>

      <Modal
        visible={zoomIndex !== null}
        animationType="fade"
        statusBarTranslucent
        navigationBarTranslucent
        onRequestClose={() => setZoomIndex(null)}
      >
        <SafeAreaView style={styles.lightbox} edges={["top", "bottom"]}>
          <View style={styles.header}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="关闭原图"
              onPress={() => setZoomIndex(null)}
              style={({ pressed }) => [styles.headerIcon, pressed && styles.pressed]}
            >
              <SourceIcon name="close" size={22} color={theme.ink} />
            </Pressable>
            <Text style={[styles.headerTitle, styles.lightboxTitle]}>
              第 {(zoomIndex ?? 0) + 1} / {images.length} 张
            </Text>
            <View style={styles.headerIcon} />
          </View>
          {source && zoomIndex !== null && images[zoomIndex] ? (
            <View style={styles.lightboxBody}>
              <ZoomableImage
                resetKey={images[zoomIndex].id}
                style={styles.lightboxStage}
                contentSize={zoomImageSizes[images[zoomIndex].id] ?? null}
                onSwipeLeft={() => setZoomIndex((current) => nextImageIndex(current, images.length, 1))}
                onSwipeRight={() => setZoomIndex((current) => nextImageIndex(current, images.length, -1))}
              >
                <SourceImage
                  sourceId={source.id}
                  attachmentId={images[zoomIndex].id}
                  fileName={images[zoomIndex].file_name}
                  cacheVersion={source.created_at}
                  style={styles.lightboxImage}
                  resizeMode="contain"
                  accessibilityLabel={`第 ${zoomIndex + 1} 张原图`}
                  onLoadSize={(size) =>
                    setZoomImageSizes((current) =>
                      current[images[zoomIndex].id] ? current : { ...current, [images[zoomIndex].id]: size },
                    )
                  }
                />
              </ZoomableImage>
              <Text style={styles.lightboxZoomHint}>
                {images.length > 1 ? "双指缩放 · 双击放大 / 还原 · 左右滑动切换" : "双指缩放 · 双击放大 / 还原"}
              </Text>
              <Text style={styles.lightboxCaption}>
                {images[zoomIndex].file_name ?? "图片附件"}
              </Text>
            </View>
          ) : null}
        </SafeAreaView>
      </Modal>

      {source ? (
        <>
          <Sheet
            visible={moveOpen}
            title="修改归属"
            onClose={() => {
              // 提交期间不允许关闭：请求是同步的，关掉弹层会让用户失去进度反馈
              if (!busy) setMoveOpen(false);
            }}
          >
            {moveBlocked ? (
              <>
                <View style={styles.notice}>
                  <Text style={styles.noticeTitle}>{moveBlocked.title}</Text>
                  <Text style={styles.noticeBody}>{moveBlocked.detail}</Text>
                </View>
                <AppButton label="知道了" onPress={() => setMoveOpen(false)} />
              </>
            ) : (
              <>
                <Text style={styles.sheetCaption}>{source.title}</Text>
                {[{ id: null, name: "未归属" }, ...projects].map((option) => {
                  const selected = option.id === selectedProjectId;
                  const current = option.id === source.project_id;
                  return (
                    <Pressable
                      key={option.id ?? "none"}
                      accessibilityRole="radio"
                      accessibilityState={{ checked: selected, disabled: busy }}
                      accessibilityLabel={option.name}
                      disabled={busy}
                      onPress={() => {
                        setMoveError("");
                        setSelectedProjectId(option.id);
                      }}
                      style={({ pressed }) => [
                        styles.option,
                        selected && styles.optionSelected,
                        pressed && styles.pressed,
                      ]}
                    >
                      <SourceIcon
                        name={option.id === null ? "info" : "folder"}
                        size={16}
                        color={selected ? theme.green : theme.muted}
                      />
                      <Text style={[styles.optionText, selected && styles.optionTextSelected]}>
                        {option.name}
                      </Text>
                      {current ? <Text style={styles.optionCurrent}>当前</Text> : null}
                      {selected ? <SourceIcon name="check" size={16} color={theme.green} /> : null}
                    </Pressable>
                  );
                })}
                {moveError ? <Text style={styles.sheetError}>{moveError}</Text> : null}
                {/* 固定高度占位：进行中说明出现时不会把弹层撑高 */}
                <View style={styles.sheetProgress}>
                  {busy ? (
                    <Text style={styles.hint}>正在更换项目并重新推荐目录，请稍候…</Text>
                  ) : null}
                </View>
                <View style={styles.sheetActions}>
                  <View style={styles.sheetAction}>
                    <AppButton label="取消" disabled={busy} onPress={() => setMoveOpen(false)} />
                  </View>
                  <View style={styles.sheetAction}>
                    <AppButton
                      label={busy ? "正在更换…" : "确认修改"}
                      variant="primary"
                      disabled={busy || selectedProjectId === source.project_id}
                      icon={busy ? <ActivityIndicator size="small" color="#FFFFFF" /> : undefined}
                      onPress={() => void submitMove()}
                    />
                  </View>
                </View>
              </>
            )}
          </Sheet>

          <Sheet
            visible={deleteOpen}
            title="删除来源"
            onClose={() => {
              // 删除进行中不允许关闭：请求是同步的，关掉弹层会让用户失去进度反馈
              if (!busy) setDeleteOpen(false);
            }}
          >
            {deleteNotice ? (
              <>
                <View style={styles.notice}>
                  <Text style={styles.noticeTitle}>{deleteNotice.title}</Text>
                  <Text style={styles.noticeBody}>{deleteNotice.detail}</Text>
                  {deleteNotice.hint ? (
                    <Text style={styles.noticeHint}>{deleteNotice.hint}</Text>
                  ) : null}
                </View>
                {deleteNotice.retryable ? (
                  // 可重试失败：给退路也给重试，布局与确认态一致，弹层高度不跳
                  <View style={styles.sheetActions}>
                    <View style={styles.sheetAction}>
                      <AppButton label="取消" disabled={busy} onPress={() => setDeleteOpen(false)} />
                    </View>
                    <View style={styles.sheetAction}>
                      <AppButton
                        label={busy ? "删除中…" : "重试删除"}
                        variant="danger"
                        disabled={busy}
                        icon={
                          busy ? <ActivityIndicator size="small" color={theme.error} /> : undefined
                        }
                        onPress={() => void submitDelete()}
                      />
                    </View>
                  </View>
                ) : (
                  <AppButton label="知道了" onPress={() => setDeleteOpen(false)} />
                )}
              </>
            ) : (
              <>
                <View style={styles.notice}>
                  <Text style={styles.noticeTitle}>{confirm?.title}</Text>
                  <Text style={styles.noticeBody}>{confirm?.detail}</Text>
                </View>
                {/* 进度落在确认按钮上：不插入新的提示行，弹层高度保持不变 */}
                <View style={styles.sheetActions}>
                  <View style={styles.sheetAction}>
                    <AppButton
                      label="取消"
                      disabled={busy}
                      onPress={() => setDeleteOpen(false)}
                    />
                  </View>
                  <View style={styles.sheetAction}>
                    <AppButton
                      label={busy ? "删除中…" : "确认删除"}
                      variant="danger"
                      disabled={busy}
                      icon={busy ? <ActivityIndicator size="small" color={theme.error} /> : undefined}
                      onPress={() => void submitDelete()}
                    />
                  </View>
                </View>
              </>
            )}
          </Sheet>
        </>
      ) : null}
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: theme.bg },
  fill: { flex: 1 },
  header: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 8,
  },
  headerIcon: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
  },
  headerTitle: { flex: 1, fontSize: 16, fontWeight: "700", color: theme.ink, textAlign: "center" },
  content: { paddingHorizontal: 16, paddingBottom: 24 },
  loading: { flexDirection: "row", alignItems: "center", gap: 10 },
  stateBody: { alignItems: "center", gap: 8 },
  stateTitle: { fontSize: 13.5, fontWeight: "700", color: theme.ink, textAlign: "center" },
  stateText: { fontSize: 12, lineHeight: 19, color: theme.muted, textAlign: "center" },
  badges: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 8 },
  title: { fontSize: 17, lineHeight: 25, fontWeight: "700", color: theme.ink },
  meta: { marginTop: 10, gap: 8 },
  metaRow: { flexDirection: "row", gap: 10 },
  metaLabel: { width: 62, fontSize: 12, lineHeight: 19, color: theme.muted },
  metaValue: { flex: 1, fontSize: 12, lineHeight: 19, color: theme.ink },
  noticeTitle: { fontSize: 12.5, fontWeight: "700", color: theme.ink, marginBottom: 4 },
  noticeBody: { fontSize: 12, lineHeight: 19, color: theme.ink },
  noticeHint: { marginTop: 4, fontSize: 11.5, lineHeight: 18, color: theme.muted },
  notice: {
    gap: 4,
    marginBottom: 12,
    padding: 11,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.soft,
  },
  sectionTitle: {
    marginTop: 18,
    marginBottom: 8,
    fontSize: 14,
    fontWeight: "700",
    color: theme.ink,
  },
  sectionMeta: { fontSize: 11, fontWeight: "600", color: theme.muted },
  quote: {
    padding: 12,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.surface,
  },
  quoteText: { fontSize: 12.5, lineHeight: 20, color: theme.ink },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  photo: {
    width: "48%",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.soft,
  },
  photoImage: { width: "100%", height: 132 },
  zoomHint: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 6,
    backgroundColor: theme.surface,
  },
  zoomHintText: { fontSize: 11, fontWeight: "600", color: theme.ink },
  hint: { fontSize: 11.5, lineHeight: 18, color: theme.muted, marginTop: 6 },
  candidateTitle: { fontSize: 13, lineHeight: 20, fontWeight: "700", color: theme.ink },
  candidateLine: { marginTop: 5, fontSize: 11.5, lineHeight: 18, color: theme.muted },
  footer: {
    flexDirection: "row",
    gap: 10,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.border,
    backgroundColor: theme.bg,
  },
  footerButton: { flex: 1 },
  // 背景用应用浅色底：原来的近黑色在长截图场景下压得人难受，也和整体浅色主题不一致
  lightbox: { flex: 1, backgroundColor: theme.bg },
  lightboxTitle: { color: theme.ink },
  lightboxBody: { flex: 1, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 12, gap: 8 },
  lightboxStage: { flex: 1 },
  // 高度交给原图长宽比（ZoomableImage 按视口宽度铺满），这里只兜底固定高度
  lightboxImage: {
    width: "100%",
    height: "100%",
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.surface,
  },
  lightboxZoomHint: { fontSize: 11, color: theme.muted, textAlign: "center" },
  lightboxCaption: { fontSize: 12, color: theme.muted, textAlign: "center" },
  sheetCaption: { marginBottom: 6, fontSize: 11.5, color: theme.muted },
  option: {
    minHeight: 48,
    marginTop: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  optionSelected: { borderColor: "#BAD5C5", backgroundColor: theme.greenSoft },
  optionText: { flex: 1, fontSize: 13, fontWeight: "600", color: theme.ink },
  optionTextSelected: { color: theme.green },
  optionCurrent: {
    fontSize: 11,
    fontWeight: "600",
    color: theme.muted,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 6,
    backgroundColor: theme.soft,
    overflow: "hidden",
  },
  sheetError: { marginTop: 12, fontSize: 12, lineHeight: 19, color: theme.error },
  sheetProgress: { height: 24, justifyContent: "center" },
  sheetActions: { flexDirection: "row", gap: 10, marginTop: 12 },
  sheetAction: { flex: 1 },
  pressed: { opacity: 0.85 },
});
