from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    zadarma_call_ids = fields.One2many('zadarma.call', 'partner_id', string='Zadarma Calls')
    zadarma_call_count = fields.Integer(compute='_compute_zadarma_call_count')

    @api.depends('zadarma_call_ids')
    def _compute_zadarma_call_count(self):
        for record in self:
            record.zadarma_call_count = len(record.zadarma_call_ids)

    def action_view_zadarma_calls(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Дзвінки Zadarma'),
            'res_model': 'zadarma.call',
            'view_mode': 'tree,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    zadarma_call_ids = fields.One2many('zadarma.call', 'lead_id', string='Zadarma Calls')
    zadarma_call_count = fields.Integer(compute='_compute_zadarma_call_count')

    @api.depends('zadarma_call_ids')
    def _compute_zadarma_call_count(self):
        for record in self:
            record.zadarma_call_count = len(record.zadarma_call_ids)

    def action_view_zadarma_calls(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Дзвінки Zadarma'),
            'res_model': 'zadarma.call',
            'view_mode': 'tree,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id},
        }
