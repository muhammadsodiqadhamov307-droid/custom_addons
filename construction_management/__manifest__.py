{
    'name': 'Construction Management',
    'version': '17.0.1.0.3',
    'category': 'Construction/Project Management',
    'summary': 'Manage construction projects, stages, materials, and payments',
    'description': """
        Construction Management Module
        ==============================
        Manage construction projects from start to finish.
        - Project tracking
        - Stage management (Demontaj, Montaj, etc.)
        - Material and Service tracking
        - Financials (Budget vs Actual, Payments)
    """,
    'author': 'Your Company Name',
    'license': 'LGPL-3',
    'depends': ['base', 'stock', 'sale_management', 'account', 'project', 'product', 'uom', 'hr'],
    'data': [
        'security/construction_security.xml',
        'security/ir.model.access.csv',
        'views/construction_menus.xml',
        'views/webapp_template.xml',
        'views/construction_project_views.xml',
        'views/construction_stage_views.xml',
        'views/construction_stage_product_template_views.xml',
        'wizard/construction_financial_report_wizard_views.xml',
        'views/construction_payment_views.xml',
        'views/construction_uom_views.xml',
        'views/construction_kirim_views.xml',
        'views/construction_delivery_views.xml',
        'views/construction_daily_photo_views.xml',
        'views/construction_work_task_views.xml',
        'views/construction_material_request_batch_views.xml',
        'views/construction_issue_views.xml',
        'data/construction_products.xml',
        'data/sequence.xml',
        'data/construction_issue_sequence.xml',
        'data/construction_stage_templates.xml',
        'reports/construction_financial_report.xml',
        'views/portal_templates.xml',
        'views/construction_file_views.xml',
        'data/construction_cron.xml',
    ],




    'assets': {
        'web.assets_backend': [
            'construction_management/static/src/css/kanban_style.css',
        ],
    },
    'installable': True,

    'application': True,
    'auto_install': False,
}
