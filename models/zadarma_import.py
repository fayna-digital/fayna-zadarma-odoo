from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from typing import Any

import requests
from markupsafe import Markup
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..lib import zadarma_client

_logger = logging.getLogger(__name__)

INTERNAL_NUMBER_MAX_LENGTH = 5


class ZadarmaImport(models.TransientModel):
    _name = 'zadarma.import'
    _description = 'Імпорт дзвінків Zadarma'

    date_from = fields.Date(
        string='Від', required=True, default=lambda self: fields.Date.today() - timedelta(days=30)
    )
    date_to = fields.Date(string='До', required=True, default=lambda self: fields.Date.today())
    result_message = fields.Text(string='Результат', readonly=True)

    def _zadarma_get(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        company = self.env.company
        key = company.zadarma_api_key
        secret = company.zadarma_api_secret
        if not key or not secret:
            raise UserError(_('Вкажіть Zadarma API Key та Secret у налаштуваннях компанії.'))
        qs, sig = zadarma_client.compute_signature(secret, method, params)
        # Zadarma may return rate-limit as HTTP 429 OR HTTP 200 with body
        # {"status":"error","message":"... rate limit ..."} — handle both.
        for attempt in range(3):
            response = requests.get(
                f'https://api.zadarma.com{method}?{qs}',
                headers={'Authorization': f'{key}:{sig}'},
                timeout=15,
            )
            body = response.json() if 'json' in response.headers.get('content-type', '') else None
            if zadarma_client.is_rate_limited(response.status_code, body):
                wait = 3 * (attempt + 1)
                _logger.warning(
                    'Zadarma API rate-limit (status=%s msg=%s), waiting %ss...',
                    response.status_code,
                    (body or {}).get('message'),
                    wait,
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            return body if body is not None else response.json()
        raise UserError(_('Zadarma API rate limit перевищено. Спробуйте через кілька хвилин.'))

    def _normalize_phone(self, phone: str | None) -> str:
        return zadarma_client.normalize_phone(phone)

    def _find_partner(self, norm_phone: str) -> models.Model:
        """Find partner by last 9 digits of phone/mobile — native Odoo fields,
        no kw_phone_search dependency. Active partners preferred over archived.
        """
        if not norm_phone:
            return self.env['res.partner'].browse()
        suffix = norm_phone[-9:] if len(norm_phone) >= 9 else norm_phone
        if not suffix:
            return self.env['res.partner'].browse()
        self.env.cr.execute(
            """
            SELECT id, active FROM res_partner
            WHERE (
                regexp_replace(COALESCE(phone,''), '[^0-9]', '', 'g') LIKE %s
                OR regexp_replace(COALESCE(mobile,''), '[^0-9]', '', 'g') LIKE %s
              )
            ORDER BY
                active DESC,
                (CASE WHEN name ~ '^[0-9 +().-]+$' THEN 1 ELSE 0 END) ASC,
                id ASC
            LIMIT 1
        """,
            [f'%{suffix}', f'%{suffix}'],
        )
        row = self.env.cr.fetchone()
        if not row:
            return self.env['res.partner'].browse()
        partner_id, is_active = row
        if not is_active:
            _logger.warning(
                'Zadarma import: matched ARCHIVED partner id=%s for phone suffix %s',
                partner_id,
                suffix,
            )
        return self.env['res.partner'].browse(partner_id)

    def action_import(self):
        self.ensure_one()
        start = f'{self.date_from} 00:00:00'
        end = f'{self.date_to} 23:59:59'

        imported = 0
        skipped = 0
        skip = 0
        limit = 1000

        while True:
            data = self._zadarma_get(
                '/v1/statistics/pbx/',
                {
                    'start': start,
                    'end': end,
                    'skip': skip,
                    'limit': limit,
                },
            )
            stats = data.get('stats', [])
            if not stats:
                break

            for call in stats:
                call_id = call.get('call_id')
                if not call_id:
                    continue

                # Skip if already in Odoo
                if self.env['zadarma.call'].sudo().search([('call_id', '=', call_id)], limit=1):
                    skipped += 1
                    continue

                sip = str(call.get('sip', ''))
                is_outbound = len(re.sub(r'\D', '', sip)) <= INTERNAL_NUMBER_MAX_LENGTH
                phone = str(call.get('destination', '')) if is_outbound else sip
                direction = 'outbound' if is_outbound else 'inbound'
                norm_phone = self._normalize_phone(phone)

                if not norm_phone:
                    continue

                partner = self._find_partner(norm_phone)
                lead = self.env['zadarma.call']._find_existing_lead(partner, norm_phone)
                # For outbound, stats API returns `sip` as the ext number — match to user.
                user = (
                    self.env['zadarma.call']._find_user_for_sip(sip)
                    if is_outbound
                    else self.env['res.users'].sudo().browse()
                )

                duration = int(call.get('seconds', 0) or call.get('billseconds', 0))
                status = self.env['zadarma.call']._normalize_status(call.get('disposition'))

                zcall = (
                    self.env['zadarma.call']
                    .sudo()
                    .create(
                        {
                            'call_id': call_id,
                            'date_start': call.get('callstart'),
                            'phone_number': phone,
                            'direction': direction,
                            'duration': duration,
                            'status': status,
                            'partner_id': partner.id if partner else False,
                            'lead_id': lead.id if lead else False,
                            'user_id': user.id if user else False,
                        }
                    )
                )

                # Fetch MP3 if Zadarma flagged the call as recorded.
                # Pace ~1 req/sec to stay under Zadarma 100/min global rate-limit.
                if str(call.get('is_recorded', '')).lower() == 'true':
                    temp_url = self.env['zadarma.call']._zadarma_fetch_recording_url(call_id)
                    if temp_url:
                        permanent = zcall._zadarma_download_recording(temp_url)
                        if permanent:
                            zcall.sudo().write({'recording_url': permanent})
                    time.sleep(1.0)

                # Post chatter note
                direction_label = _('Вихідний') if is_outbound else _('Вхідний')
                minutes, seconds = divmod(duration, 60)
                duration_str = (
                    _('%(m)sхв %(s)sс') % {'m': minutes, 's': seconds}
                    if minutes
                    else _('%(s)sс') % {'s': seconds}
                )
                status_labels = dict(self.env['zadarma.call']._fields['status'].selection)
                status_label = status_labels.get(status, '—') if status else '—'
                body = Markup(
                    _(
                        '<b>📞 {direction} дзвінок (імпорт)</b><br/>'
                        'Номер: {phone}<br/>'
                        'Тривалість: {duration}<br/>'
                        'Статус: {status}'
                    )
                ).format(
                    direction=direction_label,
                    phone=phone,
                    duration=duration_str,
                    status=status_label,
                )
                chatter_target = lead if lead else partner
                if chatter_target:
                    chatter_target.with_user(self.env.uid).message_post(
                        body=body, subtype_xmlid='mail.mt_note'
                    )

                imported += 1

            if len(stats) < limit:
                break
            skip += limit
            time.sleep(1)  # avoid rate limiting between pages

        self.result_message = _(
            'Імпортовано: %(imported)s дзвінків. Вже існували: %(skipped)s.'
        ) % {
            'imported': imported,
            'skipped': skipped,
        }
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'zadarma.import',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }
