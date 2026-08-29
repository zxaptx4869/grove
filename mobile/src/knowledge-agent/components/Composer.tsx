import {
  Keyboard,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { hasModeOverrides } from "@/src/knowledge-agent/state/modes";
import type { ModeSelection } from "@/src/knowledge-agent/state/modes";
import type { AnswerMode, ContextMode } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

const CONTEXT_LABELS: Record<ContextMode, string> = {
  auto: "",
  continue: "继续当前主题",
  new_topic: "新话题",
};

const ANSWER_LABELS: Record<AnswerMode, string> = {
  auto: "",
  quick: "快速回答",
  investigate: "深度查找",
};

export function Composer({
  value,
  onChangeText,
  onSend,
  modes,
  onOpenModes,
  onRemoveContextOverride,
  onRemoveAnswerOverride,
  submitting,
  disabled,
}: {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  modes: ModeSelection;
  onOpenModes: () => void;
  onRemoveContextOverride: () => void;
  onRemoveAnswerOverride: () => void;
  submitting: boolean;
  disabled: boolean;
}) {
  const trimmed = value.trim();
  const canSend = trimmed.length > 0 && !submitting && !disabled;
  const contextLabel = CONTEXT_LABELS[modes.contextMode];
  const answerLabel = ANSWER_LABELS[modes.answerMode];
  return (
    <View style={styles.wrap}>
      {hasModeOverrides(modes) && (
        <View style={styles.chips}>
          {contextLabel !== "" && (
            <ModeChip label={contextLabel} onRemove={onRemoveContextOverride} />
          )}
          {answerLabel !== "" && (
            <ModeChip label={answerLabel} onRemove={onRemoveAnswerOverride} />
          )}
        </View>
      )}
      <View style={styles.composer}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="本次提问设置"
          onPress={onOpenModes}
          style={({ pressed }) => [styles.toolButton, pressed && styles.pressed]}
        >
          <AgentIcon name="more" size={20} color={theme.muted} />
        </Pressable>
        <TextInput
          value={value}
          onChangeText={onChangeText}
          placeholder="问知识，或说出要做的事"
          placeholderTextColor={theme.muted}
          multiline
          maxLength={2000}
          style={styles.input}
          accessibilityLabel="对话输入"
          accessibilityHint="输入问题，发送后由知识 Agent 基于正式知识回答"
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={submitting ? "正在发送" : "发送"}
          accessibilityState={{ disabled: !canSend }}
          disabled={!canSend}
          onPress={() => {
            if (canSend) {
              Keyboard.dismiss();
              onSend();
            }
          }}
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

function ModeChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <View style={styles.chip}>
      <Text style={styles.chipText}>{label}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`移除${label}设置`}
        onPress={onRemove}
        hitSlop={8}
        style={styles.chipRemove}
      >
        <AgentIcon name="close" size={12} color={theme.green} />
      </Pressable>
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
  chips: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 7,
    marginBottom: 7,
  },
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
    shadowColor: "#162B20",
    shadowOpacity: 0.09,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 8 },
    elevation: 3,
  },
  toolButton: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 9,
  },
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
