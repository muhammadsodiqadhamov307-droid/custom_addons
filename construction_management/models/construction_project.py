from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import logging

_logger = logging.getLogger(__name__)
from datetime import date, timedelta

DEFAULT_TASKS = {
    'demontaj': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'montaj': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'santehnika': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'santehnika_acc': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'otoplenie': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'ventilyatsiya': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'elektrika': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'elektrika_acc': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'pol': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'patalok': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'kafel': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'dvery': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'obshivka': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'malyar': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'mebel': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'tehnika': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
    'other': ['Оплата мастерам за работы', 'Материалы для работы', 'Rasmlar'],
}

STAGES_ORDER = [
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
]

class ConstructionProject(models.Model):
    _name = 'construction.project'
    _description = 'Construction Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Loyiha nomi', required=True, tracking=True)
    reference = fields.Char(string='Kod', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    customer_id = fields.Many2one('res.partner', string='Buyurtmachi', required=True, tracking=True)
    budget = fields.Float(string='Shartnoma qiymati')

    address = fields.Text(string='Manzil')
    start_date = fields.Date(string='Boshlanish sanasi')
    end_date = fields.Date(string='Tugash sanasi')
    actual_end_date = fields.Date(string='Haqiqiy tugash sanasi')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Holat', default='draft', tracking=True)
    
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Valyuta', readonly=True)

    # Financials
    income_ids = fields.One2many('construction.project.income', 'project_id', string='Kirimlar')

    
    total_income = fields.Float(string='Jami kirim', compute='_compute_financials', store=True)
    total_expense = fields.Float(string='Jami chiqim', compute='_compute_financials', store=True)
    balance = fields.Float(string='Balans', compute='_compute_financials', store=True)
    
    total_cost = fields.Float(string='Jami xarajat', compute='_compute_total_cost', store=True)
    
    @api.depends('income_ids.amount', 'stage_ids.task_ids.total_cost')
    def _compute_financials(self):
        for record in self:
            record.total_income = sum(record.income_ids.mapped('amount'))
            # Expense is sum of all task costs (materials + services)
            # Efficient way: traverse stages -> tasks
            tasks = record.stage_ids.mapped('task_ids')
            record.total_expense = sum(tasks.mapped('total_cost'))
            record.balance = record.total_income - record.total_expense


    
    # Relations
    stage_ids = fields.One2many('construction.stage', 'project_id', string='Bosqichlar')
    payment_ids = fields.One2many('construction.payment', 'project_id', string='To\'lovlar')
    user_id = fields.Many2one('res.users', string='Loyiha menejeri', default=lambda self: self.env.user, tracking=True)
    
    # Team / Assignments
    designer_id = fields.Many2one('res.users', string="Dizayner", domain=[('construction_role', '=', 'designer')])
    foreman_id = fields.Many2one('res.users', string="Prorab", domain=[('construction_role', '=', 'foreman')])
    supply_id  = fields.Many2one('res.users', string="Ta'minotchi", domain=[('construction_role', '=', 'supply')])
    worker_ids = fields.Many2many('res.users', string="Ustalar", domain=[('construction_role', '=', 'worker')])

    company_id = fields.Many2one('res.company', string='Kompaniya', required=True, default=lambda self: self.env.company)


    
    # Analytic Account
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analitik hisob', copy=False, check_company=True)

    @api.model
    def create(self, vals):
        if vals.get('reference', _('New')) == _('New'):
            vals['reference'] = self.env['ir.sequence'].next_by_code('construction.project') or _('New')
        
        project = super(ConstructionProject, self).create(vals)
        
        # Auto-create analytic account
        if not project.analytic_account_id:
            analytic = self.env['account.analytic.account'].create({
                'name': project.name,
                'code': project.reference,
                'company_id': project.company_id.id,
                'partner_id': project.customer_id.id,
                'plan_id': self.env['account.analytic.plan'].search([], limit=1).id,
            })
            project.analytic_account_id = analytic.id

        # Notify Customer
        if project.customer_id:
            project._notify_customer()
            
        # Notify Team
        project._notify_project_assignment()

        # Auto-create stages
        for stage_key, stage_label in STAGES_ORDER:
            stage = self.env['construction.stage'].create({
                'name': stage_label,
                'stage_type': stage_key,
                'project_id': project.id,
                'state': 'pending',
            })
            
            # Create default tasks for this stage if defined
            if stage_key in DEFAULT_TASKS:
                for task_name in DEFAULT_TASKS[stage_key]:
                    self.env['construction.stage.task'].create({
                        'name': task_name,
                        'stage_id': stage.id,
                    })
        
        return project

    def write(self, vals):
        # Check if customer is changing
        old_customers = {}
        if 'customer_id' in vals:
            for record in self:
                old_customers[record.id] = record.customer_id

        # Track role changes for notification
        role_fields = ['designer_id', 'foreman_id', 'supply_id', 'user_id']
        
        # Pre-fetch old values for comparison
        old_values = {rec.id: {} for rec in self}
        if any(f in vals for f in role_fields) or 'worker_ids' in vals:
             for rec in self:
                 for field in role_fields:
                     field_value = getattr(rec, field)
                     old_values[rec.id][field] = field_value.id if field_value else None
                 old_values[rec.id]['worker_ids'] = set(rec.worker_ids.ids)

        res = super(ConstructionProject, self).write(vals)

        if 'customer_id' in vals:
            for record in self:
                if record.id in old_customers and record.customer_id != old_customers[record.id]:
                     record._notify_customer()
                     
        # Notify Assignment Changes
        token = self.env['ir.config_parameter'].sudo().get_param('construction_bot.token')
        if token:
            for record in self:
                # Track users we've notified to avoid duplicates
                notified_users = set()
                
                # Check Single Value Fields
                for field in role_fields:
                   if field in vals:
                       new_user = getattr(record, field)
                       old_user_id = old_values[record.id].get(field)
                       # Only notify if truly changed
                       if new_user and new_user.id != old_user_id:
                           record._send_project_notification(new_user, token)
                           notified_users.add(new_user.id)
                
                # Check M2M Workers
                if 'worker_ids' in vals:
                    new_worker_ids = set(record.worker_ids.ids)
                    old_worker_ids = old_values[record.id].get('worker_ids', set())
                    added_worker_ids = new_worker_ids - old_worker_ids
                    if added_worker_ids:
                        added_workers = self.env['res.users'].browse(list(added_worker_ids))
                        for worker in added_workers:
                             if worker.id not in notified_users:
                                 record._send_project_notification(worker, token)
                                 notified_users.add(worker.id)
                
                # Update allowed_project_ids with context to suppress res.users notifications
                if notified_users:
                    # Get all notified users and add this project if not already there
                    users_to_update = self.env['res.users'].browse(list(notified_users))
                    for user in users_to_update:
                        if record not in user.allowed_project_ids:
                            _logger.info(f"[PROJECT_WRITE] Adding project {record.name} to user {user.name} (ID: {user.id}) allowed_project_ids")
                            user.with_context(suppress_project_notification=True).sudo().write({
                                'allowed_project_ids': [(4, record.id)]
                            })
                    
                    # After the write and allowed_project_ids update, show menu for notified users
                    # This runs after the current transaction context
                    bot = self.env['construction.telegram.bot'].sudo()
                    for user in users_to_update:
                        # Re-browse to get fresh data with the new project
                        fresh_user = self.env['res.users'].sudo().browse(user.id)
                        bot._show_main_menu(fresh_user)
                        
        return res

    def _notify_project_assignment(self):
        """Notify initial assignees on create"""
        token = self.env['ir.config_parameter'].sudo().get_param('construction_bot.token')
        if not token: return
        
        for rec in self:
            if rec.designer_id: rec._send_project_notification(rec.designer_id, token)
            if rec.foreman_id: rec._send_project_notification(rec.foreman_id, token)
            if rec.supply_id: rec._send_project_notification(rec.supply_id, token)
            if rec.user_id: rec._send_project_notification(rec.user_id, token)
            for worker in rec.worker_ids:
                rec._send_project_notification(worker, token)

    def _send_project_notification(self, user, token):
        if not user.telegram_chat_id: return
        
        # Get role label from bot helper
        bot = self.env['construction.telegram.bot'].sudo()
        role_map = bot._get_roles()
        role_label = role_map.get(user.construction_role, user.construction_role or 'Xodim')
        
        msg = (
            f"🆕 *Yangi Loyiha Biriktirildi!*\n\n"
            f"🏗 Loyiha: *{self.name}*\n"
            f"👤 Rolingiz: *{role_label}*\n\n"
            f"Ishni boshlash uchun quyidagi menyudan foydalaning 👇"
        )
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': user.telegram_chat_id,
            'text': msg,
            'parse_mode': 'Markdown',
        }
        try:
            requests.post(url, json=payload, timeout=2)
            # Note: Don't call _show_main_menu here - it runs inside the write() transaction
            # and cannot see the uncommitted allowed_project_ids changes.
            # The menu will be shown by _system_notify_user_role_update after commit.
        except Exception:
            pass

    def _notify_customer(self):
        self.ensure_one()
        customer = self.customer_id
        # Check conditions: Role is Client (if field exists), Chat ID exists
        # The construction_role field is added by construction_telegram_bot module
        has_role_field = 'construction_role' in self.env['res.partner']._fields
        is_client = not has_role_field or customer.construction_role == 'client'
        has_chat_id = hasattr(customer, 'telegram_chat_id') and customer.telegram_chat_id
        
        if customer and is_client and has_chat_id:
            token = self.env['ir.config_parameter'].sudo().get_param('construction_bot.token')
            if not token:
                _logger.warning("Construction Bot Token not set, cannot send notification.")
                return 
            
            # Updated message for Customer
            msg = (
                f"🎉 Sizga yangi loyiha biriktirildi: *{self.name}*\n\n"
                f"Loyiha hisobotlarini ko‘rish uchun pastdagi menyudan foydalaning."
            )
            
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                'chat_id': customer.telegram_chat_id,
                'text': msg,
                'parse_mode': 'Markdown',
            }
            try:
                requests.post(url, json=payload, timeout=5)
            except Exception as e:
                _logger.error(f"Failed to send project notification to {customer.name}: {e}")




    @api.depends('stage_ids.actual_cost')
    def _compute_total_cost(self):
        for record in self:
            record.total_cost = sum(record.stage_ids.mapped('actual_cost'))



    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.end_date and record.start_date and record.end_date < record.start_date:
                raise ValidationError("End date cannot be before start date")
                
    def action_view_stages(self):
        self.ensure_one()
        return {
            'name': 'Project Tasks',
            'type': 'ir.actions.act_window',
            'res_model': 'construction.stage.task',
            'view_mode': 'kanban,form',
            'domain': [('stage_id.project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
            'help': """
                <p class="o_view_nocontent_smiling_face">
                    Tasks are organized by Stage.
                </p>
            """
        }

    def action_view_work_tasks(self):
        self.ensure_one()
        return {
            'name': _('Loyiha vazifalari'),
            'type': 'ir.actions.act_window',
            'res_model': 'construction.work.task',
            'view_mode': 'tree,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_complete(self):
        self.write({'state': 'completed', 'actual_end_date': fields.Date.today()})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_view_analytic_lines(self):
        self.ensure_one()
        return {
            'name': 'Financial Report',
            'type': 'ir.actions.act_window',
            'res_model': 'account.analytic.line',
            'view_mode': 'tree,form,pivot,graph',
            'domain': [('account_id', '=', self.analytic_account_id.id)],
            'context': {'default_account_id': self.analytic_account_id.id},
        }

    file_count = fields.Integer(string='Fayllar Soni', compute='_compute_file_count')

    def _compute_file_count(self):
        for record in self:
            record.file_count = self.env['construction.project.file'].search_count([('project_id', '=', record.id)])

    def action_view_files(self):
        self.ensure_one()
        return {
            'name': _('Fayllar'),
            'type': 'ir.actions.act_window',
            'res_model': 'construction.project.file',
            'view_mode': 'tree,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    delivery_count = fields.Integer(string='Yetkazib berish', compute='_compute_delivery_count')

    def _compute_delivery_count(self):
        for record in self:
            record.delivery_count = self.env['construction.material.delivery'].search_count([('project_id', '=', record.id)])

    def action_open_deliveries(self):
        self.ensure_one()
        return {
            'name': 'Yetkazib berish holati',
            'type': 'ir.actions.act_window',
            'res_model': 'construction.material.delivery',
            'view_mode': 'tree,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_print_financial_qs(self):
        self.ensure_one()
        return self.env.ref('construction_management.action_report_construction_financial').report_action(self)

    def action_open_financial_report(self):
        self.ensure_one()
        ledger_data = self.get_project_ledger()
        
        # Create Wizard
        wizard = self.env['construction.financial.report.wizard'].create({
            'project_id': self.id,
        })
        
        # Process items and Create Lines
        current_group_name = _('Initial Balance / Uncategorized')
        previous_balance = 0.0
        
        for item in ledger_data:
            # Filter out days with no activity
            if item.get('income', 0) == 0 and item.get('expense', 0) == 0:
                continue

            # If item is income, update the group name and add Previous Balance line
            if item.get('income', 0) > 0:
                amount_str = "{:,.2f}".format(item['income'])
                # Format: "YYYY-MM-DD | Income: Description (Amount)"
                current_group_name = f"{item['date']} | Income: {item['description']} ({amount_str})"
                
                # Add Previous Balance line for this new group
                self.env['construction.financial.report.line'].create({
                    'wizard_id': wizard.id,
                    'date': item['date'],
                    'description': _('Ostatka'),
                    'income': 0,
                    'expense': 0,
                    'balance': previous_balance,
                    'group_name': current_group_name,
                })
            
            self.env['construction.financial.report.line'].create({
                'wizard_id': wizard.id,
                'date': item['date'],
                'description': item['description'],
                'income': item['income'],
                'expense': item['expense'],
                'balance': item['balance'],
                'group_name': current_group_name,
            })
            
            previous_balance = item['balance']
            
        return {
            'name': _('Financial Report Preview'),
            'type': 'ir.actions.act_window',
            'res_model': 'construction.financial.report.line',
            'view_mode': 'tree',
            'domain': [('wizard_id', '=', wizard.id)],
            'context': {
                'search_default_group_by_source': 1,
                'create': False,
                'edit': False,
            },
            'target': 'new',
        }

    def get_project_ledger(self):
        self.ensure_one()
        ledger = []
        
        # 1. Determine Date Range
        start = self.start_date or fields.Date.today()
        # Find first transaction date if earlier than start_date
        dates = [start]
        if self.income_ids:
            dates.append(min(self.income_ids.mapped('date')))
        
        # Collect expenses to find min date
        all_expenses = []
        for stage in self.stage_ids:
            for task in stage.task_ids:
                for mat in task.material_ids:
                    all_expenses.append({
                        'date': mat.date,
                        'description': f"[{stage.name}] {mat.product_id.display_name}",
                        'amount': mat.total_cost,
                        'type': 'expense'
                    })
                    dates.append(mat.date)
                for svc in task.service_ids:
                    all_expenses.append({
                        'date': svc.date,
                        'description': f"[{stage.name}] {svc.service_id.display_name} ({svc.description or ''})",
                        'amount': svc.total_cost,
                        'type': 'expense'
                    })
                    dates.append(svc.date)
        
        start_date = min(dates)
        end_date = fields.Date.today()
        
        # 2. Collect Incomes
        all_incomes = []
        for income in self.income_ids:
            all_incomes.append({
                'date': income.date,
                'description': income.description or "Income",
                'amount': income.amount,
                'type': 'income'
            })

        # 3. Build Daily Ledger
        current_date = start_date
        running_balance = 0.0
        
        while current_date <= end_date:
            day_incomes = [i for i in all_incomes if i['date'] == current_date]
            day_expenses = [e for e in all_expenses if e['date'] == current_date]
            
            # If transactions exist for this day
            if day_incomes or day_expenses:
                # Add incomes first
                for inc in day_incomes:
                    running_balance += inc['amount']
                    ledger.append({
                        'date': current_date,
                        'description': inc['description'],
                        'income': inc['amount'],
                        'expense': 0,
                        'balance': running_balance
                    })
                
                # Add expenses
                for exp in day_expenses:
                    running_balance -= exp['amount']
                    ledger.append({
                        'date': current_date,
                        'description': exp['description'],
                        'income': 0,
                        'expense': exp['amount'],
                        'balance': running_balance
                    })
            else:
                # Nothing happened
                ledger.append({
                    'date': current_date,
                    'description': "",
                    'income': 0,
                    'expense': 0,
                    'balance': running_balance
                })
            
            current_date += timedelta(days=1)
            
        return ledger




class ConstructionProjectIncome(models.Model):
    _name = 'construction.project.income'
    _description = 'Project Income'
    _order = 'date desc'

    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    date = fields.Date(string='Sana', required=True, default=fields.Date.context_today)
    amount = fields.Float(string='Miqdor', required=True)
    description = fields.Char(string='Izoh')

