from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    telegram_chat_id = fields.Char(string='Telegram Chat ID', index=True, help="Telegram Chat ID for this partner (User or Client)")
    construction_role = fields.Selection([
        ('client', 'Mijoz'),
        ('manager', 'Boshqaruvchi')
    ], string='Qurilish dagi roli', default='client', required=True, help="Select the role of this contact in the construction system.")
