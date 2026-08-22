# TZ — zadarma-odoo

> Специфікація модуля за внутрішнім REPO_STANDARD Fayna Digital (6 областей spec-driven).
> Версія: **17.0.1.14.0** | License: LGPL-3.0 | Odoo 17 Community + Enterprise.
> Як працювати → CLAUDE.md. Детальна архітектура → docs/ARCHITECTURE.md.

---

## 1. Objective

**Що:** інтеграція хмарної АТС **Zadarma** з Odoo 17 CRM — логування дзвінків, MP3-записи в chatter, click-to-call, SMS, auto-lead при пропущених.

**Для кого:** CampScout CRM (Fayna Digital).

**Можливості:**
- Логування вхідних/вихідних дзвінків у `zadarma.call` (прив'язка до партнера/ліда)
- Завантаження MP3-записів у chatter ліда/партнера
- Click-to-call з картки партнера, SMS через TurboSMS
- Auto-lead при missed/answered від невідомого номера
- Multi-extension мапінг (один менеджер → N extension)
- Bulk-import історичних дзвінків через Statistics API

**Версія/license:** 17.0.1.14.0, LGPL-3.0. **Depends (manifest):** `base`, `crm`, `mail`, `phone_validation`, `sms`. **Опційно** (для SMS-аналітики над `sms.sms` з полями `kw_turbosms_*`): конектор `kw_sms_turbosms` — не оголошений у manifest, потрібен лише якщо використовується TurboSMS.

**Успіх:** кожен дзвінок створює `zadarma.call` із заповненим `lead_id`/`partner_id`; outbound MP3 у chatter; merge лідів не втрачає дзвінки.

**Технології:** [[library/tools/python]] · Odoo 17 · [[library/tools/postgresql]] · Zadarma API · HMAC · TurboSMS.

---

## 2. Commands

```bash
# Тест webhook
curl -X POST https://<your-odoo>.com/zadarma/webhook \
  -H "Content-Type: application/json" \
  -d '{"event":"NOTIFY_START","call_id":"test123","caller_id":"48500000000"}'

# Lint (pre-commit: ruff + OCA + gitleaks + bandit)
pre-commit run --all-files

# Тести (⚠️ tests/ ще не реалізовано — pyproject очікує, fail_under=70)
python -m pytest tests/ -v

# Deploy #4ZONES (Mac → GitHub → staging → prod)
git push origin main
ssh prod 'cd /opt/odoo/addons/zadarma-odoo && git pull && sudo systemctl restart odoo'
```

**Webhook:** `https://<your-odoo>.com/zadarma/webhook` — реєструється **вручну** в панелі Zadarma (Integrations → External systems → Webhooks), НЕ автоматично. `post_init_hook` лише деактивує дублюючі кнопки binotel_connect на формі партнера. HMAC у `X-Zadarma-Hmac-Sha1` / `Signature` — перевіряти обидва.

---

## 3. Project Structure

```
zadarma-odoo/
  controllers/webhook.py        # POST від Zadarma, HMAC verify, диспетч (NOTIFY_END/OUT_END/RECORD)
  models/
    zadarma_call.py             # головна модель (mail.thread, color tags, UNIQUE call_id)
    crm_lead.py                 # auto-lead + override merge_opportunity (Bug G fix)
    zadarma_import.py           # bulk-import через Statistics API (пагінація, exp-backoff)
    res_users.py / res_users_zadarma_extension.py # ext-мапінг (один менеджер → N ext)
    res_partner.py / partner_lead_ext.py # smart button + call_count
    zadarma_dashboard.py        # баланси Zadarma + TurboSMS
    res_company.py              # credentials + CallerID rules
  hooks.py                      # post_init_hook — деактивує дублюючі binotel_connect кнопки (webhook НЕ реєструє)
  data/ir_cron.xml              # 4 cron: recover_recordings→recover_user_ids→rematch_leads→rematch_calls
  views/  security/  migrations/  static/src/scss/
```

Детальна архітектура: **docs/ARCHITECTURE.md** · Експлуатація: **docs/RUNBOOK.md** · Деплой: **docs/DEPLOYMENT.md**.

---

## 4. Code Style

```python
# HMAC: завжди перевіряти обидва заголовки (legacy + new API)
# webhook.py
```

- **SQL:** `UNIQUE(call_id)` — dedup між webhook та import на рівні PostgreSQL, не Python
- **Phone:** нормалізація через `kw_phone_cleaned` (не сирий рядок), SQL LIKE %suffix%
- **Логування:** `_logger = logging.getLogger(__name__)`, WARNING для підозрілого
- **Color tags:** SPAM=1, VOICEMAIL=3, менеджери (слот 1/2/3, `res.users.zadarma_manager_slot`) 4/10/8
- **Rate-limit:** Zadarma ~100 req/min — обробляти HTTP 429 + body `status=error`
- **Status whitelist:** unknown → fallback `failed`
- **Fallback assignee** при пропущеному: `res.company.zadarma_missed_call_fallback_user_id` (Settings, не хардкод)

---

## 5. Testing Strategy

- **Фреймворк:** pytest (pyproject: `testpaths=["tests"]`, `fail_under=70`, markers slow/integration)
- ⚠️ **GAP: tests/ ще не реалізовано** — конфіг очікує, папки немає. Пріоритет: характеризаційні тести webhook-диспетчеризації (NOTIFY_END/OUT_END/RECORD) + HMAC verify + `merge_opportunity` перенесення дзвінків.
- Pre-commit: ruff + OCA + gitleaks + bandit перед кожним push.
- Webhook hill-climbing: payload → live endpoint → лог → фікс (verifier: `SELECT id,lead_id FROM zadarma_call WHERE call_id=...`).

---

## 6. Boundaries

**Always:**
- Деплой: локально → GitHub → staging → prod (ніколи напряму на сервері)
- HMAC: перевіряти обидва заголовки
- `chmod -R o+rX` / коректні права після git pull

**Ask first:**
- Зміна структури `zadarma.call` (UNIQUE + 4 індекси → migration)
- HMAC enforce mode (зараз WARNING — після прод-верифікації)
- Adapter split (fayna_telephony_base + zadarma) — лише при запиті іншого провайдера

**Never:**
- Редагувати файли напряму на сервері (nano/vim/scp/docker cp) — golden rule #3
- Секрети (`zadarma_api_key`/`zadarma_api_secret`) у код/чат/лог — лише `res.company` поля
- Force push на main, `--no-verify`

---

## Success Criteria

- [x] Дзвінки логуються з прив'язкою lead/partner
- [x] Outbound MP3 у chatter (17.0.1.12.0)
- [x] Merge лідів не втрачає дзвінки (Bug G, 17.0.1.13.0)
- [x] Multi-ext мапінг (ext 100+103 / 104+105)
- [ ] Inbound recordings (панельне налаштування Zadarma — не код)
- [ ] HMAC enforce mode (після верифікації)
- [ ] tests/ ≥70%

---

## Open Questions
- Версії у README, docs/ARCHITECTURE.md і CLAUDE.md синхронізовано на 17.0.1.14.0 (актуальний manifest).
- HMAC enforce — коли вмикати (потрібні 1-2 дні чистих прод-логів).

## Зв'язки
docs/PLAN.md · docs/ARCHITECTURE.md · docs/RUNBOOK.md · Repo: `fayna-digital/fayna-zadarma-odoo`
