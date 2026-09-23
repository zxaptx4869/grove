/** 相册下钻：先选「每张一条」或「多张合并一条」，再打开系统选择器。 */

import { Pressable, StyleSheet, Text } from "react-native";

import { Sheet } from "@/src/knowledge-agent/components/ui";
import type { CaptureKind } from "@/src/capture/batch";
import { theme } from "@/src/theme";

const CHOICES: { value: "album-separate" | "album-merged"; title: string; detail: string }[] = [
  { value: "album-separate", title: "每张一条", detail: "选 1–5 张图片，每张单独作为一条采集" },
  { value: "album-merged", title: "多张合并一条", detail: "选 2–5 张图片，合并成一条采集一起整理" },
];

export function AlbumChoiceSheet({
  visible,
  onChoose,
  onClose,
}: {
  visible: boolean;
  onChoose: (kind: CaptureKind) => void;
  onClose: () => void;
}) {
  return (
    <Sheet visible={visible} title="从相册选择" onClose={onClose}>
      {CHOICES.map((choice) => (
        <Pressable
          key={choice.value}
          accessibilityRole="button"
          accessibilityLabel={`${choice.title}（${choice.detail}）`}
          onPress={() => onChoose(choice.value)}
          style={({ pressed }) => [styles.choice, pressed && styles.pressed]}
        >
          <Text style={styles.title}>{choice.title}</Text>
          <Text style={styles.detail}>{choice.detail}</Text>
        </Pressable>
      ))}
      <Text style={styles.footnote}>系统选择器最多可选 5 张。</Text>
    </Sheet>
  );
}

const styles = StyleSheet.create({
  choice: {
    minHeight: 52,
    marginTop: 8,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  title: { fontSize: 13, fontWeight: "600", color: theme.ink },
  detail: { marginTop: 2, fontSize: 11, lineHeight: 17, color: theme.muted },
  footnote: { marginTop: 14, fontSize: 11, lineHeight: 18, color: theme.muted },
  pressed: { opacity: 0.85 },
});
