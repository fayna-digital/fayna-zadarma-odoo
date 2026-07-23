# NOTICE — Code Provenance & License

**© 2026 Fayna Digital (Volodymyr Shevchenko). All rights reserved.**

## Authorship
Original work authored by Fayna Digital — Volodymyr Shevchenko. This is a
clean-room, original implementation — no source code copied from
third-party copyleft (GPL/AGPL) projects.

## Public extract
This repository is a sanitized, standalone extract of a module that is in
active production use for a Fayna Digital client (CampScout). It was
re-extracted with fresh history for the public portfolio — no client PII,
secrets, or internal infrastructure details are included. The live
deployment continues to be maintained privately.

## License
Licensed under **LGPL-3.0** — see [LICENSE](LICENSE). This matches the
license of the Odoo Community modules it depends on (see "Dependency
hygiene" below), the standard choice for publicly shared Odoo addons.

## Module
**Fayna Zadarma Telephony** (`zadarma_odoo`) — integration of Zadarma cloud
PBX with Odoo 17 CRM. Provides automatic call logging, MP3 recordings in
chatter, click-to-call, SMS statistics, and missed-call lead auto-creation.

## Dependency hygiene
Depends only on:
- Odoo Community standard modules (`base`, `crm`, `mail`, `phone_validation`, `sms`) — LGPL-3.

**No AGPL/GPL dependencies** in the tree.

## Data hygiene
Contains no hardcoded client-specific business records. The missed-call
fallback assignee (`res.company.zadarma_missed_call_fallback_user_id`) and
the per-manager row-color slot (`res.users.zadarma_manager_slot`) are
DB-configured fields — no personal names, emails, or phone numbers are
hardcoded in source.

---
Fayna Digital · https://fayna.agency · admin@fayna.agency
