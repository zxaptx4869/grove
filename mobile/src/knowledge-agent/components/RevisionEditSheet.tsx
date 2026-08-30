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
import {
  DRAFT_MAIN_TYPES,
  DRAFT_MAIN_TYPE_LABELS,
} from "@/src/knowledge-agent/draftTypes";
import { useKeyboardHeight } from "@/src/knowledge-agent/hooks/useKeyboardHeight";
import type { KnowledgeEntryRevisionDraft } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

const INFO_NATURES = [
  "fact",
  "experience",
  "advice",
  "speculation",
  "other",
] as const;
const INFO_NATURE_LABELS: Record<string, string> = {
  fact: "事实",
  experience: "经验",
  advice: "建议",
  speculation: "推测",
  other: "其他",
};

/** 可滚动修订编辑 Sheet：长标题/正文/条件/说明、类型选择与变更摘要。 */
export function RevisionEditSheet({
  visible,
  draft,
  saving,
  error,
  onSave,
  onClose,
}: {
  visible: boolean;
  draft: KnowledgeEntryRevisionDraft | null;
  saving: boolean;
  error: string | null;
  onSave: (fields: {
    title: string;
    content: string;
    mainType: string | null;
    infoNature: string | null;
    applicableCondition: string | null;
    note: string | null;
    changeSummary: string | null;
  }) => void;
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
          accessibilityLabel="关闭修订编辑"
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
  draft: KnowledgeEntryRevisionDraft;
  insets: { bottom: number };
  scrollBottomPadding: number;
  saving: boolean;
  error: string | null;
  onSave: (fields: {
    title: string;
    content: string;
    mainType: string | null;
    infoNature: string | null;
    applicableCondition: string | null;
    note: string | null;
    changeSummary: string | null;
  }) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(draft.title ?? "");
  const [content, setContent] = useState(draft.content ?? "");
  const [mainType, setMainType] = useState<string | null>(draft.mainType ?? null);
  const [infoNature, setInfoNature] = useState<string | null>(
    draft.infoNature ?? null,
  );
  const [applicableCondition, setApplicableCondition] = useState(
    draft.applicableCondition ?? "",
  );
  const [note, setNote] = useState(draft.note ?? "");
  const [changeSummary, setChangeSummary] = useState(draft.changeSummary ?? "");
  const canSave =
    title.trim().length > 0 &&
    content.trim().length > 0 &&
    changeSummary.trim().length > 0 &&
    !saving;
  return (
    <SafeAreaView edges={["bottom"]} style={styles.sheet}>
      <View style={styles.sheetHandle} />
      <View style={styles.sheetHead}>
        <Text style={styles.sheetTitle}>编辑修订草稿</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="关闭修订编辑"
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
        accessibilityLabel="修订草稿编辑内容"
      >
        <Text style={styles.fieldLabel}>标题</Text>
        <TextInput
          value={title}
          onChangeText={setTitle}
          placeholder="修订后标题"
          placeholderTextColor={theme.faint}
          maxLength={255}
          style={styles.titleInput}
          accessibilityLabel="修订后标题"
        />
        <Text style={[styles.fieldLabel, styles.fieldGap]}>核心内容</Text>
        <TextInput
          value={content}
          onChangeText={setContent}
          placeholder="修订后核心内容"
          placeholderTextColor={theme.faint}
          multiline
          maxLength={8000}
          style={[styles.contentInput, { minHeight: 120 }]}
          accessibilityLabel="修订后核心内容"
        />
        <Text style={[styles.fieldLabel, styles.fieldGap]}>类型建议</Text>
        <View style={styles.typeRow}>
          {DRAFT_MAIN_TYPES.map((type) => {
            const selected = mainType === type;
            return (
              <Pressable
                key={type}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                accessibilityLabel={`类型：${DRAFT_MAIN_TYPE_LABELS[type]}`}
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
                  {DRAFT_MAIN_TYPE_LABELS[type]}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={[styles.fieldLabel, styles.fieldGap]}>信息性质</Text>
        <View style={styles.typeRow}>
          {INFO_NATURES.map((nature) => {
            const selected = infoNature === nature;
            return (
              <Pressable
                key={nature}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                accessibilityLabel={`信息性质：${INFO_NATURE_LABELS[nature]}`}
                onPress={() => setInfoNature(nature)}
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
                  {INFO_NATURE_LABELS[nature]}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={[styles.fieldLabel, styles.fieldGap]}>适用条件</Text>
        <TextInput
          value={applicableCondition}
          onChangeText={setApplicableCondition}
          placeholder="适用条件（可空）"
          placeholderTextColor={theme.faint}
          multiline
          maxLength={8000}
          style={[styles.contentInput, { minHeight: 70 }]}
          accessibilityLabel="适用条件"
        />
        <Text style={[styles.fieldLabel, styles.fieldGap]}>补充说明</Text>
        <TextInput
          value={note}
          onChangeText={setNote}
          placeholder="补充说明（可空）"
          placeholderTextColor={theme.faint}
          multiline
          maxLength={8000}
          style={[styles.contentInput, { minHeight: 70 }]}
          accessibilityLabel="补充说明"
        />
        <Text style={[styles.fieldLabel, styles.fieldGap]}>变更摘要</Text>
        <TextInput
          value={changeSummary}
          onChangeText={setChangeSummary}
          placeholder="用一句话说明本次修改"
          placeholderTextColor={theme.faint}
          maxLength={1000}
          style={styles.titleInput}
          accessibilityLabel="变更摘要"
        />
        <Text style={styles.hint}>
          目标知识、来源证据与基线不可编辑；确认时服务端会重新核验并计算差异。
        </Text>
        {error !== null && <Text style={styles.error}>{error}</Text>}
      </ScrollView>
      <View style={[styles.footer, { paddingBottom: insets.bottom + 10 }]}>
        <AppButton label="取消" variant="default" onPress={onClose} />
        <AppButton
          label={saving ? "保存中…" : "保存编辑"}
          variant="primary"
          disabled={!canSave}
          onPress={() =>
            onSave({
              title: title.trim(),
              content: content.trim(),
              mainType,
              infoNature,
              applicableCondition:
                applicableCondition.trim() === ""
                  ? null
                  : applicableCondition.trim(),
              note: note.trim() === "" ? null : note.trim(),
              changeSummary: changeSummary.trim(),
            })
          }
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
