import { test, expect } from '@playwright/test'

const tenantId = '11111111-1111-4111-8111-111111111111'
const ownerId = '22222222-2222-4222-8222-222222222222'
const tenant = { tenant_id: tenantId, name: 'مساحة اختبار', slug: 'test', role: 'owner',
  plan: 'starter', workspace_type: 'organizer', tenant_status: 'active', membership_status: 'active' }
const user = { id: ownerId, email: 'owner@example.test', full_name: 'مالك الاختبار', is_staff: false }

test('invitation history supports resend, confirmed cancellation and scoped member removal', async ({ page }) => {
  let resendCount = 0
  let cancelCount = 0
  let removeCount = 0
  let members = [{ tenant_id: tenantId, user_id: ownerId, role: 'owner', status: 'active', full_name: user.full_name },
    { tenant_id: tenantId, user_id: 'member-id', role: 'member', status: 'active', full_name: 'عضو الاختبار' }]
  const invites = [
    { id: 'pending-id', email: 'pending@example.test', role: 'member', status: 'pending', created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', accepted_at: null },
    { id: 'expired-id', email: 'expired@example.test', role: 'viewer', status: 'pending', created_at: '2020-01-01T00:00:00Z', expires_at: '2020-01-08T00:00:00Z', accepted_at: null },
    { id: 'accepted-id', email: 'accepted@example.test', role: 'member', status: 'accepted', created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', accepted_at: '2026-01-02T00:00:00Z' },
  ]
  await page.addInitScript(({ tenant, user }) => {
    sessionStorage.setItem('qentry-auth', JSON.stringify({ state: { user, tenants: [tenant], currentTenantId: tenant.tenant_id, permissions: [] }, version: 0 }))
    sessionStorage.setItem('qentry_tenant_id', tenant.tenant_id)
  }, { tenant, user })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let body: unknown = {}
    if (path.endsWith('/auth/refresh')) body = { access_token: 'test-access-token' }
    else if (path.endsWith('/auth/me')) body = { ...user, tenants: [tenant], permissions: [] }
    else if (path.endsWith('/invites/pending-id/resend')) {
      expect(method).toBe('POST')
      resendCount++
      body = { message: 'أُعيد إرسال الدعوة إلى خدمة البريد.' }
    } else if (path.endsWith('/invites/pending-id') && method === 'DELETE') {
      cancelCount++
      invites[0].status = 'revoked'
      await route.fulfill({ status: 204 }); return
    } else if (path.endsWith('/invites')) body = invites
    else if (path.endsWith('/tenants/current/members/member-id') && method === 'DELETE') {
      removeCount++
      members = members.filter(member => member.user_id !== 'member-id')
      await route.fulfill({ status: 204 }); return
    } else if (path.endsWith('/tenants/current/members')) body = members
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/users')
  await expect(page.getByRole('tabpanel', { name: /المستخدمون/ })).toBeVisible()
  await page.getByRole('tab', { name: /الدعوات/ }).click()
  const history = page.getByRole('tabpanel', { name: /الدعوات/ })
  await expect(history.getByText('accepted@example.test')).toBeVisible()
  await expect(page.getByText('2 دعوة معلّقة · 0 موقوف')).toBeVisible()
  const pending = history.getByRole('row').filter({ hasText: 'pending@example.test' })
  const expired = history.getByRole('row').filter({ hasText: 'expired@example.test' })
  await expect(expired.getByRole('button', { name: 'إعادة الإرسال' })).toHaveCount(0)
  await pending.getByRole('button', { name: 'إعادة الإرسال' }).click()
  await expect(page.getByText('أُعيد إرسال الدعوة إلى خدمة البريد.', { exact: true })).toBeVisible()
  expect(resendCount).toBe(1)
  await pending.getByRole('button', { name: 'إلغاء الدعوة' }).click()
  expect(cancelCount).toBe(0)
  await page.getByRole('button', { name: 'تأكيد إلغاء الدعوة' }).click()
  await expect(pending.getByText('ملغاة', { exact: true })).toBeVisible()
  await expect(page.getByText('1 دعوة معلّقة · 0 موقوف')).toBeVisible()
  expect(cancelCount).toBe(1)
  await page.getByRole('tab', { name: /المستخدمون/ }).click()
  await page.getByRole('button', { name: 'إزالة عضو الاختبار', exact: true }).click()
  await expect(page.getByText(/سيبقى حسابه الشخصي ومساحات عمله الأخرى/)).toBeVisible()
  expect(removeCount).toBe(0)
  await page.getByRole('button', { name: 'تأكيد الإزالة' }).click()
  await expect(page.getByRole('button', { name: 'إزالة عضو الاختبار', exact: true })).toHaveCount(0)
  expect(removeCount).toBe(1)
  await expect(page.getByRole('button', { name: 'إزالة مالك الاختبار', exact: true })).toHaveCount(0)
})
