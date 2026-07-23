# PLAN — zadarma-odoo (план реалізації)

> Друга черга після docs/TZ.md. Що ВЖЕ зроблено — у CHANGELOG.md (Bug Д/recording/G, multi-ext — закриті).
> Модуль на проді (v17.0.1.13.0). Цей план — відкриті покращення.

## Dependency graph

```
[HMAC enforce] ── на базі warning-mode логів ── критичний, після 1-2 днів прод
[tests/] ── незалежний ── App Store requirement + safety net
[Hand-off chatter] ── на crm.lead.user_id зміні ── важливий
[Inbound recordings] ── панель Zadarma (НЕ код) ── зовнішня дія
[Adapter split] ── далеко ── тригер: інший провайдер
```

## Task List

### Phase 1: Стабільність (критичне)

- [ ] **HMAC enforce mode** — зараз WARNING (не блокує). Після 1-2 днів чистих прод-логів → enforce.
  - Acceptance: невалідний підпис → 403, валідний → обробка; нуль false-reject на тиждень
  - Files: `controllers/webhook.py`
- [ ] **tests/** — характеризаційні тести (зараз 0, pyproject fail_under=70)
  - Acceptance: webhook-диспетч (NOTIFY_END/OUT_END/RECORD), HMAC, merge_opportunity покриті; ≥70%
  - Files: `tests/test_webhook.py`, `tests/test_crm_merge.py`

### Checkpoint: Phase 1
HMAC enforce без false-reject, tests зелені ≥70%.

### Phase 2: UX/функції

- [ ] **Hand-off chatter** — зміна `crm.lead.user_id` → пост у chatter + activity новому власнику
- [ ] **Окрема вкладка дзвінків** на картці партнера (зараз лише smart-button лічильник)
- [ ] **CallerID rules UI** — поле `res.company` декларовано, але без UI
- [ ] **Синхронізувати версії** в README/ARCHITECTURE (10.0 → 13.0)

### Phase 3: Roadmap (далеко)

- [ ] **IVR + голосове привітання** UA+PL (GDPR warning для +48) — через Zadarma кабінет
- [ ] **Call analytics dashboard** — conversion rate, avg duration, missed % per manager
- [ ] **Adapter split** (`fayna_telephony_base` + `zadarma`) — ADR-003, тригер: інший провайдер
- [ ] **S3/зовнішнє сховище** для MP3 (зараз local ir.attachment)
- [ ] **Timezone handling** (Zadarma → UTC явно)

## Зовнішнє (не код)

- [ ] **Inbound recordings** — Zadarma панель: Internal numbers ext 100-105 + DID → «Record all calls» = Yes. Після цього NOTIFY_RECORD з `in_...` збережеться авто.

## Зв'язки
docs/TZ.md · docs/ARCHITECTURE.md
