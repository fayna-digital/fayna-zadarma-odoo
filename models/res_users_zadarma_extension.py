from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResUsersZadarmaExtension(models.Model):
    """N:1 mapping — a user may own multiple Zadarma SIP extensions (e.g.
    `100` desktop + `103` mobile). The webhook resolves an incoming SIP/ext
    number to the owning user via this table, while click-to-call from Odoo
    uses the user's primary extension."""

    _name = 'res.users.zadarma.extension'
    _description = 'Zadarma SIP extension assigned to user'
    _order = 'user_id, is_primary desc, internal'
    _rec_name = 'internal'

    user_id = fields.Many2one(
        'res.users', required=True, ondelete='cascade', index=True, string='Користувач'
    )
    internal = fields.Char(
        required=True,
        index=True,
        string='SIP ext',
        help='Внутрішній номер у Zadarma (наприклад, 104)',
    )
    label = fields.Char(string='Пристрій', help='Напр. "Мобільний", "MicroSIP desktop"')
    is_primary = fields.Boolean(
        string='Основний',
        help='Використовується для click-to-call із Odoo. Тільки один на користувача.',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', default=lambda s: s.env.company, required=True, index=True
    )

    _sql_constraints = [
        (
            'uniq_internal_per_company',
            'unique(internal, company_id)',
            'Цей SIP ext вже привʼязаний до іншого користувача в цій компанії.',
        ),
    ]

    @api.constrains('is_primary', 'user_id')
    def _check_single_primary(self):
        for ext in self:
            if not ext.is_primary:
                continue
            other = self.search(
                [
                    ('user_id', '=', ext.user_id.id),
                    ('is_primary', '=', True),
                    ('id', '!=', ext.id),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(
                    _(
                        'Користувач %(user)s вже має основний ext %(other)s. Зніміть позначку перед призначенням нового.'
                    )
                    % {'user': ext.user_id.display_name, 'other': other.internal}
                )
