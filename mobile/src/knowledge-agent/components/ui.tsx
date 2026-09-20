import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import {
  Animated,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
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

const DEBUG_BOTTOM_SHEET =
  __DEV__ && process.env.EXPO_PUBLIC_GROVE_BOTTOM_SHEET_DEBUG === "1";

function traceBottomSheet(event: string, details: Record<string, number | boolean> = {}) {
  if (DEBUG_BOTTOM_SHEET) console.debug("[Grove BottomSheet]", event, details);
}

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
  animationType = "fade",
  scrollable = true,
  presentation = "fade",
  reduceMotion = false,
  onPresented,
}: {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  animationType?: "none" | "slide" | "fade";
  scrollable?: boolean;
  presentation?: "fade" | "bottom";
  reduceMotion?: boolean;
  onPresented?: () => void;
}) {
  const renderContent = (closeHandler: () => void) => (
    <View
      style={[styles.sheet, presentation === "bottom" && styles.bottomSheet]}
      accessibilityViewIsModal
    >
      <View style={styles.sheetHead}>
        <Text style={styles.sheetTitle}>{title}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="关闭"
          onPress={closeHandler}
          style={styles.sheetClose}
        >
          <AgentIcon name="close" size={20} color={theme.muted} />
        </Pressable>
      </View>
      <SafeAreaView edges={["bottom"]} style={styles.sheetSafeArea}>
        {scrollable ? (
          <ScrollView
            style={styles.sheetScroll}
            contentContainerStyle={styles.sheetBody}
            keyboardShouldPersistTaps="handled"
          >
            {children}
          </ScrollView>
        ) : (
          children
        )}
      </SafeAreaView>
    </View>
  );
  if (presentation === "bottom") {
    return (
      <BottomSheetMotion
        visible={visible}
        onClose={onClose}
        reduceMotion={reduceMotion}
        onPresented={onPresented}
      >
        {(requestClose) => renderContent(requestClose)}
      </BottomSheetMotion>
    );
  }
  return (
    <Modal visible={visible} transparent animationType={animationType} onRequestClose={onClose}>
      <View style={styles.modalRoot}>
        <Pressable
          accessibilityLabel="关闭弹层"
          style={styles.scrim}
          onPress={onClose}
        />
        {renderContent(onClose)}
      </View>
    </Modal>
  );
}

