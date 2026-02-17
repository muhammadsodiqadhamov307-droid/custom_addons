from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ConstructionKirim(models.Model):
    _name = 'construction.kirim'
    _description = 'Construction Daily Input'
    _order = 'date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Kirim raqami', required=True, copy=False, readonly=True, default=lambda self: _('Draft'))
    date = fields.Date(string='Sana', required=True, default=fields.Date.context_today)
    project_id = fields.Many2one('construction.project', string='Loyiha', required=True, index=True)
    company_id = fields.Many2one('res.company', string='Kompaniya', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Valyuta', required=True, default=lambda self: self.env.company.currency_id)

    notes = fields.Text(string='Izohlar')

    _sql_constraints = [
        ('project_date_uniq', 'unique (project_id, date)', 'Bu loyiha uchun bugungi sana bo‘yicha kirim allaqachon mavjud!')
    ]

    @api.model
    def create(self, vals):
        if vals.get('name', _('Draft')) == _('Draft'):
            vals['name'] = self.env['ir.sequence'].next_by_code('construction.kirim') or _('Draft')
        return super(ConstructionKirim, self).create(vals)

    @api.model
    def get_or_create_today(self, project_id):
        """
        Helper for Telegram Bot: Find or create a kirim record for the given project and today's date.
        """
        today = fields.Date.context_today(self)
        kirim = self.search([
            ('project_id', '=', project_id),
            ('date', '=', today)
        ], limit=1)
        
        if not kirim:
            kirim = self.create({
                'project_id': project_id,
                'date': today
            })
        return kirim

    line_ids = fields.One2many('construction.kirim.line', 'kirim_id', string='Qatorlar')
    
    total_material = fields.Float(string='Materiallar jami', compute='_compute_totals', store=True)
    total_xizmat = fields.Float(string='Xizmatlar jami', compute='_compute_totals', store=True)
    total_all = fields.Float(string='Umumiy jami', compute='_compute_totals', store=True)

    @api.depends('line_ids.total')
    def _compute_totals(self):
        for record in self:
            materials = sum(line.total for line in record.line_ids if line.type == 'material')
            services = sum(line.total for line in record.line_ids if line.type == 'service')
            record.total_material = materials
            record.total_xizmat = services
            record.total_all = materials + services


class ConstructionKirimLine(models.Model):
    _name = 'construction.kirim.line'
    _description = 'Construction Daily Input Line'

    kirim_id = fields.Many2one('construction.kirim', string='Kirim Header', required=True, ondelete='cascade')
    type = fields.Selection([
        ('material', 'Material'),
        ('service', 'Xizmat')
    ], string='Turi', required=True, default='material')
    
    name = fields.Char(string='Nomi', required=True)
    qty = fields.Float(string='Miqdor', required=True, default=1.0)
    uom_id = fields.Many2one('construction.uom', string='O‘lchov birligi', required=True)
    
    currency_id = fields.Many2one('res.currency', related='kirim_id.currency_id', store=True, readonly=True)
    unit_price = fields.Float(string='Birlik narxi', required=True)
    total = fields.Float(string='Jami', compute='_compute_total', store=True)
    
    stage_id = fields.Many2one('construction.stage', string='Bosqich', domain="[('project_id', '=', parent.project_id)]")
    
    # Stores the reference to the created record (e.g., 'construction.stage.material,15')
    pushed_record_ref = fields.Reference(selection='_get_pushable_models', string="Bosqichga uzatilgan yozuv", readonly=True)

    @api.model
    def _get_pushable_models(self):
        # Return all models to be safe, filtering happens during write
        return [(m.model, m.name) for m in self.env['ir.model'].search([])]

    @api.depends('qty', 'unit_price')
    def _compute_total(self):
        for line in self:
            line.total = line.qty * line.unit_price

    @api.constrains('unit_price')
    def _check_unit_price(self):
        for line in self:
            if line.unit_price % 1 != 0:
                raise ValidationError(_("Narx butun son bo‘lishi kerak!"))

    @api.constrains('qty')
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(_("Miqdor 0 dan katta bo‘lishi kerak!"))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.stage_id:
                record._push_to_stage()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Identify interesting fields
        if any(f in vals for f in ['stage_id', 'qty', 'unit_price', 'name']):
            for record in self:
                if record.stage_id:
                    record._push_to_stage()
        return res

    def _push_to_stage(self):
        self.ensure_one()
        target_model_name, field_map = self._detect_target_model(self.type)
        
        target_env = self.env[target_model_name]
        
        # 1. Find the mandated Task strictly
        if self.type == 'material':
            required_task_name = "Материалы для работы"
        else:
            required_task_name = "Оплата мастерам за работы"
            
        Task = self.env['construction.stage.task']
        
        task = Task.search([
            ('stage_id', '=', self.stage_id.id),
            ('name', '=', required_task_name)
        ], limit=1)
        
        if not task:
            raise UserError(_("❌ Ushbu bosqichda task topilmadi: %s. Iltimos, bosqich tasklarini tekshiring.") % required_task_name)

        # 2. Prepare Data
        data = {
            field_map['stage']: self.stage_id.id,
            field_map['task']: task.id,
            field_map['qty']: self.qty,
            field_map['price']: self.unit_price,
            # Common fields
            'company_id': self.env.company.id,
        }
        
        # Name field handling
        if field_map.get('product'):
             # Find/Create product if targeting a product_id field
             # Using name as product name
             product = self.env['product.product'].search([('name', '=', self.name), ('type', '=', 'service' if self.type == 'service' else 'product')], limit=1)
             if not product:
                 product = self.env['product.product'].create({
                     'name': self.name,
                     'type': 'service' if self.type == 'service' else 'product'
                 })
             data[field_map['product']] = product.id
        elif field_map.get('desc'):
             data[field_map['desc']] = self.name

        # Date handling
        if field_map.get('date'):
            data[field_map['date']] = self.kirim_id.date

        # UoM handling (Map construction.uom to uom.uom if needed)
        # Detection: Does target use uom.uom?
        if field_map.get('uom'):
             # Naive map by name
             uom = self.env['uom.uom'].search([('name', '=', self.uom_id.name)], limit=1)
             if uom:
                 data[field_map['uom']] = uom.id
        
        if field_map.get('construction_uom'):
            data[field_map['construction_uom']] = self.uom_id.id

        # 3. Create or Update
        if self.pushed_record_ref:
            # Check if exists and model matches
            try:
                ref_model, ref_id = self.pushed_record_ref._name, self.pushed_record_ref.id
                if ref_model == target_model_name and self.pushed_record_ref.exists():
                    self.pushed_record_ref.write(data)
                    return
            except:
                pass # Reference broken or changed model
        
        # Create new
        new_record = target_env.create(data)
        self.pushed_record_ref = f"{target_model_name},{new_record.id}"

    def _detect_target_model(self, type_key):
        """
        Dynamically finds the best model for 'material' or 'service'.
        Returns: (model_name, field_map_dict)
        """
        # Cache check could go here
        
        search_term = "stage.material" if type_key == 'material' else "stage.service"
        candidates = self.env['ir.model'].search([('model', 'like', search_term)])
        
        best_candidate = None
        best_score = 0
        best_map = {}

        for model in candidates:
            score = 0
            model_name = model.model
            if model_name.startswith('construction.'): score += 10
            
            # Introspect fields
            try:
                ModelImpl = self.env[model_name]
                fields_data = ModelImpl._fields
            except KeyError:
                continue

            field_map = {}
            
            # Must have link to stage
            for fname, field in fields_data.items():
                if field.type == 'many2one' and field.comodel_name == 'construction.stage':
                    field_map['stage'] = fname
                    break
            
            # Must have link to task
            for fname, field in fields_data.items():
                if field.type == 'many2one' and field.comodel_name == 'construction.stage.task':
                    field_map['task'] = fname
                    break
            
            if 'stage' in field_map and 'task' in field_map:
                score += 50
                
                # Detect Qty/Price
                for fname, field in fields_data.items():
                    if fname in ['quantity', 'qty', 'quantity_planned']:
                        field_map['qty'] = fname
                    if fname in ['price', 'unit_price', 'amount']:
                        field_map['price'] = fname
                    if fname in ['date']:
                        field_map['date'] = fname
                    if fname in ['uom_id']:
                        field_map['uom'] = fname
                    if fname in ['construction_uom_id']:
                        field_map['construction_uom'] = fname
                    
                    # Target spec: 'product_id' for material usually, 'service_id' or 'description' for service
                    if type_key == 'material' and fname == 'product_id':
                        field_map['product'] = fname
                    if type_key == 'service' and fname == 'service_id':
                        field_map['product'] = fname
                    if type_key == 'service' and fname == 'description':
                        field_map['desc'] = fname

                if 'qty' in field_map and 'price' in field_map:
                    score += 20
                    if score > best_score:
                        best_score = score
                        best_candidate = model_name
                        best_map = field_map

        if not best_candidate:
            raise UserError(_("Bosqich material/xizmat modeli topilmadi. Iltimos, administrator sozlamalarni tekshirsin."))
            
        return best_candidate, best_map
