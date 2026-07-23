from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    zadarma_api_key = fields.Char(string='Zadarma Key')
    zadarma_api_secret = fields.Char(string='Zadarma Secret')
    zadarma_callerid_rules = fields.Text(
        string='CallerID Rules',
        help='Одне правило на рядок: PREFIX:CALLERID\nПриклад:\n380:+380001112233\n48:+48001112233',
    )
    # Fallback assignee for a missed-call `mail.activity` when the caller has
    # no `partner.user_id` yet (see controllers/webhook.py
    # _create_missed_call_activity). Deliberately a DB-configured field, not
    # a hardcoded login — see NOTICE.md "Data hygiene".
    zadarma_missed_call_fallback_user_id = fields.Many2one(
        'res.users',
        string='Менеджер за замовчуванням (пропущені)',
        help='Кому призначати activity «Передзвонити», якщо контакт ще не '
        'має відповідального менеджера. Порожньо → base.user_admin.',
    )
