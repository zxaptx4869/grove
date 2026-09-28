/**
 * 手势接线：1x 下左右滑动切换、纵向拖动与放大态不切换。触摸事件用 RNTL 直接派发。
 */

import React from "react";
import { Text } from "react-native";
import { act, render, type RenderResult } from "@testing-library/react-native";

import { ZoomableImage } from "@/src/sources/components/ZoomableImage";

async function setup(onSwipeLeft: () => void, onSwipeRight: () => void) {
  const screen = await render(
    <ZoomableImage onSwipeLeft={onSwipeLeft} onSwipeRight={onSwipeRight}>
      <Text>图片</Text>
    </ZoomableImage>,
  );
  return screen.getByTestId("zoomable-image-viewport");
}

type TouchEvent = { nativeEvent: { touches: { pageX: number; pageY: number }[] } };

/**
 * 直接调用组件的触摸回调：RNTL 的 fireEvent 派发触摸事件会让同文件后续用例无法渲染
 * （框架层缺陷），这里只关心手势口径本身，所以绕开事件派发。
 */
async function drag(
  viewport: { props: Record<string, unknown> },
  from: { x: number; y: number },
  to: { x: number; y: number },
) {
  const onTouchStart = viewport.props.onTouchStart as (event: TouchEvent) => void;
  const onTouchMove = viewport.props.onTouchMove as (event: TouchEvent) => void;
  const onTouchEnd = viewport.props.onTouchEnd as (event: TouchEvent) => void;
  await act(async () => {
    onTouchStart({ nativeEvent: { touches: [{ pageX: from.x, pageY: from.y }] } });
    onTouchMove({ nativeEvent: { touches: [{ pageX: to.x, pageY: to.y }] } });
    onTouchEnd({ nativeEvent: { touches: [] } });
  });
}

test("向左滑触发下一张，向右滑触发上一张", async () => {
  const onSwipeLeft = jest.fn();
  const onSwipeRight = jest.fn();
  const viewport = await setup(onSwipeLeft, onSwipeRight);

  await drag(viewport, { x: 300, y: 300 }, { x: 140, y: 310 });
  expect(onSwipeLeft).toHaveBeenCalledTimes(1);
  expect(onSwipeRight).not.toHaveBeenCalled();

  await drag(viewport, { x: 140, y: 300 }, { x: 300, y: 305 });
  expect(onSwipeRight).toHaveBeenCalledTimes(1);
  expect(onSwipeLeft).toHaveBeenCalledTimes(1);
});

test("连续两次同向滑动都会触发", async () => {
  const onSwipeLeft = jest.fn();
  const onSwipeRight = jest.fn();
  const viewport = await setup(onSwipeLeft, onSwipeRight);

  await drag(viewport, { x: 300, y: 300 }, { x: 140, y: 310 });
  await drag(viewport, { x: 300, y: 300 }, { x: 140, y: 310 });
  expect(onSwipeLeft).toHaveBeenCalledTimes(2);
});

test("纵向拖动与短距离滑动都不触发切换", async () => {
  const onSwipeLeft = jest.fn();
  const onSwipeRight = jest.fn();
  const viewport = await setup(onSwipeLeft, onSwipeRight);

  await drag(viewport, { x: 200, y: 500 }, { x: 205, y: 200 });
  await drag(viewport, { x: 200, y: 300 }, { x: 180, y: 305 });

  expect(onSwipeLeft).not.toHaveBeenCalled();
  expect(onSwipeRight).not.toHaveBeenCalled();
});

/** 读当前内容层的纵向位移（jest 下 Animated 渲染成普通数值）。 */
function translateYOf(screen: RenderResult) {
  const style = screen.getByTestId("zoomable-image-content").props.style as {
    transform: { translateY?: number }[];
  };
  return style.transform.find((item) => item.translateY !== undefined)?.translateY ?? 0;
}

test("长截图在 1x 下能上下拖动并停住，不会被弹回顶部", async () => {
  // 1200x2670 的长截图在 360x600 视口里：按宽度铺满后高 801，纵向可拖动的余量是 100.5
  const screen = await render(
    <ZoomableImage contentSize={{ width: 1200, height: 2670 }}>
      <Text>长截图</Text>
    </ZoomableImage>,
  );
  const viewport = screen.getByTestId("zoomable-image-viewport");
  await act(async () => {
    viewport.props.onLayout({ nativeEvent: { layout: { width: 360, height: 600 } } });
  });

  // 起始对齐顶部
  expect(translateYOf(screen)).toBeCloseTo(100.5, 5);

  // 手指上拖 200：内容向上走，停在可拖动范围内而不是弹回顶部
  await act(async () => {
    const event = (pageY: number) => ({ nativeEvent: { touches: [{ pageX: 180, pageY }] } });
    viewport.props.onTouchStart(event(500));
    viewport.props.onTouchMove(event(300));
    viewport.props.onTouchEnd({ nativeEvent: { touches: [] } });
  });
  expect(translateYOf(screen)).toBeCloseTo(-99.5, 5);

  // 继续上拖会停在边界上，不会无限拖出（拖动态用 setValue，直接读得到当前值）
  await act(async () => {
    const event = (pageY: number) => ({ nativeEvent: { touches: [{ pageX: 180, pageY }] } });
    viewport.props.onTouchStart(event(500));
    viewport.props.onTouchMove(event(100));
  });
  expect(translateYOf(screen)).toBeCloseTo(-100.5, 5);
  await act(async () => {
    viewport.props.onTouchEnd({ nativeEvent: { touches: [] } });
  });
});
