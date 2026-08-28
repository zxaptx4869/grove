import { Redirect } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
export default function Index() { const { token, loading } = useAuth(); if (loading) return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.bg }}><ActivityIndicator color={theme.green} /></View>; return <Redirect href={token ? "/(tabs)" : "/login"} />; }
