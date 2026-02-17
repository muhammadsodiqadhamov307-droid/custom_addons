from odoo import models, fields, api, _

class ConstructionPayment(models.Model):
    _name = 'construction.payment'
    _description = 'Construction Payment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'payment_date desc, id desc'

    name = fields.Char(string='Payment Reference', copy=False, readonly=True, default=lambda self: _('New'))
    project_id = fields.Many2one('construction.project', string='Project', required=True, tracking=True)
    amount = fields.Float(string='Amount', required=True)
    payment_date = fields.Date(string='Payment Date', required=True, default=fields.Date.context_today)
    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('check', 'Check'),
        ('card', 'Card')
    ], string='Payment Method', default='bank_transfer', tracking=True)
    payment_type = fields.Selection([
        ('advance', 'Advance'),
        ('milestone', 'Milestone'),
        ('final', 'Final'),
        ('other', 'Other')
    ], string='Payment Type', default='milestone', tracking=True)
    related_stage_id = fields.Many2one('construction.stage', string='Related Stage', domain="[('project_id', '=', project_id)]")
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True)
    reference = fields.Char(string='External Reference')
    notes = fields.Text(string='Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('reconciled', 'Reconciled')
    ], string='State', default='draft', tracking=True)

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('construction.payment') or _('New')
        return super(ConstructionPayment, self).create(vals)

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_create_invoice(self):
        self.ensure_one()
        AccountMove = self.env['account.move']
        
        invoice = AccountMove.create({
            'move_type': 'out_invoice',
            'partner_id': self.project_id.customer_id.id,
            'invoice_date': self.payment_date,
            'invoice_line_ids': [(0, 0, {
                'name': f'Payment for {self.project_id.name} - {self.payment_type}',
                'quantity': 1,
                'price_unit': self.amount,
            })],
        })
        
        self.invoice_id = invoice.id
        self.state = 'reconciled'
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }
