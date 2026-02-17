from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ConstructionFileCategory(models.Model):
    _name = 'construction.file.category'
    _description = 'File Category (Bo‘lim)'
    _order = 'name'

    name = fields.Char(string='Bo‘lim', required=True, translate=True)
    active = fields.Boolean(default=True, string='Faol')
    
import logging
_logger = logging.getLogger(__name__)

class ConstructionProjectFile(models.Model):
    _name = 'construction.project.file'
    _description = 'Project File'
    _order = 'upload_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Fayl nomi', required=True)
    project_id = fields.Many2one('construction.project', string='Loyiha', required=True, index=True)
    room_ref = fields.Char(string='Xona', required=True, index=True, help="Xona nomi yoki raqami (erkin matn)")
    category_id = fields.Many2one('construction.file.category', string='Bo‘lim', required=True, index=True)
    
    attachment_id = fields.Many2one('ir.attachment', string='Fayl (Texnik)', readonly=True)
    
    file_data = fields.Binary(string='Faylni yuklang', required=True, attachment=False)
    file_name = fields.Char(string='Fayl nomi')
    
    version = fields.Integer(string='Versiya (Int)', default=1, readonly=True)
    version_display = fields.Char(string='Versiya', compute='_compute_version_display', store=True)
    is_latest = fields.Boolean(string='Oxirgi Versiya', default=True, index=True)
    
    uploaded_by = fields.Many2one('res.users', string='Yuklagan', default=lambda self: self.env.user, readonly=True)
    upload_date = fields.Datetime(string='Yuklangan vaqt', default=fields.Datetime.now, readonly=True)
    
    note = fields.Text(string='Izoh')

    @api.depends('version')
    def _compute_version_display(self):
        for record in self:
            record.version_display = f"V{record.version}" if record.version else "V1"

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info(f"DEBUG: Construction Project File Create Vals: {vals_list}")
        for vals in vals_list:
            if 'uploaded_by' in vals:
                del vals['uploaded_by']
            vals['uploaded_by'] = self.env.user.id
            
            if 'upload_date' not in vals:
                vals['upload_date'] = fields.Datetime.now()
            
            # Versioning Logic
            project_id = vals.get('project_id')
            room_ref = vals.get('room_ref')
            category_id = vals.get('category_id')
            
            # Default version
            next_version = 1
            
            if project_id and room_ref and category_id:
                # Find previous versions
                domain = [
                    ('project_id', '=', project_id),
                    ('room_ref', '=', room_ref),
                    ('category_id', '=', category_id)
                ]
                existing_files = self.search(domain, order='version desc', limit=1)
                
                if existing_files:
                    next_version = (existing_files.version or 0) + 1
                    self.search(domain).write({'is_latest': False})
            
            vals['version'] = int(next_version)
            vals['is_latest'] = True
            
        records = super(ConstructionProjectFile, self).create(vals_list)
        
        # Post-create: generate attachments
        for record in records:
            if record.file_data:
                att_vals = {
                    'name': record.file_name or record.name,
                    'datas': record.file_data,
                    'res_model': 'construction.project.file',
                    'res_id': record.id,
                    'type': 'binary',
                }
                attachment = self.env['ir.attachment'].create(att_vals)
                record.write({'attachment_id': attachment.id})
                
        return records

    def write(self, vals):
        res = super(ConstructionProjectFile, self).write(vals)
        if 'file_data' in vals and vals['file_data']:
            for record in self:
                att_vals = {
                    'name': record.file_name or record.name,
                    'datas': record.file_data,
                    'res_model': 'construction.project.file',
                    'res_id': record.id,
                    'type': 'binary',
                }
                attachment = self.env['ir.attachment'].create(att_vals)
                record.sudo().write({'attachment_id': attachment.id})
        return res
