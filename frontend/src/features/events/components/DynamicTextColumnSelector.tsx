/**
 * DynamicTextColumnSelector.tsx
 * مكون dropdown ديناميكي لاختيار أعمدة البيانات عند إضافة بيانات متغيرة
 */

import { useState } from 'react'
import { ChevronDown, Search } from 'lucide-react'
import '../styles/dynamic-text-selector.css'

export interface AvailableColumn {
  label: string
  key: string
  type: 'text' | 'phone' | 'email' | 'number' | 'date'
  category: 'standard' | 'custom'
}

interface DynamicTextColumnSelectorProps {
  value: string | null
  onChange: (key: string) => void
  columns: AvailableColumn[]
  disabled?: boolean
}

export function DynamicTextColumnSelector({
  value,
  onChange,
  columns,
  disabled = false
}: DynamicTextColumnSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  // Group columns by category
  const groupedColumns = {
    standard: columns.filter(c => c.category === 'standard'),
    custom: columns.filter(c => c.category === 'custom')
  }

  // Filter by search query
  const filteredColumns = {
    standard: groupedColumns.standard.filter(c =>
      c.label.includes(searchQuery) || c.key.includes(searchQuery)
    ),
    custom: groupedColumns.custom.filter(c =>
      c.label.includes(searchQuery) || c.key.includes(searchQuery)
    )
  }

  const selectedColumn = columns.find(c => c.key === value)

  const hasResults = filteredColumns.standard.length > 0 || filteredColumns.custom.length > 0

  return (
    <div className="dynamic-selector">
      <button
        type="button"
        className={`dynamic-selector__trigger ${isOpen ? 'dynamic-selector__trigger--open' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
        disabled={disabled}
      >
        <div className="dynamic-selector__content">
          {selectedColumn ? (
            <>
              <span className="dynamic-selector__icon">
                {selectedColumn.type === 'phone' && '📱'}
                {selectedColumn.type === 'email' && '✉️'}
                {selectedColumn.type === 'number' && '🔢'}
                {selectedColumn.type === 'date' && '📅'}
                {selectedColumn.type === 'text' && '📝'}
              </span>
              <div className="dynamic-selector__selected">
                <div className="dynamic-selector__label">{selectedColumn.label}</div>
                <div className="dynamic-selector__key">{selectedColumn.key}</div>
              </div>
            </>
          ) : (
            <span className="dynamic-selector__placeholder">اختر عمود...</span>
          )}
        </div>
        <ChevronDown
          size={18}
          className={`dynamic-selector__chevron ${isOpen ? 'rotated' : ''}`}
        />
      </button>

      {isOpen && (
        <div className="dynamic-selector__dropdown">
          <div className="dynamic-selector__search">
            <Search size={16} />
            <input
              type="text"
              placeholder="ابحث عن عمود..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              autoFocus
            />
          </div>

          <div className="dynamic-selector__list">
            {!hasResults ? (
              <div className="dynamic-selector__empty">
                <span>لم يتم العثور على نتائج</span>
              </div>
            ) : (
              <>
                {/* Standard Columns */}
                {filteredColumns.standard.length > 0 && (
                  <div className="dynamic-selector__group">
                    <div className="dynamic-selector__group-title">أعمدة معيارية</div>
                    {filteredColumns.standard.map(column => (
                      <button
                        key={column.key}
                        type="button"
                        className={`dynamic-selector__option ${
                          value === column.key ? 'dynamic-selector__option--selected' : ''
                        }`}
                        onClick={() => {
                          onChange(column.key)
                          setIsOpen(false)
                          setSearchQuery('')
                        }}
                      >
                        <span className="dynamic-selector__option-icon">
                          {column.type === 'phone' && '📱'}
                          {column.type === 'email' && '✉️'}
                          {column.type === 'number' && '🔢'}
                          {column.type === 'date' && '📅'}
                          {column.type === 'text' && '📝'}
                        </span>
                        <div className="dynamic-selector__option-text">
                          <div className="dynamic-selector__option-label">{column.label}</div>
                          <div className="dynamic-selector__option-key">{column.key}</div>
                        </div>
                        {value === column.key && (
                          <span className="dynamic-selector__option-check">✓</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}

                {/* Custom Columns */}
                {filteredColumns.custom.length > 0 && (
                  <div className="dynamic-selector__group">
                    <div className="dynamic-selector__group-title">أعمدة إضافية</div>
                    {filteredColumns.custom.map(column => (
                      <button
                        key={column.key}
                        type="button"
                        className={`dynamic-selector__option dynamic-selector__option--custom ${
                          value === column.key ? 'dynamic-selector__option--selected' : ''
                        }`}
                        onClick={() => {
                          onChange(column.key)
                          setIsOpen(false)
                          setSearchQuery('')
                        }}
                      >
                        <span className="dynamic-selector__option-icon">🔲</span>
                        <div className="dynamic-selector__option-text">
                          <div className="dynamic-selector__option-label">{column.label}</div>
                          <div className="dynamic-selector__option-key">{column.key}</div>
                        </div>
                        {value === column.key && (
                          <span className="dynamic-selector__option-check">✓</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default DynamicTextColumnSelector
