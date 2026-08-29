export const theme = {
  bg: "#F7F8F7", surface: "#FFFFFF", soft: "#F1F4F2", border: "#DDE3DF",
  ink: "#17201C", muted: "#66716B", green: "#236748", greenSoft: "#E8F3ED",
  ai: "#7251A5", aiSoft: "#F2EDF8", confirmed: "#187C72",
  confirmedSoft: "#E7F5F2", risk: "#9A6419", riskSoft: "#FFF5DF",
  error: "#B43C3C", errorSoft: "#FCEDED", ring: "#7251A5",
  faint: "#B9C3BE", navInactive: "#748078", scrim: "rgba(15,24,19,.36)",
} as const;

export const cardShadow = {
  shadowColor: "#14281E",
  shadowOpacity: 0.05,
  shadowRadius: 8,
  shadowOffset: { width: 0, height: 2 },
  elevation: 2,
} as const;

export const popShadow = {
  shadowColor: "#101C16",
  shadowOpacity: 0.18,
  shadowRadius: 50,
  shadowOffset: { width: 0, height: 18 },
  elevation: 12,
} as const;
