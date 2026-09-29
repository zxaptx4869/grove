/**
 * 图片附件：通过带认证的下载通道读取（见 useAttachmentImage），失败时给出可重试的提示。
 */

import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
  type ImageLoadEventData,
  type ImageStyle,
  type NativeSyntheticEvent,
  type StyleProp,
} from "react-native";

import { SourceIcon } from "@/src/sources/components/SourceIcon";
import { useAttachmentImage } from "@/src/sources/hooks/useAttachmentImage";
import { theme } from "@/src/theme";

export function SourceImage({
  sourceId,
  attachmentId,
  fileName,
  cacheVersion,
  style,
  resizeMode = "cover",
  accessibilityLabel,
  onLoadSize,
}: {
  sourceId: number;
  attachmentId: number;
  fileName?: string | null;
  /** 来源创建时间：本地缓存名带上它，库重置后同号附件不会复用上一代的图。 */
  cacheVersion?: string | null;
  style?: StyleProp<ImageStyle>;
  resizeMode?: "cover" | "contain";
  accessibilityLabel?: string;
  /** 原图尺寸回调：放大查看要按宽度铺满渲染，需要知道图片的长宽比。 */
  onLoadSize?: (size: { width: number; height: number }) => void;
}) {
  const { uri, loading, failed, retry } = useAttachmentImage(
    sourceId,
    attachmentId,
    fileName,
    cacheVersion,
  );
  const name = fileName?.trim() || `附件 ${attachmentId}`;

  if (failed) {
    return (
      <View style={[styles.fallback, style]} accessibilityLabel={`图片读取失败：${name}`}>
        <SourceIcon name="cloudOff" size={16} color={theme.muted} />
        <Text style={styles.fallbackText}>图片读取失败</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`重试读取图片：${name}`}
          onPress={retry}
          style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
        >
          <Text style={styles.retryText}>重试</Text>
        </Pressable>
      </View>
    );
  }

  if (!uri) {
    return (
      <View style={[styles.placeholder, style]}>
        {loading ? <ActivityIndicator size="small" color={theme.muted} /> : null}
      </View>
    );
  }

  return (
    <Image
      accessibilityLabel={accessibilityLabel}
      source={{ uri }}
      style={style}
      resizeMode={resizeMode}
      onLoad={
        onLoadSize
          ? (event: NativeSyntheticEvent<ImageLoadEventData>) => onLoadSize(event.nativeEvent.source)
          : undefined
      }
    />
  );
}

const styles = StyleSheet.create({
  placeholder: {
    backgroundColor: theme.soft,
    alignItems: "center",
    justifyContent: "center",
  },
  fallback: {
    backgroundColor: theme.soft,
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
  },
  fallbackText: { fontSize: 11.5, color: theme.muted },
  retry: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  retryText: { fontSize: 11.5, fontWeight: "600", color: theme.ink },
  pressed: { opacity: 0.75 },
});
