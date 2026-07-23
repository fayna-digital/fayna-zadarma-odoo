from __future__ import annotations

import logging

import requests
from odoo import _, api, fields, models

from ..lib import zadarma_client

_logger = logging.getLogger(__name__)


class ZadarmaDashboard(models.TransientModel):
    _name = 'zadarma.dashboard'
    _description = 'Zadarma & TurboSMS Dashboard'

    zadarma_balance = fields.Char(string='Баланс Zadarma', readonly=True)
    turbosms_balance = fields.Char(string='Баланс TurboSMS', readonly=True)

    @api.model
    def _get_zadarma_balance(self) -> str:
        company = self.env.company
        key = company.zadarma_api_key
        secret = company.zadarma_api_secret
        if not (key and secret):
            return _('API не налаштовано')
        method = '/v1/info/balance/'
        qs, sig = zadarma_client.compute_signature(secret, method, {})
        url = f'https://api.zadarma.com{method}'
        if qs:
            url += f'?{qs}'
        try:
            resp = requests.get(
                url,
                headers={'Authorization': f'{key}:{sig}'},
                timeout=10,
            )
            data = resp.json()
        except requests.RequestException as e:
            _logger.warning('Zadarma balance error: %s', e)
            return _('Помилка: %s') % e
        if data.get('status') == 'success':
            balance = data.get('balance', '?')
            currency = data.get('currency', 'USD')
            return f'{balance} {currency}'
        return _('Помилка: %s') % data.get('message', 'unknown')

    @api.model
    def _get_turbosms_balance(self) -> str | bool:
        if 'kw.sms.provider' not in self.env:
            return _('N/A')
        provider = self.env['kw.sms.provider'].search([('state', '=', 'enabled')], limit=1)
        if not provider or not provider.turbosms_token:
            return _('Не налаштовано')
        try:
            resp = requests.post(
                'https://api.turbosms.ua/user/balance.json',
                headers={
                    'Authorization': f'Basic {provider.turbosms_token}',
                    'Content-Type': 'application/json',
                },
                json={},
                timeout=10,
            )
            data = resp.json()
        except requests.RequestException as e:
            _logger.warning('TurboSMS balance error: %s', e)
            return False
        if data.get('response_code') == 0:
            bal = data['response_result']['balance']
            return _('%s грн') % bal
        return _('Помилка: %s') % data.get('response_status')

    @api.model
    def open_dashboard(self):
        rec = self.create(
            {
                'zadarma_balance': self._get_zadarma_balance(),
                'turbosms_balance': self._get_turbosms_balance(),
            }
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Баланси'),
            'res_model': 'zadarma.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_refresh(self):
        self.write(
            {
                'zadarma_balance': self._get_zadarma_balance(),
                'turbosms_balance': self._get_turbosms_balance(),
            }
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Баланси'),
            'res_model': 'zadarma.dashboard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
