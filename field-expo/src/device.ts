import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

const DEVICE_ID_KEY = "qentry_field_device_id_v1";

function createId(): string {
  const random = Math.random().toString(36).slice(2, 12);
  return `field-${Date.now().toString(36)}-${random}`;
}

export async function getFieldDeviceId(): Promise<string> {
  const existing = await AsyncStorage.getItem(DEVICE_ID_KEY);
  if (existing) return existing;
  const id = createId();
  await AsyncStorage.setItem(DEVICE_ID_KEY, id);
  return id;
}

export function deviceName(): string {
  return `بوابة — ${Platform.OS}`;
}

export function newClientScanId(): string {
  // The field API deliberately accepts UUIDs only.  Keeping this identifier
  // standards-compliant makes an online retry and an offline sync idempotent
  // without exposing the invitation code as an identifier.
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }

  // React Native engines that predate randomUUID still have getRandomValues.
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
