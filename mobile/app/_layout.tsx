import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { useState } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AuthProvider } from "@/src/auth";
import { DialogueSessionProvider } from "@/src/knowledge-agent/session/DialogueSessionProvider";

export default function Layout() {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 0, retry: 1 } } }),
  );
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={client}>
        <AuthProvider>
          <DialogueSessionProvider>
            <Stack screenOptions={{ headerShown: false }} />
          </DialogueSessionProvider>
        </AuthProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
