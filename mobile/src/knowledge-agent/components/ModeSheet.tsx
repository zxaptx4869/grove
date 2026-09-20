import { Pressable, StyleSheet, Text, View } from "react-native";

import { Sheet } from "@/src/knowledge-agent/components/ui";
import type { ModeSelection } from "@/src/knowledge-agent/state/modes";
import type { ContextMode } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

const OPTIONS: { value: ContextMode; title: string; detail: string }[] = [
  { value: "auto", title: "自动", detail: "由 Agent 判断继续当前主题或开始新话题" },
  { value: "continue", title: "继续当前主题", detail: "沿用当前主题线索理解下一条消息" },
  { value: "new_topic", title: "新话题", detail: "切断上一轮工作集，重新理解问题" },
];

export function ModeSheet({
  visible,
  modes,
  onChange,
  onClose,
}: {
  visible: boolean;
  modes: ModeSelection;
  onChange: (modes: ModeSelection) => void;
  onClose: () => void;
}) {
  return (
    <Sheet visible={visible} title="本次提问设置" onClose={onClose}>
      <Text style={styles.groupLabel}>理解上下文</Text>
      {OPTIONS.map((option) => {
        const selected = modes.contextMode === option.value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            accessibilityLabel={`${option.title}（${option.detail}）`}
            onPress={() => onChange({ contextMode: option.value })}
            style={({ pressed }) => [
              styles.option,
              selected && styles.optionSelected,
              pressed && styles.pressed,
            ]}
          >
            <View style={styles.optionMain}>
              <Text style={[styles.optionTitle, selected && styles.optionTitleSelected]}>
                {option.title}
              </Text>
              <Text style={styles.optionDetail}>{option.detail}</Text>
            </View>
            <View style={[styles.radio, selected && styles.radioSelected]}>
              {selected && <View style={styles.radioDot} />}
            </View>
          </Pressable>
        );
      })}
      <Text style={styles.footnote}>设置只作用于下一条正式消息，发送成功后恢复自动。</Text>
    </Sheet>
  );
}

const styles = StyleSheet.create({
  groupLabel: { marginBottom: 4, color: theme.muted, fontSize: 10, fontWeight: "700" },
  option: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    marginTop: 8,
    backgroundColor: theme.surface,
  },
  optionSelected: { borderColor: "#BAD5C5", backgroundColor: theme.greenSoft },
  optionMain: { flex: 1, minWidth: 0 },
  optionTitle: { fontSize: 13, fontWeight: "600", color: theme.ink },
  optionTitleSelected: { color: theme.green },
  optionDetail: { marginTop: 2, color: theme.muted, fontSize: 11, lineHeight: 17 },
  radio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: theme.border,
    alignItems: "center",
    justifyContent: "center",
  },
  radioSelected: { borderColor: theme.green },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.green },
  footnote: { marginTop: 14, color: theme.muted, fontSize: 11, lineHeight: 18 },
  pressed: { opacity: 0.85 },
});
