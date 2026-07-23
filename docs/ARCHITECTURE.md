# Fayna Zadarma Telephony — Architecture

> Стан: **17.0.1.14.0**

## Призначення

Інтеграція хмарної АТС **Zadarma** з Odoo 17 CRM. Автологування дзвінків, MP3-записи в chatter, click-to-call, SMS, auto-lead, кольорове маркування рядків списку, фільтри як вбудована легенда.

## Ключові моделі

### `zadarma.call`

Головна модель — одна запис на дзвінок. Inherits `mail.thread` + `mail.activity.mixin`.

**Ключові поля:**

| Поле | Тип | Опис |
|------|-----|------|
| `call_id` | Char (index, UNIQUE) | Zadarma-side ID дзвінка |
| `date_start` | Datetime (index) | Початок (UTC, як Zadarma шле) |
| `phone_number` | Char (index) | Зовнішній номер партнера |
| `direction` | Selection (index) | `inbound` / `outbound` |
| `duration` | Integer | Секунди |
| `duration_display` | Char (compute, stored) | `HH:MM:SS` |
| `status` | Selection (index) | `answered` / `no answer` / `cancel` / `call failed` / `busy` / `failed` |
| `partner_id` | Many2one res.partner | Знайдений контакт |
| `lead_id` | Many2one crm.lead | Зв'язаний lead (auto-create на answered або unknown) |
| `user_id` | Many2one res.users (index) | Відповідальний менеджер (fallback chain) |
| `company_id` | Many2one res.company (index) | Для multi-company ir.rule |
| `recording_url` | Char | URL до permanent `/web/content/{id}` або temporary Zadarma URL |
| `color` | Integer (compute, stored) | Legacy kanban color, лишається для compatibility |
| `color_tag` | Selection (compute, stored) | `spam` / `voicemail` / `orphan` / `manager_1` / `manager_2` / `manager_3` |
| `message_main_attachment_id` | Many2one ir.attachment | Від `mail.thread` mixin |

**SQL constraints:**
- `UNIQUE(call_id)` — PostgreSQL-level dedup між webhook + import flow.

**Indexes** (на додачу до `call_id` / `phone_number`):
- `date_start` (використовується в `_order`)
- `status`, `direction`, `user_id`, `partner_id`

### `zadarma.import` (TransientModel)

Wizard для bulk-import історичних дзвінків через Zadarma Statistics API. Pagination skip/limit=1000, 1s spacing, exp-backoff retry.

### `zadarma.dashboard` (TransientModel)

Modal для перегляду балансів Zadarma + TurboSMS.

### `res.users.zadarma.extension`

N:1 mapping `res.users` ↔ SIP extensions. Один менеджер може мати декілька внутрішніх номерів.

### Extensions на існуючі Odoo-моделі

- `res.company` (`res_company.py`) — Zadarma credentials (`zadarma_api_key`, `zadarma_api_secret`)
- `res.users` (`res_users.py`) — legacy SIP extension (читання, для migration)
- `res.partner` / `crm.lead` (`partner_lead_ext.py`) — `zadarma_call_count` з `@api.depends('zadarma_call_ids')`, smart-button
- `crm.lead` (`crm_lead.py`) — `action_rematch_orphan` для "Дзвінок: +xxx" zombie-лідів
- `mail.activity` (`mail_activity.py`) — `zadarma_call_id` back-ref для idempotent missed-call activities

## Data flow

### Вхідний / вихідний дзвінок (webhook)

