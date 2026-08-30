import { StyleSheet, Text, View } from "react-native";

import { AppButton, Sheet } from "@/src/knowledge-agent/components/ui";
import type { KnowledgeCandidateDraft } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

/** 确认草稿前的后果说明：只创建待确认 Candidate，不会直接写入正式知识。 */
export function DraftConfirmSheet({
  visible,
  draft,
  confirming,
  error,
  onConfirm,
  onClose,
}: {
  visible: boolean;
  draft: KnowledgeCandidateDraft | null;
  confirming: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const sourceCount = draft?.evidenceSummaries.length ?? 0;
  return (
    <Sheet visible={visible} title="创建待确认知识" onClose={onClose}>
      {draft !== null && (
        <>
          <View style={styles.confirmBox}>
            <Text style={styles.confirmTitle}>
              {draft.targetProjectName ?? "未知项目"}
            </Text>
            <Text style={styles.confirmTitleSub}>{draft.title ?? "未命名草稿"}</Text>
            <Text style={styles.confirmCopy}>
              将创建 1 条待确认 Candidate，保留 {sourceCount > 0 ? sourceCount : 0}{" "}
              条来源证据；不会直接写入正式知识。
            </Text>
          </View>
          <View style={styles.noteBox}>
            <Text style={styles.noteTitle}>尚未成为正式知识</Text>
            <Text style={styles.noteCopy}>
              确认后仍可在桌面确认台查看并最终确认；目录与关系建议会在确认流程中处理。
            </Text>
          </View>
          {error !== null && <Text style={styles.error}>{error}</Text>}
          <View style={styles.actions}>
            <AppButton label="返回检查" variant="default" onPress={onClose} />
            <AppButton
              label={confirming ? "创建中…" : "创建待确认知识"}
              variant="primary"
              disabled={confirming}
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
  error: { marginTop: 10, color: theme.error, fontSize: 12, lineHeight: 18 },
  actions: {
    flexDirection: "row",
    gap: 8,
    marginTop: 14,
  },
});
