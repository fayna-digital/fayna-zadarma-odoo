# Odoo 17 Zadarma Telefonia — Autologowanie, Nagrania, Click-to-Call, SMS

![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20Community-purple)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Zadarma](https://img.shields.io/badge/Zadarma-API%20v1-red)
![License](https://img.shields.io/badge/License-LGPL--3-green.svg)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

**Opracowane przez [Fayna Digital](https://www.fayna.agency) dla CampScout**
**Autor: Volodymyr Shevchenko**

---

Integracja chmurowej centrali **Zadarma** z Odoo 17 CRM. Każde połączenie
przychodzące i wychodzące jest automatycznie rejestrowane i wiązane z
`res.partner` oraz `crm.lead`, z pełnym nagraniem MP3 dołączanym do czatu.
Obsługuje click-to-call z karty partnera, analitykę SMS (nad `sms.sms`) z
pulpitami balansu TurboSMS oraz automatyczne tworzenie leadów przy nieodebranych
połączeniach z nieznanych numerów.

Referencyjne wdrożenie: [CampScout](https://campscout.eu).

---

## Możliwości

### Połączenia
- **Autologowanie połączeń** — webhook Zadarma → rekordy `zadarma.call` (`NOTIFY_END`, `NOTIFY_OUT_END`, `NOTIFY_RECORD`)
- **Nagrania rozmów** — MP3 automatycznie pobierane i dołączane do czatu partnera/leada
- **Click-to-call** — przycisk w formularzu `res.partner` → Zadarma Callback API inicjuje połączenie na wewnętrzny numer menedżera
- **Auto-lead dla nieznanych** — nieznany abonent → nowy `crm.lead` («Połączenie: +xxx»), przypisany menedżerowi po wewnętrznym numerze
- **Auto-lead na answered** — odebrano połączenie z istniejącym kontaktem bez lea → automatycznie tworzony `crm.lead` (`Rozmowa: {partner.name}`)
- **First-call ownership** — pierwsze _odebrane_ outbound od menedżera → `partner.user_id` ustawiane automatycznie
- **user_id fallback chain** — nieodebrane przychodzące bez SIP → połączenie przypisywane `partner.user_id` (lub `lead.user_id`)
- **Multi-extension mapping** — N:1 `res.users` ↔ extension przez osobną model `res.users.zadarma.extension`

### Wizualizacja
- **Kolorowe oznaczanie wierszy** przez asset SCSS (`web.assets_backend`):
  - 🔴 Spam (phone w `phone.blacklist`)
  - 🟡 Nieodebrane (dowolny `status != 'answered'`)
  - ⚪ Bez właściciela (`answered` bez `user_id`)
  - 🟦 / 🟢 / 🟣 do 3 menedżerów — kolor konfigurowany per-user (`res.users.zadarma_manager_slot`), bez hardkodu nazw w kodzie
- **Legenda widoku wyszukiwania** — filtry po kierunku/statusie/menedżerze/dacie/nagraniu, group_by

### Bezpieczeństwo i integralność
- **Weryfikacja HMAC-SHA1** webhook (warning mode → enforce po logach prod)
- **UNIQUE constraint** na `call_id` (dedup na poziomie PostgreSQL)
- **Multi-company** — pole `company_id` + `ir.rule` z domain `('|', company_id=False, company_id in company_ids)`

### SMS
- **Analityka SMS** — widoki nad standardowym `sms.sms` (drzewo/formularz/wyszukiwanie): statusy dostarczenia, podział po partnerze, pola TurboSMS (`kw_turbosms_*`)
- **Pulpit balansu TurboSMS** — model `zadarma.dashboard` pokazuje balans Zadarma + TurboSMS
- ⚠️ Moduł **nie wysyła SMS samodzielnie** — wysyłkę wykonuje standardowy stack SMS Odoo / zewnętrzny konektor TurboSMS; tutaj tylko statystyki i balanse

### Inne
- **Import masowy** — chunk-import przez Statistics API Zadarma z postępem i resume
- **Śledzenie wyniku** — answered / no answer / cancel / busy / failed / call failed
- **Chatter** na formularzu połączenia — `mail.thread` + `mail.activity.mixin`
- **Priorytety cron** (10/20/30/40) — recover_recordings → backfill_user_ids → rematch_orphan_leads → rematch_orphan_calls, serializuje wywołania API
- **Indeksy DB** na `date_start`, `status`, `direction`, `user_id` dla szybkiego widoku listy

---

## Architektura

```
zadarma-odoo/
├── __init__.py                          # importuje controllers, models + post_init_hook
├── __manifest__.py                      # 17.0.1.14.0, deklaracja bundle assets
├── hooks.py                             # post_init_hook (wyłącza binotel duplicate buttons)
├── models/
│   ├── zadarma_call.py                  # Główna model + _inherit mail.thread + _sql_constraints UNIQUE
│   ├── zadarma_import.py                # TransientModel wizard importu masowego
│   ├── zadarma_dashboard.py             # Model balansów Zadarma + TurboSMS
│   ├── crm_lead.py                      # Rozszerzenie crm.lead (orphan re-match)
│   ├── mail_activity.py                 # zadarma_call_id back-ref (idempotency)
│   ├── partner_lead_ext.py              # zadarma_call_count z @api.depends
│   ├── res_company.py                   # Dane uwierzytelniające Zadarma
│   ├── res_partner.py                   # Rozszerzenie partnera
│   ├── res_users.py                     # SIP extension (legacy)
│   └── res_users_zadarma_extension.py   # N:1 user → extensions mapping
├── controllers/
│   └── webhook.py                       # /zadarma/webhook + weryfikacja HMAC (warning mode)
├── data/
│   └── ir_cron.xml                      # 4 crony z offsetem priorytetu
├── views/
│   ├── zadarma_views.xml                # Tree + form + search + actions
│   ├── zadarma_dashboard_views.xml      # Modal balansów
│   ├── zadarma_import_views.xml         # Wizard importu
│   ├── sms_stats_views.xml              # Analityka SMS
│   ├── res_company_views.xml            # Credentials
│   ├── res_users_views.xml              # UI mapowania SIP
│   └── partner_lead_views.xml           # Smart button na partner/lead
├── security/
│   ├── zadarma_security.xml             # Grupy + ir.rule multi-company
│   └── ir.model.access.csv
├── static/
│   ├── description/
│   └── src/scss/zadarma_list.scss       # Kolorowanie wierszy per color_tag
└── docs/
    ├── ARCHITECTURE.md
    ├── DEPLOYMENT.md
    ├── RUNBOOK.md
    └── TZ.md                            # Checklist funkcji (✅ / 🔲 / ❌)
```

---

## Stack technologiczny

| Komponent | Technologia |
|-----------|-----------|
| Framework ERP | Odoo 17.0 Community |
| Główne zależności | `base`, `crm`, `mail`, `phone_validation`, `sms` |
| Centrala | Zadarma cloud (SIP + webhooks) |
| Wersja API | Zadarma API v1 |
| Podpis | HMAC-SHA1 |
| Format nagrania | MP3 (zapisywane jako `ir.attachment` na stałe) |
| Auto-atybucja | Wewnętrzny numer → `res.users.zadarma_extension` |
| Wersja modułu | 17.0.1.14.0 |
| Licencja | LGPL-3.0 |

---

## Instalacja

### 1. Klonowanie do custom-addons

```bash
cd /opt/<client>/custom-addons
git clone https://github.com/fayna-digital/fayna-zadarma-odoo.git zadarma_odoo
```

### 2. Instalacja modułu

```bash
docker exec <client>_web odoo -c /etc/odoo/odoo.conf -d <db> \
    -i zadarma_odoo --stop-after-init --no-http
```

Lub przez UI: **Aplikacje → Aktualizuj listę aplikacji → szukaj `Zadarma` → Zainstaluj**.

### 3. Restart Odoo

```bash
docker restart <client>_web
```

---

## Konfiguracja

### Krok 1 — Generowanie danych uwierzytelniających API Zadarma

1. Zaloguj się na [my.zadarma.com](https://my.zadarma.com) → **Ustawienia → API**
2. Wygeneruj **API Key** oraz **API Secret**
3. Skopiuj oba

### Krok 2 — Konfiguracja w Odoo

**Ustawienia → Użytkownicy i firmy → Firmy → [aktywna firma] → zakładka «Zadarma»**:

| Pole | Wartość |
|-------|-------|
| Zadarma User Key | wklej API Key |
| Zadarma User Secret | wklej API Secret |
| Zadarma Webhook Secret | losowo wygenerowany ciąg (np. `openssl rand -hex 32`) |

### Krok 3 — Przypisanie wewnętrznych numerów użytkownikom

Dla każdego menedżera:

1. **Ustawienia → Użytkownicy → [użytkownik] → zakładka «Zadarma»**
2. **Wewnętrzny numer Zadarma** = wewnętrzny numer (np. `100`, `101`)
3. Musi się zgadzać z wewnętrznym numerem skonfigurowanym w centrali Zadarma dla tego menedżera

### Krok 4 — Rejestracja webhook w Zadarma

[my.zadarma.com](https://my.zadarma.com) → **Integracje → CRM / Systemy zewnętrzne → Webhooks**:

- URL: `https://<your-odoo>.com/zadarma/webhook`
- Zdarzenia: włącz `NOTIFY_START`, `NOTIFY_ANSWER`, `NOTIFY_END`, `NOTIFY_RECORD`
- Secret: wklej ten sam webhook secret z ustawień Odoo

---

## Użycie

### Połączenie przychodzące

1. Klient dzwoni na Twój numer Zadarma
2. Centrala Zadarma routuje → wybiera wewnętrzny numer menedżera
3. Webhook `/zadarma/webhook` otrzymuje sekwencję zdarzeń:
   - `NOTIFY_START` → tworzony `zadarma.call`, identyfikowany partner lub automatycznie tworzony lead
   - `NOTIFY_ANSWER` → menedżer atrybuowany po wewnętrznym numerze
   - `NOTIFY_END` → zapisywany czas trwania, wynik
   - `NOTIFY_RECORD` → pobierane MP3, dołączane do czatu
4. W czacie partnera/leada pojawia się wiadomość ze szczegółami połączenia + odtwarzaczem audio

### Click-to-call

1. Otwórz formularz partnera (`res.partner`)
2. Kliknij przycisk **Zadzwoń** (ikona telefonu obok numeru)
3. Zadarma API inicjuje połączenie:
   - Najpierw dzwoni na wewnętrzny numer menedżera
   - Po odebraniu → łączy z PSTN partnera
4. Następuje standardowy łańcuch webhook (tylko z `direction='out'`)

### SMS

Moduł **nie ma własnej modelu wysyłki SMS** i nie wysyła wiadomości sam. Dostarcza:

- **Analitykę nad `sms.sms`** — osobne menu z drzewem / formularzem / wyszukiwaniem po standardowych rekordach SMS Odoo, z polami TurboSMS (`kw_turbosms_message_id`, `kw_turbosms_sms_or_viber`, `kw_turbosms_response_status`) dla używających konektora `kw_sms_turbosms`.
- **Pulpit balansu** (`zadarma.dashboard`) — balans Zadarma + balans TurboSMS (zapytanie do `api.turbosms.ua/user/balance.json`).

Samo wysyłanie SMS odbywa się przez standardowy stack SMS Odoo (`sms.sms`) lub zewnętrzny konektor TurboSMS — nie przez ten moduł.

### Import masowy połączeń

**Menu → Zadarma → Import połączeń**:

1. Podaj zakres dat (od / do)
2. Kliknij **Uruchom** — używa Statistics API Zadarma, rozmiar chunku 50
3. Pasek postępu się aktualizuje; można zatrzymać i wznowić
4. Dla tysięcy połączeń — 10-30 minut

---

## Webhook Flow (technicznie)

```
1. Klient dzwoni na +48 XXX XXX XXX (Twój numer Zadarma)
2. Centrala Zadarma routuje połączenie
3. POST https://<odoo>/zadarma/webhook
4. Controller _verify_signature_warning() — liczy oba warianty HMAC,
   loguje match/mismatch (warning mode; NIE blokuje żądania w v17.0.1.14.0)
5. Dyspozytoryzacja po typie zdarzenia (v17.0.1.14.0):
   ├── NOTIFY_END (przychodzące + outbound bez internal):
   │   ├── Określenie kierunku po długości caller_id (≤5 cyfr = outbound)
   │   ├── Normalizacja telefonu → szukanie res.partner (SQL LIKE %suffix% po kw_phone_cleaned)
   │   ├── _find_existing_lead → otwarty lead dla partnera/telefonu
   │   ├── user fallback chain: SIP → partner.user_id → lead.user_id
   │   ├── Auto-create lead:
   │   │   ├── nie znaleziono ani partnera ani lea → "Połączenie: +xxx"
   │   │   └── answered + partner ale bez lea → "Rozmowa: {partner.name}"
   │   ├── First-call ownership: answered outbound + partner bez user_id
   │   │   → partner.sudo().write({'user_id': user.id})
   │   ├── Utworzenie zadarma.call (UNIQUE call_id constraint)
   │   ├── Chatter post na target (lead lub partner)
   │   ├── Missed → mail.activity «Oddzwoń» (idempotent przez zadarma_call_id)
   │   └── _compute_color → spam / voicemail / orphan / manager / neutral
   │
   ├── NOTIFY_OUT_END (outbound z PBX-internal):
   │   └── Ta sama logika, z sip = data['internal']
   │
   └── NOTIFY_RECORD:
       ├── _zadarma_fetch_recording_url(call_id, pbx_call_id) → tymczasowy URL
       ├── _zadarma_download_recording → ir.attachment (permanent)
       └── call.write({'recording_url': '/web/content/...'})
6. Zwrot 200 OK
```

---

## Click-to-Call Flow (technicznie)

```
1. Użytkownik klika przycisk Zadzwoń w formularzu res.partner
   (button name="action_zadarma_call" w partner_lead_views.xml)
2. Backend: res.partner.action_zadarma_call() (models/res_partner.py):
   a. Określenie abonenta: user.zadarma_primary_extension
      (fallback → legacy user.zadarma_internal_number)
   b. Określenie odbiorcy: '+' + cyfry z self.phone / self.mobile
   c. Budowa podpisu HMAC-SHA1 (key:signature w nagłówku Authorization)
   d. GET https://api.zadarma.com/v1/request/callback/?from=<ext>&to=<phone>&sip=<ext>
3. Zadarma Callback API:
   a. Inicjuje połączenie na SIP-wewnętrzny numer menedżera
   b. Po odebraniu przez menedżera → łączy z PSTN odbiorcy
4. Następuje zwykły łańcuch webhook przez NOTIFY_OUT_END (direction='out')
```

---

## Rozwój lokalny

```bash
git clone https://github.com/fayna-digital/fayna-zadarma-odoo.git
cd zadarma-odoo

# Tymczasowe Odoo z podłączonym modułem:
docker run -d --name test_odoo -v $(pwd)/..:/mnt/custom-addons \
    -p 8069:8069 odoo:17

# Symulacja webhook:
curl -X POST http://localhost:8069/zadarma/webhook \
    -d 'event=NOTIFY_START&call_start=2026-01-01+12:00:00&caller_id=+48123456789&called_did=+48987654321'
```

---

## Rozwiązywanie problemów

| Błąd | Przyczyna | Naprawa |
|-------|-------|-----|
| Webhook nie przychodzi | Publiczny URL niedostępny z Zadarma | `curl -vI https://<odoo>.com/zadarma/webhook` z zewnątrz; sprawdź SSL / firewall |
| Weryfikacja podpisu nie przechodzi | Niezgodność webhook secret | Zsynchronizuj secret między ustawieniami Odoo a Zadarma (dokładna zgodność, bez spacji) |
| Nagranie się nie dołącza | NOTIFY_RECORD nie włączony LUB taryfa nie obejmuje nagrywania | my.zadarma.com → Webhooks → włącz NOTIFY_RECORD; sprawdź taryfę |
| Pobieranie nagrania nie działa | Filtr `allowed_ips` Zadarma blokuje VPS | Dodaj IP Twojego VPS Odoo do whitelist API na my.zadarma.com |
| Click-to-call nic nie robi | Menedżerowi nie przypisano wewnętrznego numeru / nie skonfigurowano w centrali | Ustawienia → Użytkownicy → menedżer → ustaw `Wewnętrzny numer Zadarma`; sprawdź w centrali |
| SMS nie jest dostarczany | Niepoprawny format telefonu (wymagany E.164 `+XX...`) | Normalizuj przez `zadarma.call._normalize_phone(phone)` |
| Błędy 429 przy imporcie masowym | Limit API Zadarma (~60 żądań/min) | Wizard już dzieli na chunki po 50; jeśli limit nadal przekraczany — zwiększ interwał pauzy w `zadarma_import.py` |

---

## Dostęp

Moduł deklaruje dwie własne grupy (`security/zadarma_security.xml`):

| Grupa | XML id | Rozszerza |
|-------|--------|----------|
| User | `zadarma_odoo.group_zadarma_user` | `base.group_user` |
| Administrator | `zadarma_odoo.group_zadarma_admin` | `group_zadarma_user` (+ `base.user_root`, `base.user_admin`) |

Prawa dostępu do modeli (`security/ir.model.access.csv`) są powiązane ze standardowymi grupami Odoo, **nie** z grupami sales_team:

- **`base.group_user`** (dowolny wewnętrzny użytkownik):
  - `zadarma.call` — tylko odczyt
  - `zadarma.dashboard`, `res.users.zadarma.extension` — odczyt
- **`base.group_system`** (Settings / administrator):
  - `zadarma.call` — pełny dostęp (read/write/create/unlink)
  - `zadarma.import` — wizard importu masowego
  - `res.users.zadarma.extension` — pełny dostęp (mapowanie wewnętrznych numerów)

Multi-company widoczność połączeń zapewnia global `ir.rule` `zadarma_call_company_rule`
(`['|', ('company_id','=',False), ('company_id','in',company_ids)]`).

Dane uwierzytelniające Zadarma (`res.company.zadarma_api_secret`) są dostępne tylko użytkownikom z dostępem do ustawień firmy.

---

## Roadmap — Migracja na adapter-pattern

Ten moduł planowany jest do refaktoryzacji wg adapter pattern (ADR-003, wewnętrzna dokumentacja architektury Fayna Digital):

```
Przyszły stan:
  fayna_telephony_base (abstrakcyjnie: model połączenia, kontrakt providera)
    ├── fayna_telephony_zadarma  (ten moduł, zmiana nazwy)
    ├── fayna_telephony_binotel  (przyszłość)
    ├── fayna_telephony_ringostat (przyszłość)
    └── fayna_telephony_kyivstar (przyszłość)
```

Trigger do refaktoryzacji: gdy klient poprosi o innego providera. Obecnie nie blokuje.

---

## Ekosystem modułów

| Moduł pokrewny | Rola |
|----------------|------|
| [fayna-sendpulse-odoo](https://github.com/fayna-digital/fayna-sendpulse-odoo) | Pokrewny messenger (oba trafiają do Odoo CRM) |
| [fayna-omnichannel-bridge](https://github.com/fayna-digital/fayna-omnichannel-bridge) | Agregator omnichannel (głos na razie osobny kanał, nie przez most) |
| [campscout-management](https://github.com/VladSh77/campscout-management) | Używa do przychodzących połączeń sprzedażowych CampScout |

Szczegółowa dokumentacja architektoniczna — w wewnętrznym repozytorium Fayna Digital (prywatne).

---

## Licencja

**LGPL-3.0** — patrz [LICENSE](LICENSE) oraz [NOTICE.md](NOTICE.md). © Fayna Digital.

---

*Opracowane przez [Fayna Digital](https://www.fayna.agency) · Volodymyr Shevchenko*
