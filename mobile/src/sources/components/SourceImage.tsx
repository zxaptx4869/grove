/** 图片附件：读取需要认证头，地址来自后端附件端点。 */

import { Image, StyleSheet, View, type ImageStyle, type StyleProp } from "react-native";

import { useAuth } from "@/src/auth";
import { sourceAttachmentUrl } from "@/src/sources/api";
import { theme } from "@/src/theme";

export function SourceImage({
  sourceId,
  attachmentId,
  style,
  resizeMode = "cover",
  accessibilityLabel,
}: {
  sourceId: number;
  attachmentId: number;
  style?: StyleProp<ImageStyle>;
  resizeMode?: "cover" | "contain";
  accessibilityLabel?: string;
}) {
  const { token } = useAuth();
  const uri = sourceAttachmentUrl(sourceId, attachmentId);
  if (!uri || !token) return <View style={[styles.placeholder, style]} />;
  return (
    <Image
      accessibilityLabel={accessibilityLabel}
      source={{ uri, headers: { Authorization: `Bearer ${token}` } }}
      style={style}
      resizeMode={resizeMode}
    />
  );
}

const styles = StyleSheet.create({
  placeholder: { backgroundColor: theme.soft },
});
