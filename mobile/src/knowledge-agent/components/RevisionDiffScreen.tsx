import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { AppButton, Badge } from "@/src/knowledge-agent/components/ui";
import type { KnowledgeEntryRevisionDraft } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

/** 单 Entry 全屏差异审阅：按改变字段展示原值/候选值，未变字段收敛，来源可达。 */
export function RevisionDiffScreen({
  visible,
  draft,
  onConfirm,
  onClose,
}: {
  visible: boolean;
  draft: KnowledgeEntryRevisionDraft | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  if (!visible || draft === null) return null;
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView edges={["top", "bottom"]} style={styles.page}>
        <View style={styles.header}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="返回对话"
            onPress={onClose}
            style={styles.headerIcon}
          >
            <AgentIcon name="chevron" size={22} color={theme.muted} />
          </Pressable>
          <Text style={styles.headerTitle} numberOfLines={1}>
            审阅完整差异
          </Text>
          <View style={styles.headerSpacer} />
        </View>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[
            styles.body,
            { paddingBottom: insets.bottom + 90 },
          ]}
          accessibilityLabel="完整差异审阅"
        >
          <View style={styles.summary}>
            <Badge tone="ai">AI 建议 · 待确认</Badge>
            <Text style={styles.summaryTitle}>{draft.title ?? "未命名修订草稿"}</Text>
            <Text style={styles.summaryPath}>
              目标：{draft.targetProjectName ?? "未知项目"}
              {draft.targetEntryId ? " · 单条正式知识" : ""}
            </Text>
            {draft.changeSummary ? (
              <Text style={styles.summaryChange}>{draft.changeSummary}</Text>
            ) : null}
          </View>

          {draft.changedFields.length === 0 ? (
            <View style={styles.emptyBox}>
              <Text style={styles.emptyText}>
                当前没有字段变化；编辑草稿后差异会由服务端重新计算。
              </Text>
            </View>
          ) : (
            draft.changedFields.map((field) => (
              <View key={field.field} style={styles.diffBlock}>
                <View style={styles.diffHead}>
                  <Text style={styles.diffLabel}>{field.label}</Text>
                  <Badge tone="neutral">已变化</Badge>
                </View>
                <View style={styles.diffSide}>
                  <Text style={styles.diffSideLabel}>原内容</Text>
                  <Text style={styles.diffBefore}>
                    {field.before || "（空）"}
                  </Text>
                </View>
                <View style={styles.diffSide}>
                  <Text style={styles.diffSideLabel}>建议内容</Text>
                  <Text style={styles.diffAfter}>{field.after || "（空）"}</Text>
                </View>
              </View>
            ))
          )}

          <View style={styles.sourceBlock}>
            <View style={styles.diffHead}>
              <Text style={styles.diffLabel}>本次采用的来源证据</Text>
              <Badge tone="confirmed">
                {draft.evidenceSummaries.length} 条
              </Badge>
            </View>
            {draft.evidenceSummaries.length === 0 ? (
              <Text style={styles.sourceEmpty}>没有可核验来源</Text>
            ) : (
              draft.evidenceSummaries.map((evidence) => (
                <View key={evidence.handle} style={styles.sourceRow}>
                  <AgentIcon name="quote" size={14} color={theme.confirmed} />
                  <View style={styles.sourceMain}>
                    <Text style={styles.sourceTitle} numberOfLines={1}>
                      {evidence.sourceTitle}
                    </Text>
                    <Text style={styles.sourceQuote} numberOfLines={3}>
                      “{evidence.quote}”
                    </Text>
                  </View>
                </View>
              ))
            )}
          </View>
        </ScrollView>
        <View style={[styles.footer, { paddingBottom: insets.bottom + 10 }]}>
          <AppButton label="返回" variant="default" onPress={onClose} />
          <AppButton label="确认修改" variant="primary" onPress={onConfirm} />
        </View>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: theme.bg },
  header: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6,
    paddingHorizontal: 10,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    backgroundColor: theme.surface,
  },
  headerIcon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 9,
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: theme.ink,
    flexShrink: 1,
    textAlign: "center",
  },
  headerSpacer: { width: 44 },
  scroll: { flex: 1 },
  body: { paddingHorizontal: 16, paddingTop: 14 },
  summary: { marginBottom: 4 },
  summaryTitle: {
    marginTop: 8,
    fontSize: 17,
    lineHeight: 24,
    fontWeight: "700",
    color: theme.ink,
  },
  summaryPath: { marginTop: 4, color: theme.muted, fontSize: 11, lineHeight: 17 },
  summaryChange: {
    marginTop: 8,
    color: theme.ink,
    fontSize: 12,
    lineHeight: 19,
  },
  emptyBox: {
    marginTop: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.surface,
  },
  emptyText: { color: theme.muted, fontSize: 12, lineHeight: 19 },
  diffBlock: {
    marginTop: 14,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.surface,
    overflow: "hidden",
  },
  diffHead: {
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    paddingHorizontal: 11,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  diffLabel: { fontSize: 12, fontWeight: "700", color: theme.ink },
  diffSide: { paddingHorizontal: 11, paddingVertical: 9 },
  diffSideLabel: {
    color: theme.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  diffBefore: {
    marginTop: 4,
    color: theme.muted,
    fontSize: 12,
    lineHeight: 19,
  },
  diffAfter: {
    marginTop: 4,
    color: theme.ink,
    fontSize: 12,
    lineHeight: 19,
  },
  sourceBlock: {
    marginTop: 14,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.surface,
    overflow: "hidden",
  },
  sourceEmpty: { padding: 11, color: theme.muted, fontSize: 12 },
  sourceRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    paddingHorizontal: 11,
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  sourceMain: { flex: 1, minWidth: 0 },
  sourceTitle: { fontSize: 12, fontWeight: "700", color: theme.ink },
  sourceQuote: { marginTop: 3, fontSize: 11, lineHeight: 18, color: theme.muted },
  footer: {
    position: "absolute",
    right: 0,
    bottom: 0,
    left: 0,
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 14,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: theme.border,
    backgroundColor: theme.surface,
  },
});
