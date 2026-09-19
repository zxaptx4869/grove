import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { hasModeOverrides, type ModeSelection } from "@/src/knowledge-agent/state/modes";
import { theme } from "@/src/theme";

const CONTEXT_LABELS = {
  auto: "",
  continue: "继续当前主题",
  new_topic: "新话题",
} as const;

export function Composer({
  value,
  onChangeText,
  onSend,
  modes,
  onOpenModes,
  onRemoveContextOverride,
  submitting,
  disabled,
}: {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  modes: ModeSelection;
  onOpenModes: () => void;
  onRemoveContextOverride: () => void;
  submitting: boolean;
  disabled: boolean;
}) {
  const canSend = value.trim().length > 0 && !submitting && !disabled;
  const contextLabel = CONTEXT_LABELS[modes.contextMode];
  return (
    <View style={styles.wrap}>
      {hasModeOverrides(modes) && contextLabel !== "" && (
        <View style={styles.chips}>
          <View style={styles.chip}>
            <Text style={styles.chipText}>{contextLabel}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`移除${contextLabel}设置`}
              onPress={onRemoveContextOverride}
              hitSlop={8}
              style={styles.chipRemove}
            >
              <AgentIcon name="close" size={12} color={theme.green} />
            </Pressable>
          </View>
        </View>
      )}
      <View style={styles.composer}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="本次提问设置"
          onPress={onOpenModes}
          style={({ pressed }) => [styles.toolButton, pressed && styles.pressed]}
        >
          <AgentIcon name="tune" size={20} color={theme.muted} />
        </Pressable>
        <TextInput
          value={value}
          onChangeText={onChangeText}
          placeholder="问知识，或说出要分析的内容"
          placeholderTextColor={theme.muted}
          multiline
          maxLength={2000}
          style={styles.input}
          accessibilityLabel="对话输入"
          accessibilityHint="输入后发送给知识 Agent"
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={submitting ? "正在发送" : "发送"}
          accessibilityState={{ disabled: !canSend }}
          disabled={!canSend}
          onPress={() => canSend && onSend()}
          style={({ pressed }) => [
            styles.sendButton,
            !canSend && styles.sendButtonDisabled,
            pressed && canSend && styles.pressed,
          ]}
        >
          <AgentIcon name="send" size={20} color="#FFFFFF" />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: 12,
    paddingTop: 9,
    paddingBottom: 6,
    backgroundColor: theme.bg,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 7, marginBottom: 7 },
  chip: {
    minHeight: 28,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingLeft: 9,
    paddingRight: 6,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "#BAD5C5",
    backgroundColor: theme.greenSoft,
  },
  chipText: { color: theme.green, fontSize: 11, fontWeight: "600" },
  chipRemove: { width: 22, height: 22, alignItems: "center", justifyContent: "center" },
  composer: {
    minHeight: 50,
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 4,
    padding: 5,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 13,
    backgroundColor: theme.surface,
  },
  toolButton: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 96,
    paddingHorizontal: 5,
    paddingVertical: 9,
    fontSize: 14,
    lineHeight: 20,
    color: theme.ink,
  },
  sendButton: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 9,
    backgroundColor: theme.green,
  },
  sendButtonDisabled: { backgroundColor: theme.faint, opacity: 0.7 },
  pressed: { opacity: 0.85 },
});
