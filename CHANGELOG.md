# CHANGELOG — zadarma_odoo

Формат: `## [version] — YYYY-MM-DD`

---

## [17.0.1.14.0] — 2026-06-12

### Added
- Інтернаціоналізація (i18n): усі рантайм-рядки інтерфейсу (notification-повідомлення, `UserError`, `message_post`, обчислювані назви, активності) обгорнуто у `_()`; f-string'и переписано на `_('...%s') % ...` для коректного перекладу.
- Каталог `i18n/` з `pl.po` (польська) та `uk_UA.po` (українська) — інтерфейс модуля автоматично перемикається на мову користувача Odoo.
- Senior-аудит (той самий реліз): +18 пропущених термінів (поля дашборду «Баланс Zadarma/TurboSMS», фільтри «Сьогодні/Цей тиждень/Цей місяць», wizard «Від/До/Результат», cron-назви, security-групи) + полагоджено msgid help-тексту CallerID Rules (реальні переноси замість літерального `\n`). Разом 166 записів/мову; msgfmt PASS, плейсхолдери 0 розбіжностей.

### Notes
- Вихідні рядки лишаються українською (source), польська підключається через `i18n/pl.po`. Поля (`string=`/`help=`/`selection`), `_sql_constraints` та тексти у XML-views Odoo витягує в переклад автоматично.

---

## [docs] — 2026-06-08 (без зміни коду)

### Changed
- Приведено до внутрішнього стандарту репозиторіїв Fayna Digital: `docs/TZ.md` переписано у 6 областей spec-driven; `docs/PLAN.md` створено (HMAC enforce, tests, hand-off, roadmap); `.gitignore` — захист секретів (api_key/secret, HMAC).
> ⚠️ Код не змінювався. Версія модуля 17.0.1.13.0.

---

## [17.0.1.12.0] — 2026-06-07

### Fixed

- **Recording в чатер ліда/партнера.** `_process_notify_record` (`controllers/webhook.py`) після збереження MP3 тепер постить внутрішню нотатку «📎 Запис розмови: Слухати запис» в чатер ліда або партнера від імені відповідального менеджера. Раніше лінк з'являвся лише у формі `zadarma.call`.

## [17.0.1.11.0] — 2026-06-01

### Fixed

- **Webhook: пропущений дзвінок не створював задачу «Передзвонити».** У `_create_missed_call_activity` (`controllers/webhook.py`) виклик `fields.Date.context_today(self)` падав з `AttributeError: 'ZadarmaWebhook' object has no attribute '_context'` (self = контролер, не recordset). Замінено на `context_today(env.user)`. Виявлено в прод-логах 2026-06-01.

## [17.0.1.10.0] — 2026-05-26

Велика сесія аудиту + фіксів. Один bump на ~10 PRs (memory `feedback_version_bump.md`).

### Added

- **Кольорове маркування рядків списку** через SCSS asset bundle (`web.assets_backend`, `static/src/scss/zadarma_list.scss`):
  - 🔴 Спам · 🟡 Пропущений · ⚪ Без власника · 🟦 / 🟢 / 🟣 до 3 менеджерів (конфігуровано per-user)
  - `color_tag` поле (Selection compute, stored) з пріоритетом spam > missed > orphan > manager > neutral
- **Search view** з вбудованою легендою — 17+ фільтрів (напрямок, статус, кольорові категорії, менеджер, дата, запис, мої дзвінки) + 5 group_by опцій
- **Auto-create lead на answered** — відповіли на дзвінок з partner без ліда → автоматично створюється `crm.lead` (`Розмова: {partner.name}`). Раніше створювався лише за відсутності і partner, і lead.
- **First-call ownership** — відповіли на outbound від менеджера + partner без salesperson → `partner.user_id` встановлюється автоматично. Тільки на `disposition='answered'`.
- **user_id fallback chain** у webhook (NOTIFY_END + NOTIFY_OUT_END): `sip → partner.user_id → lead.user_id`. Пропущені вхідні без SIP більше не лишаються orphan.
- **HMAC verification у warning mode** — обчислюються обидва варіанти підпису Zadarma (sha1 over sorted params, sha1 over md5(sorted params)), логується match/mismatch. **НЕ блокує запити** до окремого enforce-PR після верифікації прод-логів.
- **Multi-company** — `company_id` поле (Many2one з default current company, index) + `ir.rule` `('|', company_id=False, company_id in company_ids)` global.
- **Chatter на формі дзвінка** — `_inherit = ['mail.thread', 'mail.activity.mixin']` + `<div class="oe_chatter">` у form view.
- **UNIQUE constraint** на `call_id` — `_sql_constraints` (PostgreSQL-level dedup замість in-app search check).
- **DB indexes** на `date_start`, `status`, `direction`, `user_id` (раніше тільки `call_id` і `phone_number`).
- **Cron priority** 10/20/30/40 на 4 cron — серіалізує API виклики до Zadarma, no more 4-way burst.
- **cron_recover_missing_user_ids розширено** — backfill з `partner.user_id` / `lead.user_id` для inbound no-answer.
- **action_backfill_user_id_from_partner** — server action для bulk backfill.
- **post_init_hook** — деактивує `binotel_connect.view_partner_form_inherit` (раніше функція декларувалась у manifest але `hooks.py` не імпортувався з `__init__.py` → silent failure).

