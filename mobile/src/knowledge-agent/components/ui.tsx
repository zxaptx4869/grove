import type { ReactNode } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { cardShadow, popShadow, theme } from "@/src/theme";

export type BadgeTone = "ai" | "confirmed" | "risk" | "error" | "neutral";

const BADGE_TONES: Record<BadgeTone, { color: string; background: string }> = {
  ai: { color: theme.ai, background: theme.aiSoft },
  confirmed: { color: theme.confirmed, background: theme.confirmedSoft },
  risk: { color: theme.risk, background: theme.riskSoft },
  error: { color: theme.error, background: theme.errorSoft },
  neutral: { color: theme.muted, background: theme.soft },
};

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: BadgeTone;
  children: ReactNode;
}) {
  const palette = BADGE_TONES[tone];
  return (
    <View style={[styles.badge, { backgroundColor: palette.background }]}>
      <Text style={[styles.badgeText, { color: palette.color }]}>{children}</Text>
    </View>
  );
}

export function Card({
  children,
  style,
  accent,
  background,
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  accent?: "risk" | "ai";
  background?: string;
}) {
  return (
    <View
      style={[
        styles.card,
        accent === "risk" && styles.cardRiskAccent,
        accent === "ai" && styles.cardAiAccent,
        background !== undefined && { backgroundColor: background },
        style,
      ]}
    >
      {children}
    </View>
  );
}

export function CardBody({ children }: { children: ReactNode }) {
  return <View style={styles.cardBody}>{children}</View>;
}

export function Eyebrow({
  icon,
  children,
}: {
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <View style={styles.eyebrow}>
      {icon}
      <Text style={styles.eyebrowText}>{children}</Text>
    </View>
  );
}

export function AppButton({
  label,
  onPress,
  variant = "default",
  block = false,
  disabled = false,
  icon,
  accessibilityLabel,
}: {
  label: string;
  onPress: () => void;
  variant?: "default" | "primary" | "danger" | "ghost" | "ai";
  block?: boolean;
  disabled?: boolean;
  icon?: ReactNode;
  accessibilityLabel?: string;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        variant === "primary" && styles.buttonPrimary,
        variant === "danger" && styles.buttonDanger,
        variant === "ghost" && styles.buttonGhost,
        variant === "ai" && styles.buttonAi,
        block && styles.buttonBlock,
        disabled && styles.buttonDisabled,
        pressed && !disabled && styles.buttonPressed,
      ]}
    >
      {icon}
      <Text
        style={[
          styles.buttonText,
          variant === "primary" && styles.buttonTextPrimary,
          variant === "danger" && styles.buttonTextDanger,
          variant === "ai" && styles.buttonTextAi,
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

export function Sheet({
  visible,
  title,
  onClose,
  children,
}: {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalRoot}>
        <Pressable
          accessibilityLabel="关闭弹层"
          style={styles.scrim}
          onPress={onClose}
        />
        <View style={styles.sheet} accessibilityViewIsModal>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle}>{title}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="关闭"
              onPress={onClose}
              style={styles.sheetClose}
            >
              <AgentIcon name="close" size={20} color={theme.muted} />
            </Pressable>
          </View>
          <SafeAreaView edges={["bottom"]} style={styles.sheetSafeArea}>
            <ScrollView
              style={styles.sheetScroll}
              contentContainerStyle={styles.sheetBody}
              keyboardShouldPersistTaps="handled"
            >
              {children}
            </ScrollView>
          </SafeAreaView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  badge: {
    minHeight: 21,
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    alignSelf: "flex-start",
  },
  badgeText: { fontSize: 10, lineHeight: 16, fontWeight: "600" },
  card: {
    marginBottom: 12,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
    ...cardShadow,
  },
  cardRiskAccent: { borderLeftWidth: 3, borderLeftColor: theme.risk },
  cardAiAccent: { borderLeftWidth: 3, borderLeftColor: theme.ai },
  cardBody: { padding: 13 },
  eyebrow: { flexDirection: "row", alignItems: "center", gap: 5 },
  eyebrowText: {
    color: theme.muted,
    fontSize: 11,
    lineHeight: 16,
  },
  button: {
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    paddingHorizontal: 13,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  buttonPrimary: { borderColor: theme.green, backgroundColor: theme.green },
  buttonDanger: {
    borderColor: "#EFCACA",
    backgroundColor: theme.errorSoft,
  },
  buttonGhost: { borderColor: "transparent", backgroundColor: "transparent" },
  buttonAi: { borderColor: "#DACCDE", backgroundColor: theme.aiSoft },
  buttonBlock: { width: "100%" },
  buttonDisabled: { opacity: 0.48 },
  buttonPressed: { opacity: 0.92 },
  buttonText: { fontSize: 13, fontWeight: "600", color: theme.ink },
  buttonTextPrimary: { color: "#FFFFFF" },
  buttonTextDanger: { color: theme.error },
  buttonTextAi: { color: theme.ai },
  modalRoot: { flex: 1, justifyContent: "flex-end" },
  scrim: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: theme.scrim,
  },
  sheet: {
    maxHeight: "84%",
    overflow: "hidden",
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    backgroundColor: theme.surface,
    ...popShadow,
  },
  sheetHandle: {
    width: 36,
    height: 4,
    marginTop: 8,
    marginBottom: 2,
    alignSelf: "center",
    borderRadius: 2,
    backgroundColor: "#CAD2CD",
  },
  sheetHead: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    paddingHorizontal: 14,
    paddingTop: 4,
  },
  sheetTitle: { fontSize: 17, fontWeight: "700", color: theme.ink },
  sheetClose: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.soft,
  },
  sheetSafeArea: { flexShrink: 1 },
  sheetScroll: { flexGrow: 0 },
  sheetBody: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 18 },
});
