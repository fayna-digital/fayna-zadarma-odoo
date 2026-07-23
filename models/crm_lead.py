"""Inherit `crm.lead` to add orphan re-match logic (PR #6 of evening TZ).

Webhook створює auto-лід `Дзвінок: +48xxx` (без `partner_id`) коли клієнт
телефонує а партнера ще нема. Пізніше партнера створюють вручну /
Meta webhook / імпорт — лід стає zombie. Cron нижче періодично шукає такі
ліди, прив'язує до існуючого партнера через phone-search, і якщо рівно
ОДИН інший open opp на цьому ж партнері — мерджить через стандартний
`merge_opportunity`.
"""

import logging
from datetime import datetime, timedelta

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def action_rematch_orphan(self):
        """Manual button + server action: re-attach orphan 'Дзвінок:' leads.

        Per lead in `self`:
        1. Extract phone (lead.phone OR name suffix after 'Дзвінок:').
        2. `_find_partner_by_phone` — shared helper on `zadarma.call`.
        3. If partner found → write `partner_id` on lead AND on its
           orphan `zadarma.call` rows.
        4. Smart merge: search other open opp/lead on same partner.
           - 0 → done (linked only).
           - >1 → skip merge + log (manual review).
           - ==1 → guard: ensure orphan won't become merge master via
             `_sort_by_confidence_level(reverse=True)[0]`. If guard fails,
             skip + log. Else call standard `merge_opportunity()` —
             переносить activities/attachments/messages/followers, slave
             unlink (auto_unlink=True default).
        """
        call_model = self.env['zadarma.call']
        matched = 0
        merged = 0
        skipped_multi = 0
        skipped_orphan_master = 0
        for lead in self:
            if lead.partner_id:
                continue
            raw_phone = lead.phone or ''
            if not raw_phone and lead.name and 'Дзвінок:' in lead.name:
                raw_phone = lead.name.split('Дзвінок:', 1)[1].strip()
            norm = call_model._normalize_phone(raw_phone)
            if not norm or len(norm) < 6:
                continue
            partner = call_model._find_partner_by_phone(norm)
            if not partner:
                continue
            lead.sudo().write({'partner_id': partner.id})
            # Cascade partner_id onto orphan zadarma.call rows linked via lead_id.
            call_model.sudo().search([('lead_id', '=', lead.id), ('partner_id', '=', False)]).write(
                {'partner_id': partner.id}
            )
            matched += 1
            other = self.sudo().search(
                [
                    ('partner_id', '=', partner.id),
                    ('id', '!=', lead.id),
                    ('type', 'in', ('lead', 'opportunity')),
                    ('probability', '<', 100),
                    ('active', '=', True),
                ],
                limit=2,
            )
            if len(other) > 1:
                skipped_multi += 1
                _logger.info(
                    'Zadarma orphan re-match: lead %s linked, %d open opps on partner %s — skip merge',
                    lead.id,
                    len(other),
                    partner.id,
                )
                continue
            if len(other) == 1:
                pair = lead + other
                sorted_pair = pair._sort_by_confidence_level(reverse=True)
                if sorted_pair[0] == lead:
                    skipped_orphan_master += 1
                    _logger.warning(
                        'Zadarma orphan re-match: lead %s would become merge master — skip',
                        lead.id,
                    )
                    continue
                try:
                    sorted_pair.merge_opportunity()
                    merged += 1
                except Exception:
                    _logger.exception(
                        'Zadarma orphan re-match: merge failed for leads %s + %s',
                        lead.id,
                        other.id,
                    )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Zadarma orphan re-match',
                'message': _(
                    "Прив'язано: %(matched)s; злито: %(merged)s; "
                    'пропущено (≥2 open opp): %(skipped_multi)s; '
                    'пропущено (orphan master): %(skipped_orphan_master)s'
                )
                % {
                    'matched': matched,
                    'merged': merged,
                    'skipped_multi': skipped_multi,
                    'skipped_orphan_master': skipped_orphan_master,
                },
                'sticky': False,
            },
        }

    def merge_opportunity(self, *args, **kwargs):
        """Reassign zadarma.call records to winner before Odoo deletes loser leads."""
        if len(self) > 1:
            sorted_leads = self._sort_by_confidence_level(reverse=True)
            winner = sorted_leads[0]
            losers = self - winner
            calls = self.env['zadarma.call'].sudo().search([('lead_id', 'in', losers.ids)])
            if calls:
                _logger.info(
                    'Zadarma: переносимо %d call(s) %s → lead %s перед злиттям',
                    len(calls),
                    losers.ids,
                    winner.id,
                )
                calls.write({'lead_id': winner.id})
        return super().merge_opportunity(*args, **kwargs)

    @api.model
    def cron_rematch_orphan_leads(self, days=30, limit=100):
        """Scheduled: rematch zombie 'Дзвінок:' leads to partners + smart merge."""
        cutoff = datetime.now() - timedelta(days=days)
        orphans = self.sudo().search(
            [
                ('name', 'ilike', 'Дзвінок:%'),
                ('partner_id', '=', False),
                ('probability', '<', 100),
                ('active', '=', True),
                ('create_date', '>=', cutoff),
            ],
            order='create_date desc',
            limit=limit,
        )
        _logger.info(
            'Zadarma cron: %d orphan "Дзвінок:" leads candidates for re-match', len(orphans)
        )
        orphans.action_rematch_orphan()