### Fixed

- **Lambda fix** у `zadarma_import.date_to`: `default=fields.Date.today` → `default=lambda self: fields.Date.today()`. Раніше дата вираховувалась один раз при load модуля → wizard відкривав застарілу дату.
- **`@api.depends('zadarma_call_ids')`** на `_compute_zadarma_call_count` у partner + lead. Раніше recompute при кожному читанні → повільне відкриття partner-картки з 100+ дзвінків.
- **Voicemail color rule** генералізовано: був прив'язаний до одного конкретного (старого) DID, тепер будь-який `inbound + cancel/no_answer`, далі взагалі будь-який `status != 'answered'` (включно з outbound missed).
- **`_normalize_phone` + `_find_partner` дублікати** у `controllers/webhook.py` тепер делегують до моделі `zadarma.call._normalize_phone` / `._find_partner_by_phone` (single source of truth).
- **mail.thread inherit ALTER TABLE workaround** — після `_inherit` додавання Odoo upgrade не створив `message_main_attachment_id` колонку (upgrade no-op на state=installed модулі). Колонку додано вручну через SQL `ALTER TABLE zadarma_call ADD COLUMN message_main_attachment_id INTEGER REFERENCES ir_attachment(id) ON DELETE SET NULL` + restart workers.
- **Kanban view видалено** — це історія дзвінків, не CRM pipeline; зайва форма UX-шуму. `view_mode=tree,form`.

### Files

- `models/zadarma_call.py` — +90 lines (mail.thread inherit, _sql_constraints, indexes, color_tag, company_id, cron extensions)
- `controllers/webhook.py` — +120 lines (HMAC, user_id fallback, first-call, auto-lead, delegations)
- `models/zadarma_import.py` — lambda fix
- `models/partner_lead_ext.py` — @api.depends decorators
- `data/ir_cron.xml` — priority field
- `views/zadarma_views.xml` — search view, chatter on form, kanban видалено
- `security/zadarma_security.xml` — ir.rule multi-company
- `static/src/scss/zadarma_list.scss` — НОВИЙ (61 lines)
- `__init__.py` — `from .hooks import post_init_hook`
- `__manifest__.py` — assets bundle declaration

### Origin / докладніше

Запис сесії — у внутрішньому журналі розробки Fayna Digital.

PRs: #11 (kanban+decoration), #12 (badge column), #13 (5 critical bugs + HMAC warning), #14 (row colors via SCSS), #15 (auto-lead + audit), #16 (search filters + missed=yellow), + `fix/init-hook-and-mail-inherit`, + `fix/multi-company-and-edges`.

---

## [17.0.1.8.0] — 2026-05-25

### Added

- **Multi-extension mapping** — нова модель `res.users.zadarma.extension` (One2many `user_id` → `internal`). Дозволяє одному менеджеру мати декілька SIP extensions (наприклад менеджер А: 100+103, менеджер Б: 104+105).
- Migration: автоматичне копіювання legacy `zadarma_internal_number` (один рядок) у нову модель при upgrade.
- Внутрішні session-нотатки (діагностика inbound recording) — не публікуються в цьому репозиторії.

### Files

- `models/res_users_zadarma_extension.py` — НОВИЙ
- `views/res_users_views.xml` — UI editor для extensions

---

## [17.0.1.7.3] — 2026-05-25

### Fixed

- **Rate-limit як 200+body**: Zadarma при rate-limit повертає **HTTP 200** з body `status=error msg='You exceeded the rate limit by User Limits'`, не 429. Recovery cron у PR #2 не мав sleep і викликав API ~14 req/sec → попав під rate-limit.
- Hand-rolled retry + 1 req/sec pacing (`_API_CALL_SPACING = 1.0`).
- `_is_zadarma_rate_limited(status_code, body)` helper тепер перевіряє обидва варіанти.

---

## [17.0.1.7.2] — 2026-05-25

### Added

- **Recording recovery cron** — Zadarma temporary recording URLs expire за 24h. Cron щодня шукає zadarma.call записи без permanent attachment і завантажує.
- **Recording через bulk import** — `zadarma.import` тягне MP3 для historical calls.
- **Shared `_find_existing_lead`** на моделі (раніше дублювалось у webhook + import).
- **`duration_display` HH:MM:SS** через compute — раніше Integer 275s показувався як `275:00` (= 275 годин) через widget `float_time`.

