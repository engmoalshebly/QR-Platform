/**
 * All permission keys used for UI gating.
 * Each key maps to a backend permission in the `permissions` table.
 */
export const PERM = {
  // Navigation
  NAV_DASHBOARD: 'ui.nav.dashboard',
  NAV_USERS: 'ui.nav.users',
  NAV_TEAMS: 'ui.nav.teams',
  NAV_GUESTS: 'ui.nav.guests',
  NAV_EVENTS: 'ui.nav.events',
  NAV_INVITATIONS: 'ui.nav.invitations',
  NAV_CHECKIN: 'ui.nav.checkin',
  NAV_SETTINGS: 'ui.nav.settings',

  // Event tabs
  EVENT_TAB_ANALYTICS: 'ui.event.tab.analytics',
  EVENT_TAB_SETTINGS: 'ui.event.tab.settings',
  EVENT_TAB_GATES: 'ui.event.tab.gates',
  EVENT_TAB_INVITATIONS: 'ui.event.tab.invitations',
  EVENT_TAB_RSVP: 'ui.event.tab.rsvp',
  EVENT_TAB_REGISTRATION: 'ui.event.tab.registration',
  EVENT_TAB_TEMPLATES: 'ui.event.tab.templates',
  EVENT_TAB_BARCODES: 'ui.event.tab.barcodes',
  EVENT_TAB_FINAL: 'ui.event.tab.final',

  // Event actions
  EVENT_CREATE: 'ui.event.action.create',
  EVENT_PUBLISH: 'ui.event.action.publish',
  EVENT_DELETE: 'ui.event.action.delete',

  // Gates
  GATES_CREATE: 'ui.gates.action.create',
  GATES_EDIT: 'ui.gates.action.edit',
  GATES_DELETE: 'ui.gates.action.delete',

  // Invitations
  INV_GENERATE: 'ui.invitations.action.generate',
  INV_SEND: 'ui.invitations.action.send',
  INV_REVOKE: 'ui.invitations.action.revoke',
  INV_EXPORT: 'ui.invitations.action.export',

  WHATSAPP_MANAGE: 'whatsapp.manage',
  WHATSAPP_SEND: 'whatsapp.send',
  WHATSAPP_VIEW: 'whatsapp.view',

  // RSVP
  RSVP_UPDATE: 'ui.rsvp.action.update',
  RSVP_EXPORT: 'ui.rsvp.action.export',

  // Registration
  REG_MANAGE: 'ui.registration.action.manage',
  REG_APPROVE: 'ui.registration.action.approve',

  // Templates
  TMPL_CREATE: 'ui.templates.action.create',
  TMPL_EDIT: 'ui.templates.action.edit',
  TMPL_DELETE: 'ui.templates.action.delete',
  TMPL_DESIGN: 'ui.templates.action.design',

  // Batches
  BATCH_DELETE: 'ui.batches.action.delete',
  BATCH_DOWNLOAD: 'ui.batches.action.download',

  // Guests
  GUEST_CREATE: 'ui.guests.action.create',
  GUEST_EDIT: 'ui.guests.action.edit',
  GUEST_DELETE: 'ui.guests.action.delete',
  GUEST_IMPORT: 'ui.guests.action.import',

  // Teams
  TEAM_CREATE: 'ui.teams.action.create',
  TEAM_MANAGE: 'ui.teams.action.manage',
  TEAM_ARCHIVE: 'ui.teams.action.archive',

  // Members
  MEMBER_CREATE: 'ui.members.action.create',
  MEMBER_EDIT: 'ui.members.action.edit',
  MEMBER_DELETE: 'ui.members.action.delete',

  // Check-in
  CHECKIN_SCAN: 'ui.checkin.action.scan',
  CHECKIN_MANUAL: 'ui.checkin.action.manual',

  // Settings & roles
  SETTINGS_EDIT: 'ui.settings.action.edit',
  ROLES_MANAGE: 'ui.roles.action.manage',

  // Bookings, operations, billing and notifications
  BOOKINGS_VIEW: 'ui.bookings.view',
  BOOKINGS_CREATE: 'ui.bookings.create',
  BOOKINGS_MANAGE: 'ui.bookings.manage',
  BOOKINGS_RESPOND: 'ui.bookings.respond',
  OPERATIONS_VIEW: 'ui.operations.view',
  OPERATIONS_MANAGE: 'ui.operations.manage',
  OPERATIONS_MEMBERS: 'ui.operations.members',
  OPERATIONS_ATTACHMENTS: 'ui.operations.attachments',
  BILLING_VIEW: 'billing.view',
  BILLING_MANAGE: 'billing.manage',
  NOTIFICATIONS_VIEW: 'ui.notifications.view',
  TEAM_DASHBOARD_VIEW: 'ui.organizer.nav.home',
  TEAM_REQUESTS_VIEW: 'ui.organizer.nav.requests',
  TEAM_OPERATIONS_VIEW: 'ui.organizer.nav.operations',
  TEAM_CALENDAR_VIEW: 'ui.organizer.nav.operations',
  TEAM_TASKS_VIEW: 'ui.operation.tab.tasks',
  TEAM_MEMBERS_VIEW: 'ui.organizer.nav.members',
  TEAM_GUESTS_VIEW: 'ui.operation.tab.guests',
  TEAM_ATTENDANCE_VIEW: 'ui.operation.tab.live',
  TEAM_FILES_VIEW: 'ui.operation.tab.files',
  TEAM_NOTIFICATIONS_VIEW: 'notifications.view',
  TEAM_REPORTS_VIEW: 'reports.view',
  TEAM_SETTINGS_VIEW: 'ui.organizer.nav.settings',
  // Organizer workspace navigation. Unlike the legacy TEAM_* entries above,
  // these are independent UI permissions, so admins can hide each area safely.
  ORGANIZER_NAV_HOME: 'ui.organizer.nav.home',
  ORGANIZER_NAV_REQUESTS: 'ui.organizer.nav.requests',
  ORGANIZER_NAV_OPERATIONS: 'ui.organizer.nav.operations',
  ORGANIZER_NAV_MEMBERS: 'ui.organizer.nav.members',
  ORGANIZER_NAV_GROUPS: 'ui.organizer.nav.groups',
  ORGANIZER_NAV_SETTINGS: 'ui.organizer.nav.settings',

  // Internal operation tabs. API routes keep their own data-level checks.
  OPERATION_TAB_OVERVIEW: 'ui.operation.tab.overview',
  OPERATION_TAB_TASKS: 'ui.operation.tab.tasks',
  OPERATION_TAB_TEAM: 'ui.operation.tab.team',
  OPERATION_TAB_GUESTS: 'ui.operation.tab.guests',
  OPERATION_TAB_GATES: 'ui.operation.tab.gates',
  OPERATION_TAB_LIVE: 'ui.operation.tab.live',
  OPERATION_TAB_FILES: 'ui.operation.tab.files',
  OPERATION_TAB_ACTIVITY: 'ui.operation.tab.activity',
  TASK_VIEW: 'operations.tasks.view',
  TASK_CREATE: 'operations.tasks.create',
  TASK_UPDATE_OWN: 'operations.tasks.update_own',
  TASK_UPDATE_ANY: 'operations.tasks.update_any',
  TASK_ASSIGN: 'operations.tasks.assign',
  TASK_APPROVE: 'operations.tasks.approve',
  ATTACHMENT_VIEW: 'operations.attachments.view',
  ATTACHMENT_UPLOAD: 'operations.attachments.upload',
  ATTACHMENT_DELETE: 'operations.attachments.delete',
  ATTACHMENT_DOWNLOAD: 'operations.attachments.download',
  REPORTS_EXPORT: 'reports.export',
} as const

