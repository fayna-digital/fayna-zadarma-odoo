# Odoo 17 Zadarma Телефонія — Автологування, Запис, Click-to-Call, SMS

![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20Community-purple)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Zadarma](https://img.shields.io/badge/Zadarma-API%20v1-red)
![License](https://img.shields.io/badge/License-LGPL--3-green.svg)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

**Розроблено [Fayna Digital](https://www.fayna.agency) для CampScout**
**Автор: Volodymyr Shevchenko**

---

Інтеграція хмарної АТС **Zadarma** з Odoo 17 CRM. Кожен вхідний та вихідний дзвінок автоматично фіксується і прив'язується до `res.partner` та `crm.lead`, з повним MP3-записом, прикріпленим до чатера. Підтримує click-to-call з картки партнера, аналітику SMS (над `sms.sms`) із дашбордом балансу TurboSMS та автостворення лідів при пропущених дзвінках з невідомих номерів.

Еталонне розгортання: [CampScout](https://campscout.eu).

---

## Можливості

### Дзвінки
- **Автологування дзвінків** — webhook Zadarma → записи `zadarma.call` (`NOTIFY_END`, `NOTIFY_OUT_END`, `NOTIFY_RECORD`)
- **Запис розмов** — MP3 автозавантажується і прикріплюється до chatter партнера/ліда
- **Click-to-call** — кнопка у формі `res.partner` → Zadarma Callback API ініціює дзвінок на внутрішній номер менеджера
- **Автолід для невідомих** — невідомий абонент → новий `crm.lead` («Дзвінок: +xxx»), призначений менеджеру за внутрішнім номером
- **Auto-lead на answered** — відповіли на дзвінок з існуючим контактом без ліда → автоматично створюється `crm.lead` (`Розмова: {partner.name}`)
- **First-call ownership** — перший _відповідений_ outbound від менеджера → `partner.user_id` встановлюється автоматично
- **user_id fallback chain** — пропущений вхідний без SIP → дзвінок призначається `partner.user_id` (або `lead.user_id`)
- **Multi-extension mapping** — N:1 `res.users` ↔ extension через окрему модель `res.users.zadarma.extension`

### Візуалізація
- **Кольорове маркування рядків** через SCSS asset (`web.assets_backend`):
  - 🔴 Спам (phone у `phone.blacklist`)
  - 🟡 Пропущений (будь-який `status != 'answered'`)
  - ⚪ Без власника (`answered` без `user_id`)
  - 🟦 / 🟢 / 🟣 до 3 менеджерів — колір конфігурується per-user (`res.users.zadarma_manager_slot`), без хардкоду імен у коді
- **Search view легенда** — фільтри за напрямком/статусом/менеджером/датою/записом, group_by

### Безпека та цілісність
- **HMAC-SHA1 verification** webhook (warning mode → enforce після прод-логів)
- **UNIQUE constraint** на `call_id` (PostgreSQL-level dedup)
- **Multi-company** — `company_id` поле + `ir.rule` із domain `('|', company_id=False, company_id in company_ids)`

### SMS
- **Аналітика SMS** — представлення над стандартною `sms.sms` (дерево/форма/пошук): статуси доставки, розбивка по партнеру, поля TurboSMS (`kw_turbosms_*`)
- **Дашборд балансу TurboSMS** — модель `zadarma.dashboard` показує баланс Zadarma + TurboSMS
- ⚠️ Модуль **не надсилає SMS самостійно** — відправлення виконує стандартний SMS-стек Odoo / зовнішній конектор TurboSMS; тут лише статистика та баланси

### Інше
- **Масовий імпорт** — чанк-імпорт через Statistics API Zadarma з прогресом та resume
- **Відстеження результату** — answered / no answer / cancel / busy / failed / call failed
- **Chatter** на формі дзвінка — `mail.thread` + `mail.activity.mixin`
- **Cron priorities** (10/20/30/40) — recover_recordings → backfill_user_ids → rematch_orphan_leads → rematch_orphan_calls, серіалізує API виклики
- **DB indexes** на `date_start`, `status`, `direction`, `user_id` для швидкого list view

---

## Архітектура

```
zadarma-odoo/
├── __init__.py                          # imports controllers, models + post_init_hook
├── __manifest__.py                      # 17.0.1.14.0, assets bundle declaration
├── hooks.py                             # post_init_hook (вимикає binotel duplicate buttons)
├── models/
│   ├── zadarma_call.py                  # Основна модель + _inherit mail.thread + _sql_constraints UNIQUE
│   ├── zadarma_import.py                # TransientModel wizard масового імпорту
│   ├── zadarma_dashboard.py             # Модель балансів Zadarma + TurboSMS
│   ├── crm_lead.py                      # Розширення crm.lead (orphan re-match)
│   ├── mail_activity.py                 # zadarma_call_id back-ref (idempotency)
│   ├── partner_lead_ext.py              # zadarma_call_count з @api.depends
│   ├── res_company.py                   # Облікові дані Zadarma
│   ├── res_partner.py                   # Розширення партнера
│   ├── res_users.py                     # SIP extension (legacy)
│   └── res_users_zadarma_extension.py   # N:1 user → extensions mapping
├── controllers/
│   └── webhook.py                       # /zadarma/webhook + HMAC verification (warning mode)
├── data/
│   └── ir_cron.xml                      # 4 cron з priority offset
├── views/
│   ├── zadarma_views.xml                # Tree + form + search + actions
│   ├── zadarma_dashboard_views.xml      # Modal балансів
│   ├── zadarma_import_views.xml         # Wizard імпорту
│   ├── sms_stats_views.xml              # Аналітика SMS
│   ├── res_company_views.xml            # Credentials
│   ├── res_users_views.xml              # SIP mapping UI
│   └── partner_lead_views.xml           # Smart button на partner/lead
├── security/
│   ├── zadarma_security.xml             # Groups + ir.rule multi-company
│   └── ir.model.access.csv
├── static/
│   ├── description/
│   └── src/scss/zadarma_list.scss       # Row coloring per color_tag
└── docs/
    ├── ARCHITECTURE.md
    ├── DEPLOYMENT.md
    ├── RUNBOOK.md
    └── TZ.md                            # Features checklist (✅ / 🔲 / ❌)
```

---

## Технологічний стек

| Компонент | Технологія |
|-----------|-----------|
| ERP-фреймворк | Odoo 17.0 Community |
| Основні залежності | `base`, `crm`, `mail`, `phone_validation`, `sms` |
| АТС | Zadarma cloud (SIP + webhooks) |
| Версія API | Zadarma API v1 |
| Підпис | HMAC-SHA1 |
| Формат запису | MP3 (зберігається як `ir.attachment` постійно) |
| Автоатрибуція | Внутрішній номер → `res.users.zadarma_extension` |
| Версія модуля | 17.0.1.14.0 |
| Ліцензія | LGPL-3.0 |

---

## Встановлення

### 1. Клонування в custom-addons

```bash
cd /opt/<client>/custom-addons
git clone https://github.com/VladSh77/zadarma-odoo.git zadarma_odoo
```

### 2. Встановлення модуля

```bash
docker exec <client>_web odoo -c /etc/odoo/odoo.conf -d <db> \
    -i zadarma_odoo --stop-after-init --no-http
```

Або через UI: **Застосунки → Оновити список застосунків → пошук `Zadarma` → Встановити**.

### 3. Перезапуск Odoo

```bash
docker restart <client>_web
```

---

## Налаштування

### Крок 1 — Генерація облікових даних Zadarma API

1. Увійдіть на [my.zadarma.com](https://my.zadarma.com) → **Налаштування → API**
2. Згенеруйте **API Key** та **API Secret**
3. Скопіюйте обидва

### Крок 2 — Налаштування в Odoo

**Налаштування → Користувачі й компанії → Компанії → [активна компанія] → вкладка «Zadarma»**:

| Поле | Значення |
|-------|-------|
| Zadarma User Key | вставте API Key |
| Zadarma User Secret | вставте API Secret |
| Zadarma Webhook Secret | випадково згенерований рядок (наприклад `openssl rand -hex 32`) |

### Крок 3 — Призначення внутрішніх номерів користувачам

Для кожного менеджера:

1. **Налаштування → Користувачі → [користувач] → вкладка «Zadarma»**
2. **Внутрішній номер Zadarma** = внутрішній номер (наприклад `100`, `101`)
3. Повинен збігатися з внутрішнім номером, налаштованим у Zadarma АТС для цього менеджера

### Крок 4 — Реєстрація webhook у Zadarma

[my.zadarma.com](https://my.zadarma.com) → **Інтеграції → CRM / Зовнішні системи → Webhooks**:

- URL: `https://<your-odoo>.com/zadarma/webhook`
- Події: увімкніть `NOTIFY_START`, `NOTIFY_ANSWER`, `NOTIFY_END`, `NOTIFY_RECORD`
- Secret: вставте той самий webhook secret з налаштувань Odoo

---

## Використання

### Вхідний дзвінок

1. Клієнт дзвонить на ваш номер Zadarma
2. Zadarma АТС маршрутизує → вибирає внутрішній номер менеджера
3. Webhook `/zadarma/webhook` отримує послідовність подій:
   - `NOTIFY_START` → створюється `zadarma.call`, ідентифікується партнер або автоматично створюється лід
   - `NOTIFY_ANSWER` → менеджер атрибутується за внутрішнім номером
   - `NOTIFY_END` → записується тривалість, результат
   - `NOTIFY_RECORD` → завантажується MP3, прикріплюється до чатера
4. У чатері партнера/ліда з'являється повідомлення з деталями дзвінка + аудіоплеєром

### Click-to-call

1. Відкрийте форму партнера (`res.partner`)
2. Натисніть кнопку **Дзвінок** (значок телефону поруч з номером)
3. Zadarma API ініціює дзвінок:
   - Спочатку дзвонить на внутрішній номер менеджера
   - При відповіді → з'єднує з PSTN партнера
4. Слідує стандартний webhook-ланцюжок (тільки з `direction='out'`)

### SMS

Модуль **не має власної моделі відправлення SMS** і не шле повідомлення сам. Він надає:

- **Аналітику над `sms.sms`** — окреме меню з деревом / формою / пошуком по стандартних SMS-записах Odoo, з полями TurboSMS (`kw_turbosms_message_id`, `kw_turbosms_sms_or_viber`, `kw_turbosms_response_status`) для тих, хто використовує конектор `kw_sms_turbosms`.
- **Дашборд балансу** (`zadarma.dashboard`) — баланс Zadarma + баланс TurboSMS (запит до `api.turbosms.ua/user/balance.json`).

Саме надсилання SMS відбувається через стандартний SMS-стек Odoo (`sms.sms`) або зовнішній конектор TurboSMS — не через цей модуль.

### Масовий імпорт дзвінків

**Меню → Zadarma → Імпорт дзвінків**:

1. Вкажіть діапазон дат (від / до)
2. Натисніть **Запустити** — використовує Statistics API Zadarma, розмір чанку 50
3. Прогрес-бар оновлюється; можна зупинити і продовжити
4. Для тисяч дзвінків — 10-30 хвилин

---

## Webhook Flow (технічно)

```
1. Клієнт дзвонить на +48 XXX XXX XXX (ваш номер Zadarma)
2. Zadarma АТС маршрутизує дзвінок
3. POST https://<odoo>/zadarma/webhook
4. Controller _verify_signature_warning() — обчислює обидва варіанти HMAC,
   логує match/mismatch (warning mode; НЕ блокує запит у v17.0.1.14.0)
5. Диспетчеризація за типом події (v17.0.1.14.0):
   ├── NOTIFY_END (вхідний + outbound без internal):
   │   ├── Визначення direction за довжиною caller_id (≤5 цифр = outbound)
   │   ├── Нормалізація телефону → пошук res.partner (SQL LIKE %suffix% по kw_phone_cleaned)
   │   ├── _find_existing_lead → відкритий lead для партнера/телефону
   │   ├── user fallback chain: SIP → partner.user_id → lead.user_id
   │   ├── Auto-create lead:
   │   │   ├── не знайдено ні partner ні lead → "Дзвінок: +xxx"
   │   │   └── answered + partner але без lead → "Розмова: {partner.name}"
   │   ├── First-call ownership: answered outbound + partner без user_id
   │   │   → partner.sudo().write({'user_id': user.id})
   │   ├── Створення zadarma.call (UNIQUE call_id constraint)
   │   ├── Chatter post на target (lead або partner)
   │   ├── Missed → mail.activity «Передзвонити» (idempotent via zadarma_call_id)
   │   └── _compute_color → spam / voicemail / orphan / manager / neutral
   │
   ├── NOTIFY_OUT_END (outbound з PBX-internal):
   │   └── Та сама логіка, з sip = data['internal']
   │
   └── NOTIFY_RECORD:
       ├── _zadarma_fetch_recording_url(call_id, pbx_call_id) → temporary URL
       ├── _zadarma_download_recording → ir.attachment (permanent)
       └── call.write({'recording_url': '/web/content/...'})
6. Повернення 200 OK
```

---

## Click-to-Call Flow (технічно)

```
1. Користувач натискає кнопку Дзвінок у формі res.partner
   (button name="action_zadarma_call" у partner_lead_views.xml)
2. Backend: res.partner.action_zadarma_call() (models/res_partner.py):
   a. Визначення абонента: user.zadarma_primary_extension
      (fallback → legacy user.zadarma_internal_number)
   b. Визначення одержувача: '+' + цифри з self.phone / self.mobile
   c. Побудова HMAC-SHA1 підпису (key:signature у заголовку Authorization)
   d. GET https://api.zadarma.com/v1/request/callback/?from=<ext>&to=<phone>&sip=<ext>
3. Zadarma Callback API:
   a. Ініціює дзвінок на SIP-внутрішній номер менеджера
   b. При відповіді менеджера → з'єднує з PSTN одержувача
4. Слідує звичайний webhook-ланцюжок через NOTIFY_OUT_END (direction='out')
```

---

## Локальна розробка

```bash
git clone https://github.com/VladSh77/zadarma-odoo.git
cd zadarma-odoo

# Тимчасовий Odoo з підключеним модулем:
docker run -d --name test_odoo -v $(pwd)/..:/mnt/custom-addons \
    -p 8069:8069 odoo:17

# Симуляція webhook:
curl -X POST http://localhost:8069/zadarma/webhook \
    -d 'event=NOTIFY_START&call_start=2026-01-01+12:00:00&caller_id=+48123456789&called_did=+48987654321'
```

---

## Усунення несправностей

| Помилка | Причина | Виправлення |
|-------|-------|-----|
| Webhook не надходить | Публічний URL недоступний з Zadarma | `curl -vI https://<odoo>.com/zadarma/webhook` ззовні; перевірте SSL / firewall |
| Перевірка підпису не вдається | Невідповідність webhook secret | Синхронізуйте secret між налаштуваннями Odoo та Zadarma (точна відповідність, без пробілів) |
| Запис не прикріплюється | NOTIFY_RECORD не увімкнено АБО тариф не включає запис | my.zadarma.com → Webhooks → увімкніть NOTIFY_RECORD; перевірте тариф |
| Завантаження запису не вдається | Фільтр `allowed_ips` Zadarma блокує VPS | Додайте IP вашого Odoo VPS до whitelist API на my.zadarma.com |
| Click-to-call нічого не робить | Менеджеру не призначено внутрішній номер / не налаштовано в АТС | Налаштування → Користувачі → менеджер → встановіть `Внутрішній номер Zadarma`; перевірте в АТС |
| SMS не доставляється | Неправильний формат телефону (потрібен E.164 `+XX...`) | Нормалізуйте через `zadarma.call._normalize_phone(phone)` |
| Помилки 429 при масовому імпорті | Ліміт API Zadarma (~60 запитів/хв) | Майстер вже ділить на чанки по 50; якщо ліміт все ще перевищується — збільшіть інтервал паузи в `zadarma_import.py` |

---

## Доступ

Модуль оголошує дві власні групи (`security/zadarma_security.xml`):

| Група | XML id | Розширює |
|-------|--------|----------|
| User | `zadarma_odoo.group_zadarma_user` | `base.group_user` |
| Administrator | `zadarma_odoo.group_zadarma_admin` | `group_zadarma_user` (+ `base.user_root`, `base.user_admin`) |

Права доступу до моделей (`security/ir.model.access.csv`) прив'язані до стандартних Odoo-груп, **не** до груп sales_team:

- **`base.group_user`** (будь-який внутрішній користувач):
  - `zadarma.call` — тільки читання
  - `zadarma.dashboard`, `res.users.zadarma.extension` — читання
- **`base.group_system`** (Settings / адміністратор):
  - `zadarma.call` — повний доступ (read/write/create/unlink)
  - `zadarma.import` — майстер масового імпорту
  - `res.users.zadarma.extension` — повний доступ (мапінг внутрішніх номерів)

Multi-company видимість дзвінків забезпечує global `ir.rule` `zadarma_call_company_rule`
(`['|', ('company_id','=',False), ('company_id','in',company_ids)]`).

Облікові дані Zadarma (`res.company.zadarma_api_secret`) доступні лише користувачам із доступом до налаштувань компанії.

---

## Дорожня карта — Міграція на адаптер-патерн

Цей модуль планується рефакторити за adapter pattern (ADR-003, внутрішня документація архітектури Fayna Digital):

```
Майбутній стан:
  fayna_telephony_base (абстрактно: модель дзвінка, контракт провайдера)
    ├── fayna_telephony_zadarma  (цей модуль, перейменування)
    ├── fayna_telephony_binotel  (майбутнє)
    ├── fayna_telephony_ringostat (майбутнє)
    └── fayna_telephony_kyivstar (майбутнє)
```

Тригер для рефакторингу: коли клієнт запросить інший провайдер. Зараз не блокує.

---

## Екосистема модулів

| Суміжний модуль | Роль |
|----------------|------|
| [fayna-sendpulse-odoo](https://github.com/VladSh77/fayna-sendpulse-odoo) | Суміжний месенджер (обидва потрапляють до Odoo CRM) |
| [omnichannel-bridge](https://github.com/VladSh77/omnichannel-bridge) | Omnichannel-агрегатор (голос поки окремий канал, не через міст) |
| [campscout-management](https://github.com/VladSh77/campscout-management) | Використовує для вхідних sales-дзвінків CampScout |

Детальна архітектурна документація — у внутрішньому репозиторії Fayna Digital (приватний).

---

## Ліцензія

**LGPL-3.0** — дивіться [LICENSE](LICENSE) та [NOTICE.md](NOTICE.md). © Fayna Digital.

---

*Розроблено [Fayna Digital](https://www.fayna.agency) · Volodymyr Shevchenko*
