from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Deprecated single-extension field. Migration moves its value to a
    # res.users.zadarma.extension row (is_primary=True). Kept read-only for
    # one release to ease rollback; webhook/import no longer read it.
    zadarma_internal_number = fields.Char(
        string='Zadarma SIP ID (deprecated)',
        help='Застаріле — використовуйте вкладку «Zadarma Integration» з кількома ext-нами.',
    )

    zadarma_extension_ids = fields.One2many(
        'res.users.zadarma.extension', 'user_id', string='Zadarma SIP розширення'
    )
    zadarma_primary_extension = fields.Char(
        string='Основний ext (Zadarma)',
        compute='_compute_zadarma_primary_extension',
        store=True,
        help='Використовується для click-to-call із Odoo. Обчислюється з первинного активного розширення.',
    )

    # Data-driven row-color slot for this manager's calls in the Zadarma call
    # list (zadarma.call.color / color_tag, see models/zadarma_call.py
    # _compute_color). Deliberately a small fixed enum — not a free color
    # picker — because each slot maps to a pre-defined kanban color +
    # matching SCSS rule (static/src/scss/zadarma_list.scss). No manager
    # identity is hardcoded in code; this field is the single source of
    # truth and is configured per deployment in Settings → Users.
    zadarma_manager_slot = fields.Selection(
        [
            ('1', 'Слот 1'),
            ('2', 'Слот 2'),
            ('3', 'Слот 3'),
        ],
        string='Колір у списку дзвінків Zadarma',
        help='Візуальне маркування рядків zadarma.call, де цей користувач є '
        'відповідальним менеджером. Не впливає на права доступу — лише UI.',
    )

    @api.depends(
        'zadarma_extension_ids.is_primary',
        'zadarma_extension_ids.internal',
        'zadarma_extension_ids.active',
    )
    def _compute_zadarma_primary_extension(self):
        for u in self:
            active_ext = u.zadarma_extension_ids.filtered('active')
            primary = active_ext.filtered('is_primary')[:1] or active_ext[:1]
            u.zadarma_primary_extension = primary.internal if primary else False
