from __future__ import annotations

import logging

import requests
from odoo import models

from ..lib import zadarma_client

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_zadarma_call(self) -> bool:
        self.ensure_one()

        user = self.env.user
        company = self.env.company

        key = company.zadarma_api_key
        secret = company.zadarma_api_secret
        # Use primary extension from new multi-ext model; fall back to legacy
        # single Char field for users not yet migrated.
        sip_id = str(user.zadarma_primary_extension or user.zadarma_internal_number or '').strip()
        digits = ''.join(filter(str.isdigit, str(self.phone or self.mobile)))
        target = '+' + digits

        _logger.info("Zadarma call: SIP='%s', Target='%s'", sip_id, target)

        if not (key and secret and sip_id and target):
            _logger.error('Zadarma: missing key/secret/sip/phone, cancelling')
            return False

        api_method = '/v1/request/callback/'
        params = {'from': sip_id, 'to': target, 'sip': sip_id}
        query_string, signature = zadarma_client.compute_signature(secret, api_method, params)
        headers = {'Authorization': f'{key}:{signature}'}

        try:
            url = f'https://api.zadarma.com{api_method}?{query_string}'
            _logger.info('Zadarma API Call (GET): %s', url)
            response = requests.get(url, headers=headers, timeout=10)
            _logger.info('Zadarma API Result: %s', response.json())
        except requests.RequestException as e:
            _logger.error('Zadarma API Exception: %s', e)
            return False

        return True
