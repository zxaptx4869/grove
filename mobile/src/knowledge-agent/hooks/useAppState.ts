import { useEffect, useState } from "react";
import { AppState } from "react-native";

/** App 前台状态：非 active 时停止 Run 轮询，服务端继续执行。 */
export function useAppStateActive(): boolean {
  const [active, setActive] = useState(AppState.currentState === "active");
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      setActive(state === "active");
    });
    return () => subscription?.remove();
  }, []);
  return active;
}
