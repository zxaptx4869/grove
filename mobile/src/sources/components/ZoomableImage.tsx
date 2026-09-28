/**
 * 可缩放图片视口：双指捏合缩放、拖动平移，双击在 1x / 2.5x 之间切换。
 *
 * 用 View 的原生触摸事件 + Animated 实现，不额外引入手势库。内容按视口宽度铺满
 * （长截图即「按宽度适配」），所以放大后仍然是接近原图的分辨率；起始位置对齐顶部，
 * 长截图不会一上来就停在中间。几何计算抽成纯函数便于单测。
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Animated,
  StyleSheet,
  View,
  type GestureResponderEvent,
  type LayoutChangeEvent,
  type StyleProp,
  type ViewStyle,
} from "react-native";

export const ZOOM_MIN_SCALE = 1;
export const ZOOM_MAX_SCALE = 4;
export const ZOOM_DOUBLE_TAP_SCALE = 2.5;

const TAP_MAX_DURATION_MS = 250;
const TAP_MAX_MOVE_PX = 8;
const DOUBLE_TAP_INTERVAL_MS = 300;

export type Size = { width: number; height: number };

export function clamp(value: number, min: number, max: number) {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}

export function clampScale(value: number) {
  return clamp(value, ZOOM_MIN_SCALE, ZOOM_MAX_SCALE);
}

export function pinchDistance(touches: readonly { pageX: number; pageY: number }[]) {
  if (touches.length < 2) return 0;
  const [a, b] = touches;
  return Math.hypot(a.pageX - b.pageX, a.pageY - b.pageY);
}

/** 图片在视口里按宽度铺满后的尺寸；拿不到原图尺寸时返回 null，由调用方回退。 */
export function fittedSize(content: Size | null | undefined, viewport: Size): Size | null {
  if (!content || content.width <= 0 || content.height <= 0) return null;
  if (viewport.width <= 0) return null;
  return { width: viewport.width, height: (viewport.width * content.height) / content.width };
}

/** 某个缩放下允许的单侧最大位移：内容比视口大出来的那一半。 */
export function maxOffset(scale: number, contentSize: number, viewportSize: number) {
  return Math.max(0, (contentSize * scale - viewportSize) / 2);
}

export function clampOffset(offset: number, scale: number, contentSize: number, viewportSize: number) {
  const limit = maxOffset(scale, contentSize, viewportSize);
  return clamp(offset, -limit, limit);
}

type GestureState = {
  scale: number;
  x: number;
  y: number;
  startScale: number;
  startX: number;
  startY: number;
  startDistance: number;
  startTouchX: number;
  startTouchY: number;
  startAt: number;
  moved: boolean;
  lastTapAt: number;
  viewportW: number;
  viewportH: number;
  contentW: number;
  contentH: number;
};