export type PermissionKey = (typeof PERM)[keyof typeof PERM]

/** Grouped labels for the roles management UI (Arabic) */
const BASE_PERMISSION_GROUPS: { label: string; keys: PermissionKey[] }[] = [
  {
    label: 'التنقل — القائمة الجانبية',
    keys: [
      PERM.NAV_DASHBOARD, PERM.NAV_USERS, PERM.NAV_TEAMS,
      PERM.NAV_EVENTS, PERM.NAV_SETTINGS,
    ],
  },
  {
    label: 'تبويبات تفاصيل المناسبة',
    keys: [
      PERM.EVENT_TAB_ANALYTICS, PERM.EVENT_TAB_SETTINGS, PERM.EVENT_TAB_GATES,
      PERM.EVENT_TAB_INVITATIONS, PERM.EVENT_TAB_RSVP, PERM.EVENT_TAB_REGISTRATION,
      PERM.EVENT_TAB_TEMPLATES, PERM.EVENT_TAB_BARCODES, PERM.EVENT_TAB_FINAL,
    ],
  },
  {
    label: 'عمليات المناسبة',
    keys: [PERM.EVENT_CREATE, PERM.EVENT_PUBLISH, PERM.EVENT_DELETE],
  },
  {
    label: 'البوابات',
    keys: [PERM.GATES_CREATE, PERM.GATES_EDIT, PERM.GATES_DELETE],
  },
  {
    label: 'الدعوات',
    keys: [PERM.INV_GENERATE, PERM.INV_SEND, PERM.INV_REVOKE, PERM.INV_EXPORT],
  },
  { label: 'WhatsApp', keys: [PERM.WHATSAPP_MANAGE, PERM.WHATSAPP_SEND, PERM.WHATSAPP_VIEW] },
  {
    label: 'ردود الضيوف والتسجيل',
    keys: [PERM.RSVP_UPDATE, PERM.RSVP_EXPORT, PERM.REG_MANAGE, PERM.REG_APPROVE],
  },
  {
    label: 'القوالب والإنشاء',
    keys: [
      PERM.TMPL_CREATE, PERM.TMPL_EDIT, PERM.TMPL_DELETE, PERM.TMPL_DESIGN,
      PERM.BATCH_DELETE, PERM.BATCH_DOWNLOAD,
    ],
  },
  {
    label: 'الضيوف والفرق والأعضاء',
    keys: [
      PERM.GUEST_CREATE, PERM.GUEST_EDIT, PERM.GUEST_DELETE, PERM.GUEST_IMPORT,
      PERM.TEAM_CREATE, PERM.TEAM_MANAGE, PERM.TEAM_ARCHIVE,
      PERM.MEMBER_CREATE, PERM.MEMBER_EDIT, PERM.MEMBER_DELETE,
    ],
  },
  {
    label: 'تسجيل الحضور والإعدادات',
    keys: [PERM.CHECKIN_SCAN, PERM.CHECKIN_MANUAL, PERM.SETTINGS_EDIT, PERM.ROLES_MANAGE],
  },
]

