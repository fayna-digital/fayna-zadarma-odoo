from __future__ import annotations

import base64
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import requests
from odoo import _, api, fields, models

from ..lib import zadarma_client

_logger = logging.getLogger(__name__)

# Zadarma SIP extension numbers are short internal numbers (e.g. 100-105).
# Mirrors INTERNAL_NUMBER_MAX_LENGTH in webhook.py + zadarma_import.py.
_INTERNAL_NUMBER_MAX_LENGTH = 5

# Color mapping verified against Odoo 17 source:
#   addons/web/static/src/core/colorlist/colorlist.js (ColorList.COLORS)
#   + addons/web/static/src/scss/secondary_variables.scss ($o-colors)
# 1=Red, 2=Orange, 3=Yellow, 4=Cyan, 5=Purple, 6=Almond, 7=Teal, 8=Blue,
# 9=Raspberry, 10=Green, 11=Violet.
_COLOR_SPAM = 1  # Red — phone matches phone.blacklist
_COLOR_VOICEMAIL = 3  # Yellow — any non-answered call
_COLOR_ANSWERED_NO_OWNER = 5  # Purple — answered without user_id

# Manager row-color slot → Odoo kanban color index. The slot itself is a
# per-user Selection field (res.users.zadarma_manager_slot, see
# models/res_users.py) configured in Settings — nothing manager-specific is
# hardcoded here, so this table only ever needs to grow if more slots are
# added, never edited per deployment/client.
_COLOR_BY_MANAGER_SLOT = {'1': 4, '2': 10, '3': 8}  # Cyan / Green / Blue

# Tag keys for list-view widget=badge / decoration-* conditions. Each of the
# 3 category tags maps 1:1 to a kanban color above; manager tags are derived
# from `_COLOR_BY_MANAGER_SLOT`'s keys as `manager_<slot>`.
_TAG_SPAM = 'spam'
_TAG_VOICEMAIL = 'voicemail'
_TAG_ORPHAN = 'orphan'
_TAG_MANAGER_PREFIX = 'manager_'

# Zadarma API rate limit (docs: zadarma.com/en/support/api/#api_limits):
# 100 req/min account-wide. Rate-limit can return EITHER HTTP 429 OR HTTP 200
# with body `{"status":"error","message":"... rate limit ..."}` — both must
# be handled (see `zadarma_client.is_rate_limited`).
_API_CALL_SPACING = 1.0  # seconds between calls in batch loops (60/min < 100/min cap)
_API_MAX_RETRIES = 3
_API_BACKOFF = (1, 2, 4, 8, 16, 30)  # exp-backoff seconds per retry attempt

# Whitelist of Zadarma `disposition` values accepted by the `status`
# Selection field. Any unknown value (e.g. a future Zadarma addition) is
# logged and stored as `failed` to avoid a ValueError on write.
_STATUS_WHITELIST = frozenset({'answered', 'no answer', 'cancel', 'call failed', 'busy', 'failed'})
_STATUS_FALLBACK = 'failed'


