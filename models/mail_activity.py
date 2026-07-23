"""Inherit `mail.activity` to add Zadarma call back-reference (PR #7 of evening TZ).

Backref `zadarma_call_id` гарантує idempotency missed-call activity:
webhook check before create → якщо вже існує — skip. ondelete='set null'
щоб видалення `zadarma.call` не каскадно зносило activity (вона має
свою цінність як TODO для менеджера).
"""

from odoo import fields, models


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    zadarma_call_id = fields.Many2one(
        'zadarma.call',
        string='Zadarma Call',
        ondelete='set null',
        index=True,
        help='Back-reference to the Zadarma call that triggered this activity '
        '(used for idempotency of webhook-created missed-call follow-ups).',
    )
