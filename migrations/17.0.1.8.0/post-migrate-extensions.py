"""Migrate single-ext (`res.users.zadarma_internal_number`) to multi-ext
table (`res.users.zadarma.extension`). One row per user, flagged as
is_primary so click-to-call keeps working unchanged."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # Find users with a legacy SIP ID not yet mirrored as an extension row.
    cr.execute(
        """
        SELECT u.id, u.zadarma_internal_number, u.company_id
        FROM res_users u
        WHERE u.zadarma_internal_number IS NOT NULL
          AND TRIM(u.zadarma_internal_number) != ''
          AND NOT EXISTS (
              SELECT 1 FROM res_users_zadarma_extension e
              WHERE e.user_id = u.id AND TRIM(e.internal) = TRIM(u.zadarma_internal_number)
          )
        """
    )
    rows = cr.fetchall()
    if not rows:
        _logger.info('zadarma_odoo migration: no legacy SIP IDs to migrate')
        return
    for user_id, internal, company_id in rows:
        # Skip if another user/company already owns this ext (unique constraint)
        cr.execute(
            "SELECT id FROM res_users_zadarma_extension WHERE internal = %s AND company_id = %s",
            (internal.strip(), company_id),
        )
        if cr.fetchone():
            _logger.warning(
                'zadarma_odoo migration: ext %s already mapped in company %s — skipping user %s',
                internal, company_id, user_id,
            )
            continue
        cr.execute(
            """
            INSERT INTO res_users_zadarma_extension
                (user_id, internal, is_primary, active, company_id, create_uid, write_uid,
                 create_date, write_date)
            VALUES (%s, %s, true, true, %s, 1, 1, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
            """,
            (user_id, internal.strip(), company_id),
        )
    _logger.info('zadarma_odoo migration: created %s extension row(s) from legacy field', len(rows))
