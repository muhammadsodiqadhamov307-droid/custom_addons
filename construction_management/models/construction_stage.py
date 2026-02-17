from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ConstructionStage(models.Model):
    _name = 'construction.stage'
    _description = 'Construction Stage'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id'


    name = fields.Char(string='Bosqich nomi', required=True, tracking=True)
    project_id = fields.Many2one('construction.project', string='Loyiha', required=True, ondelete='cascade', tracking=True)
    
    company_id = fields.Many2one('res.company', string='Kompaniya', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Valyuta', readonly=True)

    stage_type = fields.Selection([
        ('demontaj', 'Демонтаж'),
        ('montaj', 'Монтаж'),
        ('santehnika', 'Сантехника'),
        ('santehnika_acc', 'Сантехника аксессуары'),
        ('otoplenie', 'Отопление'),
        ('ventilyatsiya', 'Вентиляция'),
        ('elektrika', 'Электрика'),
        ('elektrika_acc', 'Электрика аксессуары'),
        ('pol', 'Пол'),
        ('patalok', 'Паталок'),
        ('kafel', 'Кафель'),
        ('dvery', 'Двери'),
        ('obshivka', 'Обшивка стен'),
        ('malyar', 'Маларные работы'),
        ('mebel', 'Мебель'),
        ('tehnika', 'Бытовая техника'),
        ('other', 'Питание - прочие расходы'),
    ], string='Bosqich turi', default='other', tracking=True, group_expand='_group_expand_stage_type')



    state = fields.Selection([
        ('pending', 'Ожидание'),
        ('in_progress', 'В процессе'),
        ('completed', 'Завершено'),
        ('blocked', 'Заблокировано')
    ], string='Holat', default='pending', tracking=True)
    
    start_date = fields.Date(string='Boshlanish sanasi')
    end_date = fields.Date(string='Tugash sanasi')
    actual_end_date = fields.Date(string='Haqiqiy tugash sanasi')
    
    estimated_budget = fields.Float(string='Taxminiy byudjet')
    actual_cost = fields.Float(string='Haqiqiy xarajat', compute='_compute_actual_cost', store=True)
    progress = fields.Float(string='Jarayon (%)')
    
    material_ids = fields.One2many('construction.stage.material', 'stage_id', string='Materiallar')
    service_ids = fields.One2many('construction.stage.service', 'stage_id', string='Xizmatlar')
    task_ids = fields.One2many('construction.stage.task', 'stage_id', string='Vazifalar')
    image_ids = fields.One2many('construction.stage.image', 'stage_id', string='Rasmlar')
    
    notes = fields.Text(string='Izohlar')
    responsible_user_id = fields.Many2one('res.users', string='Mas\'ul', tracking=True)

    def action_view_materials(self):
        self.ensure_one()
        return {
            'name': 'Materials',
            'type': 'ir.actions.act_window',
            'res_model': 'construction.stage.material',
            'view_mode': 'tree,form',
            'domain': [('stage_id', '=', self.id)],
            'context': {'default_stage_id': self.id},
        }

    def action_view_services(self):
        self.ensure_one()
        return {
            'name': 'Services',
            'type': 'ir.actions.act_window',
            'res_model': 'construction.stage.service',
            'view_mode': 'tree,form',
            'domain': [('stage_id', '=', self.id)],
            'context': {'default_stage_id': self.id},
        }

    @api.depends('material_ids.total_cost', 'service_ids.total_cost')
    def _compute_actual_cost(self):
        for record in self:
            material_cost = sum(record.material_ids.mapped('total_cost'))
            service_cost = sum(record.service_ids.mapped('total_cost'))
            record.actual_cost = material_cost + service_cost

    def action_start(self):
        self.write({'state': 'in_progress', 'start_date': fields.Date.today()})

    def action_complete(self):
        self.write({'state': 'completed', 'actual_end_date': fields.Date.today(), 'progress': 100})

    def action_block(self):
        self.write({'state': 'blocked'})

    def _check_material_availability(self):
        # Helper to check if everything planned is reserved or consumed
        self.ensure_one()
        for material in self.material_ids:
             if material.state not in ['reserved', 'consumed']:
                 return False
        return True

    @api.model
    def _group_expand_stage_type(self, stages, domain, order):
        return [key for key, val in self._fields['stage_type'].selection]

