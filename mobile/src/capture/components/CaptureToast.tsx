/** 轻提示：底部深色提示条，约 2.4 秒自动消失，不阻塞操作（对齐原型 .toast）。 */

import { useEffect, useState } from "react";
import { Animated, StyleSheet, Text } from "react-native";

export const TOAST_DURATION_MS = 2400;

export function CaptureToast({
  message,
  bottom,
  onHide,
}: {
  message: string;
  /** 距栏目底部（底部导航之上）的距离 */
  bottom: number;
  onHide: () => void;
}) {
  // 用 state 持有动画值：render 期间读取 ref.current 会踩到 react-hooks/refs，与既有 Sheet 写法一致
  const [progress] = useState(() => new Animated.Value(0));

  useEffect(() => {
    Animated.timing(progress, { toValue: 1, duration: 180, useNativeDriver: true }).start();
    const timer = setTimeout(() => {
      Animated.timing(progress, { toValue: 0, duration: 180, useNativeDriver: true }).start(() =>
        onHide(),
      );
    }, TOAST_DURATION_MS);
    return () => clearTimeout(timer);
  }, [message, progress, onHide]);

  return (
    <Animated.View
      pointerEvents="none"
      accessibilityLiveRegion="polite"
      accessibilityLabel={message}
      style={[
        styles.toast,
        {
          bottom,
          opacity: progress,
          transform: [
            {
              translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [8, 0] }),
            },
          ],
        },
      ]}
    >
      <Text style={styles.text}>{message}</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  toast: {
    position: "absolute",
    right: 14,
    left: 14,
    zIndex: 50,
    paddingVertical: 11,
    paddingHorizontal: 12,
    borderRadius: 9,
    backgroundColor: "#26342D",
    shadowColor: "#000",
    shadowOpacity: 0.18,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 10 },
    elevation: 6,
  },
  text: { fontSize: 12, lineHeight: 18, textAlign: "center", color: "#FFFFFF" },
});
