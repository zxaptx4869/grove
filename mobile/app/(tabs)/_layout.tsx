import { Tabs } from "expo-router";
import { NavIcon, type IconName } from "@/src/NavIcon";
import { theme } from "@/src/theme";
const tabs: { name: "index" | "collect" | "pending" | "knowledge"; label: string; icon: IconName }[] = [{name:"index",label:"对话",icon:"chat"},{name:"collect",label:"收集",icon:"collect"},{name:"pending",label:"待处理",icon:"pending"},{name:"knowledge",label:"知识",icon:"knowledge"}];
export default function TabLayout() { return <Tabs screenOptions={({ route }) => { const item = tabs.find((tab) => tab.name === route.name)!; return { headerShown:false, tabBarLabel:item.label, tabBarIcon:({ color }) => <NavIcon name={item.icon} color={String(color)} />, tabBarActiveTintColor:theme.green, tabBarInactiveTintColor:"#748078", tabBarStyle:{height:66,borderTopColor:theme.border,backgroundColor:theme.surface}, tabBarLabelStyle:{fontSize:11,fontWeight:"600"}, tabBarHideOnKeyboard:true }; }} />; }
