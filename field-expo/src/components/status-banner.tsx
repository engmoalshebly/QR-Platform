import { StyleSheet, Text, View } from "react-native";

export function StatusBanner({ message, tone = "info" }: { message: string; tone?: "info" | "error" | "warning" | "success" }) {
  return (
    <View accessibilityRole="alert" style={[styles.base, toneStyles[tone]]}>
      <Text selectable style={[styles.icon, iconStyles[tone]]}>{tone === "error" ? "!" : tone === "warning" ? "!" : tone === "success" ? "✓" : "i"}</Text>
      <Text selectable style={styles.text}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  base: { borderRadius: 14, padding: 14, flexDirection: "row", alignItems: "flex-start", gap: 10, borderWidth: 1, borderCurve: "continuous" },
  text: { color: "#E9EEF8", fontSize: 14, lineHeight: 21, flex: 1, textAlign: "right" },
  icon: { width: 20, height: 20, borderRadius: 10, textAlign: "center", fontWeight: "900" },
});

const toneStyles = {
  info: { backgroundColor: "#172944", borderColor: "#2D5B91" },
  error: { backgroundColor: "#3A2029", borderColor: "#8A3849" },
  warning: { backgroundColor: "#3B311D", borderColor: "#8F7130" },
  success: { backgroundColor: "#16382F", borderColor: "#247453" },
};
const iconStyles = { info: { color: "#93C5FD" }, error: { color: "#FCA5A5" }, warning: { color: "#FCD34D" }, success: { color: "#6EE7B7" } };
