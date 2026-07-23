{
    'name': 'Fayna Zadarma Telephony',
    'version': '17.0.1.14.0',
    'category': 'CRM',
    'summary': 'Fayna Digital — інтеграція хмарної АТС Zadarma з Odoo CRM: автозбереження дзвінків, chatter, SMS, аналітика',
    'description': """
Fayna Zadarma Telephony
=======================

Повна інтеграція хмарної АТС Zadarma з Odoo 17 CRM.

Ключові можливості
------------------
* Автоматичне збереження всіх вхідних/вихідних дзвінків до партнера та lead
* Click-to-call із картки партнера (через Zadarma API)
* Запис розмов — автоматичний download MP3 у chatter
* Автоматичне створення lead при пропущеному дзвінку з нового номера
* SMS через Zadarma + статистика доставки
* Zadarma Import — bulk import історичних дзвінків
* Автодетекція власника дзвінка (по internal extension → res.users)

Автор: Fayna Digital — Volodymyr Shevchenko
Ліцензія: LGPL-3
    """,
    'author': 'Fayna Digital — Volodymyr Shevchenko',
    'website': 'https://fayna.agency',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'crm',
        'mail',
        'phone_validation',
        'sms',
    ],
    'data': [
        'security/zadarma_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/zadarma_views.xml',
        'views/sms_stats_views.xml',
        'views/res_company_views.xml',
        'views/res_users_views.xml',
        'views/partner_lead_views.xml',
        'views/zadarma_import_views.xml',
        'views/zadarma_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'zadarma_odoo/static/src/scss/zadarma_list.scss',
        ],
    },
    'installable': True,
    'application': True,
    'post_init_hook': 'post_init_hook',
}