```
Клієнт ↔ Zadarma PBX
    │
    ▼
POST /zadarma/webhook (Signature header)
    │
    ▼
ZadarmaWebhook controller (controllers/webhook.py):
    │
    ├── _verify_signature_warning(params)
    │       обчислює sig_a = base64(hmac_sha1(secret, sorted_params))
    │       обчислює sig_b = base64(hmac_sha1(secret, md5(sorted_params)))
    │       логує match/mismatch (warning mode, НЕ блокує)
    │
    ├── dispatch by event:
    │
    ├── NOTIFY_END (inbound + simple outbound):
    │   ├── direction = 'outbound' if len(digits(caller_id)) ≤ 5 else 'inbound'
    │   ├── phone = called_did if outbound else caller_id
    │   ├── sip = caller_id if outbound (SIP extension)
    │   ├── partner = _find_partner_by_phone(norm) — kw_phone_cleaned LIKE %suffix%
    │   ├── user = _find_user_for_sip(sip) — через res.users.zadarma.extension
    │   ├── lead = _find_existing_lead(partner, norm) — відкритий lead
    │   │
    │   ├── Auto-create lead branches:
    │   │   ├── не знайдено ні partner ні lead → "Дзвінок: +xxx" (з phone)
    │   │   └── answered + partner + не знайдено lead → "Розмова: {partner.name}"
    │   │
    │   ├── User fallback chain:
    │   │   sip → partner.user_id → lead.user_id
    │   │
    │   ├── First-call ownership (answered + outbound):
    │   │   partner.sudo().write({'user_id': user.id})
    │   │
    │   ├── Create zadarma.call (UNIQUE на call_id)
    │   ├── _compute_color → spam | voicemail | orphan | manager | neutral
    │   ├── Post chatter на target (lead || partner)
    │   └── If missed → _create_missed_call_activity (idempotent via zadarma_call_id)
    │
    ├── NOTIFY_OUT_END (outbound з PBX-internal):
    │   └── Та сама логіка з sip = data['internal'], phone = data['destination']
    │
    └── NOTIFY_RECORD:
        ├── _zadarma_fetch_recording_url(call_id, pbx_call_id) → temporary URL
        ├── _zadarma_download_recording(temp_url) → ir.attachment permanent
        └── call.write({'recording_url': '/web/content/{id}?download=true'})

Return 'OK'
```

### Click-to-Call (outbound trigger)

```
Manager натискає кнопку у формі res.partner
    │
    ▼
action_zadarma_call() на res.partner:
    ├── user_ext = self.env.user → знаходить first extension
    ├── partner_phone = self.phone normalized з + prefix
    └── Zadarma GET /v1/request/callback/?from=<ext>&to=<phone>&sip=<ext>
    │
    ▼
Zadarma piднімає 2-leg call:
    1. Ext manager-а (звучить дзвінок у менеджера)
    2. Після відповіді менеджера → PSTN partner
    │
    ▼
Подальша обробка через NOTIFY_OUT_END (як вище).
```

### Recording recovery cron

Zadarma temporary URLs expire за 24h. Cron `cron_recover_missing_recordings` (priority 10, daily) шукає `zadarma.call` записи без permanent attachment + з recent date_start і завантажує MP3.

### Color compute logic

Пріоритет (`_compute_color`):

1. **spam** — `phone.blacklist` match (batch lookup для performance)
2. **voicemail** — будь-який `status != 'answered'` (cancel / no answer / busy / failed / call failed)
3. **orphan** — `answered` + порожнє `user_id`
4. **manager_1 / manager_2 / manager_3** — за `user_id.zadarma_manager_slot` (data-driven, Settings → Users, без хардкоду ідентичності у коді)
5. **neutral** — default (color=0, color_tag=False)

## SCSS Asset Bundle

`static/src/scss/zadarma_list.scss` зареєстрований у `__manifest__.py` → `web.assets_backend`. Селектори:

```scss
tr.o_data_row.text-danger  { background: #ff5252; }   // spam
tr.o_data_row.text-warning { background: #ffeb3b; }   // missed
tr.o_data_row.text-muted   { background: #cfd8dc; }   // orphan
tr.o_data_row.text-info    { background: #4fc3f7; }   // manager slot 1
tr.o_data_row.text-success { background: #69f0ae; }   // manager slot 2
tr.o_data_row.text-primary { background: #b39ddb; }   // manager slot 3
```

Селектори намірено unscoped. Bootstrap `decoration-*` атрибути на `<tree>` рівні застосовуються через text-class на `<tr>`.

## Configuration

`res.company` fields (Settings → Companies → Zadarma tab):
- `zadarma_api_key` — API key з my.zadarma.com
- `zadarma_api_secret` — API secret (також webhook signature)
- `zadarma_callerid_rules` — CallerID за напрямком (per-prefix)
- `zadarma_missed_call_fallback_user_id` — fallback-менеджер для пропущених дзвінків без відповідального (замінює хардкод-логін)

