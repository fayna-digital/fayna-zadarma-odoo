# Fayna Zadarma Telephony — CLAUDE.md

> 🚫 **Ніколи не працювати напряму на сервері.** Локально → GitHub (push) →
> staging → prod (pull). Жодних правок файлів/скриптів на сервері — git
> єдине джерело правди.

> 🔒 **No-AI-signature policy.** Це публічний/портфоліо-репозиторій. Коміти —
> **без** AI co-author трейлерів та будь-яких згадок AI-асистента. Гвардія:
> `.pre-commit-config.yaml` → `no-ai-signature` (блокує і в контенті, і в
> commit-message). Автор комітів — людина.

## Призначення

Інтеграція хмарної АТС Zadarma з Odoo 17 CRM. Автологування дзвінків,
MP3-записи у chatter, click-to-call, SMS, auto-lead при пропущеному дзвінку.

**Версія:** `17.0.1.14.0` | Odoo 17 Community + Enterprise | License: LGPL-3

## Public extract

Цей репозиторій — санітизований, standalone re-extract з модуля, що активно
працює в production для клієнта Fayna Digital. Витягнутий за процедурою
Showcase Promote: чиста git-історія, без client PII, секретів чи внутрішньої
інфраструктури. Оригінальний робочий репозиторій лишається приватним.

## Ключові файли

| Файл | Що робить |
|------|-----------|
| `controllers/webhook.py` | Отримує POST від Zadarma, верифікує HMAC, диспетчеризує події |
| `models/zadarma_call.py` | Модель `zadarma.call` — головний запис дзвінка |
| `models/crm_lead.py` | Auto-create lead при missed/answered від невідомого номера |
| `models/res_users.py` | Extension mapping internal ext → `res.users` |
| `models/partner_lead_ext.py` | Кнопка click-to-call на партнері |
| `models/zadarma_import.py` | Bulk-import CSV з порталу Zadarma |
| `lib/zadarma_client.py` | Framework-independent HMAC signing / rate-limit / normalization helpers (юніт-тестовані без Odoo) |
| `hooks.py` | `post_init_hook` — деактивує дублюючі кнопки стороннього конектора на формі партнера |

## Команди

```bash
uvx pre-commit run --all-files      # lint + format + security + no-ai-signature
python -m pytest tests/ -v          # framework-independent юніт-тести (lib/)
```

## Дані

- Жодних персональних ідентифікаторів (email, телефон, SIP-номер) не
  хардкодиться в коді. Fallback-менеджер і кольорове маркування рядків
  configurable через `res.company` / `res.users` (Settings), не константи.

## Boundaries

- **Always:** нову конфігурацію (fallback-менеджер, CallerID rules,
  manager-color slots) — через UI/DB, не хардкодити в Python.
- **Ask first:** зміна публічності репо, зміна ліцензії, публікація нових
  screenshots/демо-даних.
- **Never:** повертати реальні клієнтські дані вихідного проєкту (телефони,
  email співробітників, internal server paths) у цей репозиторій; додавати
  AI co-author трейлери чи будь-яку AI-атрибуцію.
