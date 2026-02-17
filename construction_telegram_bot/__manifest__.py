{
    'name': 'Construction Telegram Bot',
    'version': '17.0.1.0.1',
    'category': 'Construction/Tools',
    'summary': 'Telegram Bot integration for Construction Management',
    'description': """
        Integrates Construction Management with Telegram Bot.
        - Manage Projects and Stages from Telegram
        - Add Materials and Services via simple text commands
    """,
    'author': 'Antigravity',
    'depends': ['base', 'construction_management'],
    'data': [
        'data/ir_config_parameter.xml',
        # 'data/gemini_param.xml',
        'data/bot_token.xml',
        'views/res_users_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
