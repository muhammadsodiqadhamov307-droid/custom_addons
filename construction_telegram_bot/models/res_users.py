from odoo import models, fields, api

class ResUsers(models.Model):
    _inherit = 'res.users'


    # Explicit stored field as requested by User (Step 3738)
    telegram_chat_id = fields.Char(related='partner_id.telegram_chat_id', readonly=False, store=True, string='Telegram Chat ID')
    last_bot_msg_id = fields.Integer(string="Last Processed Message ID", default=0)
    last_processed_update_id = fields.Char(string="Last Telegram Update ID", default="0")
    
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
        ('snab_price_input_line', 'Snab: Inputting Line Price'),
        ('snab_voice_price_wait', 'Snab: Voice Price Wait'),
        ('usta_ai_input', 'Usta: AI Material Input (Photo/Voice/Text)'),
        ('registration_name', 'Registration: Inputting Name'),
        ('registration_role', 'Registration: Selecting Role'),
    ], string='Bot State', default='idle')

    # AI Context
    usta_ai_project_id = fields.Many2one('construction.project', string='AI Request Project')
    
    # MR Draft Context
    mr_draft_project_id = fields.Many2one('construction.project', string='MR Draft Project')
    mr_draft_lines_json = fields.Text(string='MR Draft Lines (JSON)', default='[]')

    construction_selected_project_id = fields.Many2one('construction.project', string='Selected Project')
    construction_selected_stage_id = fields.Many2one('construction.stage', string='Selected Stage')
    construction_selected_task_id = fields.Many2one('construction.stage.task', string='Selected Task')
    construction_selected_product_tmpl_id = fields.Many2one('product.template', string='Selected Product Template')
    construction_selected_product_id = fields.Many2one('product.product', string='Selected Product')

    # Snab Batch Pricing Context
    snab_price_batch_id = fields.Many2one('construction.material.request.batch', string='Snab Pricing Batch')
    snab_price_line_id = fields.Many2one('construction.material.request.line', string='Snab Pricing Line')
    snab_last_priced_line_ids = fields.Many2many('construction.material.request.line', 'snab_last_priced_lines_rel', 'user_id', 'line_id', string='Snab Last Priced Lines')


    # File Navigation Context
    file_nav_project_id = fields.Many2one('construction.project', string='File Nav Project')
    file_nav_room_ref = fields.Char(string='File Nav Room')
    file_nav_category_id = fields.Many2one('construction.file.category', string='File Nav Category')

    # Usta File Navigation Context
    usta_files_project_id = fields.Many2one('construction.project', string='Usta Files Project')
    usta_files_category_id = fields.Many2one('construction.file.category', string='Usta Files Category')
    usta_files_room_ref = fields.Char(string='Usta Files Room')
    usta_files_room_map = fields.Text(string='Usta Files Room Map (JSON)')
    bot_verification_status = fields.Selection([
        ('approved', 'Approved'),
        ('pending', 'Pending Approval'),
        ('draft', 'Draft')
    ], string='Bot Verification Status', default='approved')

    @api.model_create_multi
    def create(self, vals_list):
        users = super(ResUsers, self).create(vals_list)
        for user in users:
            # Check for immediate onboarding (Chat ID + Role)
            if user.telegram_chat_id and not self.env.context.get('no_notify_role'):
                # If created with Chat ID, it's a new assignment
                try:
                    self.env['construction.telegram.bot'].sudo()._system_notify_user_role_update([user], is_new_access=True)
                except Exception as e:
                    pass
        return users

    def write(self, vals):
        import logging
        _logger = logging.getLogger(__name__)
        
        # Optimization: If we are not updating role or projects, skip all this logic
        # But we must allow 'construction_role' or 'allowed_project_ids' or 'telegram_chat_id' or 'bot_verification_status'
        relevant_keys = {'construction_role', 'allowed_project_ids', 'telegram_chat_id', 'bot_verification_status'}
        if not any(key in vals for key in relevant_keys):
            return super(ResUsers, self).write(vals)

        # Logging to identify broadcast writes
        if len(self) > 1:
            _logger.info(f"[RES_USERS_WRITE_BATCH] Writing to {len(self)} users. Vals: {vals.keys()}")
            
        # Pre-capture state for comparison
        # We need to check each user individually as write is batch
        user_states = {}
        for user in self:
            user_states[user.id] = {
                'has_chat_id': bool(user.telegram_chat_id),
                'role': user.construction_role,
                'status': user.bot_verification_status,
                'project_ids': set(user.allowed_project_ids.ids) if user.allowed_project_ids else set()
            }

        res = super(ResUsers, self).write(vals)

        # Suppress notifications if called from project assignment
        if self.env.context.get('suppress_project_notification'):
            _logger.info(f"[RES_USERS_WRITE] Suppressing notification due to suppress_project_notification context for {len(self)} user(s)")
            return res

        if self.env.context.get('no_notify_role'):
            _logger.info(f"[RES_USERS_WRITE] Suppressing notification due to no_notify_role context for {len(self)} user(s)")
            return res

        users_to_notify_welcome = []
        users_to_notify_update = []
        users_to_notify_approved = []

        for user in self:
            old_state = user_states.get(user.id)
            if not old_state: continue
            
            new_has_chat_id = bool(user.telegram_chat_id)
            new_status = user.bot_verification_status
            
            # 0. Approval Logic: Pending -> Approved
            if old_state['status'] != 'approved' and new_status == 'approved':
                users_to_notify_approved.append(user.id)
                continue

            # 1. Onboarding: Was not connected, now connected (Manual Backend)
            if not old_state['has_chat_id'] and new_has_chat_id:
                users_to_notify_welcome.append(user.id)
            
            # Skip notifications during registration (pending/draft status)
            if old_state['status'] in ('pending', 'draft'):
                _logger.info(f"[RES_USERS_WRITE] Skipping notification for {user.name} (status: {old_state['status']})")
                continue
            
            # 3. Update: Was connected, still connected. Check for ACTUAL changes
            if old_state['has_chat_id'] and new_has_chat_id:
                should_notify = False
                
                # Check if role ACTUALLY changed (not just written)
                if 'construction_role' in vals:
                    new_role = user.construction_role
                    if new_role != old_state['role']:
                        should_notify = True
                        _logger.info(f"[BOT_NOTIFY] User {user.name} role changed from {old_state['role']} to {new_role}")
                
                # Check if projects ACTUALLY changed
                if 'allowed_project_ids' in vals and not should_notify:
                    new_project_ids = set(user.allowed_project_ids.ids) if user.allowed_project_ids else set()
                    if new_project_ids != old_state['project_ids']:
                        should_notify = True
                        _logger.info(f"[BOT_NOTIFY] User {user.name} projects changed from {old_state['project_ids']} to {new_project_ids}")
                    else:
                        _logger.info(f"[BOT_NOTIFY] User {user.name} projects unchanged: {new_project_ids}, suppressing notification")
                
                if should_notify:
                     users_to_notify_update.append(user.id)

        try:
            bot = self.env['construction.telegram.bot'].sudo()
            if users_to_notify_welcome:
                bot._system_notify_user_role_update(self.browse(users_to_notify_welcome), is_new_access=True)
            if users_to_notify_update:
                bot._system_notify_user_role_update(self.browse(users_to_notify_update), is_new_access=False)
            if users_to_notify_approved:
                # Notify approval
                for user_id in users_to_notify_approved:
                    u = self.browse(user_id)
                    bot._on_user_approved(u)
                    
        except Exception as e:
            _logger.error(f"[BOT_NOTIFY] Error: {e}")

        return res

    def get_allowed_construction_projects(self):
        self.ensure_one()
        # Priority 1: Explicitly allowed projects
        if self.allowed_project_ids:
            return self.allowed_project_ids
            
        # Priority 2: Role-based automatic access (Legacy/Fallback)
        # If no allowed projects set, fall back to old logic?
        # User said "Add/ensure allowed project assignment exists". 
        # implies filtering should rely on it mainly.
        # But if EMPTY, maybe they have NO access?
        # Let's say: if allowed_project_ids is not empty, restrict to it.
        # If empty, use defaults logic below.
        
        domain = ['|','|','|','|','|',
            ('user_id','=', self.id), # Manager
            ('designer_id','=', self.id),
            ('foreman_id','=', self.id),
            ('supply_id','=', self.id),
            ('worker_ids','in', self.id),
            ('customer_id','=', self.partner_id.id),
        ]
        return self.env['construction.project'].search(domain)

    def action_register_webhook(self):
        """Registers the Telegram Webhook for this instance"""
        import requests
        from odoo.exceptions import UserError
        
        token = self.env['ir.config_parameter'].sudo().get_param('construction_bot.token')
        if not token or token.startswith('YOUR'):
            raise UserError("Bot Token is not set! Check System Parameters.")
            
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        if not base_url:
            raise UserError("System Parameter 'web.base.url' is missing!")
            
        # Ensure HTTPS (Cloud Clusters usually handles this, but good to check)
        # However, users might use HTTP for testing, so only warn if needed.
        # But Telegram requires HTTPS.
        
        webhook_url = f"{base_url.rstrip('/')}/telegram/webhook"
        
        url = f"https://api.telegram.org/bot{token}/setWebhook"
        try:
            res = requests.post(url, data={'url': webhook_url}, timeout=10)
            res.raise_for_status()
            result = res.json()
            
            if result.get('ok'):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': f"Webhook Registered!\nURL: {webhook_url}",
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                 raise UserError(f"Telegram Error: {result.get('description')}")
                 
        except Exception as e:
            raise UserError(f"Failed to register webhook: {str(e)}")