---

## [17.0.1.7.1] — 2026-05-25

### Fixed

- **Webhook calltype filter видалено**: був фільтр `data.get('calltype') == 'callback_leg2'` у NOTIFY_OUT_END handler, що пропускав ВСІ 347/347 outbound events за 6 тижнів (prod logs verified — всі shle `calltype=normal`).
- **Archived partner matching**: прибрано `active=true` фільтр з `_find_partner` SQL — дзвінок має зв'язатись з існуючим контактом навіть якщо архівний (manager отримує activity для unarchive).
- Order partners з нечисловими іменами перші (real human partners > placeholder контакти).

---

## [17.0.1.7.0] — 2026-04-22

### Added

- **Баланси dashboard** (`zadarma.dashboard`) — новий меню-пункт «Баланси» у Zadarma root showing:
  - Zadarma API balance (HMAC-SHA1 signed request)
  - TurboSMS balance (через `kw.sms.provider`)
- Кнопка «Оновити» для refresh
- Access: `base.group_user` (всі authenticated)

### Origin

Цей код був розроблений **2026-04-20 напряму на проді** (workflow violation — golden rule #3 порушено). 2026-04-22 rescued з прода → git → origin. Детально у внутрішньому журналі розробки Fayna Digital.

### Dependencies

- `kw.sms.provider` (third-party KW Labs TurboSMS module) — для turbosms balance fetching

### Files

- `models/zadarma_dashboard.py` — 109 lines
- `views/zadarma_dashboard_views.xml` — 38 lines
- `models/__init__.py` — +1 import
- `security/ir.model.access.csv` — +1 grant
- `__manifest__.py` — +1 view у data

---

## [17.0.1.6.0] — 2026-04-22

### Змінено (Fayna brand alignment)

- **Manifest:** `name` → `Fayna Zadarma Telephony` (додано префікс Fayna, прибрано «(Campscout)» з name — він у summary);
- **Manifest:** `author` → `Fayna Digital — Volodymyr Shevchenko` (раніше `Fayna`, занадто коротко);
- **Manifest:** `website` → `https://fayna.agency` (fix stale `fayna.company`);
- **Manifest:** version schema `17.0.X.Y.Z` (раніше `1.5.0` без Odoo prefix);
- **Manifest:** додано повний `description` з переліком можливостей;
- `static/description/index.html` — canonical Fayna-style (green #20ac41 badge, wordmark, meta, features cards, flow, requirements);
- README h1 → `Fayna Zadarma Telephony — Odoo 17`.

### Причина

Вирівняння з canonical Fayna module standard (memory `reference_fayna_odoo_module_style.md`). Всі наші модулі мають єдиний brand-формат.

## [ops] — 2026-04-10

- Git sync only: локально, **`origin/main`** і сервер узгоджені (**`git pull --ff-only`**); змін коду **немає**.

---

## [1.5.0] — 2026-03-26

- Docs: README повністю переписано — professional header, badges, features, quick setup
- Docs: LGPL-3.0 license файл
- Fix: Click-to-Call — номер клієнта передається з `+` prefix → CallerID routing в Zadarma обирає правильний транк
- Feat: `NOTIFY_RECORD` → MP3 завантажується у Odoo filestore через `ir.attachment`, `recording_url` вказує на постійний internal URL
- Fix: Zadarma API повертає `links[]` (масив), а не `link` (рядок) — виправлено парсинг
- Fix: Chatter нотатки публікуються від імені менеджера (`with_user(user.id)`), не від Public User
- Fix: `_find_partner` ORDER BY — пріоритет контактів з нечисловими іменами
- Fix: Callback API — додано параметр `sip=` для CallerID-by-destination і prefix dialling
- Fix: `_zadarma_get_recording_url` — пошук компанії з `zadarma_api_key`, не `search([])`
- Fix: прибрано надлишкове агресивне логування

## [1.3.0] — 2026-03-26

- Feat: поле `recording_url` у `zadarma.call`
- Feat: відображення посилання на запис у form view

## [1.2.0] — 2026-03-26

- Feat: Click-to-Call через Zadarma Callback API
- Feat: ретроспективний імпорт дзвінків (`zadarma.import`)
- Feat: Rate limit handling (HTTP 429 — 3 спроби з затримками 3/6/9 сек)

## [1.1.0] — 2026-03-26

- Feat: обробка webhook `NOTIFY_END`, `NOTIFY_OUT_END`
- Feat: авто-створення лідів для невідомих номерів
- Feat: Chatter нотатки від імені менеджера
- Feat: пошук менеджера за SIP ID

## [1.0.0] — 2026-03-26

- Feat: початкова версія — модель `zadarma.call`, базові views, security
- Feat: HMAC-SHA1 аутентифікація
- Feat: Smart prefix логіка (визначення напрямку дзвінка за довжиною caller_id)
