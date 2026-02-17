from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class StageMaterial(models.Model):
    _name = 'construction.stage.material'
    _description = 'Stage Material'

    stage_id = fields.Many2one('construction.stage', string='Bosqich', required=True, ondelete='cascade')
    task_id = fields.Many2one('construction.stage.task', string='Vazifa', ondelete='cascade')

    company_id = fields.Many2one('res.company', string='Kompaniya', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Valyuta', readonly=True)

    product_id = fields.Many2one('product.product', string='Mahsulot', required=True, domain=[('type', '=', 'product')])
    quantity_planned = fields.Float(string='Rejalashtirilgan miqdor', required=True, default=1.0)
    quantity_used = fields.Float(string='Ishlatilgan miqdor')
    uom_id = fields.Many2one('uom.uom', related='product_id.uom_id', string='O\'lchov birligi (Standard)', readonly=True)
    construction_uom_id = fields.Many2one('construction.uom', string='O\'lchov birligi')
    unit_price = fields.Float(string='Narx', readonly=False, store=True)
    date = fields.Date(string='Sana', required=True, default=fields.Date.context_today)

    total_cost = fields.Float(string='Jami xarajat', compute='_compute_total_cost', store=True)
    stock_picking_id = fields.Many2one('stock.picking', string='Ombor hujjati', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('reserved', 'Reserved'),
        ('consumed', 'Consumed'),
        ('returned', 'Returned')
    ], string='Holat', default='draft')
    notes = fields.Text(string='Izohlar')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.unit_price = self.product_id.lst_price
            # Try to auto-select UoM if names match? Optional.


    @api.depends('quantity_planned', 'unit_price')
    def _compute_total_cost(self):
        for record in self:
            record.total_cost = record.quantity_planned * record.unit_price


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'task_id' in vals and not vals.get('stage_id'):
                task = self.env['construction.stage.task'].browse(vals['task_id'])
                if task.stage_id:
                    vals['stage_id'] = task.stage_id.id
        return super(StageMaterial, self).create(vals_list)





class StageService(models.Model):
    _name = 'construction.stage.service'
    _description = 'Stage Service'

    stage_id = fields.Many2one('construction.stage', string='Bosqich', required=True, ondelete='cascade')
    task_id = fields.Many2one('construction.stage.task', string='Vazifa', ondelete='cascade')

    company_id = fields.Many2one('res.company', string='Kompaniya', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Valyuta', readonly=True)

    service_id = fields.Many2one('product.product', string='Xizmat', required=True, domain=[('type', '=', 'service')])
    description = fields.Text(string='Tavsif')
    employee_id = fields.Many2one('hr.employee', string='Xodim')
    
    quantity = fields.Float(string='Miqdor', default=1.0)
    uom_id = fields.Many2one('uom.uom', related='service_id.uom_id', string='O\'lchov birligi (Standard)', readonly=True)
    construction_uom_id = fields.Many2one('construction.uom', string='O\'lchov birligi')
    unit_price = fields.Float(string='Narx', related='service_id.list_price', readonly=False, store=True)
    
    total_cost = fields.Float(string='Jami xarajat', compute='_compute_total_cost', store=True)
    
    date_start = fields.Datetime(string='Boshlanish sanasi')
    date_end = fields.Datetime(string='Tugash sanasi')
    date = fields.Date(string='Xarajat sanasi', required=True, default=fields.Date.context_today)
    
    state = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed')
    ], string='Holat', default='planned')
    notes = fields.Text(string='Izohlar')

    is_done = fields.Boolean(string='Bajarildi')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'task_id' in vals and not vals.get('stage_id'):
                task = self.env['construction.stage.task'].browse(vals['task_id'])
                if task.stage_id:
                    vals['stage_id'] = task.stage_id.id
        return super(StageService, self).create(vals_list)

    @api.depends('quantity', 'unit_price')
    def _compute_total_cost(self):
        for record in self:
            record.total_cost = record.quantity * record.unit_price

    def action_toggle_done(self):
        for record in self:
            record.is_done = not record.is_done
            record.state = 'completed' if record.is_done else 'planned'



class StageTask(models.Model):
    _name = 'construction.stage.task'
    _description = 'Stage Task'
    _order = 'sequence, id'

    stage_id = fields.Many2one('construction.stage', string='Bosqich', required=True, ondelete='cascade')
    name = fields.Char(string='Vazifa nomi', required=True)
    description = fields.Text(string='Tavsif')
    sequence = fields.Integer(string='Ketma-ketlik', default=10)

    company_id = fields.Many2one('res.company', string='Kompaniya', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Valyuta', readonly=True)

    completed = fields.Boolean(string='Bajarildi')
    assigned_to = fields.Many2one('res.users', string='Biriktirilgan')
    deadline = fields.Date(string='Muddati')
    completed_date = fields.Datetime(string='Bajarilgan sana', readonly=True)
    
    material_ids = fields.One2many('construction.stage.material', 'task_id', string='Materiallar')
    service_ids = fields.One2many('construction.stage.service', 'task_id', string='Xizmatlar')
    
    total_cost = fields.Float(string='Jami xarajat', compute='_compute_total_cost', store=True)
    limit_content = fields.Html(string='Kontent xulosasi', compute='_compute_content_summary')
    progress = fields.Float(string='Jarayon (%)', compute='_compute_progress', store=True)

    image_ids = fields.One2many('construction.stage.image', 'task_id', string='Rasmlar')

    @api.depends('service_ids.is_done', 'service_ids')
    def _compute_progress(self):
        for record in self:
            services = record.service_ids
            total = len(services)
            if total > 0:
                # Use string filter for optimization and safety
                done = len(services.filtered('is_done'))
                record.progress = (done / total) * 100
            else:
                record.progress = 0

    @api.depends('material_ids.total_cost', 'service_ids.total_cost')
    def _compute_total_cost(self):
        for record in self:
            materials_cost = sum(record.material_ids.mapped('total_cost'))
            services_cost = sum(record.service_ids.mapped('total_cost'))
            record.total_cost = materials_cost + services_cost

    @api.depends('material_ids', 'service_ids', 'name')
    def _compute_content_summary(self):
        for record in self:
            lines = []
            if record.name == 'Материалы для работы':
                lines.append("<strong>Materials:</strong>")
                for m in record.material_ids:
                    lines.append(f"<div>{m.product_id.name}: {m.total_cost}</div>")
            elif record.name == 'Оплата мастерам за работы':
                lines.append("<strong>Services:</strong>")
                for s in record.service_ids:
                     lines.append(f"<div>{s.service_id.name}: {s.total_cost}</div>")
            
            record.limit_content = "".join(lines) if len(lines) > 1 else False




    def toggle_completed(self):
        for record in self:
            record.completed = not record.completed
            if record.completed:
                record.completed_date = fields.Datetime.now()
            else:
                record.completed_date = False

    def action_back(self):
        self.ensure_one()
        return {
            'name': 'Project Tasks',
            'type': 'ir.actions.act_window',
            'res_model': 'construction.stage.task',
            'view_mode': 'kanban,form',
            'domain': [('stage_id.project_id', '=', self.stage_id.project_id.id)],
            'context': {'default_project_id': self.stage_id.project_id.id},
            'target': 'current',
        }




