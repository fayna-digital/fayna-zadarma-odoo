from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from markupsafe import Markup
from odoo import SUPERUSER_ID, _, fields, http, models
from odoo.http import request

from ..lib import zadarma_client

_logger = logging.getLogger(__name__)

INTERNAL_NUMBER_MAX_LENGTH = 5

# Possible HTTP headers Zadarma uses for the HMAC signature on different
# webhook versions — checked in order.
_SIGNATURE_HEADERS = ('Signature', 'X-Signature', 'Zadarma-Signature')


class ZadarmaWebhook(http.Controller):
    @http.route('/zadarma/webhook', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def zadarma_webhook(self, **kwargs: Any) -> str:
        params = request.params
        if request.httprequest.method == 'GET' and params.get('zd_echo'):
            return params.get('zd_echo')

        # HMAC verification — WARNING MODE: log mismatch but do not reject.
        # Enforcement is a follow-up once production logs confirm which
        # variant Zadarma sends consistently for this deployment.
        try:
            self._verify_signature_warning(params)
        except Exception:
            # Deliberately broad: a bug in the *observation-only* signature
            # check must never block webhook processing itself.
            _logger.exception('Zadarma webhook: signature verification error (non-blocking)')

        _logger.info(
            'Zadarma webhook received: event=%s, params=%s', params.get('event'), dict(params)
        )

        event = params.get('event')
        try:
            if event == 'NOTIFY_END':
                self._process_call_end(params)
            elif event == 'NOTIFY_OUT_END':
                self._process_outbound_call_end(params)
            elif event == 'NOTIFY_RECORD':
                self._process_notify_record(params)
        except Exception:
            # Deliberately broad: Zadarma retries on non-200, and any
            # unhandled error here must still surface via logs rather than
            # trigger a webhook retry-storm — see docs/RUNBOOK.md.
            _logger.exception('Zadarma webhook processing error (event=%s)', event)

        return 'OK'

    def _verify_signature_warning(self, params: dict[str, Any]) -> None:
        """Compute both known Zadarma webhook signature variants and log
        which (if any) matches the incoming `Signature` header.

        Both variants are documented across different versions of the
        Zadarma docs; one prod webhook will match exactly one. Does NOT
        raise — observation only (see `zadarma_client.verify_webhook_signature`).
        """
        signature = None
        for header_name in _SIGNATURE_HEADERS:
            signature = request.httprequest.headers.get(header_name)
            if signature:
                break
        if not signature:
            _logger.warning(
                'Zadarma webhook: no Signature header (event=%s, ip=%s)',
                params.get('event'),
                request.httprequest.remote_addr,
            )
            return

        company = (
            request.env['res.company'].sudo().search([('zadarma_api_secret', '!=', False)], limit=1)
        )
        secret = company.zadarma_api_secret if company else None
        if not secret:
            _logger.warning('Zadarma webhook: no API secret configured — cannot verify signature')
            return

        sorted_string = '&'.join(
            f'{k}={v}' for k, v in sorted(params.items()) if k.lower() not in ('signature',)
        )
        matched_variant = zadarma_client.verify_webhook_signature(secret, sorted_string, signature)
        if matched_variant:
            _logger.info('Zadarma webhook: signature OK (variant %s)', matched_variant)
        else:
            sig_a, sig_b = zadarma_client.compute_webhook_signatures(secret, sorted_string)
            _logger.warning(
                'Zadarma webhook: signature MISMATCH (event=%s, ip=%s, got=%s..., '
                'expected A=%s... B=%s...)',
                params.get('event'),
                request.httprequest.remote_addr,
                signature[:8],
                sig_a[:8],
                sig_b[:8],
            )

    def _normalize_phone(self, phone: str | None) -> str:
        """Delegate to shared canonical helper on zadarma.call model."""
        return request.env['zadarma.call']._normalize_phone(phone)

    def _find_partner(self, norm_phone: str) -> models.Model:
        """Delegate to shared helper on zadarma.call model."""
        return request.env['zadarma.call']._find_partner_by_phone(norm_phone)

    def _find_existing_lead(self, env: Any, partner: models.Model, norm_phone: str) -> models.Model:
        """Delegate to shared helper on zadarma.call model."""
        return env['zadarma.call']._find_existing_lead(partner, norm_phone)

    def _find_user_by_sip(self, sip: str | None) -> models.Model:
        return request.env['zadarma.call']._find_user_for_sip(sip)

    def _create_missed_call_activity(
        self, zcall: models.Model, lead: models.Model, partner: models.Model
    ) -> None:
        """Create idempotent `mail.activity` "Передзвонити <phone>" for missed call.

        Idempotency: domain check on `zadarma_call_id` before create.
        Target: lead if present else partner. Assignee: partner.user_id, else
        the company's configured fallback (`res.company.
        zadarma_missed_call_fallback_user_id`), else `base.user_admin`.
        Due in 1 day.
        """
        env = request.env
        if env['mail.activity'].sudo().search_count([('zadarma_call_id', '=', zcall.id)]):
            return
        target = lead if lead else partner
        if not target:
            return
        assignee = (
            partner.user_id if partner and partner.user_id else env['res.users'].sudo().browse()
        )
        if not assignee:
            # Configured per company (Settings → Companies → Zadarma tab) —
            # no manager identity is hardcoded in code, see res_company.py.
            company = env['res.company'].sudo().search([('zadarma_api_key', '!=', False)], limit=1)
            fallback_user = company.zadarma_missed_call_fallback_user_id if company else None
            if fallback_user and fallback_user.active:
                assignee = fallback_user
        if not assignee:
            try:
                assignee = env.ref('base.user_admin')
            except ValueError:
                _logger.warning(
                    'Zadarma: missed-call activity skipped — no assignee available for call_id=%s',
                    zcall.call_id,
                )
                return
        activity_type = env.ref('mail.mail_activity_data_call', raise_if_not_found=False)
        if not activity_type:
            _logger.warning('Zadarma: mail.mail_activity_data_call not found — skip activity')
            return
        model = env['ir.model'].sudo()._get(target._name)
        env['mail.activity'].sudo().create(
            {
                'res_model_id': model.id,
                'res_model': target._name,
                'res_id': target.id,
                'activity_type_id': activity_type.id,
                'user_id': assignee.id,
                'summary': (_('Передзвонити %s') % (zcall.phone_number or '')).strip(),
                'note': _(
                    'Пропущений %(direction)s дзвінок (тривалість %(duration)sс). Запис: %(rec)s'
                )
                % {
                    'direction': _('вихідний') if zcall.direction == 'outbound' else _('вхідний'),
                    'duration': zcall.duration or 0,
                    'rec': zcall.recording_url or '—',
                },
                'date_deadline': fields.Date.context_today(env.user) + timedelta(days=1),
                'zadarma_call_id': zcall.id,
            }
        )

    def _post_chatter(
        self, lead, partner, direction, phone, duration, status, recording_url=None, user=None
    ):
        direction_label = _('Вихідний') if direction == 'outbound' else _('Вхідний')
        minutes, seconds = divmod(duration, 60)
        duration_str = (
            _('%(m)sхв %(s)sс') % {'m': minutes, 's': seconds}
            if minutes
            else _('%(s)sс') % {'s': seconds}
        )
        normalized = request.env['zadarma.call']._normalize_status(status)
        status_labels = dict(request.env['zadarma.call']._fields['status'].selection)
        status_label = status_labels.get(normalized, '—') if normalized else '—'
        body = Markup(
            _(
                '<b>📞 {direction} дзвінок</b><br/>'
                'Номер: {phone}<br/>'
                'Тривалість: {duration}<br/>'
                'Статус: {status}'
            )
        ).format(direction=direction_label, phone=phone, duration=duration_str, status=status_label)
        if recording_url:
            body += Markup('<br/><a href="{url}">{label}</a>').format(
                url=recording_url, label=_('Слухати запис')
            )
        chatter_target = lead if lead else partner
        if chatter_target:
            poster_uid = user.id if user else SUPERUSER_ID
            chatter_target.with_user(poster_uid).message_post(
                body=body, subtype_xmlid='mail.mt_note'
            )

    def _process_call_end(self, data):
        # Inbound PBX calls (NOTIFY_END)
        call_id = data.get('call_id') or data.get('pbx_call_id')
        if not call_id or not data.get('call_start'):
            _logger.warning(
                'Zadarma webhook: missing call_id/pbx_call_id or call_start. Payload: %s',
                dict(data),
            )
            return

        env = request.env
        is_outbound = (
            len(re.sub(r'\D', '', str(data.get('caller_id', '')))) <= INTERNAL_NUMBER_MAX_LENGTH
        )
        phone = data.get('called_did') if is_outbound else data.get('caller_id')
        direction = 'outbound' if is_outbound else 'inbound'
        sip = data.get('caller_id') if is_outbound else None

        norm_phone = self._normalize_phone(phone)
        if not norm_phone:
            _logger.warning(
                'Zadarma webhook: empty phone. caller_id=%s called_did=%s',
                data.get('caller_id'),
                data.get('called_did'),
            )
            return

        partner = self._find_partner(norm_phone)
        user = self._find_user_by_sip(sip) if sip else env['res.users'].sudo().browse()

        lead = self._find_existing_lead(env, partner, norm_phone)
        is_answered = data.get('disposition') == 'answered'

        if not partner and not lead:
            lead = (
                env['crm.lead']
                .sudo()
                .create(
                    {
                        'name': _('Дзвінок: %s') % phone,
                        'contact_name': phone,
                        'phone': phone,
                    }
                )
            )
        elif is_answered and partner and not lead:
            # Answered call with a known partner but no open lead → create one
            # so the conversation outcome is tracked in CRM, not lost.
            lead = (
                env['crm.lead']
                .sudo()
                .create(
                    {
                        'name': _('Розмова: %s') % partner.name,
                        'partner_id': partner.id,
                        'phone': phone,
                    }
                )
            )

        # Fallback chain when SIP lookup did not yield a user (inbound no-answer
        # = missed call → assign to the contact's salesperson so they see it).
        if not user:
            if partner and partner.user_id:
                user = partner.user_id
            elif lead and lead.user_id:
                user = lead.user_id

        # First-call ownership: only on ANSWERED outbound — a brief no-answer
        # attempt should not assign the dialing manager as the partner's owner.
        if is_answered and user and partner and not partner.user_id and direction == 'outbound':
            partner.sudo().write({'user_id': user.id})

        duration = int(data.get('duration', 0))
        zcall = (
            env['zadarma.call']
            .sudo()
            .create(
                {
                    'call_id': call_id,
                    'date_start': data.get('call_start'),
                    'phone_number': phone,
                    'direction': direction,
                    'duration': duration,
                    'status': request.env['zadarma.call']._normalize_status(
                        data.get('disposition')
                    ),
                    'partner_id': partner.id if partner else False,
                    'lead_id': lead.id if lead else False,
                    'user_id': user.id if user else False,
                    'recording_url': data.get('recording'),
                }
            )
        )
        _logger.info('Zadarma: Saved %s call for %s', direction, phone)
        self._post_chatter(
            lead,
            partner,
            direction,
            phone,
            duration,
            data.get('disposition'),
            data.get('recording'),
            user=user,
        )
        # Missed inbound → "Передзвонити" activity (idempotent via zadarma_call_id).
        if direction == 'inbound' and data.get('disposition') == 'cancel':
            try:
                self._create_missed_call_activity(zcall, lead, partner)
            except Exception:
                # Deliberately broad: the call itself is already saved above;
                # a failure to create the follow-up activity must not be
                # reported as a webhook processing failure to Zadarma.
                _logger.exception(
                    'Zadarma: missed-call activity creation failed for call_id=%s', call_id
                )

    def _process_outbound_call_end(self, data):
        # Outbound calls (NOTIFY_OUT_END). Verified on prod logs 2026-04-12..05-25:
        # 347/347 events have calltype='normal', not 'callback_leg2'.
        # Payload: internal=ext (always present), destination=external phone,
        # caller_id=external CallerID (NOT ext — do not use for SIP lookup).
        call_id = data.get('pbx_call_id') or data.get('call_id')
        if not call_id or not data.get('call_start'):
            return

        env = request.env

        # Skip if already saved (can arrive with NOTIFY_END too)
        if env['zadarma.call'].sudo().search([('call_id', '=', call_id)], limit=1):
            return

        phone = self._normalize_phone(data.get('destination'))
        sip = data.get('internal')
        if not phone:
            return

        partner = self._find_partner(phone)
        user = self._find_user_by_sip(sip)

        lead = self._find_existing_lead(env, partner, phone)
        is_answered = data.get('disposition') == 'answered'

        # Auto-create lead on answered outbound when we have a partner but no
        # open lead — the conversation should leave a trace in CRM.
        if is_answered and partner and not lead:
            lead = (
                env['crm.lead']
                .sudo()
                .create(
                    {
                        'name': _('Розмова: %s') % partner.name,
                        'partner_id': partner.id,
                        'phone': phone,
                    }
                )
            )

        # Fallback chain — outbound NOTIFY_OUT_END almost always has SIP, but
        # keep the same logic for symmetry with NOTIFY_END handler.
        if not user:
            if partner and partner.user_id:
                user = partner.user_id
            elif lead and lead.user_id:
                user = lead.user_id

        # First-call ownership: only on ANSWERED outbound — a brief no-answer
        # attempt should not assign the dialing manager as the partner's owner.
        if is_answered and user and partner and not partner.user_id:
            partner.sudo().write({'user_id': user.id})

        duration = int(data.get('duration', 0))
        zcall = (
            env['zadarma.call']
            .sudo()
            .create(
                {
                    'call_id': call_id,
                    'date_start': data.get('call_start'),
                    'phone_number': phone,
                    'direction': 'outbound',
                    'duration': duration,
                    'status': request.env['zadarma.call']._normalize_status(
                        data.get('disposition')
                    ),
                    'partner_id': partner.id if partner else False,
                    'lead_id': lead.id if lead else False,
                    'user_id': user.id if user else False,
                }
            )
        )
        _logger.info('Zadarma: Saved outbound call for %s by SIP %s', phone, sip)
        self._post_chatter(
            lead, partner, 'outbound', phone, duration, data.get('disposition'), user=user
        )
        # Missed outbound → "Передзвонити" activity (idempotent via zadarma_call_id).
        if data.get('disposition') == 'cancel':
            try:
                self._create_missed_call_activity(zcall, lead, partner)
            except Exception:
                # Deliberately broad: the call itself is already saved above;
                # a failure to create the follow-up activity must not be
                # reported as a webhook processing failure to Zadarma.
                _logger.exception(
                    'Zadarma: missed-call activity creation failed for call_id=%s', call_id
                )

    def _process_notify_record(self, data):
        pbx_call_id = data.get('pbx_call_id')
        call_id_with_rec = data.get('call_id_with_rec')
        if not pbx_call_id or not call_id_with_rec:
            return
        env = request.env
        # Try webhook-format call_id first, then statistics-format (for import-created rows)
        call = env['zadarma.call'].sudo().search([('call_id', '=', pbx_call_id)], limit=1)
        if not call:
            call = env['zadarma.call'].sudo().search([('call_id', '=', call_id_with_rec)], limit=1)
        if not call:
            _logger.warning(
                'Zadarma NOTIFY_RECORD: call not found for pbx_call_id=%s call_id=%s',
                pbx_call_id,
                call_id_with_rec,
            )
            return
        temp_url = env['zadarma.call']._zadarma_fetch_recording_url(call_id_with_rec, pbx_call_id)
        if not temp_url:
            return
        permanent = call._zadarma_download_recording(temp_url)
        if permanent:
            call.sudo().write({'recording_url': permanent})
            _logger.info('Zadarma: Saved recording for call %s', pbx_call_id)
            chatter_target = call.lead_id or call.partner_id
            if chatter_target:
                poster_uid = call.user_id.id if call.user_id else SUPERUSER_ID
                chatter_target.with_user(poster_uid).message_post(
                    body=Markup(
                        _('<b>📎 Запис розмови:</b> <a href="{url}">Слухати запис</a>')
                    ).format(url=permanent),
                    subtype_xmlid='mail.mt_note',
                )
