/** 采集结果：进行中 / 全部成功 / 部分失败 / 全部失败，失败项可逐条重试。 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { CaptureIcon } from "@/src/capture/components/CaptureIcon";
import {
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
};

const STATUS_LABEL: Record<CaptureResult["status"], string> = {
  pending: "等待提交",
  uploading: "上传中",
  saved: "已提交",
  failed: "未成功",
};

function unitLabel(unit: CaptureSubmitUnit): string {
  if (unit.text) return unit.text.split("\n")[0].slice(0, 40) || "文字来源";
  if (unit.files.length > 1) return `${unit.files.length} 张图片`;
  return unit.title ?? "图片";
}

export function SubmitStatus({
  session,
  onRetryUnit,
  onRetryFailed,
  onRetryProcessing,
  onStartOver,
}: {
  session: CaptureSession;
  onRetryUnit: (key: string) => void;
  onRetryFailed: () => void;
  onRetryProcessing: (key: string, sourceId: number) => void;
  onStartOver: () => void;
}) {
  const summary = summarizeCapture(session.results);
  const finished = summary.saved + summary.failed;
  const unitByKey = new Map(session.units.map((unit) => [unit.key, unit]));
  const headline = session.running
    ? progressText(session.kind, { total: session.units.length, current: finished + 1 })
    : summaryText(summary);

  return (
    <View style={styles.card} accessibilityRole="summary" accessibilityLabel={headline}>
      <View style={styles.head}>
        <View style={[styles.mark, summary.failed > 0 && !session.running && styles.markError]}>
          <CaptureIcon
            name={session.running ? "refresh" : summary.failed > 0 ? "alert" : "check"}
            size={18}
            color={session.running ? theme.green : summary.failed > 0 ? theme.error : theme.confirmed}
          />
        </View>
        <Text style={styles.headline}>{headline}</Text>
      </View>
      <Text style={styles.hint}>
        {session.running
          ? "请保持 Grove 在前台。上传结束前不要重复提交，这一批材料不会重复生成。"
          : "可以到桌面工作台的收集箱核对处理进展。"}
      </Text>
      {!session.running && summary.failed > 0 ? (
        <Text style={styles.rowError}>
          未成功的材料没有保存到 Grove：可按提示调整后逐条重试，已提交的条目不受影响。
        </Text>
      ) : null}

      {session.results.length > 1 || summary.failed > 0 ? (
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
      {!session.running ? (
        <AppButton label="再采一次" variant="ghost" block onPress={onStartOver} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
    gap: 8,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  mark: {
    width: 32,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.greenSoft,
  },
  markError: { backgroundColor: theme.errorSoft },
  headline: { flex: 1, fontSize: 14, fontWeight: "700", color: theme.ink },
  hint: { fontSize: 11, lineHeight: 18, color: theme.muted },
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
