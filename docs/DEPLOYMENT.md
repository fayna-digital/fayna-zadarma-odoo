# Fayna Zadarma Telephony — Deployment

## Prerequisites

- Odoo 17 Community
- Python 3.10+
- `base`, `crm`, `mail`, `sms` Odoo-модулі встановлені
- Public URL для webhook-а (ngrok OK для dev, production — real domain з SSL)
- Zadarma акаунт з активним тарифом (API access увімкнений у my.zadarma.com → Settings → API)

## Install

### Через git clone

```bash
cd /opt/<client>/custom-addons
sudo -u \#1000 git clone https://github.com/VladSh77/zadarma-odoo.git zadarma_odoo
```

### Через scp

```bash
scp -r zadarma-odoo/ <client>:/tmp/
ssh <client> "sudo cp -r /tmp/zadarma-odoo /opt/<client>/custom-addons/zadarma_odoo && sudo chown -R 1000:1000 /opt/<client>/custom-addons/zadarma_odoo"
```

### Install модуля

```bash
ssh <client> "docker exec <client>_web odoo -c /etc/odoo/odoo.conf -d <db> -i zadarma_odoo --stop-after-init --no-http 2>&1 | tail -20"
```

Очікуване у логах:
```
INFO odoo.modules.loading: loading zadarma_odoo/security/...
INFO odoo.modules.loading: loading zadarma_odoo/views/...
INFO odoo.modules.loading: Module zadarma_odoo loaded
INFO odoo.modules.registry: Registry loaded
```

### Python dependencies

```bash
docker exec <client>_web pip install --user requests
```

Зазвичай `requests` вже є у base Odoo image.

## Configuration

### Step 1: Zadarma credentials

У my.zadarma.com:
1. Перейти в **Settings → API**
2. Згенерувати **API Key** і **API Secret**
3. Copy обидва

У Odoo:
1. Settings → Users & Companies → Companies → edit active company
2. Вкладка **Zadarma**:
   - `Zadarma User Key`: <paste API Key>
   - `Zadarma User Secret`: <paste API Secret>
   - `Zadarma Webhook Secret`: згенеруй random string (openssl rand -hex 32) — збережи

### Step 2: User extensions

Для кожного manager:
1. Settings → Users → edit user
2. Поле `Zadarma Extension`: впиши внутрішній номер (e.g. `100`, `101`)
3. Save

**Важливо:** extension має collar збігатись з тим, що налаштований у Zadarma PBX для цього manager.

### Step 3: Webhook URL у Zadarma

У my.zadarma.com:
1. **Integrations → CRM / External systems → Webhooks**
2. Додати новий webhook:
   - URL: `https://<client>.com/zadarma/webhook`
   - Events: увімкнути NOTIFY_START, NOTIFY_ANSWER, NOTIFY_END, NOTIFY_RECORD
   - Secret: `<webhook secret з Odoo settings>`
3. Save

### Step 4: Verify

Зробити тестовий дзвінок на твій Zadarma-номер. У Odoo:
- Zadarma → Calls → має з'явитись запис протягом 2-5 секунд після NOTIFY_START
- Після end — duration, disposition
- Після 30-60 сек — recording attached

## Post-install

### Bulk-import історичних дзвінків (optional)

Якщо Zadarma використовувалась раніше, але без Odoo integration:

1. У Odoo: Zadarma → Wizards → **Import calls**
2. Встановити дати (from / to)
3. Run — імпорт через Statistics API, chunk 50, може зайняти 10-30 хв на тисячі дзвінків

### Monitoring Zadarma balance

Можна налаштувати cron який щоденно перевіряє баланс:
```python
# У Odoo shell
balance = env['zadarma.call'].check_balance()
if balance < 100:  # UAH
    env['mail.mail'].create({
        'subject': 'Zadarma balance low: ' + str(balance),
        'email_to': 'admin@fayna.agency',
        'body_html': '<p>Поповнити терміново</p>',
    }).send()
```

## Upgrade

```bash
# 1. Pull / copy новий код
ssh <client>
cd /opt/<client>/custom-addons/zadarma_odoo
sudo -u \#1000 git pull

# 2. Upgrade
docker exec <client>_web odoo -c /etc/odoo/odoo.conf -d <db> -u zadarma_odoo --stop-after-init --no-http

# 3. Restart
docker restart <client>_web
```

Див `fayna-digital-docs/runbooks/UPGRADE_PROD.md`.

## Uninstall

⚠️ `zadarma.call` records залишаться у БД але стануть недоступні через UI. Якщо потрібно реально їх видалити:
```sql
DROP TABLE zadarma_call CASCADE;
DROP TABLE zadarma_import CASCADE;
-- Але це руйнівно — використовувати тільки при повному exit з Zadarma-ї
```

## Troubleshooting

### Webhook не приходить

1. Перевір Public URL: `curl -X POST https://<client>.com/zadarma/webhook -d '{}'` — має відповісти 400 Bad Request (означає що endpoint живий)
2. Перевір Zadarma webhook log: my.zadarma.com → Integrations → Webhooks → History
3. Перевір Odoo log: `docker exec <client>_web tail -100 /var/log/<client>/odoo.log | grep zadarma`
4. Часто — SSL cert недоступний з Zadarma server (у них свій allowlist). Перевір з-за межі: `curl -vI https://<client>.com`

### Signature verification fails

- Webhook secret у Odoo settings ≠ секрет у Zadarma webhook config. Перевір exact match (пробіли / перенос строк!)

### Recording не attach-ється

- Recording availability затримується 30-60 сек після кінця розмови. Відчекай.
- Перевір що у Zadarma тарифі увімкнено «Call recording»
- Check `ir.attachment` для file — можливо вже збережено, але не пов'язано з `recording_attachment_id`

### Click-to-call не працює

- Manager не має `zadarma_extension` заповненого — перевір user profile
- Manager's extension не налаштований у Zadarma PBX — перевір там
- Call-to-extension блокується налаштуваннями `allowed_ips` у Zadarma API — додай IP свого VPS у whitelist

## Посилання

- [ARCHITECTURE.md](ARCHITECTURE.md)
- Zadarma API docs: https://zadarma.com/support/api/
- Platform `runbooks/UPGRADE_PROD.md`
