import { useEffect, useState } from "react";
import { Keyboard, Platform } from "react-native";

/** 真实键盘高度：不依赖 KeyboardAvoidingView/系统 resize，直接垫在输入区下方。
 *
 * Android 部分输入法（如讯飞小米版）上报的键盘高度常不含底部导航/手势条，
 * 因此对 Android 在事件高度上补底部 inset；iOS 事件高度已包含底部安全区。
 */
export function useKeyboardHeight(bottomInset: number): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const showEvent = Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow";
    const hideEvent = Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide";
    const showSubscription = Keyboard.addListener(showEvent, (event) => {
      setHeight(event.endCoordinates.height);
    });
    const hideSubscription = Keyboard.addListener(hideEvent, () => {
      setHeight(0);
    });
    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  if (height === 0) return 0;
  return Platform.OS === "android" ? height + bottomInset : height;
}
