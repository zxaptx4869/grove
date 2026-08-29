import Svg, { Circle, Path } from "react-native-svg";

export type AgentIconName =
  | "history"
  | "down"
  | "send"
  | "plus"
  | "close"
  | "check"
  | "alert"
  | "search"
  | "quote"
  | "folder"
  | "book"
  | "retry"
  | "chevron"
  | "circleCheck"
  | "message"
  | "file"
  | "more";

const PATHS: Record<AgentIconName, string[]> = {
  history: [
    "M4.5 7.5h10a3 3 0 0 1 3 3V13a3 3 0 0 1-3 3H9l-4 2.8v-3.7a3 3 0 0 1-.5-1.6z",
    "M7.5 4.5h9a3 3 0 0 1 3 3V12",
  ],
  down: ["m6 9 6 6 6-6"],
  send: ["m22 2-7 20-4-9-9-4z", "M22 2 11 13"],
  plus: ["M12 5v14M5 12h14"],
  close: ["M18 6 6 18M6 6l12 12"],
  check: ["m5 12 4 4L19 6"],
  alert: [
    "M10.3 3.2 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.2a2 2 0 0 0-3.4 0z",
    "M12 9v4M12 17h.01",
  ],
  search: ["M11 11m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0", "m21 21-4.3-4.3"],
  quote: [
    "M3 21c3 0 7-1 7-8V5H4v8h3c0 4-2 5-4 5zM14 21c3 0 7-1 7-8V5h-6v8h3c0 4-2 5-4 5z",
  ],
  folder: ["M3 5h6l2 2h10v12H3z"],
  book: [
    "M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5z",
    "M4 6.5v13A2.5 2.5 0 0 0 6.5 22H20",
  ],
  retry: ["M21 12a9 9 0 1 1-2.6-6.4L21 8", "M21 3v5h-5"],
  chevron: ["m9 18 6-6-6-6"],
  circleCheck: ["M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0", "m8 12 3 3 5-6"],
  message: ["M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"],
  file: ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6"],
  more: [],
};

export function AgentIcon({
  name,
  size = 20,
  color,
  strokeWidth = 1.9,
}: {
  name: AgentIconName;
  size?: number;
  color: string;
  strokeWidth?: number;
}) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {name === "search" && (
        <Circle cx={11} cy={11} r={8} fill="none" stroke={color} strokeWidth={strokeWidth} />
      )}
      {name === "circleCheck" && (
        <Circle cx={12} cy={12} r={9} fill="none" stroke={color} strokeWidth={strokeWidth} />
      )}
      {name === "more" &&
        [5, 12, 19].map((cx) => (
          <Circle key={cx} cx={cx} cy={12} r={1} fill={color} stroke="none" />
        ))}
      {PATHS[name].map((d) => (
        <Path
          key={d}
          d={d}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </Svg>
  );
}