export function ZoomableImage({
  children,
  style,
  resetKey,
  contentSize,
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  /** 变化时复位缩放：切换图片不该把上一张的放大状态带过来。 */
  resetKey?: string | number;
  /** 原图尺寸（像素）；给到后内容按视口宽度铺满，放大时更清晰。 */
  contentSize?: Size | null;
}) {
  const [scale] = useState(() => new Animated.Value(ZOOM_MIN_SCALE));
  const [translateX] = useState(() => new Animated.Value(0));
  const [translateY] = useState(() => new Animated.Value(0));
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 });
  const gestureRef = useRef<GestureState>({
    scale: ZOOM_MIN_SCALE,
    x: 0,
    y: 0,
    startScale: ZOOM_MIN_SCALE,
    startX: 0,
    startY: 0,
    startDistance: 0,
    startTouchX: 0,
    startTouchY: 0,
    startAt: 0,
    moved: false,
    lastTapAt: 0,
    viewportW: 0,
    viewportH: 0,
    contentW: 0,
    contentH: 0,
  });

  const box = useMemo(() => fittedSize(contentSize, viewport), [contentSize, viewport]);

  useEffect(() => {
    const state = gestureRef.current;
    state.contentW = box?.width ?? viewport.width;
    state.contentH = box?.height ?? viewport.height;
    state.scale = ZOOM_MIN_SCALE;
    state.x = 0;
    // 起始对齐顶部：长截图从中间开始看没有意义
    state.y = maxOffset(ZOOM_MIN_SCALE, state.contentH, state.viewportH);
    state.lastTapAt = 0;
    scale.setValue(ZOOM_MIN_SCALE);
    translateX.setValue(0);
    translateY.setValue(state.y);
  }, [box, resetKey, scale, translateX, translateY, viewport]);

  /** 把当前缩放与位移吸附到合法范围；回到 1x 时连位移一起回位。 */
  const settle = useCallback(() => {
    const state = gestureRef.current;
    if (state.scale <= ZOOM_MIN_SCALE + 0.01) {
      state.scale = ZOOM_MIN_SCALE;
      state.x = 0;
      state.y = maxOffset(ZOOM_MIN_SCALE, state.contentH, state.viewportH);
      Animated.parallel([
        Animated.spring(scale, { toValue: ZOOM_MIN_SCALE, useNativeDriver: true }),
        Animated.spring(translateX, { toValue: 0, useNativeDriver: true }),
        Animated.spring(translateY, { toValue: state.y, useNativeDriver: true }),
      ]).start();
      return;
    }
    state.x = clampOffset(state.x, state.scale, state.contentW, state.viewportW);
    state.y = clampOffset(state.y, state.scale, state.contentH, state.viewportH);
    Animated.parallel([
      Animated.spring(translateX, { toValue: state.x, useNativeDriver: true }),
      Animated.spring(translateY, { toValue: state.y, useNativeDriver: true }),
    ]).start();
  }, [scale, translateX, translateY]);

  const zoomTo = useCallback(
    (next: number) => {
      const state = gestureRef.current;
      state.scale = clampScale(next);
      state.x = 0;
      state.y = maxOffset(state.scale, state.contentH, state.viewportH);
      Animated.parallel([
        Animated.spring(scale, { toValue: state.scale, useNativeDriver: true }),
        Animated.spring(translateX, { toValue: 0, useNativeDriver: true }),
        Animated.spring(translateY, { toValue: state.y, useNativeDriver: true }),
      ]).start();
    },
    [scale, translateX, translateY],
  );

  const handleTouchStart = useCallback((event: GestureResponderEvent) => {
    const state = gestureRef.current;
    const touches = event.nativeEvent.touches;
    state.startScale = state.scale;
    state.startX = state.x;
    state.startY = state.y;
    state.startDistance = touches.length >= 2 ? pinchDistance(touches) : 0;
    state.startTouchX = touches[0]?.pageX ?? 0;
    state.startTouchY = touches[0]?.pageY ?? 0;
    state.startAt = Date.now();
    state.moved = false;
  }, []);

  const handleTouchMove = useCallback(
    (event: GestureResponderEvent) => {
      const state = gestureRef.current;
      const touches = event.nativeEvent.touches;
      if (touches.length >= 2) {
        // 单指拖到一半再补第二根手指时，以当前距离为缩放起点
        if (state.startDistance <= 0) {
          state.startDistance = pinchDistance(touches);
          state.startScale = state.scale;
        }
        state.moved = true;
        const next = clampScale(state.startScale * (pinchDistance(touches) / state.startDistance));
        state.scale = next;
        scale.setValue(next);
        // 缩放会让已有位移超出新边界，实时收紧避免内容被拖出视口
        state.x = clampOffset(state.x, next, state.contentW, state.viewportW);
        state.y = clampOffset(state.y, next, state.contentH, state.viewportH);
        translateX.setValue(state.x);
        translateY.setValue(state.y);
        return;
      }
      const touch = touches[0];
      if (!touch) return;
      // 从双指回到单指：重新锚定，避免位移跳变
      if (state.startDistance > 0) {
        state.startDistance = 0;
        state.startX = state.x;
        state.startY = state.y;
        state.startTouchX = touch.pageX;
        state.startTouchY = touch.pageY;
        state.moved = true;
        return;
      }
      const dx = touch.pageX - state.startTouchX;
      const dy = touch.pageY - state.startTouchY;
      if (Math.abs(dx) > TAP_MAX_MOVE_PX || Math.abs(dy) > TAP_MAX_MOVE_PX) {
        state.moved = true;
      }
      state.x = clampOffset(state.startX + dx, state.scale, state.contentW, state.viewportW);
      state.y = clampOffset(state.startY + dy, state.scale, state.contentH, state.viewportH);
      translateX.setValue(state.x);
      translateY.setValue(state.y);
    },
    [scale, translateX, translateY],
  );

  const handleTouchEnd = useCallback(
    (event: GestureResponderEvent) => {
      // 还有手指留在屏幕上就不结算，等最后一根抬起
      if (event.nativeEvent.touches.length > 0) return;
      const state = gestureRef.current;
      const isTap = !state.moved && Date.now() - state.startAt < TAP_MAX_DURATION_MS;
      if (isTap) {
        const now = Date.now();
        if (now - state.lastTapAt < DOUBLE_TAP_INTERVAL_MS) {
          state.lastTapAt = 0;
          zoomTo(state.scale > ZOOM_MIN_SCALE + 0.01 ? ZOOM_MIN_SCALE : ZOOM_DOUBLE_TAP_SCALE);
          return;
        }
        state.lastTapAt = now;
      }
      settle();
    },
    [settle, zoomTo],
  );

  const handleLayout = useCallback((event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    const state = gestureRef.current;
    state.viewportW = width;
    state.viewportH = height;
    setViewport((current) =>
      current.width === width && current.height === height ? current : { width, height },
    );
  }, []);

  return (
    <View
      style={[styles.viewport, style]}
      onLayout={handleLayout}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={handleTouchEnd}
      testID="zoomable-image-viewport"
    >
      <Animated.View
        style={[box ?? styles.content, { transform: [{ translateX }, { translateY }, { scale }] }]}
        testID="zoomable-image-content"
      >
        {children}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  viewport: { flex: 1, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  // 拿不到原图尺寸时的回退：内容撑满视口，内部图片再用百分比宽度解析
  content: { width: "100%", height: "100%" },
});
