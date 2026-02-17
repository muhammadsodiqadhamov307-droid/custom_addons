from odoo import models, fields, api, _

class ConstructionFinancialReportWizard(models.TransientModel):
    _name = 'construction.financial.report.wizard'
    _description = 'Construction Financial Report Wizard'

    project_id = fields.Many2one('construction.project', string='Project', required=True, readonly=True)
    line_ids = fields.One2many('construction.financial.report.line', 'wizard_id', string='Lines')
    
    currency_id = fields.Many2one('res.currency', related='project_id.currency_id', readonly=True)
    
    # Totals
    total_income = fields.Float(string='Jami kirim', compute='_compute_totals')
    total_expense = fields.Float(string='Jami chiqim', compute='_compute_totals')
    balance = fields.Float(string='Balans', compute='_compute_totals')

    @api.depends('line_ids.income', 'line_ids.expense')
    def _compute_totals(self):
        for record in self:
            record.total_income = sum(record.line_ids.mapped('income'))
            record.total_expense = sum(record.line_ids.mapped('expense'))
            record.balance = record.total_income - record.total_expense

class ConstructionFinancialReportLine(models.TransientModel):
    _name = 'construction.financial.report.line'
    _description = 'Construction Financial Report Line'
    _order = 'date asc, id asc'

    wizard_id = fields.Many2one('construction.financial.report.wizard', string='Wizard', required=True, ondelete='cascade')
    
    date = fields.Date(string='Sana')
    description = fields.Char(string='Izoh')
    income = fields.Float(string='Kirim')
    expense = fields.Float(string='Chiqim')
    balance = fields.Float(string='Balans', group_operator=False)
    
    # Grouping key
    group_name = fields.Char(string='Moliyalashtirish manbai')
    
    currency_id = fields.Many2one('res.currency', related='wizard_id.currency_id', readonly=True)