class ZadarmaCall(models.Model):
    _name = 'zadarma.call'
    _description = 'Zadarma Call'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc'
    _sql_constraints = [
        (
            'call_id_uniq',
            'UNIQUE(call_id)',
            'Дзвінок з таким Call ID вже існує.',
        ),
    ]

    name = fields.Char(string='Заголовок', compute='_compute_name', store=True)
    call_id = fields.Char(string='Call ID', index=True, readonly=True)
    date_start = fields.Datetime(string='Дата початку', readonly=True, index=True)
    phone_number = fields.Char(string='Номер телефону', index=True, readonly=True)
    direction = fields.Selection(
        [('inbound', 'Вхідний'), ('outbound', 'Вихідний')],
        string='Тип',
        readonly=True,
        index=True,
    )
    duration = fields.Integer(string='Тривалість (сек)', readonly=True)
    duration_display = fields.Char(
        string='Тривалість', compute='_compute_duration_display', store=True
    )
    status = fields.Selection(
        [
            ('answered', 'Відповів'),
            ('no answer', 'Без відповіді'),
            ('cancel', 'Скасовано'),
            ('call failed', "Помилка з'єднання"),
            ('busy', 'Зайнято'),
            ('failed', 'Невдалий'),
        ],
        string='Статус',
        readonly=True,
        index=True,
    )
    partner_id = fields.Many2one('res.partner', string='Контакт', readonly=True)
    lead_id = fields.Many2one('crm.lead', string='Лід', readonly=True)
    user_id = fields.Many2one('res.users', string='Відповідальний', readonly=True, index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Компанія',
        default=lambda self: self.env.company,
        index=True,
        readonly=True,
    )
    recording_url = fields.Char(string='Запис розмови', readonly=True)
    color = fields.Integer(
        string='Color Index',
        compute='_compute_color',
        store=True,
        help='Kanban color tag — 0=neutral, 1=red(spam), 3=yellow(voicemail), '
        '5=purple(answered no owner), or the color configured on the manager '
        '(res.users.zadarma_manager_slot).',
    )
    color_tag = fields.Selection(
        [
            (_TAG_SPAM, 'Спам'),
            (_TAG_VOICEMAIL, 'Голос. пошта'),
            (_TAG_ORPHAN, 'Без власника'),
            (f'{_TAG_MANAGER_PREFIX}1', 'Менеджер (слот 1)'),
            (f'{_TAG_MANAGER_PREFIX}2', 'Менеджер (слот 2)'),
            (f'{_TAG_MANAGER_PREFIX}3', 'Менеджер (слот 3)'),
        ],
        string='Тег',
        compute='_compute_color',
        store=True,
        help='Кольоровий тег для list view (widget=badge). '
        'Обчислюється разом із полем color у _compute_color.',
    )

    @api.depends('phone_number', 'date_start')
    def _compute_name(self):
        for record in self:
            date_str = (
                record.date_start.strftime('%Y-%m-%d %H:%M') if record.date_start else _('Н/Д')
            )
            record.name = _('Дзвінок %(phone)s (%(date)s)') % {
                'phone': record.phone_number,
                'date': date_str,
            }

    @api.depends('duration')
    def _compute_duration_display(self):
        for r in self:
            s = max(int(r.duration or 0), 0)
            h, rem = divmod(s, 3600)
            m, sec = divmod(rem, 60)
            r.duration_display = f'{h:d}:{m:02d}:{sec:02d}' if h else f'{m:02d}:{sec:02d}'

    @api.depends('status', 'direction', 'user_id', 'user_id.zadarma_manager_slot', 'phone_number')
    def _compute_color(self) -> None:
        """Compute kanban color tag in priority order:
        spam → voicemail → answered-no-owner → manager slot → neutral.

        Batch-loads phone.blacklist matches for performance (1 SQL per recordset
        replace per-record lookups).
        """
        # Batch phone.blacklist lookup by 9-digit suffix (forgiving for
        # different formats: +48xxx vs 48xxx vs 0048xxx).
        suffixes_by_id = {}
        for r in self:
            if r.phone_number:
                digits = re.sub(r'\D', '', r.phone_number)
                if digits:
                    suffixes_by_id[r.id] = digits[-9:]
        blocked_suffixes = set()
        if suffixes_by_id:
            unique_suffixes = set(suffixes_by_id.values())
            bl_rows = self.env['phone.blacklist'].sudo().search([('active', '=', True)])
            for entry in bl_rows:
                entry_digits = re.sub(r'\D', '', entry.number or '')[-9:]
                if entry_digits and entry_digits in unique_suffixes:
                    blocked_suffixes.add(entry_digits)
        for r in self:
            suffix = suffixes_by_id.get(r.id)
            if suffix and suffix in blocked_suffixes:
                r.color = _COLOR_SPAM
                r.color_tag = _TAG_SPAM
                continue
            # Any non-answered call is "missed" regardless of direction —
            # cancel / no answer / busy / call failed / failed all qualify.
            # Has priority over the per-manager color so missed outbound by
            # a known manager still shows yellow.
            if r.status and r.status != 'answered':
                r.color = _COLOR_VOICEMAIL
                r.color_tag = _TAG_VOICEMAIL
                continue
            if r.status == 'answered' and not r.user_id:
                r.color = _COLOR_ANSWERED_NO_OWNER
                r.color_tag = _TAG_ORPHAN
                continue
            slot = r.user_id.zadarma_manager_slot if r.user_id else False
            if slot in _COLOR_BY_MANAGER_SLOT:
                r.color = _COLOR_BY_MANAGER_SLOT[slot]
                r.color_tag = f'{_TAG_MANAGER_PREFIX}{slot}'
            else:
                r.color = 0
                r.color_tag = False

    @api.model
    def _normalize_status(self, raw: str | None) -> str | bool:
        """Normalize Zadarma `disposition` value to whitelisted Selection key.

        Гарантує що value завжди можна записати у Selection-поле `status`
        без ValueError. Якщо API повертає новий невідомий статус — пишемо
        у лог warning + fallback на 'failed' (зберігаємо інформацію про
        дзвінок, не блокуємо webhook/import).

        :param raw: сирий рядок з Zadarma API (може бути None/'' /невідомий)
        :return: ключ Selection або False (для null)
        """
        normalized = zadarma_client.normalize_status(raw, _STATUS_WHITELIST, _STATUS_FALLBACK)
        if raw and normalized == _STATUS_FALLBACK and str(raw).strip().lower() != _STATUS_FALLBACK:
            _logger.warning(
                'Zadarma: unknown disposition value %r — falling back to %r. '
                'Add to _STATUS_WHITELIST in zadarma_call.py if it is a valid status.',
                raw,
                _STATUS_FALLBACK,
            )
        return normalized

    @api.model
    def _find_user_for_sip(self, sip: str | None) -> models.Model:
        """Resolve SIP extension number to owning res.users via the multi-ext
        mapping table. Shared by webhook + import."""
        if not sip:
            return self.env['res.users'].sudo().browse()
        ext = (
            self.env['res.users.zadarma.extension']
            .sudo()
            .search([('internal', '=', str(sip).strip()), ('active', '=', True)], limit=1)
        )
        return ext.user_id if ext else self.env['res.users'].sudo().browse()

    @api.model
    def _normalize_phone(self, phone: str | None) -> str:
        """Strip non-digits. Shared canonical normalization for webhook+import+orphan re-match."""
        return zadarma_client.normalize_phone(phone)

    @api.model
    def _find_partner_by_phone(self, norm_phone: str) -> models.Model:
        """Find one partner by phone-suffix (last 9 digits) using native Odoo
        phone/mobile fields. Active partners take priority over archived (via
        active_test=False + ORDER BY active DESC). Logs WARNING if matched
        record is archived. Returns empty browse() if no match.
        """
        if not norm_phone:
            return self.env['res.partner'].sudo().browse()
        suffix = norm_phone[-9:] if len(norm_phone) >= 9 else norm_phone
        if not suffix:
            return self.env['res.partner'].sudo().browse()
        # Use raw SQL for performance and to preserve active DESC ordering.
        # regexp_replace on the stored phone/mobile columns gives the same
        # digit-only suffix match without requiring the kw_phone_search module.
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
            return self.env['res.partner'].sudo().browse()
        partner_id, is_active = row
        if not is_active:
            _logger.warning(
                'Zadarma orphan re-match: matched ARCHIVED partner id=%s for phone suffix %s',
                partner_id,
                suffix,
            )
        return self.env['res.partner'].sudo().browse(partner_id)

    @api.model
    def _find_existing_lead(self, partner: models.Model, norm_phone: str) -> models.Model:
        """Find one open lead/opportunity by partner or phone-suffix. Shared between webhook + import."""
        lead_model = self.env['crm.lead'].sudo()
        if partner:
            lead = lead_model.search(
                [
                    ('partner_id', '=', partner.id),
                    ('type', 'in', ('lead', 'opportunity')),
                    ('probability', '<', 100),
                ],
                limit=1,
            )
            if lead:
                return lead
        if norm_phone:
            suffix = norm_phone[-9:]
            lead = lead_model.search(
                [
                    ('phone', 'ilike', suffix),
                    ('type', 'in', ('lead', 'opportunity')),
                    ('probability', '<', 100),
                ],
                order='create_date desc',
                limit=1,
            )
            if lead:
                return lead
        return lead_model.browse()

    # --- Recording helpers -------------------------------------------------
    # Verified on prod 2026-05-25: `/v1/pbx/record/request/` accepts `call_id`
    # alone (statistics format `<unix>.<id>`); `pbx_call_id` is optional.
    # Response uses `link` (single) for call_id-only or `links` (array) for
    # both/pbx_call_id-only — handle both.

    @api.model
    def _zadarma_fetch_recording_url(
        self, call_id: str, pbx_call_id: str | None = None
    ) -> str | None:
        company = self.env['res.company'].sudo().search([('zadarma_api_key', '!=', False)], limit=1)
        if not company:
            _logger.warning('Zadarma: no company with API credentials found')
            return None
        key, secret = company.zadarma_api_key, company.zadarma_api_secret
        if not key or not secret:
            _logger.warning('Zadarma: API key/secret missing on company %s', company.name)
            return None
        method = '/v1/pbx/record/request/'
        params: dict[str, Any] = {'call_id': call_id}
        if pbx_call_id:
            params['pbx_call_id'] = pbx_call_id
        qs, sig = zadarma_client.compute_signature(secret, method, params)
        url = f'https://api.zadarma.com{method}?{qs}'
        headers = {'Authorization': f'{key}:{sig}'}
        for attempt in range(_API_MAX_RETRIES + 1):
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                data = resp.json() if 'json' in resp.headers.get('content-type', '') else {}
            except requests.RequestException as e:
                _logger.error('Zadarma: HTTP error for %s: %s', call_id, e)
                return None
            if zadarma_client.is_rate_limited(resp.status_code, data):
                sleep_s = _API_BACKOFF[min(attempt, len(_API_BACKOFF) - 1)]
                _logger.warning(
                    'Zadarma rate-limit hit (attempt %s/%s) for %s — sleep %ss',
                    attempt + 1,
                    _API_MAX_RETRIES + 1,
                    call_id,
                    sleep_s,
                )
                time.sleep(sleep_s)
                continue
            if data.get('status') != 'success':
                _logger.info(
                    'Zadarma: record/request non-success for %s: %s',
                    call_id,
                    data.get('message'),
                )
                return None
            links = data.get('links') or []
            return links[0] if links else data.get('link')
        _logger.warning('Zadarma: gave up on %s after %s retries', call_id, _API_MAX_RETRIES)
        return None

    def _zadarma_download_recording(self, temp_url: str | None) -> str | None:
        """Download MP3 from temp Zadarma URL into ir.attachment, return permanent URL."""
        self.ensure_one()
        if not temp_url:
            return None
        # Reuse existing attachment if any
        existing = (
            self.env['ir.attachment']
            .sudo()
            .search(
                [
                    ('res_model', '=', self._name),
                    ('res_id', '=', self.id),
                    ('mimetype', '=', 'audio/mpeg'),
                ],
                limit=1,
            )
        )
        if existing:
            return f'/web/content/{existing.id}?download=true'
        try:
            resp = requests.get(temp_url, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            _logger.error('Zadarma: download MP3 failed for call %s: %s', self.id, e)
            return temp_url  # fallback to temp URL
        attachment = (
            self.env['ir.attachment']
            .sudo()
            .create(
                {
                    'name': f'call_{self.call_id or self.id}.mp3',
                    'datas': base64.b64encode(resp.content).decode(),
                    'res_model': self._name,
                    'res_id': self.id,
                    'mimetype': 'audio/mpeg',
                }
            )
        )
        _logger.info(
            'Zadarma: Downloaded recording for call %s (id=%s, %d bytes)',
            self.call_id,
            self.id,
            len(resp.content),
        )
        return f'/web/content/{attachment.id}?download=true'

    def action_recover_recording(self):
        """Manual button: re-attempt recording fetch for selected calls.

        Paces ~1 req/sec to stay under Zadarma's 100 req/min global rate-limit.
        Each fetch also retries internally on rate-limit response (see
        _zadarma_fetch_recording_url).
        """
        recovered = 0
        pending = [
            c
            for c in self
            if c.call_id and not (c.recording_url and c.recording_url.startswith('/web/content/'))
        ]
        for idx, call in enumerate(pending):
            temp_url = self._zadarma_fetch_recording_url(call.call_id)
            if temp_url:
                permanent = call._zadarma_download_recording(temp_url)
                if permanent:
                    call.sudo().write({'recording_url': permanent})
                    recovered += 1
            if idx + 1 < len(pending):
                time.sleep(_API_CALL_SPACING)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Zadarma',
                'message': _('Відновлено записів: %(done)s з %(total)s')
                % {'done': recovered, 'total': len(self)},
                'sticky': False,
            },
        }

    @api.model
    def cron_recover_missing_recordings(self, days: int = 60, limit: int = 100) -> None:
        """Scheduled: fetch recordings for answered calls that have no MP3 yet."""
        cutoff = datetime.now() - timedelta(days=days)
        candidates = self.sudo().search(
            [
                ('recording_url', 'in', [False, '']),
                ('status', '=', 'answered'),
                ('duration', '>', 0),
                ('date_start', '>=', cutoff),
                ('call_id', '!=', False),
            ],
            order='date_start desc',
            limit=limit,
        )
        _logger.info('Zadarma cron: %d candidates for recording recovery', len(candidates))
        candidates.action_recover_recording()

    # --- user_id backfill (PR #5) ------------------------------------------
    # 488 outbound calls (з 1201, 2026-05-25) мають user_id=NULL — створені
    # до multi-ext mapping (PR #4). Statistics API `/v1/statistics/pbx/`
    # повертає `sip = <ext>` для outbound — той самий source-of-truth,
    # який webhook NOTIFY_OUT_END використовує (field `internal`). Cron
    # групує candidates по date (для мінімізації API calls), тягне stats
    # на кожну унікальну дату paginated, build call_id→sip mapping,
    # резолвить через існуючий `_find_user_for_sip`.

    @api.model
    def _zadarma_get_stats(self, date_str: str) -> list[dict[str, Any]]:
        """Fetch ALL Zadarma /v1/statistics/pbx/ rows for a UTC date (YYYY-MM-DD), paginated.

        Returns list of stats dicts (each containing call_id, sip, disposition,
        seconds, callstart, destination, is_recorded, etc.). Honors 100 req/min
        rate-limit through `zadarma_client.is_rate_limited` + exponential backoff.
        """
        company = self.env['res.company'].sudo().search([('zadarma_api_key', '!=', False)], limit=1)
        if not company:
            _logger.warning('Zadarma: no company with API credentials found')
            return []
        key, secret = company.zadarma_api_key, company.zadarma_api_secret
        if not key or not secret:
            _logger.warning('Zadarma: API key/secret missing on company %s', company.name)
            return []
        method = '/v1/statistics/pbx/'
        all_stats: list[dict[str, Any]] = []
        skip = 0
        page_size = 1000
        while True:
            params: dict[str, Any] = {
                'start': f'{date_str} 00:00:00',
                'end': f'{date_str} 23:59:59',
                'skip': skip,
                'limit': page_size,
            }
            qs, sig = zadarma_client.compute_signature(secret, method, params)
            url = f'https://api.zadarma.com{method}?{qs}'
            headers = {'Authorization': f'{key}:{sig}'}
            page_loaded = False
            for attempt in range(_API_MAX_RETRIES + 1):
                try:
                    resp = requests.get(url, headers=headers, timeout=15)
                except requests.RequestException:
                    _logger.exception(
                        'Zadarma stats fetch failed (attempt %d, date %s)', attempt, date_str
                    )
                    if attempt >= _API_MAX_RETRIES:
                        return all_stats
                    time.sleep(_API_BACKOFF[min(attempt, len(_API_BACKOFF) - 1)])
                    continue
                body = resp.json() if 'json' in resp.headers.get('content-type', '') else None
                if zadarma_client.is_rate_limited(resp.status_code, body):
                    wait = _API_BACKOFF[min(attempt, len(_API_BACKOFF) - 1)]
                    _logger.warning(
                        'Zadarma stats rate-limit (status=%s), waiting %ds...',
                        resp.status_code,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = body if body is not None else resp.json()
                stats = data.get('stats', []) or []
                all_stats.extend(stats)
                page_loaded = True
                if len(stats) < page_size:
                    return all_stats
                skip += page_size
                time.sleep(_API_CALL_SPACING)
                break
            if not page_loaded:
                return all_stats

    def action_recover_user_id(self):
        """Manual button + server action: backfill user_id for outbound calls.

        Групує `self` по `date_start::date`, для кожної унікальної дати
        тягне всю Zadarma stats payload, мапить call_id→sip, резолвить
        sip→user через існуючий `_find_user_for_sip` (multi-ext mapping
        table). Pace ~1 sec між API-викликами щоб не перевищити 100/min
        глобальний rate-limit Zadarma.

        Idempotent: domain `('user_id','=',False)` гарантує що повторний
        прохід не торкне вже заповнених рядків.
        """
        pending = self.filtered(
            lambda c: c.call_id and c.direction == 'outbound' and not c.user_id and c.date_start
        )
        if not pending:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Zadarma',
                    'message': _('Немає кандидатів для перематчингу.'),
                    'sticky': False,
                },
            }

        dates_to_calls = defaultdict(list)
        for call in pending:
            date_str = call.date_start.strftime('%Y-%m-%d')
            dates_to_calls[date_str].append(call)

        recovered = 0
        unresolved = 0
        unique_dates = sorted(dates_to_calls.keys())
        for idx, date_str in enumerate(unique_dates):
            try:
                stats_rows = self._zadarma_get_stats(date_str)
            # RequestException: raise_for_status()/timeout not already retried
            # inside _zadarma_get_stats. ValueError: malformed JSON body.
            # Caught here (not re-raised) so one bad date doesn't abort the
            # whole multi-date backfill — the cron simply retries tomorrow.
            except (requests.RequestException, ValueError):
                _logger.exception('Zadarma backfill: stats fetch failed for date %s', date_str)
                if idx + 1 < len(unique_dates):
                    time.sleep(_API_CALL_SPACING)
                continue

            # Build call_id → sip mapping. Stats include both inbound and
            # outbound rows — skip inbound (sip > 5 digits = external caller).
            sip_by_call = {}
            for row in stats_rows:
                cid = row.get('call_id')
                sip = str(row.get('sip', '') or '').strip()
                if not cid or not sip:
                    continue
                if len(re.sub(r'\D', '', sip)) > _INTERNAL_NUMBER_MAX_LENGTH:
                    continue
                sip_by_call[cid] = sip

            for call in dates_to_calls[date_str]:
                sip = sip_by_call.get(call.call_id)
                if not sip:
                    unresolved += 1
                    continue
                user = self._find_user_for_sip(sip)
                if user:
                    call.sudo().write({'user_id': user.id})
                    recovered += 1
                else:
                    _logger.info(
                        'Zadarma backfill: no user for sip=%s call_id=%s',
                        sip,
                        call.call_id,
                    )
                    unresolved += 1

            if idx + 1 < len(unique_dates):
                time.sleep(_API_CALL_SPACING)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Zadarma',
                'message': _(
                    'Перематчено менеджерів: %(done)s з %(total)s (не знайдено в stats: %(missing)s)'
                )
                % {'done': recovered, 'total': len(pending), 'missing': unresolved},
                'sticky': False,
            },
        }

    @api.model
    def cron_recover_missing_user_ids(self, days: int = 60, limit: int = 100) -> None:
        """Scheduled: backfill user_id for outbound calls (per PR #5)."""
        cutoff = datetime.now() - timedelta(days=days)
        candidates = self.sudo().search(
            [
                ('user_id', '=', False),
                ('direction', '=', 'outbound'),
                ('date_start', '>=', cutoff),
                ('call_id', '!=', False),
                # Filter to statistics-format call_ids (format: <unix>.<id>)
                # — webhook UUIDs не матчать `like '%.%'`, бо stats API
                # повертає тільки цей формат.
                ('call_id', 'like', '%.%'),
            ],
            order='date_start desc',
            limit=limit,
        )
        _logger.info('Zadarma cron: %d candidates for user_id backfill', len(candidates))
        candidates.action_recover_user_id()

        # Inbound (no SIP from Zadarma) + missed outbound → fall back to the
        # contact's salesperson so missed-call activities go to the right owner.
        inbound_candidates = self.sudo().search(
            [
                ('user_id', '=', False),
                '|',
                ('partner_id.user_id', '!=', False),
                ('lead_id.user_id', '!=', False),
                ('date_start', '>=', cutoff),
            ],
            order='date_start desc',
            limit=limit,
        )
        _logger.info(
            'Zadarma cron: %d candidates for partner.user_id fallback', len(inbound_candidates)
        )
        inbound_candidates.action_backfill_user_id_from_partner()

    def action_backfill_user_id_from_partner(self):
        """Backfill user_id from partner.user_id (or lead.user_id) for calls
        without an owner. Used for inbound no-answer/cancel where Zadarma
        provides no SIP — the contact's salesperson should still see the
        missed call.
        """
        updated = 0
        for call in self:
            if call.user_id:
                continue
            user = False
            if call.partner_id and call.partner_id.user_id:
                user = call.partner_id.user_id
            elif call.lead_id and call.lead_id.user_id:
                user = call.lead_id.user_id
            if user:
                call.sudo().write({'user_id': user.id})
                updated += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Zadarma',
                'message': _('Backfill з partner.user_id: %(done)s з %(total)s')
                % {'done': updated, 'total': len(self)},
                'sticky': False,
            },
        }

    # --- Orphan partner re-match (PR #6) -----------------------------------
    # `zadarma.call` запис може опинитися без partner_id, якщо webhook
    # відпрацював коли клієнт ще не був контактом у БД. Пізніше партнера
    # створюють вручну / Meta webhook — і виклик стає "zombie". Cron нижче
    # періодично шукає такі записи й під'єднує до існуючого партнера.

    def action_rematch_orphan(self):
        """Manual button + server action: re-attach orphan zadarma.call to existing partner."""
        rematched = 0
        for call in self:
            if call.partner_id:
                continue
            norm = self._normalize_phone(call.phone_number)
            if not norm or len(norm) < 6:
                continue
            partner = self._find_partner_by_phone(norm)
            if not partner:
                continue
            call.sudo().write({'partner_id': partner.id})
            rematched += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Zadarma',
                'message': _("Прив'язано до партнера: %(done)s з %(total)s")
                % {'done': rematched, 'total': len(self)},
                'sticky': False,
            },
        }

    @api.model
    def cron_rematch_orphan_calls(self, days: int = 30, limit: int = 200) -> None:
        """Scheduled: re-attach orphan zadarma.call records to partner via phone search."""
        cutoff = datetime.now() - timedelta(days=days)
        orphans = self.sudo().search(
            [
                ('partner_id', '=', False),
                ('phone_number', '!=', False),
                ('date_start', '>=', cutoff),
            ],
            order='date_start desc',
            limit=limit,
        )
        _logger.info('Zadarma cron: %d orphan calls candidates for partner re-match', len(orphans))
        orphans.action_rematch_orphan()
