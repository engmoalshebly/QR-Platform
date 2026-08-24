const DEVICE_ID_KEY = 'qentry_field_device_id'

function newDeviceId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export function getFieldDeviceId(): string {
  const existing = localStorage.getItem(DEVICE_ID_KEY)
  if (existing && existing.length >= 8) return existing
  const id = newDeviceId()
  localStorage.setItem(DEVICE_ID_KEY, id)
  return id
}

export function defaultDeviceName(): string {
  const enhancedNavigator = navigator as Navigator & { userAgentData?: { platform?: string } }
  const platform = enhancedNavigator.userAgentData?.platform || navigator.platform || 'Web'
  return `جهاز بوابة — ${platform}`.slice(0, 160)
}
