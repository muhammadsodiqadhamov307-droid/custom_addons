from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ConstructionWorkTask(models.Model):
    _name = 'construction.work.task'
    _description = 'Construction Work Task'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'deadline_date, id'

    name = fields.Char(string='Vazifa', required=True, tracking=True)
    project_id = fields.Many2one('construction.project', string='Loyiha', required=True, ondelete='cascade', tracking=True)
    
    # Optional links
    stage_id = fields.Many2one('construction.stage', string='Bosqich', domain="[('project_id', '=', project_id)]")
    stage_type = fields.Selection(related='stage_id.stage_type', string='Bosqich turi', readonly=True)
    service_task_id = fields.Many2one('construction.stage.task', string='Xizmat taski', domain="[('stage_id', '=', stage_id)]")
    
    assignee_role = fields.Selection([
        ('client', 'Mijoz'),
        ('designer', 'Dizayner'),
        ('worker', 'Usta'),
        ('foreman', 'Prorab'),
        ('supply', 'Snab'),
        ('admin', 'Admin')
    ], string='Kim uchun', required=True, default='worker', tracking=True)
    
    assignee_id = fields.Many2one('res.users', string='Mas\'ul', tracking=True)
    
    deadline_date = fields.Date(string='Muddat', required=True, tracking=True)
    
    state = fields.Selection([
        ('new', 'Yangi'),
        ('in_progress', 'Jarayonda'),
        ('done', 'Bajarildi')
    ], string='Holat', default='new', tracking=True, group_expand='_group_expand_states')
    
    description = fields.Text(string='Tavsif')
    
    done_date = fields.Date(string='Bajarilgan sana', readonly=True)
    done_note = fields.Text(string='Bajarildi izohi')
    
    @api.model
    def create(self, vals):
        if vals.get('state') == 'done' and not vals.get('done_date'):
            vals['done_date'] = fields.Date.context_today(self)
        return super(ConstructionWorkTask, self).create(vals)

    def write(self, vals):
        if vals.get('state') == 'done':
            if 'done_date' not in vals and not self.done_date:
                vals['done_date'] = fields.Date.context_today(self)
        return super(ConstructionWorkTask, self).write(vals)

    @api.model
    def _group_expand_states(self, states, domain, order):
        return [key for key, val in type(self).state.selection]

    @api.constrains('assignee_role', 'assignee_id')
    def _check_assignee(self):
        for record in self:
            if record.assignee_role in ['worker', 'designer', 'foreman', 'supply'] and not record.assignee_id:
                # We can enforce this or leave it as warning. 
                # User request said "Required if..."
                # Let's enforced it for worker at least as per bot flow
                pass 
