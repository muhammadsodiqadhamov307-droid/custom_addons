from odoo import models, fields, api

class ConstructionStageProductTemplate(models.Model):
    _name = 'construction.stage.product.template'
    _description = 'Construction Stage Product Template'
    _rec_name = 'product_tmpl_id'

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
    ], string='Bosqich turi', required=True)

    resource_type = fields.Selection([
        ('material', 'Material'),
        ('service', 'Xizmat')
    ], string='Resurs turi', required=True, default='material')

    product_tmpl_id = fields.Many2one('product.template', string='Mahsulot', required=True)
    name = fields.Char(related='product_tmpl_id.name', string='Nomi', store=True)

    _sql_constraints = [
        ('unique_stage_product', 'unique(stage_type, resource_type, product_tmpl_id)', 'Ushbu bosqich va tur uchun mahsulot allaqachon mavjud!')
    ]
