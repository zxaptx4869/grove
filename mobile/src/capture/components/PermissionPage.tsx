/** 权限被拒页：讲清用途，提供「去设置」，不在客户端反复弹窗。 */

import { StyleSheet, Text, View } from "react-native";

import { CaptureIcon } from "@/src/capture/components/CaptureIcon";
import type { PermissionKind } from "@/src/capture/picker";
import { AppButton } from "@/src/knowledge-agent/components/ui";
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

/** 权限页标题：与原型 PERMISSIONS[kind].title 一致。 */
export function permissionTitle(kind: PermissionKind): string {
  return CONTENT[kind].title;
}

export function PermissionPage({
  kind,
  onOpenSettings,
  onBack,
}: {
  kind: PermissionKind;
  onOpenSettings: () => void;
  onBack: () => void;
}) {
  const content = CONTENT[kind];
  return (
    <View>
      <View style={styles.card}>
        <View style={styles.mark}>
          <CaptureIcon name={content.icon} size={18} color={theme.risk} />
        </View>
        <Text style={styles.heading}>{content.heading}</Text>
        <Text style={styles.purpose}>{content.purpose}</Text>
        <View style={styles.bullets}>
          {content.bullets.map((bullet) => (
            <Text key={bullet} style={styles.bullet}>
              · {bullet}
            </Text>
          ))}
        </View>
      </View>

      <View style={styles.notice}>
        <View style={styles.noticeHead}>
          <CaptureIcon name="lock" size={16} color={theme.risk} />
          <Text style={styles.noticeTitle}>需要你在系统设置里开启</Text>
        </View>
        <Text style={styles.noticeBody}>
          系统不会再重复弹出授权提示。需要继续采集时，请到系统设置里为 Grove 打开{content.title}。
        </Text>
      </View>

      <View style={styles.actions}>
        <AppButton label="去设置" variant="primary" block onPress={onOpenSettings} />
        <AppButton label="返回收集" variant="ghost" block onPress={onBack} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    gap: 8,
    padding: 16,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
  },
  mark: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: theme.riskSoft,
  },
  heading: { fontSize: 16, lineHeight: 23, fontWeight: "700", color: theme.ink },
  purpose: { fontSize: 12.5, lineHeight: 20, color: theme.muted },
  bullets: { gap: 6, marginTop: 2 },
  bullet: { fontSize: 12, lineHeight: 19, color: theme.muted },
  notice: {
    gap: 5,
    marginTop: 14,
    padding: 11,
    borderWidth: 1,
    borderLeftWidth: 3,
    borderColor: "#E8D5B0",
    borderLeftColor: theme.risk,
    borderRadius: 9,
    backgroundColor: theme.riskSoft,
  },
  noticeHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  noticeTitle: { fontSize: 12.5, fontWeight: "700", color: theme.risk },
  noticeBody: { fontSize: 11.5, lineHeight: 18, color: "#76501C" },
  actions: { gap: 8, marginTop: 14 },
});
