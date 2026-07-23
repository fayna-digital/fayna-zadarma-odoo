# Fayna Zadarma Telephony — Runbook

Операційні процедури specific до модуля.

## Щоденні task-и

### Монторити Zadarma balance

```python
# Quick check in Odoo shell
from odoo.addons.zadarma_odoo.api import ZadarmaAPI
company = env['res.company'].browse(1)
api = ZadarmaAPI(company.zadarma_user_key, company.zadarma_user_secret)
balance = api.get_balance()
print(f"Balance: {balance['balance']} {balance['currency']}")
```

Алерт при `balance < 50 UAH`.

### Щоденна активність

```sql
-- Дзвінки за останні 24h
SELECT direction, disposition, COUNT(*), SUM(duration_sec)/60 as minutes
FROM zadarma_call
WHERE started_at > NOW() - INTERVAL '1 day'
GROUP BY direction, disposition
ORDER BY COUNT(*) DESC;
```

Здорові метрики:
- Missed (no_answer) дзвінки < 20% total
- Середня тривалість вхідного answered > 60 сек (інакше — quick drops = UX problem)

## Щотижневі task-и

### Storage cleanup (optional)

`ir.attachment` з MP3 ростуть швидко. Якщо не використовуємо — archive на S3 + видаляти local.

```sql
-- Розмір attachments за Zadarma за місяць
SELECT DATE_TRUNC('month', a.create_date),
       pg_size_pretty(SUM(a.file_size)) as size
FROM ir_attachment a
JOIN zadarma_call z ON a.id = z.recording_attachment_id
GROUP BY 1 ORDER BY 1;
```

Якщо > 5 GB/month — розглянути S3 migration або retention policy (keep 3 місяці, після того — delete).

## Incident playbooks

### Webhook раптом перестав приходити

**Симптоми:** у Odoo немає нових `zadarma.call` записів, але клієнти кажуть що дзвонять.

**Action:**
1. Перевір Zadarma webhook log: my.zadarma.com → Integrations → Webhooks → History
   - Якщо Zadarma показує 5xx від нашого server → Odoo проблема, див наступний пункт
   - Якщо Zadarma показує timeout → public URL недоступний ззовні
2. Перевір Odoo:
   ```bash
   docker exec <client>_web tail -100 /var/log/<client>/odoo.log | grep -iE "zadarma|webhook|traceback"
   ```
3. Якщо Odoo down → див platform INCIDENT_RESPONSE.md
4. Якщо public URL unreachable:
   ```bash
   curl -vI https://<client>.com/zadarma/webhook  # перевір ззовні
   ```

### Recording-и raptом перестали додаватись

**Симптоми:** дзвінки логуються але без MP3.

**Action:**
1. Перевір що NOTIFY_RECORD event увімкнений у webhook settings
2. Zadarma — перевір status «Call recording» у тарифі
3. Якщо `recording_url` заповнюється але download fails → можливо `allowed_ips` обмеження у Zadarma API — додай VPS IP
4. Manual download for specific call:
   ```python
   call = env['zadarma.call'].browse(<id>)
   call._fetch_recording()
   env.cr.commit()
   ```

### Click-to-call не працює у manager

**Action:**
1. Перевір Odoo user: Settings → Users → <user> → `Zadarma Extension`
2. Перевір Zadarma PBX — той extension існує і активний
3. Ручний тест API:
   ```python
   company = env['res.company'].browse(1)
   from odoo.addons.zadarma_odoo.api import ZadarmaAPI
   api = ZadarmaAPI(company.zadarma_user_key, company.zadarma_user_secret)
   result = api.click_to_call(sip_from='100', sip_to='+48XXXXXXXXX')
   print(result)  # очікуємо {'status': 'success', ...}
   ```

## Audit queries

### Missed calls без follow-up

```sql
SELECT z.id, z.caller_num, z.started_at, p.name as partner, l.name as lead
FROM zadarma_call z
LEFT JOIN res_partner p ON z.caller_partner_id = p.id
LEFT JOIN crm_lead l ON z.lead_id = l.id
WHERE z.disposition = 'no_answer'
  AND z.direction = 'in'
  AND z.started_at > NOW() - INTERVAL '7 days'
ORDER BY z.started_at DESC;
```

### Manager performance

```sql
SELECT u.login,
       COUNT(*) FILTER (WHERE z.direction = 'in') as incoming,
       COUNT(*) FILTER (WHERE z.direction = 'out') as outgoing,
       AVG(z.duration_sec) FILTER (WHERE z.disposition = 'answered') as avg_duration
FROM zadarma_call z
JOIN res_users u ON z.user_id = u.id
WHERE z.started_at > NOW() - INTERVAL '30 days'
GROUP BY u.login
ORDER BY incoming + outgoing DESC;
```

## SMS — статистика (модуль НЕ шле SMS)

Модуль не має власної моделі відправки SMS. Він показує статистику над стандартною `sms.sms` (view `views/sms_stats_views.xml`) + дашборд балансу TurboSMS (`zadarma_dashboard.py`). Саме надсилання — через стандартний Odoo `sms.sms` / TurboSMS-конектор.

Перевірка активності (стандартна таблиця Odoo):
```sql
SELECT state, COUNT(*)
FROM sms_sms
WHERE create_date > NOW() - INTERVAL '7 days'
GROUP BY state;
```

Delivery rate < 90% → перевір номера (phone format), content (чи немає суперблокованих слів), balance TurboSMS у дашборді.

## Backup specific

`zadarma.call` records — у standard PostgreSQL backup. `ir.attachment` MP3-files — у filestore (`/opt/<client>/odoo-data/filestore/`). Обидва backup-іться стандартним runbook.

## Посилання

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- Platform `runbooks/INCIDENT_RESPONSE.md`
- Zadarma status page: https://status.zadarma.com
