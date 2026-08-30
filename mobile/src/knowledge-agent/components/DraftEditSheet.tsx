import { useState } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { AppButton } from "@/src/knowledge-agent/components/ui";
import { useKeyboardHeight } from "@/src/knowledge-agent/hooks/useKeyboardHeight";
import type { KnowledgeCandidateDraft } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

const MAIN_TYPES = ["knowledge", "method", "parameter", "reminder"] as const;
const MAIN_TYPE_LABELS: Record<string, string> = {
  knowledge: "知识",
  method: "方法",
  parameter: "参数",
  reminder: "提醒",
};

/** 可滚动编辑 Sheet：长标题/正文、多行键盘、类型选择与保存。 */
export function DraftEditSheet({
  visible,
  draft,
  saving,
  error,
  onSave,
  onClose,
}: {
  visible: boolean;
  draft: KnowledgeCandidateDraft | null;
  saving: boolean;
  error: string | null;
  onSave: (title: string, content: string, mainType: string | null) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  const keyboardHeight = useKeyboardHeight(insets.bottom);
  const scrollBottomPadding = keyboardHeight > 0 ? keyboardHeight + 24 : 24;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        style={styles.modalRoot}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Pressable
          accessibilityLabel="关闭编辑"
          style={styles.scrim}
          onPress={onClose}
        />
        {visible && draft !== null && (
          <EditForm
            key={draft.id}
            draft={draft}
            insets={insets}
            scrollBottomPadding={scrollBottomPadding}
            saving={saving}
            error={error}
            onSave={onSave}
            onClose={onClose}
          />
        )}
      </KeyboardAvoidingView>
    </Modal>
  );
}

function EditForm({
  draft,
  insets,
  scrollBottomPadding,
  saving,
  error,
  onSave,
  onClose,
}: {
  draft: KnowledgeCandidateDraft;
  insets: { bottom: number };
  scrollBottomPadding: number;
  saving: boolean;
  error: string | null;
  onSave: (title: string, content: string, mainType: string | null) => void;
  onClose: () => void;
}) {
  // 用 key 重挂载保证每次打开都从服务端 Draft 重新初始化，避免在 effect 中同步状态
  const [title, setTitle] = useState(draft.title ?? "");
  const [content, setContent] = useState(draft.content ?? "");
  const [mainType, setMainType] = useState<string | null>(draft.mainType ?? null);
  const canSave = title.trim().length > 0 && content.trim().length > 0 && !saving;
  return (
    <SafeAreaView edges={["bottom"]} style={styles.sheet}>
      <View style={styles.sheetHandle} />
      <View style={styles.sheetHead}>
        <Text style={styles.sheetTitle}>编辑知识草稿</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="关闭编辑"
          onPress={onClose}
          style={styles.sheetClose}
        >
          <AgentIcon name="close" size={20} color={theme.muted} />
        </Pressable>
      </View>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[styles.body, { paddingBottom: scrollBottomPadding }]}
        keyboardShouldPersistTaps="handled"
        accessibilityLabel="草稿编辑内容"
      >
        <Text style={styles.fieldLabel}>标题</Text>
        <TextInput
          value={title}
          onChangeText={setTitle}
          placeholder="草稿标题"
          placeholderTextColor={theme.faint}
          maxLength={255}
          style={styles.titleInput}
          accessibilityLabel="草稿标题"
        />
        <Text style={[styles.fieldLabel, styles.fieldGap]}>核心内容</Text>
        <TextInput
          value={content}
          onChangeText={setContent}
          placeholder="草稿核心内容"
          placeholderTextColor={theme.faint}
          multiline
          maxLength={8000}
          style={[styles.contentInput, { minHeight: 120 }]}
          accessibilityLabel="草稿核心内容"
        />
        <Text style={[styles.fieldLabel, styles.fieldGap]}>类型建议</Text>
        <View style={styles.typeRow}>
          {MAIN_TYPES.map((type) => {
            const selected = mainType === type;
            return (
              <Pressable
                key={type}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                accessibilityLabel={`类型：${MAIN_TYPE_LABELS[type]}`}
                onPress={() => setMainType(type)}
                style={({ pressed }) => [
                  styles.typeChip,
                  selected && styles.typeChipActive,
                  pressed && styles.pressed,
                ]}
              >
                <Text
                  style={[
                    styles.typeChipText,
                    selected && styles.typeChipTextActive,
                  ]}
                >
                  {MAIN_TYPE_LABELS[type]}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={styles.hint}>
          目标项目与来源证据不可编辑；确认时仍会重新核验来源。
        </Text>
        {error !== null && <Text style={styles.error}>{error}</Text>}
      </ScrollView>
      <View style={[styles.footer, { paddingBottom: insets.bottom + 10 }]}>
        <AppButton label="取消" variant="default" onPress={onClose} />
        <AppButton
          label={saving ? "保存中…" : "保存编辑"}
          variant="primary"
          disabled={!canSave}
          onPress={() => onSave(title.trim(), content.trim(), mainType)}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  modalRoot: { flex: 1, justifyContent: "flex-end" },
  scrim: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: theme.scrim,
  },
  sheet: {
    maxHeight: "92%",
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    backgroundColor: theme.surface,
  },
  sheetHandle: {
    width: 36,
    height: 4,
    marginTop: 8,
    marginBottom: 2,
    alignSelf: "center",
    borderRadius: 2,
    backgroundColor: "#CAD2CD",
  },
  sheetHead: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    paddingHorizontal: 14,
    paddingTop: 4,
  },
  sheetTitle: { fontSize: 17, fontWeight: "700", color: theme.ink },
  sheetClose: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.soft,
  },
  scroll: { flexGrow: 0 },
  body: { paddingHorizontal: 16, paddingTop: 8 },
  fieldLabel: {
    color: theme.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  fieldGap: { marginTop: 14 },
  titleInput: {
    height: 44,
    marginTop: 6,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 7,
    backgroundColor: theme.bg,
    color: theme.ink,
    fontSize: 14,
    fontWeight: "600",
  },
  contentInput: {
    marginTop: 6,
    paddingHorizontal: 10,
    paddingVertical: 9,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 7,
    backgroundColor: theme.bg,
    color: theme.ink,
    fontSize: 13,
    lineHeight: 20,
    textAlignVertical: "top",
  },
  typeRow: { flexDirection: "row", gap: 8, marginTop: 6, flexWrap: "wrap" },
  typeChip: {
    minHeight: 44,
    minWidth: 56,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  typeChipActive: { borderColor: theme.green, backgroundColor: theme.greenSoft },
  typeChipText: { fontSize: 12, fontWeight: "600", color: theme.muted },
  typeChipTextActive: { color: theme.green },
  pressed: { opacity: 0.85 },
  hint: {
    marginTop: 12,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  error: { marginTop: 8, color: theme.error, fontSize: 12, lineHeight: 18 },
  footer: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 14,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: theme.border,
    backgroundColor: theme.surface,
  },
});
