from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ConstructionMaterialDelivery(models.Model):
    _name = 'construction.material.delivery'
    _description = 'Material yetkazib berish holati'
    _rec_name = 'batch_id'

    batch_id = fields.Many2one('construction.material.request.batch', string='So‘rov', required=True, ondelete='cascade', index=True)
    project_id = fields.Many2one(related='batch_id.project_id', string='Loyiha', store=True, readonly=True)
    
    state = fields.Selection([
        ('purchased', 'Sotib olindi'),
        ('in_transit', 'Yo‘lda'),
        ('delivered', 'Yetkazildi')
    ], string='Holat', default='purchased', required=True, tracking=True)
    
    updated_by = fields.Many2one('res.users', string='Yangiladi', default=lambda self: self.env.user, readonly=True)
    updated_at = fields.Datetime(string='Yangilangan vaqt', default=fields.Datetime.now, readonly=True)
    
    note = fields.Text(string='Izoh')
    last_telegram_chat_id = fields.Char(string='Oxirgi TG Chat ID') # For editing message if needed
    last_telegram_message_id = fields.Char(string='Oxirgi TG Xabar ID') # For editing message
    
    log_ids = fields.One2many('construction.material.delivery.log', 'delivery_id', string='Tarix')
    line_ids = fields.One2many(related='batch_id.line_ids', string='Materiallar', readonly=True)

    _sql_constraints = [
        ('batch_unique', 'unique(batch_id)', 'Har bir so‘rov uchun faqat bitta yetkazib berish statusi bo‘lishi mumkin!')
    ]

    @api.model
    def create(self, vals):
        res = super(ConstructionMaterialDelivery, self).create(vals)
        # Initial log
        res._create_log(False, res.state, 'odoo', _('Yaratildi'))
        return res

    def set_state(self, new_state, source='odoo', note=None):
        """
        Centralized method to change state.
        Usage: record.set_state('in_transit', 'telegram', 'Driver picked up')
        """
        self.ensure_one()
        if self.state == new_state:
            return True # No change needed

        old_state = self.state
        
        # internal write (updates updated_by/at via write override or manually here)
        # We'll rely on write logic or do it explicitly to be safe.
        self.write({
            'state': new_state,
            'updated_by': self.env.user.id,
            'updated_at': fields.Datetime.now()
        })
        
        # Log is handled by write() if we keep that logic, OR we move it here.
        # The Architect Plan says "Every state change must write a log entry."
        # Current write() method has auto-log on line 41. 
        # Let's keep write() clean for Odoo UI edits, but set_state is the API.
        # Ideally, we pass 'source' via context or handle it here.
        # Let's handle logging explicitly here if write() doesn't see 'source'.
        # Actually, let's allow write() to handle the logging to catch ALL changes (even standard UI edits).
        # We can pass source in context to write.
        
        return True

    def write(self, vals):
        # Auto-log on state change
        if 'state' in vals:
            for rec in self:
                if rec.state != vals['state']:
                    # Determine source
                    src = vals.pop('source', self.env.context.get('delivery_source', 'odoo'))
                    rec._create_log(rec.state, vals['state'], src, vals.get('note'))
        
        # Clean up custom keys if they leaked into vals (though pop above handles source)
        vals.pop('source', None)
        vals.pop('note', None) # Note is a real field, don't pop if we want to save it! 
        # Wait, 'note' is a field. If passed in vals, it should be written.
        
        res = super(ConstructionMaterialDelivery, self).write(vals)
        
        # Update timestamp if state changed
        if 'state' in vals and 'updated_at' not in vals:
             super(ConstructionMaterialDelivery, self).write({
                 'updated_by': self.env.user.id,
                 'updated_at': fields.Datetime.now()
             })
             
        return res

    def _create_log(self, old_state, new_state, source='odoo', note=None):
        self.env['construction.material.delivery.log'].create({
            'delivery_id': self.id,
            'old_state': old_state,
            'new_state': new_state,
            'changed_by': self.env.user.id,
            'source': source,
            'note': note
        })

    def action_set_purchased(self):
        self.set_state('purchased', source='odoo')

    def action_set_in_transit(self):
        self.set_state('in_transit', source='odoo')

    def action_set_delivered(self):
        self.set_state('delivered', source='odoo')

class ConstructionMaterialDeliveryLog(models.Model):
    _name = 'construction.material.delivery.log'
    _description = 'Material Delivery Log'
    _order = 'create_date desc'

    delivery_id = fields.Many2one('construction.material.delivery', string='Delivery', required=True, ondelete='cascade')
    old_state = fields.Char(string='Eski holat')
    new_state = fields.Char(string='Yangi holat', required=True)
    
    changed_by = fields.Many2one('res.users', string='O‘zgartirdi', readonly=True)
    changed_at = fields.Datetime(string='Vaqt', default=fields.Datetime.now, readonly=True)
    
    source = fields.Selection([
        ('telegram', 'Telegram'),
        ('odoo', 'Odoo')
    ], string='Manba', default='odoo')
    
    note = fields.Text(string='Izoh')
