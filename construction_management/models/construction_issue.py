from odoo import models, fields, api, _

class ConstructionIssue(models.Model):
    _name = 'construction.issue'
    _description = 'Construction Issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    
    name = fields.Char(string='Muammo', required=True, copy=False, readonly=True, default=lambda self: _('Yangi'))
    project_id = fields.Many2one('construction.project', string='Loyiha', required=True, tracking=True)
    stage_id = fields.Many2one('construction.stage', string='Bosqich', tracking=True)
    task_id = fields.Many2one('construction.work.task', string='Vazifa', tracking=True)
    reported_by = fields.Many2one('res.users', string='Yuborgan', readonly=True, tracking=True, default=lambda self: self.env.user)
    description = fields.Text(string='Muammo tavsifi', required=True)
    priority = fields.Selection([
        ('low', 'Past'),
        ('medium', 'O\'rta'),
        ('high', 'Yuqori')
    ], string='Prioritet', default='medium', tracking=True)
    state = fields.Selection([
        ('new', 'Yangi'),
        ('in_progress', 'Ko\'rib chiqilmoqda'),
        ('resolved', 'Hal bo\'ldi'),
        ('canceled', 'Bekor')
    ], string='Holat', default='new', tracking=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Rasmlar')
    resolved_at = fields.Datetime(string='Hal qilingan vaqti', readonly=True)
    
    # Notification Tracking
    notify_chat_id = fields.Char(string='Notification Chat ID')
    notify_message_id = fields.Char(string='Notification Message ID')
    
    @api.model
    def create(self, vals):
        if vals.get('name', _('Yangi')) == _('Yangi'):
            vals['name'] = self.env['ir.sequence'].next_by_code('construction.issue') or _('Yangi')
        return super(ConstructionIssue, self).create(vals)
    
    def write(self, vals):
        if vals.get('state') == 'resolved':
            for record in self:
                if record.state != 'resolved':
                    vals['resolved_at'] = fields.Datetime.now()
        return super(ConstructionIssue, self).write(vals)
