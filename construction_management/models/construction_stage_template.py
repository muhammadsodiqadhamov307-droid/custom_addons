from odoo import models, fields, api, _

class ConstructionStageProductTemplate(models.Model):
    _name = 'construction.stage.product.template'
    _description = 'Stage Product Template'
    _order = 'stage_type, name'

    name = fields.Char(string='Display Name', required=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', required=True)
    
    stage_type = fields.Selection([
        ('demontaj', 'Demolition'),
        ('montaj', 'Mounting'),
        ('santehnika', 'Plumbing'),
        ('santehnika_acc', 'Plumbing Accessories'),
        ('otoplenie', 'Heating'),
        ('ventilyatsiya', 'Ventilation'),
        ('elektrika', 'Electrical'),
        ('elektrika_acc', 'Electrical Accessories'),
        ('pol', 'Floor'),
        ('patalok', 'Ceiling'),
        ('kafel', 'Tile'),
        ('dvery', 'Doors'),
        ('obshivka', 'Wall Cladding'),
        ('malyar', 'Painting'),
        ('mebel', 'Furniture'),
        ('tehnika', 'Appliances'),
        ('other', 'Other'),
    ], string='Stage Type', required=True)
    
    resource_type = fields.Selection([
        ('material', 'Material'),
        ('service', 'Service')
    ], string='Resource Type', required=True, default='material')
