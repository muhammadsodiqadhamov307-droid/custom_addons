from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ConstructionUom(models.Model):
    _name = 'construction.uom'
    _description = 'Construction Unit of Measure'
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(string='O\'lchov birligi', required=True, index=True)
    active = fields.Boolean(string='Faol', default=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'O\'lchov birligi nomi takrorlanmasligi kerak!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'name' in vals and vals['name']:
                vals['name'] = vals['name'].strip()
        return super().create(vals_list)

    def write(self, vals):
        if 'name' in vals and vals['name']:
            vals['name'] = vals['name'].strip()
        return super().write(vals)
