import { StyleSheet, Text, View } from "react-native";

import { AppButton, Sheet } from "@/src/knowledge-agent/components/ui";
import type { KnowledgeEntryRevisionDraft } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

/** 撤销二次确认：恢复操作前状态；审计记录不会删除。 */
export function RevisionUndoSheet({
  visible,
  draft,
  undoing,
  error,
  retryable,
  onUndo,
  onClose,
}: {
  visible: boolean;
  draft: KnowledgeEntryRevisionDraft | null;
  undoing: boolean;
  error: string | null;
  /** 网络结果未知时保留撤销键，可原键重试；确定性冲突不可重试。 */
  retryable: boolean;
  onUndo: () => void;
  onClose: () => void;
}) {
  const blocked = error !== null && !retryable;
  const retry = error !== null && retryable;
  return (
    <Sheet visible={visible} title="撤销此次操作？" onClose={onClose}>
      {draft !== null && (
        <>
          <View style={styles.confirmBox}>
            <Text style={styles.confirmTitle}>恢复操作前状态</Text>
            <Text style={styles.confirmCopy}>
              目标正式知识将恢复到修订前字段，只移除本次新增的来源关系，
              追加恢复版本；审计记录不会删除。
            </Text>
          </View>
          <View style={styles.noteBox}>
            <Text style={styles.noteTitle}>仅当没有后续修改时可撤销</Text>
            <Text style={styles.noteCopy}>
              如果知识随后被人工编辑或再次修订，撤销会被拒绝，请到版本历史处理。
            </Text>
          </View>
          {blocked && (
            <View style={styles.conflictBox}>
              <Text style={styles.conflictTitle}>无法撤销</Text>
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
            <AppButton label="取消" variant="default" onPress={onClose} />
            <AppButton
              label={undoing ? "撤销中…" : retry ? "重试撤销" : "撤销操作"}
              variant="danger"
              disabled={undoing || blocked}
              onPress={onUndo}
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
  confirmCopy: {
    marginTop: 4,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
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
