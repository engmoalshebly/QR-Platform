import React from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Can, PERM } from '@shared/permissions'
import type { GuestImportRow } from './types'

// The guest form has only the fixed guest-template fields; extra per-guest
// fields are no longer offered (the field props remain for the callers).
interface QuickNamesPanelProps {
  quickManualGuests: GuestImportRow[]
  newQuickFieldName: string
  setNewQuickFieldName: (val: string) => void
  quickDynamicFields: string[]
  handleAddQuickField: () => void
  removeQuickDynamicField: (field: string) => void
  quickFormName: string
  setQuickFormName: (val: string) => void
  quickFormCount: number
  setQuickFormCount: (val: number) => void
  quickFormClass: 'vip' | 'normal'
  setQuickFormClass: (val: 'vip' | 'normal') => void
  requireRsvp: boolean
  quickFormPhone: string
  setQuickFormPhone: (val: string) => void
  quickFormEmail: string
  setQuickFormEmail: (val: string) => void
  quickFormCustomFields: Record<string, string>
  setQuickFormCustomFields: React.Dispatch<React.SetStateAction<Record<string, string>>>
  addQuickManualGuest: () => void
  deleteQuickManualGuest: (index: number) => void
}

export function QuickNamesPanel({
  quickManualGuests,
  quickFormName,
  setQuickFormName,
  quickFormCount,
  setQuickFormCount,
  quickFormClass,
  setQuickFormClass,
  requireRsvp,
  quickFormPhone,
  setQuickFormPhone,
  quickFormEmail,
  setQuickFormEmail,
  addQuickManualGuest,
  deleteQuickManualGuest,
}: QuickNamesPanelProps) {
  return (
    <div className="inv-import-card inv-guest-list-panel">
      <div className="inv-import-card__header">
        <div>
          <strong>إدخال أسماء المدعوين يدوياً</strong>
          <span>أدخل الأسماء مباشرة، وسيتم بناء قائمة بالمدعوين لإصدار بطاقاتهم دفعة واحدة.</span>
        </div>
      </div>

      {/* Form to add a guest */}
      <div
        className="inv-design-tab-row inv-guest-entry"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          background: 'var(--color-bg-card)',
          padding: 18,
          borderRadius: 12,
          marginBottom: 16,
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, width: '100%' }}>
          <div style={{ flex: '2 1 250px' }}>
            <label className="inv-label">
              اسم الضيف <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <input
              type="text"
              value={quickFormName}
              onChange={(e) => setQuickFormName(e.target.value)}
              className="inv-input"
              style={{ width: '100%' }}
              placeholder="اكتب اسم الضيف الكامل..."
            />
          </div>
          <div style={{ flex: '1 1 100px' }}>
            <label className="inv-label">عدد الأشخاص (شاملاً الضيف)</label>
            <input
              type="number"
              min={1}
              value={quickFormCount}
              onChange={(e) => setQuickFormCount(Number(e.target.value))}
              className="inv-input"
              style={{ width: '100%' }}
            />
          </div>
          <div style={{ flex: '1 1 120px' }}>
            <label className="inv-label">الفئة</label>
            <select
              value={quickFormClass}
              onChange={(e) => setQuickFormClass(e.target.value as any)}
              className="inv-input"
              style={{ width: '100%' }}
            >
              <option value="normal">عادي</option>
              <option value="vip">VIP</option>
            </select>
          </div>
        </div>

        {requireRsvp && (
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 12,
              width: '100%',
              borderTop: '1px solid var(--color-border)',
              paddingTop: 12,
            }}
          >
            <div style={{ flex: '1 1 200px' }}>
              <label className="inv-label">
                رقم الجوال
              </label>
              <input
                type="text"
                value={quickFormPhone}
                onChange={(e) => setQuickFormPhone(e.target.value)}
                className="inv-input"
                style={{ width: '100%' }}
                placeholder="رقم دولي، مثال: +967700000000"
              />
            </div>
            <div style={{ flex: '1 1 200px' }}>
              <label className="inv-label">
                البريد الإلكتروني
              </label>
              <input
                type="text"
                value={quickFormEmail}
                onChange={(e) => setQuickFormEmail(e.target.value)}
                className="inv-input"
                style={{ width: '100%' }}
                placeholder="مثال: guest@example.com"
              />
            </div>
          </div>
        )}

        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            width: '100%',
            borderTop: '1px solid var(--color-border)',
            paddingTop: 12,
          }}
        >
          <Can permission={PERM.GUEST_CREATE}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={addQuickManualGuest}
              style={{
                height: '42px',
                background: 'var(--color-primary)',
                borderColor: 'var(--color-primary)',
                color: '#fff',
                padding: '0 24px',
                borderRadius: '8px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontWeight: '600',
              }}
            >
              <Plus size={16} /> إضافة الضيف للقائمة
            </button>
          </Can>
        </div>
      </div>

      {/* Preview List Table */}
      {quickManualGuests.length > 0 ? (
        <div className="inv-design-preview" style={{ marginTop: 12 }}>
          <div className="inv-design-preview__header">
            <strong>قائمة الضيوف الحالية ({quickManualGuests.length} ضيوف)</strong>
          </div>
          <div className="inv-design-preview__table-wrap">
            <table className="inv-design-preview__table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>اسم الضيف</th>
                  <th>الفئة</th>
                  <th>عدد الأشخاص</th>
                  {requireRsvp && (
                    <>
                      <th>رقم الجوال</th>
                      <th>البريد الإلكتروني</th>
                    </>
                  )}
                  <th style={{ width: 100 }}>إجراءات</th>
                </tr>
              </thead>
              <tbody>
                {quickManualGuests.map((guest, index) => (
                  <tr key={index}>
                    <td>{index + 1}</td>
                    <td>{guest.guest_name}</td>
                    <td>
                      <span
                        className={`inv-guest-class ${
                          guest.ticket_class === 'vip' ? 'inv-guest-class--vip' : ''
                        }`}
                        style={{ fontSize: '11px', padding: '2px 8px' }}
                      >
                        {guest.ticket_class === 'vip' ? 'VIP' : 'عادي'}
                      </span>
                    </td>
                    <td>{guest.invitation_count}</td>
                    {requireRsvp && (
                      <>
                        <td>{guest.custom_fields?.['رقم الجوال'] || guest.custom_fields?.['جوال'] || '—'}</td>
                        <td>
                          {guest.custom_fields?.['البريد الإلكتروني'] || guest.custom_fields?.['بريد'] || '—'}
                        </td>
                      </>
                    )}
                    <td>
                      <Can permission={PERM.GUEST_DELETE}>
                        <button
                          type="button"
                          className="inv-card-action-btn inv-card-action-btn--delete"
                          onClick={() => deleteQuickManualGuest(index)}
                          style={{
                            position: 'relative',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            background: 'rgba(239, 68, 68, 0.08)',
                            color: '#ef4444',
                          }}
                          title="حذف"
                        >
                          <Trash2 size={13} />
                        </button>
                      </Can>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div
          style={{
            textAlign: 'center',
            padding: '30px 20px',
            border: '1px dashed var(--color-border)',
            borderRadius: 12,
            opacity: 0.6,
            fontSize: '13px',
          }}
        >
          القائمة فارغة حالياً. ابدأ بإدخال اسم ضيف وإضافته للقائمة أعلاه.
        </div>
      )}
    </div>
  )
}
