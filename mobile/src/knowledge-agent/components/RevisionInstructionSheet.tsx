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
import type { RevisionTarget } from "@/src/knowledge-agent/adapters/answer";
import { theme } from "@/src/theme";

/** 修订指令 Sheet：先显示目标与后果，再提交非空指令。 */
export function RevisionInstructionSheet({
  visible,
  target,
  sourceRunId,
  submitting,
  error,
  onSubmit,
  onClose,
}: {
  visible: boolean;
  target: RevisionTarget | null;
  sourceRunId: number | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (sourceRunId: number, targetEntryId: number, instruction: string) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  const keyboardHeight = useKeyboardHeight(insets.bottom);
  const scrollBottomPadding = keyboardHeight > 0 ? keyboardHeight + 24 : 24;
  const [instruction, setInstruction] = useState("");
  const canSubmit =
    instruction.trim().length > 0 && !submitting && target !== null;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.modalRoot}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Pressable
          accessibilityLabel="关闭修订指令"
          style={styles.scrim}
          onPress={onClose}
        />
        {visible && target !== null && (
          <SafeAreaView edges={["bottom"]} style={styles.sheet}>
            <View style={styles.sheetHandle} />
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>修订这条知识</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="关闭修订指令"
                onPress={onClose}
                style={styles.sheetClose}
              >
                <AgentIcon name="close" size={20} color={theme.muted} />
              </Pressable>
            </View>
            <ScrollView
              style={styles.scroll}
              contentContainerStyle={[
                styles.body,
                { paddingBottom: scrollBottomPadding },
              ]}
              keyboardShouldPersistTaps="handled"
              accessibilityLabel="修订指令内容"
            >
              <Text style={styles.entryTitle}>{target.entryTitle}</Text>
              <Text style={styles.path}>
                {[target.projectName, target.nodePath].filter(Boolean).join(" / ") ||
                  "归属未标注"}
              </Text>
              <View style={styles.consequenceBox}>
                <Text style={styles.consequenceTitle}>确认后会发生什么</Text>
                <Text style={styles.consequenceCopy}>
                  将修改这条正式知识并追加版本；来源只采用本次回答核验的证据，
                  你确认前不会写入。
                </Text>
              </View>
              <Text style={styles.fieldLabel}>修订要求</Text>
              <TextInput
                value={instruction}
                onChangeText={setInstruction}
                placeholder="说明希望如何修订这条知识（不能为空）"
                placeholderTextColor={theme.faint}
                multiline
                maxLength={2000}
                style={[styles.instructionInput, { minHeight: 110 }]}
                accessibilityLabel="修订要求"
                editable={!submitting}
              />
              <Text style={styles.hint}>
                只会修订你明确选中的这一条知识；普通问答不会自动触发修改。
              </Text>
              {error !== null && <Text style={styles.error}>{error}</Text>}
            </ScrollView>
            <View style={[styles.footer, { paddingBottom: insets.bottom + 10 }]}>
              <AppButton label="关闭" variant="default" onPress={onClose} />
              <AppButton
                label={submitting ? "提交中…" : "提交修订"}
                variant="primary"
                disabled={!canSubmit}
                onPress={() => {
                  if (sourceRunId !== null && target !== null) {
                    onSubmit(sourceRunId, target.entryId, instruction.trim());
                  }
                }}
              />
            </View>
          </SafeAreaView>
        )}
      </KeyboardAvoidingView>
    </Modal>
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
  entryTitle: { fontSize: 16, fontWeight: "700", lineHeight: 23, color: theme.ink },
  path: { marginTop: 4, color: theme.muted, fontSize: 11, lineHeight: 17 },
  consequenceBox: {
    marginTop: 12,
    padding: 11,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.bg,
  },
  consequenceTitle: { fontSize: 12, fontWeight: "700", color: theme.ink },
  consequenceCopy: {
    marginTop: 4,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  fieldLabel: {
    marginTop: 14,
    color: theme.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  instructionInput: {
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
  hint: {
    marginTop: 10,
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
