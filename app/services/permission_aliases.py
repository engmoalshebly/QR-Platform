"""
Maps ui.* permission keys to legacy API permission keys.
Keeps frontend role assignments (ui.*) aligned with backend route checks.
"""

UI_TO_LEGACY: dict[str, str] = {
    "ui.nav.dashboard": "reports.view",
    "ui.nav.users": "members.view",
    "ui.nav.teams": "teams.view",
    "ui.nav.guests": "guests.view",
    "ui.nav.events": "events.view",
    "ui.nav.invitations": "invitations.view",
    "ui.nav.checkin": "checkin.view",
    "ui.nav.settings": "settings.view",
    "ui.event.tab.analytics": "events.view",
    "ui.event.tab.settings": "events.edit",
    "ui.event.tab.gates": "gates.view",
    "ui.event.tab.invitations": "invitations.create",
    "ui.event.tab.rsvp": "invitations.view",
    "ui.event.tab.registration": "events.edit",
    "ui.event.tab.templates": "templates.view",
    "ui.event.tab.barcodes": "batches.view",
    "ui.event.tab.final": "invitations.view",
    "ui.event.action.create": "events.create",
    "ui.event.action.publish": "events.publish",
    "ui.event.action.delete": "events.delete",
    "ui.gates.action.create": "gates.manage",
    "ui.gates.action.edit": "gates.manage",
    "ui.gates.action.delete": "gates.manage",
    "ui.invitations.action.generate": "invitations.create",
    "ui.invitations.action.send": "invitations.send",
    "ui.invitations.action.revoke": "invitations.revoke",
    "ui.invitations.action.export": "invitations.export",
    "ui.rsvp.action.update": "invitations.create",
    "ui.rsvp.action.export": "reports.export",
    "ui.registration.action.manage": "events.edit",
    "ui.registration.action.approve": "events.edit",
    "ui.templates.action.create": "templates.create",
    "ui.templates.action.edit": "templates.edit",
    "ui.templates.action.delete": "templates.delete",
    "ui.templates.action.design": "templates.edit",
    "ui.batches.action.delete": "batches.manage",
    "ui.batches.action.download": "invitations.export",
    "ui.guests.action.create": "guests.create",
    "ui.guests.action.edit": "guests.edit",
    "ui.guests.action.delete": "guests.delete",
    "ui.guests.action.import": "guests.import",
    "ui.teams.action.create": "teams.manage",
    "ui.teams.action.manage": "teams.manage",
    "ui.teams.action.archive": "teams.manage",
    "ui.members.action.create": "members.manage",
    "ui.members.action.edit": "members.manage",
    "ui.members.action.delete": "members.manage",
    "ui.checkin.action.scan": "checkin.scan",
    "ui.checkin.action.manual": "checkin.manual",
    "ui.settings.action.edit": "settings.manage",
    "ui.roles.action.manage": "roles.manage",
}


def resolve_permission_keys(permission_key: str) -> list[str]:
    """Return equivalent keys to check (requested key first)."""
    keys = [permission_key]
    if permission_key.startswith("ui."):
        legacy = UI_TO_LEGACY.get(permission_key)
        if legacy and legacy not in keys:
            keys.append(legacy)
    else:
        for ui_key, legacy in UI_TO_LEGACY.items():
            if legacy == permission_key and ui_key not in keys:
                keys.append(ui_key)
    return keys
