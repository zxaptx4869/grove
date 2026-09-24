/** 提交状态覆盖层：全屏盖住页面与底部导航；结束后停在结果页，由底部固定区域返回（对齐原型 #submitOverlay 与 .overlay-footer）。 */

import { ActivityIndicator, Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { CaptureIcon } from "@/src/capture/components/CaptureIcon";
import {
  prepareProgressText,
  progressText,
  summarizeCapture,
  summaryText,
  type CaptureKind,
  type CaptureResult,
  type CaptureSubmitUnit,
} from "@/src/capture/batch";
import { AppButton } from "@/src/knowledge-agent/components/ui";
import { theme } from "@/src/theme";

export type CaptureSession = {
  batchId: string;
  kind: CaptureKind;
  /** 提交时固化的表单字段，重试沿用同一份说明与归属 */
  note: string;
  projectId: number | null;
  units: CaptureSubmitUnit[];
  results: CaptureResult[];
  running: boolean;
  /** 提交前的图片压缩进度；null 表示当前不在压缩阶段 */
  preparing: { total: number; current: number } | null;
};

const STATUS_LABEL: Record<CaptureResult["status"], string> = {
  pending: "等待提交",
  preparing: "正在压缩图片",
  uploading: "上传中",
  saved: "已提交",
  failed: "未成功",
};

/** 缩略图上的状态文案：比列表更短，直接压在图上。 */
const THUMB_LABEL: Record<CaptureResult["status"], string> = {
  pending: "等待",
  preparing: "压缩中",
  uploading: "上传中",
  saved: "已提交",
  failed: "未成功",
};

/** 缩略图底部固定出口高度：内容要留出这么多，最后一条才不会被挡住。 */
const FOOTER_HEIGHT = 62;

function unitLabel(unit: CaptureSubmitUnit): string {
  if (unit.text) return unit.text.split("\n")[0].slice(0, 40) || "文字来源";
  if (unit.files.length > 1) return `${unit.files.length} 张图片`;
  return unit.title ?? "图片";
}

export function SubmitOverlay({
  visible,
  session,
  projectName,
  onRetryUnit,
  onRetryFailed,
  onRetryProcessing,
  onClose,
}: {
  visible: boolean;
  session: CaptureSession;
  projectName: string;
  onRetryUnit: (key: string) => void;
  onRetryFailed: () => void;
  onRetryProcessing: (key: string, sourceId: number) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  const summary = summarizeCapture(session.results);
  const finished = summary.saved + summary.failed;
  const unitByKey = new Map(session.units.map((unit) => [unit.key, unit]));
  const failed = summary.failed > 0;
  const headline = session.preparing
    ? prepareProgressText(session.preparing)
    : session.running
      ? progressText(session.kind, { total: session.units.length, current: finished + 1 })
      : summaryText(summary);
  const title = failed && !session.running ? "提交未成功" : "提交材料";
  const materialText = session.kind === "text" ? "文字" : `${session.units.length} 张图片`;
  // 进度放在材料本身：每条提交单元一张缩略图，压缩/上传时压一层加载动效
  const thumbs = session.results
    .map((result) => {
      const unit = unitByKey.get(result.key);
      const uri = unit?.files[0]?.uri;
      if (!unit || !uri) return null;
      return { key: result.key, uri, count: unit.files.length, status: result.status };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);
  // 逐条列表在有多个提交单元、存在失败或存在「处理未启动」时都要出现
  const showList =
    session.results.length > 1 ||
    summary.failed > 0 ||
    session.results.some((item) => item.processError);

  return (
    <Modal
      visible={visible}
      animationType="slide"
      statusBarTranslucent
      onRequestClose={() => {
        // 提交进行中不允许关闭，避免重复进入采集页
        if (!session.running) onClose();
      }}
    >
      <SafeAreaView style={styles.page} edges={["top"]} accessibilityLabel="提交状态">
        <View style={styles.header}>
          <View style={styles.headerSlot} />
          <Text style={styles.headerTitle} numberOfLines={1}>
            {title}
          </Text>
          <View style={styles.headerSlot} />
        </View>
        <ScrollView
          contentContainerStyle={[
            styles.content,
            { paddingBottom: 24 + (session.running ? 0 : FOOTER_HEIGHT) + insets.bottom },
          ]}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.card} accessibilityRole="summary" accessibilityLabel={headline}>
            <View style={styles.head}>
              <View style={[styles.mark, failed && styles.markError]}>
                <CaptureIcon
                  name={session.running ? "refresh" : failed ? "alert" : "check"}
                  size={20}
                  color={session.running ? theme.green : failed ? theme.error : theme.confirmed}
                />
              </View>
              <Text style={styles.headline}>{headline}</Text>
            </View>
            <Text style={styles.hint}>
              {session.preparing
                ? "正在把原图压缩成 jpg，压缩完会自动开始上传，请保持 Grove 在前台。"
                : session.running
                ? "请保持 Grove 在前台。上传结束前不要重复提交，这一批材料不会重复生成。"
                : failed
                  ? "未成功的材料没有保存到 Grove：可按提示调整后逐条重试，已提交的条目不受影响。"
                  : "可以到桌面工作台的收集箱核对处理进展。"}
            </Text>
            {thumbs.length > 0 ? (
              <View style={styles.strip}>
                {thumbs.map((thumb, index) => {
                  const busy = thumb.status === "preparing" || thumb.status === "uploading";
                  const waiting = thumb.status === "pending";
                  return (
                    <View
                      key={thumb.key}
                      style={styles.thumb}
                      accessibilityLabel={`材料 ${index + 1}：${THUMB_LABEL[thumb.status]}`}
                    >
                      <Image source={{ uri: thumb.uri }} style={styles.thumbImage} />
                      {busy || waiting ? (
                        <View style={styles.thumbScrim}>
                          {busy ? <ActivityIndicator color="#FFFFFF" /> : null}
                          <Text style={styles.thumbLabel}>{THUMB_LABEL[thumb.status]}</Text>
                        </View>
                      ) : null}
                      {thumb.status === "saved" ? (
                        <View style={styles.thumbBadge}>
                          <CaptureIcon name="check" size={13} color="#FFFFFF" />
                        </View>
                      ) : null}
                      {thumb.status === "failed" ? (
                        <View style={[styles.thumbBadge, styles.thumbBadgeError]}>
                          <CaptureIcon name="alert" size={13} color="#FFFFFF" />
                        </View>
                      ) : null}
                      {thumb.count > 1 ? (
                        <Text style={styles.thumbCount}>{thumb.count} 张</Text>
                      ) : null}
                    </View>
                  );
                })}
              </View>
            ) : null}

            <View style={styles.facts}>
              <Text style={styles.fact}>材料：{materialText}</Text>
              <Text style={styles.fact}>所属项目：{projectName}</Text>
            </View>

            {showList ? (
              <View style={styles.list}>
                {session.results.map((result) => {
                  const unit = unitByKey.get(result.key);
                  if (!unit) return null;
                  return (
                    <View key={result.key} style={styles.row}>
                      <View style={styles.rowMain}>
                        <Text style={styles.rowTitle} numberOfLines={1}>
                          {unitLabel(unit)}
                        </Text>
                        <Text style={styles.rowMeta}>{STATUS_LABEL[result.status]}</Text>
                        {result.error ? <Text style={styles.rowError}>{result.error}</Text> : null}
                        {result.processError ? (
                          <Text style={styles.rowWarn}>
                            来源已保存，但处理启动失败（{result.processError}）
                          </Text>
                        ) : null}
                      </View>
                      {result.status === "failed" ? (
                        <Pressable
                          accessibilityRole="button"
                          accessibilityLabel="重试这一条"
                          onPress={() => onRetryUnit(result.key)}
                          disabled={session.running}
                          style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
                        >
                          <Text style={styles.retryText}>重试</Text>
                        </Pressable>
                      ) : null}
                      {result.processError && result.sourceId ? (
                        <Pressable
                          accessibilityRole="button"
                          accessibilityLabel="重试处理"
                          onPress={() => onRetryProcessing(result.key, result.sourceId as number)}
                          disabled={session.running}
                          style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
                        >
                          <Text style={styles.retryText}>重试处理</Text>
                        </Pressable>
                      ) : null}
                    </View>
                  );
                })}
              </View>
            ) : null}

            {!session.running && summary.failed > 1 ? (
              <AppButton label={`重试未成功的 ${summary.failed} 条`} block onPress={onRetryFailed} />
            ) : null}
          </View>
        </ScrollView>
        {!session.running ? (
          <View style={[styles.footer, { paddingBottom: 9 + insets.bottom }]}>
            <AppButton label="回到收集" block onPress={onClose} />
          </View>
        ) : null}
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: theme.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    backgroundColor: theme.surface,
  },
  headerSlot: { width: 44 },
  headerTitle: { flex: 1, fontSize: 16, fontWeight: "700", textAlign: "center", color: theme.ink },
  content: { padding: 16 },
  footer: { paddingTop: 9, paddingHorizontal: 16, backgroundColor: theme.bg },
  card: {
    gap: 8,
    padding: 14,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  mark: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: theme.greenSoft,
  },
  markError: { backgroundColor: theme.errorSoft },
  headline: { flex: 1, fontSize: 15, fontWeight: "700", color: theme.ink },
  hint: { fontSize: 12, lineHeight: 19, color: theme.muted },
  strip: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  thumb: { width: 72, height: 72, borderRadius: 9, overflow: "hidden" },
  thumbImage: { width: "100%", height: "100%", backgroundColor: theme.soft },
  thumbScrim: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    backgroundColor: "rgba(23,32,28,.42)",
  },
  thumbLabel: { fontSize: 10, fontWeight: "600", color: "#FFFFFF" },
  thumbBadge: {
    position: "absolute",
    right: 4,
    bottom: 4,
    width: 20,
    height: 20,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: theme.confirmed,
  },
  thumbBadgeError: { backgroundColor: theme.error },
  thumbCount: {
    position: "absolute",
    left: 4,
    top: 4,
    paddingHorizontal: 5,
    borderRadius: 6,
    overflow: "hidden",
    backgroundColor: "rgba(23,32,28,.72)",
    fontSize: 10,
    lineHeight: 16,
    color: "#FFFFFF",
  },
  facts: { gap: 2 },
  fact: { fontSize: 11.5, lineHeight: 18, color: theme.muted },
  list: { borderTopWidth: 1, borderTopColor: theme.border, paddingTop: 8, gap: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowMain: { flex: 1, minWidth: 0 },
  rowTitle: { fontSize: 12.5, fontWeight: "600", color: theme.ink },
  rowMeta: { marginTop: 2, fontSize: 10.5, color: theme.muted },
  rowError: { marginTop: 3, fontSize: 11, lineHeight: 17, color: theme.error },
  rowWarn: { marginTop: 3, fontSize: 11, lineHeight: 17, color: theme.risk },
  retry: {
    minHeight: 40,
    paddingHorizontal: 12,
    justifyContent: "center",
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  retryText: { fontSize: 12, fontWeight: "600", color: theme.ink },
  pressed: { opacity: 0.85 },
});
