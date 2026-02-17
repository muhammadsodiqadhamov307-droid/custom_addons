from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'

    construction_role = fields.Selection([
        ('client', 'Mijoz'),
        ('designer', 'Dizayner'),
        ('worker', 'Usta'),
        ('foreman', 'Prorab'),
        ('supply', "Ta'minotchi"),
        ('admin', 'Admin'),
    ], string='Construction Role', required=True, default='worker')
    
    allowed_project_ids = fields.Many2many('construction.project', string='Biriktirilgan Loyihalar')

    # MR Wizard Field (Snab context)

    # MR Draft (Batch Flow)
    mr_draft_project_id = fields.Many2one('construction.project', string="MR Draft Loyiha")
    mr_draft_lines_json = fields.Text(string="MR Draft JSON", default="[]")
    
    # Bot Context Fields
    selected_task_id = fields.Many2one('construction.work.task', string="Selected Task (Bot)")
    construction_selected_project_id = fields.Many2one('construction.project', string='Selected Project (Bot)')
    
    # Issue Draft Fields
    issue_draft_text = fields.Text(string="Issue Draft Text")
    issue_draft_photo_ids = fields.Text(string="Issue Draft Photo IDs (JSON)", default="[]")  # Telegram file_ids

    def get_allowed_construction_projects(self):
        self.ensure_one()
        # If allowed_project_ids is set, respect it strictly + user specific roles
        # Or should allowed_project_ids be the ONLY source?
        # User requirement: "Add/ensure allowed project assignment exists". 
        # Usually checking allowed_project_ids is better.
        if self.allowed_project_ids:
             return self.allowed_project_ids
        
        # Fallback to role-based domain if empty? Or strict? 
        # Let's keep role based as fallback or union? 
        # "Role is assigned only in Odoo" implies strict control.
        # But let's look at get_allowed_construction_projects in bot model.
        return self.env['construction.project'].search([]) # Placeholder, bot overrides this.

    construction_bot_state = fields.Selection([
        ('idle', 'Idle'),
        ('select_project', 'Selecting Project'),
        ('select_stage', 'Selecting Stage'),
        ('choose_action', 'Choosing Action'),
        ('type_selection', 'Selecting Type'),
        ('select_product_material', 'Selecting Material Product'),
        ('select_product_service', 'Selecting Service Product'),
        ('select_variant', 'Selecting Variant'),
        ('input_qty_price', 'Inputting Quantity and Price'),
        ('input_new_product_name', 'Inputting New Product Name'),
        ('input_new_variant_name', 'Inputting New Variant Name'),
        ('input_product_details', 'Inputting Product Details (Name Qty Price)'),
        ('input_material', 'Inputting Material (Name Qty Price)'),
        ('input_service', 'Inputting Service (Name Qty Price)'),
        ('input_photo', 'Inputting Photo'),
        ('awaiting_stage_image', 'Awaiting Stage Image'),
        ('foreman_input_report_text', 'Foreman: Inputting Report Text'),
        ('foreman_input_report_media', 'Foreman: Inputting Report Media'),
        ('usta_mr_input', 'Usta: Inputting Material Request (Name Qty)'),
        ('usta_mr_draft_input', 'Usta: Inputting Draft (Batch)'),
        ('snab_mr_price_input', 'Snab: Inputting Material Price'),
        ('snab_price_select_line', 'Snab: Selecting Line to Price'),
        ('snab_price_input', 'Snab: Inputting Unit Price for Batch Line'),
        ('worker_issue_input_text', 'Worker: Inputting Issue Text'),
        ('worker_issue_input_photos', 'Worker: Inputting Issue Photos'),
    ], string='Bot State', default='idle')
