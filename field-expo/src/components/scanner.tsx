import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, Alert, StyleSheet, Text, View } from "react-native";

import { AppButton } from "./app-button";

export function Scanner({
  onScan,
}: {
  onScan: (rawCode: string, kind: "camera" | "code128") => Promise<void>;
}) {
  const [permission, requestPermission] = useCameraPermissions();
  const [locked, setLocked] = useState(false);
  const lastCodeRef = useRef<{ value: string; at: number } | null>(null);

  const handleScan = useCallback(
    async ({ data, type }: { data: string; type: string }) => {
      const value = data.trim();
      if (locked || !value) return;
      const now = Date.now();
      // Camera frameworks may emit the same QR for multiple frames.  Suppress
      // only that immediate duplicate; a different guest's code stays instant.
      if (
        lastCodeRef.current?.value === value &&
        now - lastCodeRef.current.at < 1400
      )
        return;
      setLocked(true);
      lastCodeRef.current = { value, at: now };
      await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(
        () => undefined,
      );
      try {
        await onScan(
          value,
          type.toLowerCase().includes("code128") ? "code128" : "camera",
        );
      } catch (error) {
        Alert.alert(
          "تعذر تنفيذ المسح",
          error instanceof Error ? error.message : "حاول مرة أخرى.",
        );
      } finally {
        setTimeout(() => setLocked(false), 350);
      }
    },
    [locked, onScan],
  );

  if (!permission) {
    return (
      <View style={styles.permission}>
        <ActivityIndicator color="#D4A32C" />
      </View>
    );
  }
  if (!permission.granted) {
    return (
      <View style={styles.permission}>
        <Text selectable style={styles.permissionTitle}>
          السماح بالكاميرا مطلوب
        </Text>
        <Text selectable style={styles.permissionText}>
          تُستخدم الكاميرا لمسح QR وCode128 عند البوابة فقط.
        </Text>
        <AppButton
          label="السماح بالكاميرا"
          onPress={() => void requestPermission()}
        />
      </View>
    );
  }
  return (
    <View style={styles.frame}>
      <CameraView
        style={StyleSheet.absoluteFill}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ["qr", "code128"] }}
        onBarcodeScanned={locked ? undefined : handleScan}
      />
      <View pointerEvents="none" style={styles.overlay}>
        <View style={styles.target} />
        <Text selectable style={styles.hint}>
          {locked ? "جارٍ التحقق من الرمز…" : "ضع رمز الدعوة داخل الإطار"}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    height: 360,
    overflow: "hidden",
    borderRadius: 24,
    backgroundColor: "#08111F",
    borderWidth: 1,
    borderColor: "#465A79",
    borderCurve: "continuous",
  },
  overlay: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(3, 9, 20, 0.18)",
  },
  target: {
    height: 208,
    width: 208,
    borderRadius: 22,
    borderWidth: 3,
    borderColor: "#F0D68B",
    backgroundColor: "rgba(232, 197, 115, 0.06)",
  },
  hint: {
    position: "absolute",
    bottom: 22,
    color: "#FFFFFF",
    fontSize: 15,
    fontWeight: "800",
    backgroundColor: "rgba(8,17,31,0.8)",
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 12,
  },
  permission: {
    backgroundColor: "#15243A",
    borderRadius: 24,
    borderWidth: 1,
    borderColor: "#314563",
    padding: 24,
    alignItems: "center",
    gap: 12,
    borderCurve: "continuous",
  },
  permissionTitle: {
    color: "#F5F7FB",
    fontSize: 19,
    fontWeight: "900",
    textAlign: "center",
  },
  permissionText: {
    color: "#A9B7CE",
    fontSize: 15,
    lineHeight: 22,
    textAlign: "center",
  },
});
