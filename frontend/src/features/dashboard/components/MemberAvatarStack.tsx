import { motion } from 'framer-motion'
import type { DashboardMember } from '../types'

interface MemberAvatarStackProps {
  members: DashboardMember[]
  maxVisible?: number
}

const AVATAR_COLORS = [
  'linear-gradient(135deg, #D4A32C, #F0D68B)',
  'linear-gradient(135deg, #3B82F6, #60A5FA)',
  'linear-gradient(135deg, #8B5CF6, #A78BFA)',
  'linear-gradient(135deg, #22C55E, #4ADE80)',
  'linear-gradient(135deg, #F59E0B, #FBBF24)',
]

const statusLabel: Record<string, string> = {
  active: 'نشط',
  owner: 'مالك',
  admin: 'مدير',
  member: 'عضو',
  viewer: 'مشاهد',
}

export function MemberAvatarStack({ members, maxVisible = 5 }: MemberAvatarStackProps) {
  const visible = members.slice(0, maxVisible)
  const remaining = members.length - maxVisible

  if (!members.length) {
    return (
      <div className="avatar-stack-empty">
        <span>لا يوجد أعضاء</span>
      </div>
    )
  }

  return (
    <div className="avatar-stack">
      <div className="avatar-stack__row">
        {visible.map((member, i) => (
          <motion.div
            key={`${member.full_name}-${i}`}
            className="avatar-stack__item"
            initial={{ opacity: 0, scale: 0.7 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.06, duration: 0.3, ease: [0.34, 1.56, 0.64, 1] }}
            style={{ zIndex: maxVisible - i }}
            title={member.full_name || 'مستخدم'}
          >
            <div
              className="avatar-stack__circle"
              style={{ background: AVATAR_COLORS[i % AVATAR_COLORS.length] }}
            >
              {(member.full_name || 'U').charAt(0).toUpperCase()}
            </div>
          </motion.div>
        ))}
        {remaining > 0 && (
          <div className="avatar-stack__item avatar-stack__more" style={{ zIndex: 0 }}>
            <div className="avatar-stack__circle avatar-stack__circle--more">
              +{remaining}
            </div>
          </div>
        )}
      </div>

      {/* member list below */}
      <div className="avatar-stack__list">
        {visible.map((member, i) => (
          <div className="avatar-stack__detail" key={`detail-${i}`}>
            <div
              className="avatar-stack__mini"
              style={{ background: AVATAR_COLORS[i % AVATAR_COLORS.length] }}
            >
              {(member.full_name || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="avatar-stack__info">
              <strong>{member.full_name || 'مستخدم'}</strong>
              <span>{statusLabel[member.role] || member.role}</span>
            </div>
            <span className={`avatar-stack__status avatar-stack__status--${member.status}`}>
              {statusLabel[member.status] || member.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
