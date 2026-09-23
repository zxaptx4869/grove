/** 采集入口区：相机 / 相册 / 文本 三个动作横排。 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { CaptureIcon, type CaptureIconName } from "@/src/capture/components/CaptureIcon";
import { theme } from "@/src/theme";

const ENTRIES: { key: "camera" | "album" | "text"; label: string; icon: CaptureIconName }[] = [
  { key: "camera", label: "相机", icon: "camera" },
  { key: "album", label: "相册", icon: "images" },
  { key: "text", label: "文本", icon: "text" },
];

export function EntryRow({
  onSelect,
  disabled = false,
}: {
  onSelect: (entry: "camera" | "album" | "text") => void;
  disabled?: boolean;
}) {
  return (
    <View style={styles.row}>
      {ENTRIES.map((entry) => (
        <Pressable
          key={entry.key}
          accessibilityRole="button"
          accessibilityLabel={`${entry.label}采集`}
          accessibilityState={{ disabled }}
          disabled={disabled}
          onPress={() => onSelect(entry.key)}
          style={({ pressed }) => [styles.tile, pressed && !disabled && styles.pressed]}
        >
          <View style={styles.icon}>
            <CaptureIcon name={entry.icon} size={19} color={theme.green} />
          </View>
          <Text style={styles.label}>{entry.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 10 },
  tile: {
    flex: 1,
    minHeight: 92,
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
  },
  icon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.greenSoft,
  },
  label: { fontSize: 13, lineHeight: 20, fontWeight: "600", color: theme.ink },
  pressed: { opacity: 0.85 },
});
