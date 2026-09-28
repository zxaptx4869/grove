/**
 * 图片缩放视口：只测可独立验证的几何口径（按宽度铺满、位移边界、缩放范围）。
 * 手势与观感依赖真机触摸，走查清单里由用户手动验收。
 */

import {
  ZOOM_MAX_SCALE,
  ZOOM_MIN_SCALE,
  clampOffset,
  clampScale,
  fittedSize,
  maxOffset,
  pinchDistance,
} from "@/src/sources/components/ZoomableImage";

test("clampScale 限制在 1x 到 4x 之间", () => {
  expect(clampScale(0.2)).toBe(ZOOM_MIN_SCALE);
  expect(clampScale(1.8)).toBe(1.8);
  expect(clampScale(9)).toBe(ZOOM_MAX_SCALE);
  expect(clampScale(Number.NaN)).toBe(ZOOM_MIN_SCALE);
});

test("pinchDistance 返回两指间距离，单指或空手返回 0", () => {
  expect(pinchDistance([])).toBe(0);
  expect(pinchDistance([{ pageX: 5, pageY: 5 }])).toBe(0);
  expect(pinchDistance([{ pageX: 0, pageY: 0 }, { pageX: 3, pageY: 4 }])).toBe(5);
});

test("fittedSize 按视口宽度铺满并保持长宽比", () => {
  // 长截图 1200x2670 在 360 宽的视口里：宽度铺满，高度按比例变长（可上下拖动）
  expect(fittedSize({ width: 1200, height: 2670 }, { width: 360, height: 600 })).toEqual({
    width: 360,
    height: 801,
  });
  // 横图同样按宽度铺满
  expect(fittedSize({ width: 1000, height: 500 }, { width: 300, height: 400 })).toEqual({
    width: 300,
    height: 150,
  });
  // 缺原图尺寸或视口还没测量出来时返回 null，交给调用方回退
  expect(fittedSize(null, { width: 300, height: 400 })).toBeNull();
  expect(fittedSize({ width: 0, height: 0 }, { width: 300, height: 400 })).toBeNull();
  expect(fittedSize({ width: 1000, height: 500 }, { width: 0, height: 0 })).toBeNull();
});

test("maxOffset 只在内容超出视口时才允许平移", () => {
  // 内容与视口等大：不能拖
  expect(maxOffset(1, 400, 400)).toBe(0);
  // 长截图在 1x 下就能上下拖动，横向没有余量
  expect(maxOffset(1, 800, 600)).toBe(100);
  expect(maxOffset(1, 400, 600)).toBe(0);
  // 放大后两个方向都有余量
  expect(maxOffset(2, 400, 400)).toBe(200);
  // 缩到 1x 以下不会算出负数区间
  expect(maxOffset(0.5, 400, 400)).toBe(0);
});

test("clampOffset 把位移收在边界内", () => {
  expect(clampOffset(120, 2, 400, 400)).toBe(120);
  expect(clampOffset(500, 2, 400, 400)).toBe(200);
  expect(clampOffset(-500, 2, 400, 400)).toBe(-200);
  // 长截图纵向余量大于视口，回中不会把内容拖出边界
  expect(clampOffset(50, 1, 800, 600)).toBe(50);
  expect(clampOffset(999, 1, 800, 600)).toBe(100);
});
