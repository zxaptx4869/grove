import { Pressable, StyleSheet, Text, View } from "react-native";

import { Sheet } from "@/src/knowledge-agent/components/ui";
import type {
  AnswerMode,
  ContextMode,
  ResultMode,
} from "@/src/knowledge-agent/types";
import type { ModeSelection } from "@/src/knowledge-agent/state/modes";
import { theme } from "@/src/theme";

const CONTEXT_OPTIONS: { value: ContextMode; title: string; detail: string }[] = [
  { value: "auto", title: "自动", detail: "由 Agent 判断继续当前主题或新话题" },
  { value: "continue", title: "继续当前主题", detail: "基于上一轮主题与工作集回答" },
  { value: "new_topic", title: "新话题", detail: "切断上一轮工作集，重新理解指代" },
];

const ANSWER_OPTIONS: { value: AnswerMode; title: string; detail: string }[] = [
  { value: "auto", title: "自动", detail: "由 Agent 选择快速回答或深度查找" },
  { value: "quick", title: "快速回答", detail: "单轮检索，最快返回" },
  { value: "investigate", title: "深度查找", detail: "最多三轮受限调查，带证据核验" },
];

const RESULT_OPTIONS: { value: ResultMode; title: string; detail: string }[] = [
  { value: "auto", title: "自动", detail: "由 Agent 判断综合回答或列出知识" },
  { value: "answer", title: "综合回答", detail: "返回带引用的综合结论" },
  { value: "entries", title: "知识列表", detail: "列出匹配的正式知识条目" },
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
      {CONTEXT_OPTIONS.map((option) => (
        <ModeOption
          key={option.value}
          title={option.title}
          detail={option.detail}
          selected={modes.contextMode === option.value}
          onPress={() => onChange({ ...modes, contextMode: option.value })}
        />
      ))}
      <Text style={[styles.groupLabel, styles.groupLabelSecond]}>回答方式</Text>
      {ANSWER_OPTIONS.map((option) => (
        <ModeOption
          key={option.value}
          title={option.title}
          detail={option.detail}
          selected={modes.answerMode === option.value}
          onPress={() => onChange({ ...modes, answerMode: option.value })}
        />
      ))}
      <Text style={[styles.groupLabel, styles.groupLabelSecond]}>结果形式</Text>
      {RESULT_OPTIONS.map((option) => (
        <ModeOption
          key={option.value}
          title={option.title}
          detail={option.detail}
          selected={modes.resultMode === option.value}
          onPress={() => onChange({ ...modes, resultMode: option.value })}
        />
      ))}
      <Text style={styles.footnote}>
        设置只作用于下一条消息，发送成功后恢复为自动。
      </Text>
    </Sheet>
  );
}

function ModeOption({
  title,
  detail,
  selected,
  onPress,
}: {
  title: string;
  detail: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: selected }}
      accessibilityLabel={`${title}（${detail}）`}
      onPress={onPress}
      style={({ pressed }) => [
        styles.option,
        selected && styles.optionSelected,
        pressed && styles.pressed,
      ]}
    >
      <View style={styles.optionMain}>
        <Text style={[styles.optionTitle, selected && styles.optionTitleSelected]}>
          {title}
        </Text>
        <Text style={styles.optionDetail}>{detail}</Text>
      </View>
      <View style={[styles.radio, selected && styles.radioSelected]}>
        {selected && <View style={styles.radioDot} />}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  groupLabel: {
    marginBottom: 4,
    color: theme.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  groupLabelSecond: { marginTop: 14 },
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
  optionSelected: {
    borderColor: "#BAD5C5",
    backgroundColor: theme.greenSoft,
  },
  pressed: { opacity: 0.85 },
  optionMain: { flex: 1, minWidth: 0 },
  optionTitle: { fontSize: 13, fontWeight: "600", color: theme.ink },
  optionTitleSelected: { color: theme.green },
  optionDetail: { marginTop: 2, color: theme.muted, fontSize: 11 },
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
  footnote: {
    marginTop: 14,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
});
