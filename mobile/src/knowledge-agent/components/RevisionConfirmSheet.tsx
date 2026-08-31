import { StyleSheet, Text, View } from "react-native";

import { AppButton, Sheet } from "@/src/knowledge-agent/components/ui";
import type { KnowledgeEntryRevisionDraft } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

/** 确认修订前的后果说明：明确将更新 1 条正式知识并追加版本。 */
export function RevisionConfirmSheet({
  visible,
  draft,
  confirming,
  error,
  retryable,
  onConfirm,
  onClose,
}: {
  visible: boolean;
  draft: KnowledgeEntryRevisionDraft | null;
  confirming: boolean;
  error: string | null;
  /** 网络结果未知时保留幂等键，可原键重试；确定性冲突不可重试。 */
  retryable: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const sourceCount = draft?.evidenceSummaries.length ?? 0;
  const changedCount = draft?.changedFields.length ?? 0;
  const blocked = error !== null && !retryable;
  const retry = error !== null && retryable;
  return (
    <Sheet visible={visible} title="确认知识修改" onClose={onClose}>
      {draft !== null && (
        <>
          <View style={styles.confirmBox}>
            <Text style={styles.confirmTitle}>
              {draft.targetProjectName ?? "未知项目"}
            </Text>
            <Text style={styles.confirmTitleSub}>{draft.title ?? "未命名修订草稿"}</Text>
            <Text style={styles.confirmCopy}>
              将更新 1 条正式知识并追加版本，保留既有来源
              {sourceCount > 0 ? `；本次采用 ${sourceCount} 条核验来源` : ""}；
              未发生后续修改时可以撤销。
            </Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>变化字段</Text>
            <Text style={styles.metaValue}>
              {changedCount > 0 ? `${changedCount} 项` : "—"}
            </Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>新增来源</Text>
            <Text style={styles.metaValue}>
              {sourceCount > 0 ? "确认时按去重结果计算" : "—"}
            </Text>
          </View>
          <View style={styles.noteBox}>
            <Text style={styles.noteTitle}>确认后不能直接撤销后续修改</Text>
            <Text style={styles.noteCopy}>
              如果正式知识随后被人工编辑或再次修订，撤销将被阻止，请到版本历史处理。
            </Text>
          </View>
          {blocked && (
            <View style={styles.conflictBox}>
              <Text style={styles.conflictTitle}>未能确认</Text>
              <Text style={styles.conflictCopy}>{error}</Text>
            </View>
          )}
          {retry && (
            <View style={styles.conflictBox}>
              <Text style={styles.conflictTitle}>结果未知，可重试</Text>
              <Text style={styles.conflictCopy}>{error}</Text>
            </View>
          )}
          <View style={styles.actions}>
            <AppButton label="返回检查" variant="default" onPress={onClose} />
            <AppButton
              label={
                confirming
                  ? "确认中…"
                  : retry
                    ? "重试确认"
                    : "确认执行"
              }
              variant="primary"
              disabled={confirming || blocked}
              onPress={onConfirm}
            />
          </View>
        </>
      )}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  confirmBox: {
    padding: 11,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.bg,
  },
  confirmTitle: { fontSize: 13, fontWeight: "700", color: theme.ink },
  confirmTitleSub: { marginTop: 2, fontSize: 13, fontWeight: "600", color: theme.ink },
  confirmCopy: {
    marginTop: 4,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  metaRow: {
    minHeight: 36,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  metaLabel: { fontSize: 12, color: theme.ink },
  metaValue: { fontSize: 12, color: theme.muted },
  noteBox: {
    marginTop: 10,
    padding: 10,
    borderLeftWidth: 3,
    borderLeftColor: theme.risk,
    borderRadius: 7,
    backgroundColor: theme.riskSoft,
  },
  noteTitle: { fontSize: 12, fontWeight: "700", color: "#76501C" },
  noteCopy: { marginTop: 4, color: "#76501C", fontSize: 11, lineHeight: 18 },
  conflictBox: {
    marginTop: 10,
    padding: 10,
    borderRadius: 7,
    backgroundColor: theme.errorSoft,
  },
  conflictTitle: { fontSize: 12, fontWeight: "700", color: theme.error },
  conflictCopy: { marginTop: 4, color: "#7C2E2E", fontSize: 11, lineHeight: 18 },
  actions: {
    flexDirection: "row",
    gap: 8,
    marginTop: 14,
  },
});