function BottomSheetMotion({
  visible,
  onClose,
  reduceMotion,
  onPresented,
  children,
}: {
  visible: boolean;
  onClose: () => void;
  reduceMotion: boolean;
  onPresented?: () => void;
  children: (requestClose: () => void) => ReactNode;
}) {
  const [scrimOpacity] = useState(() => new Animated.Value(0));
  const [panelOpacity] = useState(() => new Animated.Value(0));
  const [translateY] = useState(() => new Animated.Value(0));
  const cycleRef = useRef(0);
  const modalShownRef = useRef(false);
  const panelHeightRef = useRef(0);
  const openingStartedRef = useRef(false);
  const presentedRef = useRef(false);
  const closingRef = useRef(false);
  const openingAnimationRef = useRef<Animated.CompositeAnimation | null>(null);
  const closingAnimationRef = useRef<Animated.CompositeAnimation | null>(null);
  const finishPresentation = useCallback(
    (cycle: number) => {
      if (
        cycle !== cycleRef.current ||
        !visible ||
        closingRef.current ||
        presentedRef.current
      ) {
        return;
      }
      presentedRef.current = true;
      scrimOpacity.setValue(1);
      translateY.setValue(0);
      panelOpacity.setValue(1);
      onPresented?.();
    },
    [onPresented, panelOpacity, scrimOpacity, translateY, visible],
  );

  const startPresentationIfReady = useCallback(() => {
    if (
      !visible ||
      closingRef.current ||
      openingStartedRef.current ||
      !modalShownRef.current ||
      panelHeightRef.current <= 0
    ) {
      return;
    }
    const cycle = cycleRef.current;
    openingStartedRef.current = true;
    openingAnimationRef.current?.stop();
    closingAnimationRef.current?.stop();
    scrimOpacity.setValue(0);
    translateY.setValue(panelHeightRef.current + 24);
    panelOpacity.setValue(1);
    traceBottomSheet("open_start", {
      cycle,
      panelHeight: panelHeightRef.current,
      reduceMotion,
    });
    if (reduceMotion) {
      finishPresentation(cycle);
      return;
    }
    const opening = Animated.parallel([
      Animated.timing(scrimOpacity, {
        toValue: 1,
        duration: 160,
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        toValue: 0,
        duration: 220,
        useNativeDriver: true,
      }),
    ]);
    openingAnimationRef.current = opening;
    opening.start(({ finished }) => {
      if (cycle !== cycleRef.current || openingAnimationRef.current !== opening) return;
      openingAnimationRef.current = null;
      traceBottomSheet(finished ? "open_complete" : "open_cancel", { cycle });
      if (finished) finishPresentation(cycle);
    });
  }, [finishPresentation, panelOpacity, reduceMotion, scrimOpacity, translateY, visible]);

  useLayoutEffect(() => {
    cycleRef.current += 1;
    traceBottomSheet("cycle_reset", { cycle: cycleRef.current, visible });
    modalShownRef.current = false;
    panelHeightRef.current = 0;
    openingStartedRef.current = false;
    presentedRef.current = false;
    closingRef.current = false;
    openingAnimationRef.current?.stop();
    openingAnimationRef.current = null;
    closingAnimationRef.current?.stop();
    closingAnimationRef.current = null;
    panelOpacity.stopAnimation();
    scrimOpacity.setValue(0);
    translateY.setValue(0);
    panelOpacity.setValue(0);
    return () => {
      cycleRef.current += 1;
      openingAnimationRef.current?.stop();
      closingAnimationRef.current?.stop();
      openingAnimationRef.current = null;
      closingAnimationRef.current = null;
    };
  }, [panelOpacity, scrimOpacity, translateY, visible]);

  useLayoutEffect(() => {
    if (!visible || !reduceMotion || presentedRef.current || closingRef.current) return;
    if (openingStartedRef.current) {
      const cycle = cycleRef.current;
      openingAnimationRef.current?.stop();
      openingAnimationRef.current = null;
      finishPresentation(cycle);
      return;
    }
    startPresentationIfReady();
  }, [finishPresentation, reduceMotion, startPresentationIfReady, visible]);

  const handleModalShow = useCallback(() => {
    modalShownRef.current = true;
    traceBottomSheet("modal_show", { cycle: cycleRef.current });
    startPresentationIfReady();
  }, [startPresentationIfReady]);

  const handlePanelLayout = useCallback(
    (event: LayoutChangeEvent) => {
      const measuredHeight = event.nativeEvent.layout.height;
      if (measuredHeight <= 0 || !visible || closingRef.current) return;
      panelHeightRef.current = measuredHeight;
      traceBottomSheet("panel_layout", {
        cycle: cycleRef.current,
        panelHeight: measuredHeight,
      });
      startPresentationIfReady();
    },
    [startPresentationIfReady, visible],
  );

  const requestClose = useCallback(() => {
    if (closingRef.current || !visible) return;
    closingRef.current = true;
    const cycle = cycleRef.current;
    traceBottomSheet("close_start", { cycle, openingStarted: openingStartedRef.current });
    openingAnimationRef.current?.stop();
    openingAnimationRef.current = null;
    if (reduceMotion || !openingStartedRef.current) {
      onClose();
      return;
    }
    const closing = Animated.parallel([
      Animated.timing(scrimOpacity, {
        toValue: 0,
        duration: 150,
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        toValue: panelHeightRef.current + 24,
        duration: 190,
        useNativeDriver: true,
      }),
    ]);
    closingAnimationRef.current = closing;
    closing.start(({ finished }) => {
      if (cycle !== cycleRef.current || closingAnimationRef.current !== closing) return;
      closingAnimationRef.current = null;
      traceBottomSheet(finished ? "close_complete" : "close_cancel", { cycle });
      if (finished) onClose();
      else closingRef.current = false;
    });
  }, [onClose, reduceMotion, scrimOpacity, translateY, visible]);

  return (
    <Modal
      testID="bottom-sheet-modal"
      visible={visible}
      transparent
      animationType="none"
      hardwareAccelerated
      onRequestClose={requestClose}
      onShow={handleModalShow}
    >
      <View style={styles.modalRoot}>
        <Animated.View style={[styles.animatedScrim, { opacity: scrimOpacity }]}>
          <Pressable
            accessibilityLabel="关闭弹层"
            style={styles.scrim}
            onPress={requestClose}
          />
        </Animated.View>
        <Animated.View
          testID="bottom-sheet-panel"
          collapsable={false}
          onLayout={handlePanelLayout}
          style={[
            styles.bottomPanel,
            { opacity: panelOpacity, transform: [{ translateY }] },
          ]}
        >
          <BottomSheetContent render={children} onClose={requestClose} />
        </Animated.View>
      </View>
    </Modal>
  );
}

function BottomSheetContent({
  render,
  onClose,
}: {
  render: (requestClose: () => void) => ReactNode;
  onClose: () => void;
}) {
  return <>{render(onClose)}</>;
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
  animatedScrim: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
  },
  bottomPanel: { maxHeight: "84%" },
  sheet: {
    maxHeight: "84%",
    overflow: "hidden",
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    backgroundColor: theme.surface,
    ...popShadow,
  },
  bottomSheet: { maxHeight: "100%" },
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
