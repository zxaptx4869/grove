/** 权限被拒说明：讲清用途，提供「去设置」，不反复弹窗。 */

import { StyleSheet, Text, View } from "react-native";

import { CaptureIcon } from "@/src/capture/components/CaptureIcon";
import { AppButton, Sheet } from "@/src/knowledge-agent/components/ui";
import type { PermissionKind } from "@/src/capture/picker";
import { theme } from "@/src/theme";

const CONTENT: Record<
  PermissionKind,
  { title: string; heading: string; purpose: string; bullets: string[]; icon: "camera" | "images" }
> = {
  camera: {
    title: "相机权限",
    heading: "无法使用相机",
    purpose: "Grove 需要调用系统相机完成拍摄，照片会直接作为这条来源的原始材料。",
    bullets: [
      "只在拍摄时调用相机",
      "不保存取景过程，也不做连续拍摄",
      "照片只保存在你当前的 Workspace",
    ],
    icon: "camera",
  },
  album: {
    title: "相册权限",
    heading: "无法访问相册",
    purpose: "Grove 需要读取你主动选择的图片，作为这条来源的原始材料，再交给处理流程生成候选。",
    bullets: [
      "只读取你选中的图片",
      "不会遍历或上传相册里的其它内容",
      "图片只保存在你当前的 Workspace",
    ],
    icon: "images",
  },
};

export function PermissionNotice({
  kind,
  onOpenSettings,
  onClose,
}: {
  kind: PermissionKind | null;
  onOpenSettings: () => void;
  onClose: () => void;
}) {
  const content = kind ? CONTENT[kind] : null;
  return (
    <Sheet visible={kind !== null} title={content?.title ?? "权限"} onClose={onClose}>
      {content ? (
        <View>
          <View style={styles.head}>
            <View style={styles.mark}>
              <CaptureIcon name={content.icon} size={18} color={theme.risk} />
            </View>
            <Text style={styles.heading}>{content.heading}</Text>
          </View>
          <Text style={styles.purpose}>{content.purpose}</Text>
          {content.bullets.map((bullet) => (
            <Text key={bullet} style={styles.bullet}>
              · {bullet}
            </Text>
          ))}
          <Text style={styles.note}>
            系统不会再重复弹出授权提示。需要继续采集时，请到系统设置里为 Grove 打开{content.title}。
          </Text>
          <View style={styles.actions}>
            <AppButton label="去设置" variant="primary" block onPress={onOpenSettings} />
            <AppButton label="返回收集" variant="ghost" block onPress={onClose} />
          </View>
        </View>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  mark: {
    width: 30,
    height: 30,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.riskSoft,
  },
  heading: { flex: 1, fontSize: 14, fontWeight: "700", color: theme.ink },
  purpose: { fontSize: 12, lineHeight: 19, color: theme.ink },
  bullet: { marginTop: 4, fontSize: 12, lineHeight: 19, color: theme.muted },
  note: { marginTop: 12, fontSize: 11, lineHeight: 18, color: theme.muted },
  actions: { marginTop: 14, gap: 8 },
});
