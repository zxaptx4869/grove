import * as SecureStore from "expo-secure-store";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Platform } from "react-native";
import { getMe, mobileLogin, mobileLogout, type Me } from "@/src/api";
import { clearDialogueIdentityStorage } from "@/src/knowledge-agent/session/workStorage";

const key = "grove_mobile_session";
type Auth = {
  token: string | null;
  me: Me | null;
  loading: boolean;
  signIn: (username: string, password: string, register: boolean) => Promise<void>;
  signOut: () => Promise<void>;
};
const Context = createContext<Auth | null>(null);

const sessionStorage = {
  get: async () =>
    Platform.OS === "web" ? globalThis.localStorage.getItem(key) : SecureStore.getItemAsync(key),
  set: async (token: string) =>
    Platform.OS === "web"
      ? globalThis.localStorage.setItem(key, token)
      : SecureStore.setItemAsync(key, token),
  clear: async () =>
    Platform.OS === "web"
      ? globalThis.localStorage.removeItem(key)
      : SecureStore.deleteItemAsync(key),
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const clear = useCallback(async () => {
    if (me) {
      await clearDialogueIdentityStorage({
        userId: me.user.id,
        workspaceId: me.workspace.id,
      });
    }
    await sessionStorage.clear();
    setToken(null);
    setMe(null);
  }, [me]);
  useEffect(() => {
    void (async () => {
      const saved = await sessionStorage.get();
      if (saved) {
        try {
          setMe(await getMe(saved));
          setToken(saved);
        } catch (error) {
          if ((error as { status?: number }).status === 401) {
            await sessionStorage.clear();
            setToken(null);
            setMe(null);
          }
        }
      }
      setLoading(false);
    })();
  }, []);
  const value = useMemo<Auth>(
    () => ({
      token,
      me,
      loading,
      signIn: async (username, password, register) => {
        const result = await mobileLogin(username, password, register);
        await sessionStorage.set(result.token);
        setToken(result.token);
        setMe(await getMe(result.token));
      },
      signOut: async () => {
        if (!token) return;
        try {
          await mobileLogout(token);
        } finally {
          await clear();
        }
      },
    }),
    [clear, loading, me, token],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export const useAuth = () => {
  const value = useContext(Context);
  if (!value) throw new Error("认证上下文不可用");
  return value;
};
