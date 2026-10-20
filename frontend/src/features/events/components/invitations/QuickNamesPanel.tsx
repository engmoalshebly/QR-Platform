import React from 'react'
import { Database, Plus, X, Trash2 } from 'lucide-react'
import { Can, PERM } from '@shared/permissions'
import type { GuestImportRow } from './types'

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
  newQuickFieldName,
  setNewQuickFieldName,
  quickDynamicFields,
  handleAddQuickField,
  removeQuickDynamicField,
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
  quickFormCustomFields,
  setQuickFormCustomFields,
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

      {/* Dynamic Fields Management */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          marginTop: 12,
          marginBottom: 12,
          padding: 12,
          background: 'rgba(255,255,255,0.01)',
          borderRadius: 8,
          border: '1px solid rgba(255,255,255,0.04)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Database size={14} style={{ color: 'var(--color-primary)' }} />
            <span style={{ fontSize: '13px', fontWeight: '600' }}>الحقول المخصصة النشطة</span>
          </div>

          {/* Input to add a new custom field */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="text"
              placeholder="اسم الحقل (مثال: الجهة، المنصب)"
              value={newQuickFieldName}
              onChange={(e) => setNewQuickFieldName(e.target.value)}
              className="inv-input"
              style={{ width: '180px', height: '32px', fontSize: '12px', padding: '0 8px' }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  handleAddQuickField()
                }
              }}
            />
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleAddQuickField}
              style={{
                height: '32px',
                padding: '0 12px',
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                borderRadius: '6px',
              }}
            >
              <Plus size={12} /> إضافة حقل
            </button>
          </div>
        </div>

        {quickDynamicFields.length > 0 ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
            {quickDynamicFields.map((field) => (
              <span
                key={field}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  background: 'rgba(var(--color-primary-rgb), 0.1)',
                  border: '1px solid rgba(var(--color-primary-rgb), 0.2)',
                  color: 'var(--color-primary)',
                  padding: '2px 8px',
                  borderRadius: '16px',
                  fontSize: '11px',
                }}
              >
                {field}
                <button
                  type="button"
                  onClick={() => removeQuickDynamicField(field)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--color-text-muted)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    padding: 0,
                  }}
                  title="حذف الحقل"
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
            لا توجد حقول مخصصة حالياً. أضف حقولاً مثل "الجهة" أو "رقم الطاولة" لتعبئتها لكل ضيف.
          </div>
        )}
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

        {/* Render custom dynamic fields */}
        {quickDynamicFields.length > 0 && (
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
            {quickDynamicFields.map((fieldName) => (
              <div key={fieldName} style={{ flex: '1 1 200px' }}>
                <label className="inv-label">{fieldName}</label>
                <input
                  type="text"
                  className="inv-input"
                  style={{ width: '100%' }}
                  value={quickFormCustomFields[fieldName] || ''}
                  onChange={(e) =>
                    setQuickFormCustomFields((prev) => ({
                      ...prev,
                      [fieldName]: e.target.value,
                    }))
                  }
                  placeholder={`بيانات ${fieldName}...`}
                />
              </div>
            ))}
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
                  {quickDynamicFields.map((field) => (
                    <th key={field}>{field}</th>
                  ))}
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
                    {quickDynamicFields.map((field) => (
                      <td key={field}>{guest.custom_fields?.[field] || '—'}</td>
                    ))}
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
