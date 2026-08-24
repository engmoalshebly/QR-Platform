import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, ViewStyle } from "react-native";

type Tone = "primary" | "secondary" | "danger" | "success";

export function AppButton({
  label,
  onPress,
  disabled,
  loading,
  tone = "primary",
  style,
  icon,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  loading?: boolean;
  tone?: Tone;
  style?: ViewStyle;
  icon?: ReactNode;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: Boolean(disabled || loading), busy: Boolean(loading) }}
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        styles.base,
        toneStyles[tone],
        (disabled || loading) && styles.disabled,
        pressed && !disabled && !loading && styles.pressed,
        style,
      ]}
    >
      {loading ? <ActivityIndicator color={tone === "secondary" ? "#E9EEF8" : "#101827"} /> : icon}
      <Text style={[styles.label, tone === "secondary" && styles.secondaryLabel]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 52,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 18,
    borderCurve: "continuous",
  },
  label: { color: "#101827", fontSize: 16, fontWeight: "800", textAlign: "center" },
  secondaryLabel: { color: "#E9EEF8" },
  pressed: { opacity: 0.82, transform: [{ scale: 0.985 }] },
  disabled: { opacity: 0.5 },
});

const toneStyles: Record<Tone, ViewStyle> = {
  primary: { backgroundColor: "#D7B46A" },
  secondary: { backgroundColor: "#1B2940", borderWidth: 1, borderColor: "#314563" },
  danger: { backgroundColor: "#F87171" },
  success: { backgroundColor: "#34D399" },
};
