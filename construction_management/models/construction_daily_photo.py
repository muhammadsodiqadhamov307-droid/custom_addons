from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ConstructionDailyPhoto(models.Model):
    _name = 'construction.daily.photo'
    _description = 'Construction Daily Photos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Rasm raqami', required=True, copy=False, readonly=True, default=lambda self: _('Draft'))
    date = fields.Date(string='Sana', required=True, default=fields.Date.context_today)
    project_id = fields.Many2one('construction.project', string='Loyiha', required=True, index=True)
    company_id = fields.Many2one('res.company', string='Kompaniya', required=True, default=lambda self: self.env.company)
    
    daily_report_text = fields.Text(string="Kunlik hisobot matni")
    
    line_ids = fields.One2many('construction.daily.photo.line', 'photo_id', string='Rasmlar')

    _sql_constraints = [
        ('project_date_uniq', 'unique (project_id, date)', 'Bu loyiha uchun bugungi sana bo‘yicha rasmlar allaqachon mavjud!')
    ]

    @api.model
    def create(self, vals):
        if vals.get('name', _('Draft')) == _('Draft'):
            vals['name'] = self.env['ir.sequence'].next_by_code('construction.daily.photo') or _('Draft')
        return super(ConstructionDailyPhoto, self).create(vals)

    @api.model
    def get_or_create_today(self, project_id):
        today = fields.Date.context_today(self)
        record = self.search([
            ('project_id', '=', project_id),
            ('date', '=', today)
        ], limit=1)
        
        if not record:
            record = self.create({
                'project_id': project_id,
                'date': today
            })
        return record


class ConstructionDailyPhotoLine(models.Model):
    _name = 'construction.daily.photo.line'
    _description = 'Construction Daily Photo Line'

    photo_id = fields.Many2one('construction.daily.photo', string='Photo Header', required=True, ondelete='cascade')
    
    image = fields.Binary(string="Rasm", required=True)
    caption = fields.Text(string="Izoh")
    
    stage_id = fields.Many2one('construction.stage', string='Bosqich', domain="[('project_id', '=', parent.project_id)]")
    created_at = fields.Datetime(string='Yaratilgan vaqt', default=fields.Datetime.now)
    
    # Optional field for future linking
    pushed_stage_image_id = fields.Many2one('construction.stage.image', string="Bosqich rasmi", readonly=True)

    @api.model
    def create(self, vals):
        record = super(ConstructionDailyPhotoLine, self).create(vals)
        if record.stage_id:
            record._sync_to_stage_image()
        return record

    def write(self, vals):
        res = super(ConstructionDailyPhotoLine, self).write(vals)
        if 'stage_id' in vals or 'caption' in vals:
            for record in self:
                if record.stage_id:
                    record._sync_to_stage_image()
        return res

    def _sync_to_stage_image(self):
        self.ensure_one()
        if not self.stage_id:
            return

        vals = {
            'name': self.caption or f"Daily Report {self.create_date}",
            'stage_id': self.stage_id.id,
            'image': self.image,
            'source': 'telegram', # Assuming most come from telegram
            'upload_date': self.created_at or fields.Datetime.now()
        }

        if self.pushed_stage_image_id:
            self.pushed_stage_image_id.write(vals)
        else:
            # Create new
            stage_image = self.env['construction.stage.image'].create(vals)
            # Avoid infinite recursion if stage image writes back (though not implemented yet)
            # Use SQL write to bypass write method if needed, but here simple write is fine
            # as this field is readonly in UI usually.
            super(ConstructionDailyPhotoLine, self).write({'pushed_stage_image_id': stage_image.id})