export const PERMISSION_GROUPS: { label: string; keys: PermissionKey[] }[] = [
  ...BASE_PERMISSION_GROUPS,
  {
    label: 'فريق التنظيم — القائمة الجانبية',
    keys: [
      PERM.ORGANIZER_NAV_HOME, PERM.ORGANIZER_NAV_REQUESTS,
      PERM.ORGANIZER_NAV_OPERATIONS, PERM.ORGANIZER_NAV_MEMBERS,
      PERM.ORGANIZER_NAV_GROUPS, PERM.ORGANIZER_NAV_SETTINGS,
    ],
  },
  {
    label: 'فريق التنظيم — تبويبات تفاصيل الحفل',
    keys: [
      PERM.OPERATION_TAB_OVERVIEW, PERM.OPERATION_TAB_TASKS,
      PERM.OPERATION_TAB_TEAM, PERM.OPERATION_TAB_GUESTS,
      PERM.OPERATION_TAB_GATES, PERM.OPERATION_TAB_LIVE,
      PERM.OPERATION_TAB_FILES, PERM.OPERATION_TAB_ACTIVITY,
    ],
  },
]

export const PERMISSION_LABELS_AR: Record<string, string> = {
  [PERM.ORGANIZER_NAV_HOME]: 'قائمة الفريق: الرئيسية',
  [PERM.ORGANIZER_NAV_REQUESTS]: 'قائمة الفريق: الطلبات',
  [PERM.ORGANIZER_NAV_OPERATIONS]: 'قائمة الفريق: الحفلات والمشاريع',
  [PERM.ORGANIZER_NAV_MEMBERS]: 'قائمة الفريق: الأعضاء',
  [PERM.ORGANIZER_NAV_GROUPS]: 'قائمة الفريق: مجموعات الفريق',
  [PERM.ORGANIZER_NAV_SETTINGS]: 'قائمة الفريق: الإعدادات',
  [PERM.OPERATION_TAB_OVERVIEW]: 'تبويب الحفل: نظرة عامة',
  [PERM.OPERATION_TAB_TASKS]: 'تبويب الحفل: المهام',
  [PERM.OPERATION_TAB_TEAM]: 'تبويب الحفل: فريق العمل',
  [PERM.OPERATION_TAB_GUESTS]: 'تبويب الحفل: الضيوف والدعوات',
  [PERM.OPERATION_TAB_GATES]: 'تبويب الحفل: البوابات',
  [PERM.OPERATION_TAB_LIVE]: 'تبويب الحفل: المتابعة المباشرة',
  [PERM.OPERATION_TAB_FILES]: 'تبويب الحفل: المرفقات',
  [PERM.OPERATION_TAB_ACTIVITY]: 'تبويب الحفل: سجل النشاط',
  [PERM.NAV_DASHBOARD]: 'الرئيسية',
  [PERM.NAV_USERS]: 'المستخدمون',
  [PERM.NAV_TEAMS]: 'الفرق',
  [PERM.NAV_GUESTS]: 'الضيوف',
  [PERM.NAV_EVENTS]: 'المناسبات',
  [PERM.NAV_INVITATIONS]: 'الدعوات',
  [PERM.NAV_CHECKIN]: 'تسجيل الحضور',
  [PERM.NAV_SETTINGS]: 'الإعدادات',
  [PERM.EVENT_TAB_ANALYTICS]: 'تبويب: تحليلات',
  [PERM.EVENT_TAB_SETTINGS]: 'تبويب: إعدادات',
  [PERM.EVENT_TAB_GATES]: 'تبويب: بوابات',
  [PERM.EVENT_TAB_INVITATIONS]: 'تبويب: إنشاء دعوات',
  [PERM.EVENT_TAB_RSVP]: 'عرض ردود الضيوف',
  [PERM.EVENT_TAB_REGISTRATION]: 'تبويب: التسجيل',
  [PERM.EVENT_TAB_TEMPLATES]: 'تبويب: قوالب',
  [PERM.EVENT_TAB_BARCODES]: 'تبويب: عمليات إنشاء الدعوات',
  [PERM.EVENT_TAB_FINAL]: 'تبويب: الدعوات الجاهزة للدخول',
  [PERM.EVENT_CREATE]: 'إضافة مناسبة',
  [PERM.EVENT_PUBLISH]: 'نشر مناسبة',
  [PERM.EVENT_DELETE]: 'حذف مناسبة',
  [PERM.GATES_CREATE]: 'إنشاء بوابة',
  [PERM.GATES_EDIT]: 'تعديل بوابة',
  [PERM.GATES_DELETE]: 'حذف بوابة',
  [PERM.INV_GENERATE]: 'إنشاء دعوات',
  [PERM.INV_SEND]: 'إرسال دعوات',
  [PERM.INV_REVOKE]: 'إلغاء دعوات',
  [PERM.INV_EXPORT]: 'تصدير دعوات',
  [PERM.WHATSAPP_MANAGE]: 'إدارة اتصال WhatsApp',
  [PERM.WHATSAPP_SEND]: 'إرسال عبر WhatsApp',
  [PERM.WHATSAPP_VIEW]: 'عرض سجل WhatsApp',
  [PERM.RSVP_UPDATE]: 'تحديث رد الضيف',
  [PERM.RSVP_EXPORT]: 'تنزيل قائمة ردود الضيوف',
  [PERM.REG_MANAGE]: 'إدارة نموذج التسجيل',
  [PERM.REG_APPROVE]: 'قبول/رفض متقدمين',
  [PERM.TMPL_CREATE]: 'إنشاء قالب',
  [PERM.TMPL_EDIT]: 'تعديل قالب',
  [PERM.TMPL_DELETE]: 'حذف قالب',
  [PERM.TMPL_DESIGN]: 'محرر التصميم',
  [PERM.BATCH_DELETE]: 'حذف دفعة إنشاء',
  [PERM.BATCH_DOWNLOAD]: 'تحميل PDF/ZIP',
  [PERM.GUEST_CREATE]: 'إضافة ضيف',
  [PERM.GUEST_EDIT]: 'تعديل ضيف',
  [PERM.GUEST_DELETE]: 'حذف ضيف',
  [PERM.GUEST_IMPORT]: 'استيراد ضيوف',
  [PERM.TEAM_CREATE]: 'إنشاء فريق',
  [PERM.TEAM_MANAGE]: 'إدارة أعضاء الفريق',
  [PERM.TEAM_ARCHIVE]: 'أرشفة فريق',
  [PERM.MEMBER_CREATE]: 'إضافة عضو',
  [PERM.MEMBER_EDIT]: 'تعديل عضو',
  [PERM.MEMBER_DELETE]: 'حذف عضو',
  [PERM.CHECKIN_SCAN]: 'مسح QR',
  [PERM.CHECKIN_MANUAL]: 'تسجيل يدوي',
  [PERM.SETTINGS_EDIT]: 'تعديل إعدادات المؤسسة',
  [PERM.ROLES_MANAGE]: 'إدارة الأدوار',
}
