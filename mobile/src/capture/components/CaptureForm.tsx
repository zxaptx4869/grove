/** 采集表单：原始材料预览 + 补充说明 + 所属项目，图片不提供正文输入。 */

import { Image, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import type { CaptureKind } from "@/src/capture/batch";
import { CaptureIcon } from "@/src/capture/components/CaptureIcon";
import type { PickedImage } from "@/src/capture/image";
import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { theme } from "@/src/theme";

export type CaptureDraft = {
  kind: CaptureKind;
  images: PickedImage[];
  text: string;
  note: string;
  projectId: number | null;
  fromCamera: boolean;
};

export function CaptureForm({
  draft,
  projectName,
  error,
  onChangeText,
  onChangeNote,
  onRemoveImage,
  onRetake,
  onOpenProject,
  onFillFromClipboard,
}: {
  draft: CaptureDraft;
  projectName: string;
  error: string;
  onChangeText: (value: string) => void;
  onChangeNote: (value: string) => void;
  onRemoveImage: (index: number) => void;
  onRetake: () => void;
  onOpenProject: () => void;
  onFillFromClipboard: () => void;
}) {
  const isText = draft.kind === "text";
  return (
    <View style={styles.form}>
      {isText ? (
        <View style={styles.section}>
          <View style={styles.labelRow}>
            <Text style={styles.label}>要收集的文字</Text>
            <Text style={styles.optional}>{draft.text.length} 字</Text>
          </View>
          <TextInput
            accessibilityLabel="要收集的文字"
            multiline
            value={draft.text}
            onChangeText={onChangeText}
            placeholder="粘贴或输入要收集的文字"
            placeholderTextColor={theme.muted}
            style={[styles.field, styles.textArea]}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="从剪贴板填入"
            onPress={onFillFromClipboard}
            style={({ pressed }) => [styles.miniButton, pressed && styles.pressed]}
          >
            <CaptureIcon name="clipboard" size={15} color={theme.ink} />
            <Text style={styles.miniButtonText}>从剪贴板填入</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.section}>
          <View style={styles.labelRow}>
            <Text style={styles.label}>原始材料</Text>
            <Text style={styles.optional}>共 {draft.images.length} 张</Text>
          </View>
          <View style={styles.strip}>
            {draft.images.map((image, index) => (
              <View key={`${image.uri}-${index}`} style={styles.thumb}>
                <Image source={{ uri: image.uri }} style={styles.thumbImage} />
                {draft.fromCamera ? null : (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`移除第 ${index + 1} 张图片`}
                    onPress={() => onRemoveImage(index)}
                    style={styles.thumbAction}
                  >
                    <CaptureIcon name="trash" size={15} color={theme.error} />
                  </Pressable>
                )}
              </View>
            ))}
          </View>
          {draft.fromCamera ? (
            <View style={styles.inlineActions}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="重拍"
                onPress={onRetake}
                style={({ pressed }) => [styles.miniButton, pressed && styles.pressed]}
              >
                <CaptureIcon name="refresh" size={15} color={theme.ink} />
                <Text style={styles.miniButtonText}>重拍</Text>
              </Pressable>
              <Text style={styles.caption}>来自系统相机，一次拍摄一张</Text>
            </View>
          ) : null}
          <View style={[styles.banner, draft.kind === "album-merged" && styles.bannerMerged]}>
            <CaptureIcon
              name="info"
              size={15}
              color={draft.kind === "album-merged" ? theme.green : theme.muted}
            />
            <View style={styles.bannerMain}>
              <Text style={styles.bannerTitle}>
                {draft.kind === "album-merged"
                  ? `这 ${draft.images.length} 张将作为一条材料一起整理`
                  : `这 ${draft.images.length} 张将分别作为 ${draft.images.length} 条材料提交`}
              </Text>
              <Text style={styles.bannerBody}>
                {draft.kind === "album-merged"
                  ? "这一批会一起整理成知识，不用逐张处理。"
                  : "每张单独成为一条采集，之后可以分别处理。"}
              </Text>
            </View>
          </View>
        </View>
      )}

      <View style={styles.section}>
        <View style={styles.labelRow}>
          <Text style={styles.label}>补充说明</Text>
          <Text style={styles.optional}>可选</Text>
        </View>
        <TextInput
          accessibilityLabel="补充说明"
          multiline
          value={draft.note}
          onChangeText={onChangeNote}
          placeholder="给这批材料留一句说明"
          placeholderTextColor={theme.muted}
          style={[styles.field, styles.noteArea]}
        />
      </View>

      <View style={styles.section}>
        <Text style={styles.label}>所属项目</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`所属项目：${projectName}`}
          onPress={onOpenProject}
          style={({ pressed }) => [styles.projectRow, pressed && styles.pressed]}
        >
          <View style={styles.projectValue}>
            <AgentIcon name="folder" size={16} color={theme.muted} />
            <Text style={styles.projectText} numberOfLines={1}>
              {projectName}
            </Text>
          </View>
          <AgentIcon name="chevron" size={16} color={theme.muted} />
        </Pressable>
      </View>

      {error ? (
        <View style={styles.errorCard} accessibilityRole="alert">
          <Text style={styles.errorTitle}>提交未成功</Text>
          <Text style={styles.errorBody}>{error}</Text>
          <Text style={styles.errorSource}>材料没有保存到 Grove，已填写的内容仍在表单里。</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  form: { gap: 16 },
  section: { gap: 7 },
  labelRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  label: { fontSize: 12.5, fontWeight: "700", color: theme.ink },
  optional: { fontSize: 10, color: theme.muted },
  field: {
    paddingVertical: 10,
    paddingHorizontal: 11,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.surface,
    fontSize: 13,
    lineHeight: 20,
    color: theme.ink,
  },
  textArea: { minHeight: 132, textAlignVertical: "top" },
  noteArea: { minHeight: 76, textAlignVertical: "top" },
  strip: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  thumb: { width: 98, height: 98, borderRadius: 9, overflow: "hidden" },
  thumbImage: { width: "100%", height: "100%", backgroundColor: theme.soft },
  thumbAction: {
    position: "absolute",
    top: 4,
    right: 4,
    width: 28,
    height: 28,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 7,
    backgroundColor: "rgba(255,255,255,.9)",
  },
  inlineActions: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 },
  miniButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    minHeight: 40,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  miniButtonText: { fontSize: 12, fontWeight: "600", color: theme.ink },
  caption: { fontSize: 11, color: theme.muted },
  banner: {
    flexDirection: "row",
    gap: 8,
    marginTop: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.surface,
  },
  bannerMerged: { borderColor: "#BAD5C5", backgroundColor: theme.greenSoft },
  bannerMain: { flex: 1, minWidth: 0 },
  bannerTitle: { fontSize: 12.5, lineHeight: 19, fontWeight: "600", color: theme.ink },
  bannerBody: { marginTop: 3, fontSize: 11, lineHeight: 17, color: theme.muted },
  projectRow: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 11,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.surface,
  },
  projectValue: { flex: 1, minWidth: 0, flexDirection: "row", alignItems: "center", gap: 7 },
  projectText: { fontSize: 13, fontWeight: "600", color: theme.ink },
  errorCard: {
    gap: 4,
    padding: 11,
    borderWidth: 1,
    borderColor: "#EFCACA",
    borderLeftWidth: 3,
    borderRadius: 9,
    backgroundColor: theme.errorSoft,
  },
  errorTitle: { fontSize: 12.5, fontWeight: "700", color: theme.error },
  errorBody: { fontSize: 12, lineHeight: 19, color: "#7D2C2C" },
  errorSource: { fontSize: 10.5, lineHeight: 16, color: "#8A4A4A" },
  pressed: { opacity: 0.85 },
});
