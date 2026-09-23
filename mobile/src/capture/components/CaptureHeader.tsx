/** 采集页顶栏：左侧返回、居中标题（对齐原型 .app-header）。 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { CaptureIcon } from "@/src/capture/components/CaptureIcon";
import { theme } from "@/src/theme";

export function CaptureHeader({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <View style={styles.header}>
      <View style={styles.slot}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="返回收集列表"
          onPress={onBack}
          style={({ pressed }) => [styles.icon, pressed && styles.pressed]}
        >
          <CaptureIcon name="back" size={22} color={theme.ink} />
        </Pressable>
      </View>
      <Text style={styles.title} numberOfLines={1}>
        {title}
      </Text>
      <View style={styles.slot} />
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    backgroundColor: theme.surface,
  },
  slot: { width: 44, alignItems: "center" },
  icon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 9,
  },
  title: { flex: 1, fontSize: 16, fontWeight: "700", textAlign: "center", color: theme.ink },
  pressed: { opacity: 0.85 },
});
