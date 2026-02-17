from odoo import models, fields, api

class ConstructionStageImage(models.Model):
    _name = 'construction.stage.image'
    _description = 'Stage Image'
    _order = 'upload_date desc'

    name = fields.Char(string='Description')
    stage_id = fields.Many2one('construction.stage', string='Stage', ondelete='cascade')
    task_id = fields.Many2one('construction.stage.task', string='Task', domain="[('stage_id', '=', stage_id)]")
    image = fields.Binary(string='Image', required=True, attachment=True)
    uploaded_by = fields.Many2one('res.users', string='Uploaded By', default=lambda self: self.env.user)
    upload_date = fields.Datetime(string='Upload Date', default=fields.Datetime.now)
    source = fields.Selection([
        ('odoo', 'Odoo'),
        ('telegram', 'Telegram')
    ], string='Source', default='odoo')

    @api.model
    def create(self, vals):
        if vals.get('task_id') and not vals.get('stage_id'):
            task = self.env['construction.stage.task'].browse(vals['task_id'])
            vals['stage_id'] = task.stage_id.id
        return super(ConstructionStageImage, self).create(vals)