`res.users` fields (Settings → Users → Zadarma tab):
- `zadarma_manager_slot` — кольоровий слот (1-3) для рядків цього менеджера у списку дзвінків

## Security

- **Webhook endpoint** `/zadarma/webhook` — `auth='public'`, `csrf=False`. HMAC verification у **warning mode** (v17.0.1.14.0) — обчислюється, логується, але НЕ блокує. Enforce mode заплановано.
- **Credentials** зберігаються у `res.company.zadarma_api_secret` — доступні тільки admin-group.
- **Recording MP3** — `ir.attachment` з ACL як у власника-партнера.
- **`ir.rule`** `Zadarma Call — multi-company`: `('|', company_id=False, company_id in company_ids)` global. Existing рядки з NULL company лишаються видимими для всіх.
- **Groups**: `group_zadarma_user` (extends `base.group_user`), `group_zadarma_admin` (extends user). Admin додані base.user_root + base.user_admin.

## Cron Jobs

| Cron | Priority | Interval | Purpose |
|------|----------|----------|---------|
| `ir_cron_recover_missing_recordings` | 10 | 1 day | Завантажити MP3 для дзвінків без permanent attachment (limit 100) |
| `ir_cron_recover_missing_user_ids` | 20 | 1 day | Backfill `user_id` через SIP (outbound) + partner.user_id (inbound), limit 100 |
| `ir_cron_rematch_orphan_leads` | 30 | 1 day | Прив'язати «Дзвінок: +xxx» zombie-ліди до пізніше створених партнерів (limit 100) |
| `ir_cron_rematch_orphan_calls` | 40 | 1 day | Прив'язати zadarma.call без partner до пізніше створених партнерів (limit 200) |

Priority встановлений щоб серіалізувати виконання (нижчий priority = виконується першим). Не дає 4-way burst Zadarma API.

## Extension points

### Custom post-call hooks

```python
class ZadarmaCallExt(models.Model):
    _inherit = 'zadarma.call'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for r in records:
            # My custom logic після створення
            if r.lead_id and r.duration > 300:
                r.lead_id.write({'probability': 40})
        return records
```

### Custom color tag

Розширити `_compute_color` через inherit з додатковими branches до `super()`.

### Custom recording storage

Override `_zadarma_download_recording(url)` щоб зберігати у S3 замість local `ir.attachment`.

## Відомі обмеження

- **Rate limit Zadarma API:** ~60-100 req/min на інтеграцію. Bulk-import + recovery cron мають `_API_CALL_SPACING = 1.0` + exp-backoff. Rate-limit може повертатись як HTTP 200 з body `status=error msg='rate limit'`, не тільки 429 — обробляємо обидва.
- **Recording availability:** Zadarma тримає записи 3 місяці безкоштовно. Permanent — через attach до `ir.attachment` (це і робимо).
- **Click-to-call works тільки якщо** у manager-а внутрішній extension призначений у Zadarma PBX + є запис у `res.users.zadarma.extension`.
- **HMAC enforce TBD** — поки warning mode, security дірка існує до переходу на enforce.

## Roadmap

- **HMAC enforce mode** — окремий PR після 1-2 днів прод-логів (`signature OK (variant A|B)` confirmation).
- **App Store readiness:** `tests/` директорія (pytest unittest), `.po` файли (i18n замість inline UA labels), banner 1280×720, screenshots.
- **Search refinement:** дата-фільтри ("Сьогодні / Тиждень / Місяць") треба верифікувати domain syntax у Odoo 17.
- **Винести в adapter pattern:** `fayna_telephony_base` + `fayna_telephony_zadarma` (див ADR-003), щоб swap на Binotel/Ringostat без data loss.
- **Call analytics dashboard** — conversion rate, avg duration, missed % per manager.

## Посилання

- ADR-003 — adapter pattern (fayna-digital-docs, приватне)
- Zadarma API docs: https://zadarma.com/support/api/
- Zadarma Webhook: my.zadarma.com → Integrations → External systems → Webhooks
- TZ.md — features checklist у цьому модулі
