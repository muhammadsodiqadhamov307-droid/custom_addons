import requests
import logging
import re
import traceback
import json
import base64
import subprocess
import tempfile
import os
from odoo import models, fields, api, _
from odoo.addons.construction_management.services.inventory_lite import InventoryLiteService
from .gemini_service import GeminiService

_logger = logging.getLogger(__name__)

class ConstructionTelegramBot(models.AbstractModel):
    _name = 'construction.telegram.bot'
    _description = 'Construction Telegram Bot Service'

    def _curl_request(self, method, url, params=None, json_data=None, data=None, files=None, timeout=30):
        """
        Execute request using system curl command to bypass Python networking issues.
        """
        cmd = ['curl', '-s', '-v']
        
        # Method
        if method == 'POST':
            cmd.extend(['-X', 'POST'])
        elif method == 'GET':
            cmd.extend(['-X', 'GET'])
            
        # URL & Params
        full_url = url
        if params:
            import urllib.parse
            query_string = urllib.parse.urlencode(params)
            full_url = f"{url}?{query_string}"
        cmd.append(full_url)
        
        # Headers (JSON)
        if json_data is not None:
             cmd.extend(['-H', 'Content-Type: application/json'])
             cmd.extend(['-d', json.dumps(json_data)])
             
        # Form Data
        if data:
            for k, v in data.items():
                cmd.extend(['-F', f'{k}={v}'])
                
        # Files (Multipart)
        temp_files = []
        try:
            if files:
                for k, v in files.items():
                    # v is tuple (filename, file_object or bytes, content_type)
                    # or (filename, file_object or bytes)
                    filename = v[0]
                    content = v[1]
                    content_type = v[2] if len(v) > 2 else None
                    
                    # Create temp file
                    fd, path = tempfile.mkstemp(prefix='curl_upload_')
                    os.write(fd, content if isinstance(content, bytes) else content.read())
                    os.close(fd)
                    temp_files.append(path)
                    
                    # Add to curl command
                    # Format: field=@filepath;filename=name;type=mimetype
                    file_param = f"{k}=@{path};filename={filename}"
                    if content_type:
                        file_param += f";type={content_type}"
                    cmd.extend(['-F', file_param])
            
            # Timeout
            cmd.extend(['--max-time', str(timeout)])
            
            _logger.info(f"Executing curl: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=False) # Binary output
            
            if result.returncode != 0:
                _logger.error(f"Curl failed with code {result.returncode}: {result.stderr.decode('utf-8', errors='ignore')}")
                # Fallback to requests? No, requests is broken.
                raise Exception(f"Curl failed: {result.stderr.decode('utf-8', errors='ignore')}")
                
            # Parse output
            # Curl might output headers if -i is used, but we used -v to stderr.
            # stdout should be body.
            stdout_str = result.stdout.decode('utf-8', errors='replace')
            _logger.info(f"Curl STDOUT: {stdout_str}")  # LOGGING RESPONSE
            return result.stdout
            
        finally:
            # Cleanup temp files
            for path in temp_files:
                if os.path.exists(path):
                    os.unlink(path)

    def _get_token(self):
        return self.env['ir.config_parameter'].sudo().get_param('construction_bot.token')

    def _download_file(self, file_id):
        """Downloads file from Telegram"""
        token = self._get_token()
        try:
            # 1. Get File Path
            path_url = f"https://api.telegram.org/bot{token}/getFile"
            # res = requests.get(path_url, params={'file_id': file_id}, timeout=10)
            res_content = self._curl_request('GET', path_url, params={'file_id': file_id}, timeout=10)
            if not res_content: return None
            
            res_json = json.loads(res_content)
            if not res_json.get('ok'):
                _logger.error(f"Telegram getFile error: {res_json}")
                return None
                
            file_path = res_json['result']['file_path']
            
            # 2. Download Content
            dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            # content_res = requests.get(dl_url, timeout=30)
            content = self._curl_request('GET', dl_url, timeout=30)
            
            return content
        except Exception as e:
            _logger.error(f"[BOT] File download failed: {e}")
            return None

    # --- Communication Helpers ---

    def _send_message(self, chat_id, text, reply_markup=None, parse_mode='Markdown'):
        token = self._get_token()
        if not token or token == 'YOUR_BOT_TOKEN_HERE':
            _logger.warning("[BOT] Token not set!")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
        }
        if parse_mode:
            payload['parse_mode'] = parse_mode
        if reply_markup:
            payload['reply_markup'] = reply_markup

        try:
            # res = requests.post(url, json=payload, timeout=10)
            res_content = self._curl_request('POST', url, json_data=payload, timeout=10)
            if res_content:
                return json.loads(res_content)
            return None
        except Exception as e:
            _logger.error(f"[BOT] Failed to send message to {chat_id}: {e}")
            _logger.error(f"[BOT] Payload: {json.dumps(payload, ensure_ascii=False)}")
            return None

    def _send_photo(self, chat_id, photo_data, caption=None, reply_markup=None):
        token = self._get_token()
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        
        data = {'chat_id': chat_id, 'parse_mode': 'Markdown'}
        if caption:
            data['caption'] = caption
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
            
        files = {'photo': ('photo.jpg', photo_data, 'image/jpeg')}
        
        try:
            # res = requests.post(url, data=data, files=files, timeout=30)
            res_content = self._curl_request('POST', url, data=data, files=files, timeout=30)
            if res_content:
                return json.loads(res_content)
            return None
        except Exception as e:
            _logger.error(f"[BOT] Failed to send photo to {chat_id}: {e}")
            return None

    def _send_document(self, chat_id, doc_data, filename="file.pdf", caption=None, reply_markup=None):
        token = self._get_token()
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        
        data = {'chat_id': chat_id, 'parse_mode': 'Markdown'}
        if caption:
            data['caption'] = caption
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
            
        files = {'document': (filename, doc_data)}
        
        try:
            # res = requests.post(url, data=data, files=files, timeout=40)
            res_content = self._curl_request('POST', url, data=data, files=files, timeout=40)
            if res_content:
                return json.loads(res_content)
            return None
        except Exception as e:
            _logger.error(f"[BOT] Failed to send document to {chat_id}: {e}")
            return None

    def _edit_message_caption(self, chat_id, message_id, caption, reply_markup=None):
        token = self._get_token()
        url = f"https://api.telegram.org/bot{token}/editMessageCaption"
        
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'caption': caption,
            'parse_mode': 'Markdown'
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
            
        try:
            # requests.post(url, json=payload, timeout=10)
            self._curl_request('POST', url, json_data=payload, timeout=10)
        except Exception as e:
            _logger.error(f"[BOT] Failed to edit caption {chat_id}/{message_id}: {e}")

    def _edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        token = self._get_token()
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
        try:
            # requests.post(url, json=payload, timeout=10)
            self._curl_request('POST', url, json_data=payload, timeout=10)
        except Exception as e:
            _logger.error(f"[BOT] Failed to edit text {chat_id}/{message_id}: {e}")

    # --- Role Definitions ---
    
    def _get_roles(self):
        return {
            'client': "Mijoz",
            'designer': "Dizayner",
            'worker': "Usta",
            'foreman': "Prorab",
            'supply': "Ta'minotchi",
            'admin': "Admin"
        }

    # --- Main Handler ---

    def handle_update(self, data):
        """Dispatch update to appropriate handler with deduplication"""
        update_id = data.get('update_id')
        
        # Extract User ID to finding the user record
        telegram_user_id = None
        if 'message' in data:
            telegram_user_id = data['message'].get('from', {}).get('id')
        elif 'callback_query' in data:
            telegram_user_id = data['callback_query'].get('from', {}).get('id')
            
        if telegram_user_id:
             # Find user
             user = self.env['res.users'].sudo().search([('telegram_chat_id', '=', str(telegram_user_id))], limit=1)
             if user:
                 # LOCKING: Prevent race conditions
                 self.env.cr.execute("SELECT id FROM res_users WHERE id = %s FOR UPDATE", [user.id])
                 user.invalidate_recordset(['last_processed_update_id'])
                 
                 last_id = int(user.last_processed_update_id or 0)
                 if update_id and int(update_id) <= last_id:
                     _logger.info(f"Skipping duplicate update {update_id} for user {user.name}")
                     return

                 # Update immediately to prevent race conditions
                 if update_id:
                     user.sudo().write({'last_processed_update_id': str(update_id)})
                     # CRITICAL: Commit immediately to release the row lock.
                     # This prevents long-running requests (video upload) from blocking 
                     # subsequent duplicate requests, avoiding SerializationFailure.
                     self.env.cr.commit()

        if 'message' in data:
            self._handle_message(data['message'])
        elif 'callback_query' in data:
            self._handle_callback(data['callback_query'])

    def _handle_message(self, message):
        chat_id = str(message.get('chat', {}).get('id'))
        text = message.get('text', '').strip()
        user_name = message.get('from', {}).get('first_name', 'User')

        # 1. Find User
        user = self.env['res.users'].search([('telegram_chat_id', '=', chat_id)], limit=1)

        # 2. Access Control
        if not user:
            # 2. Self-Registration Start
            _logger.info(f"[BOT] New User Registration: {chat_id}, Name: {user_name}")
            user = self.env['res.users'].with_context(no_notify_role=True).sudo().create({
                'name': user_name or "New Telegram User",
                'login': f"telegram_{chat_id}",
                'email': f"telegram_{chat_id}@example.com", # Dummy email
                'telegram_chat_id': chat_id,
                'construction_role': 'worker', # Default placeholder
                'active': True,
                'groups_id': [(6, 0, [self.env.ref('base.group_user').id])] # Basic internal user
            })
            # Start registration immediately
            self._start_registration(user)
            return

        # 3. Deduplication (Atomic)
        current_msg_id = message.get('message_id')
        if current_msg_id:
            self.env.cr.execute("""
                UPDATE res_users 
                SET last_bot_msg_id = %s 
                WHERE id = %s AND (last_bot_msg_id IS NULL OR last_bot_msg_id != %s)
                RETURNING id
            """, (current_msg_id, user.id, current_msg_id))
            
            if not self.env.cr.fetchone():
                _logger.info(f"[BOT] Ignoring duplicate message {current_msg_id} from {user.name}")
                return
            
            user.invalidate_recordset(['last_bot_msg_id'])

        _logger.info(f"[BOT] Update from {user.name} ({chat_id}): {text}")

        # Command handling
        if text == '/start':
            self._handle_start(user)
            return

        # Check Registration Status (only by state, not verification)
        if user.construction_bot_state.startswith('registration_'):
            self._handle_registration_flow(user, text)
            return
        # State machine handling
        state = user.construction_bot_state
        
        # AI Input Handling (Photo/Voice/Text)
        if state == 'usta_ai_input':
            self._handle_usta_ai_input(user, message)
            return

        if state != 'idle':
            # ... (State handling logic unchanged)
            if state == 'registration_name': # Fallback if caught here
                 self._handle_registration_flow(user, text)
                 return
            elif state == 'select_project':
                self._handle_project_selection(user, text)
                return
            elif state == 'select_stage':
                self._handle_stage_selection(user, text)
                return
            elif state == 'choose_action':
                self._handle_action_selection(user, text)
                return
            elif state == 'type_selection':
                self._handle_type_selection(user, text)
                return
            # ... (Rest of states unchanged)
            elif state == 'select_product_material':
                self._handle_product_selection(user, text, 'material')
                return
            elif state == 'select_product_service':
                self._handle_product_selection(user, text, 'service')
                return
            elif state == 'select_variant':
                self._handle_variant_selection(user, text)
                return
            elif state == 'input_qty_price':
                self._handle_qty_price_input(user, text)
                return
            elif state == 'input_new_product_name':
                self._handle_new_product_name(user, text)
                return
            # ...
            elif state == 'input_new_variant_name':
                self._handle_new_variant_name(user, text)
                return
            elif state == 'input_product_details':
                self._handle_product_details_input(user, text)
                return
            elif state == 'input_material':
                self._handle_material_input(user, text)
                return
            elif state == 'input_service':
                self._handle_service_input(user, text)
                return
            elif state == 'input_photo':
                self._handle_photo_upload(user, message)
                return
            elif state == 'awaiting_stage_image':
                self._handle_stage_image_upload(user, message)
                return
            elif state == 'foreman_input_report_text':
                self._handle_foreman_report_text(user, text)
                return
            elif state == 'foreman_input_report_media':
                self._handle_foreman_report_media(user, message)
                return
            elif state == 'worker_issue_input_text':
                self._handle_issue_text_input(user, text)
                return
            elif state == 'worker_issue_input_photos':
                self._handle_issue_photo(user, message)
                return
            elif state == 'usta_mr_input':
                self._handle_mr_input(user, text)
                return
            elif state == 'usta_mr_draft_input':
                self._handle_mr_draft_input(user, text)
                return
            elif state == 'snab_price_input':
                self._handle_snab_price_input(user, text)
                return
            elif state == 'snab_mr_price_input':
                self._handle_snab_mr_price(user, text)
                return
            elif state == 'snab_price_input_line':
                self._handle_snab_line_price_input(user, text)
                return
            elif state == 'snab_voice_price_wait':
                # Text fallback for voice pricing
                self._handle_snab_voice_pricing(user, message)
                return

            # Default fallback for state not handled explicitly above
            self._show_main_menu(user)
            return

        # Idle state
        if text == '/start':
            self._handle_start(user)
        else:
            self._show_main_menu(user)
            
    def _handle_start(self, user):
        # Reset state
        user.write({
            'construction_bot_state': 'idle',
            'construction_selected_project_id': False,
            'construction_selected_stage_id': False
        })
        
        # Check if still in registration
        if user.construction_bot_state.startswith('registration_'):
            self._handle_registration_flow(user, '')
            return
        if not user.construction_role:
             self._send_message(user.telegram_chat_id, "⚠️ Sizga rol biriktirilmagan. Adminga murojaat qiling.")
        else:
             self._show_main_menu(user)

    def _start_registration(self, user):
        msg = (
            "👋 *Assalomu alaykum!*\n\n"
            "Construction Management Botiga xush kelibsiz.\n"
            "Ro‘yxatdan o‘tish uchun, iltimos, *Ism-Familiyangizni* kiriting:"
        )
        user.sudo().write({'construction_bot_state': 'registration_name'})
        self._send_message(user.telegram_chat_id, msg)

    def _handle_registration_flow(self, user, text):
        state = user.construction_bot_state
        
        if state == 'registration_name':
            if len(text) < 3:
                self._send_message(user.telegram_chat_id, "⚠️ Ism juda qisqa. Iltimos, to‘liq ismingizni kiriting:")
                return
                
            # Save Name
            user.sudo().write({
                'name': text,
                'construction_bot_state': 'registration_role'
            })
            
            # Ask Role
            roles = [
                ('designer', '🖌 Dizayner'),
                ('foreman', '👷 Prorab'),
                ('worker', '🛠 Usta'),
                ('supply', "📦 Ta'minotchi"),
                ('client', '👤 Buyurtmachi (Mijoz)'),
            ]
            
            keyboard = []
            for r_key, r_label in roles:
                keyboard.append([{'text': r_label, 'callback_data': f'reg:role:{r_key}'}])
                
            reply_markup = {'inline_keyboard': keyboard}
            
            msg = f"Rahmat, *{text}*!\nEndi o‘z vazifangizni (rolingizni) tanlang:"
            self._send_message(user.telegram_chat_id, msg, reply_markup=reply_markup)
            
        elif state == 'registration_role':
            self._send_message(user.telegram_chat_id, "Iltimos, yuqoridagi tugmalardan birini tanlang ⬆️")

    def _on_user_approved(self, user):
        """Called automatically when Admin approves the user in Odoo"""
        if not user.telegram_chat_id: return
        
        role_map = self._get_roles()
        role_label = role_map.get(user.construction_role, user.construction_role)
        
        msg = (
            "🎉 *Tabriklaymiz!*\n\n"
            "Sizning so‘rovingiz tasdiqlandi.\n"
            f"Sizga *{role_label}* roli biriktirildi.\n\n"
        )
        
        # Check if project assigned
        if user.allowed_project_ids:
             proj_names = ", ".join(user.allowed_project_ids.mapped('name'))
             msg += f"🏗 *Biriktirilgan loyihalar:* {proj_names}\n\n"
        else:
             msg += "⚠️ Hozircha sizga loyiha biriktirilmagan.\n\n"
             
        msg += "Ishni boshlash uchun quyidagi menyudan foydalaning 👇"
        
        self._send_message(user.telegram_chat_id, msg)
        self._show_main_menu(user)

    def _system_notify_user_role_update(self, users, is_new_access=False):
        for user in users:
            if not user.telegram_chat_id: continue
            
            role_label = dict(user._fields['construction_role'].selection).get(user.construction_role, user.construction_role)
            
            projects = user.allowed_project_ids
            if projects:
                proj_names = ", ".join(projects.mapped('name'))
                proj_label = "Loyihalar" if len(projects) > 1 else "Loyiha"
                project_line = f"🏗 *{proj_label}:* {proj_names}"
            else:
                project_line = "⚠️ Sizga hali loyiha biriktirilmagan."

            # Specific Assignment Message
            msg = (
                "✅ *Siz loyihaga biriktirildingiz!*\n\n"
                f"👤 *Rol:* {role_label}\n"
                f"{project_line}"
            )
                
            self._send_message(user.telegram_chat_id, msg)
            self._show_main_menu(user)

    def _handle_callback(self, callback):
        data = callback.get('data')
        chat_id = str(callback.get('message', {}).get('chat', {}).get('id'))
        callback_id = callback.get('id')
        
        if not data: return
        
        # User check
        user = self.env['res.users'].search([('telegram_chat_id', '=', chat_id)], limit=1)
        if not user: return
        
        _logger.info(f"[BOT] Callback {data} from {user.name}")
        
        # --- Navigation ---
        if data.startswith('reg:role:'):
            role_key = data.split(':')[2]
            
            # Validate Role
            valid_roles = ['designer', 'worker', 'foreman', 'supply', 'client']
            if role_key not in valid_roles:
                return
                
            user.with_context(no_notify_role=True).sudo().write({
                'construction_role': role_key,
                'construction_bot_state': 'idle'
            })
            
            # Notify Admin? (Optional)
            
            # Notify User
            msg = "✅ *Sorov yuborildi. Sizga loyiha biriktirilishini kuting.*"
            # Edit previous message to remove buttons
            self._edit_message_text(user.telegram_chat_id, callback.get('message', {}).get('message_id'), "Rol tanlandi.")
            self._send_message(user.telegram_chat_id, msg)
            return

        if data == 'nav:cancel_role':
            # This shouldn't happen with new logic, but safe remove
            pass 
        elif data == 'nav:home':
            self._handle_nav_home(user)
        elif data == 'nav:back':
            self._show_main_menu(user) 

        # --- Menu Callbacks ---
        elif data.startswith('menu:'):
            # Special redirects for Step 3
            if data == 'menu:main':
                self._handle_nav_home(user)
                return
            elif data == 'menu:worker:today_tasks':
                self._ask_project_selection_for_tasks(user)
                return
            # Special redirects for Step 4
            elif data == 'menu:foreman:daily_report':
                self._ask_project_selection_for_report(user)
                return
            # Step 7: Supply Purchase Request Entry
            # Step 18: Issue Reporting
            elif data == 'menu:worker:issue':
                self._start_issue_flow(user)
                return
            # Step 8: Material Request Entry (Batch Flow)
            elif data == 'menu:worker:material_request':
                self._start_mr_batch_flow(user)
                return
            # Step 12: Usta File Browsing
            elif data == 'menu:worker:files':
                self._start_usta_file_browsing(user)
                return
            
            # --- Snab Menus ---
            elif data == 'menu:supply:pending_requests':
                self._start_snab_pending_requests(user)
                return
            elif data == 'menu:supply:approved_requests':
                self._start_snab_approved_requests(user) # Will create this wrapper
                return
                
            # --- Foreman Menus ---
            elif data == 'menu:foreman:issues':
                self._start_foreman_issues(user)
                return
            
            # Step 23: Client Dashboard
            elif data == 'menu:client:status':
                self._start_client_project_status(user)
                return
            elif data == 'menu:client:money':
                self._start_client_cash_flow(user)
                return
            elif data == 'menu:supply:delivery_status':
                 self._start_snab_delivery_status(user)
                 return

            self._handle_menu_placeholder(user, data)
        
        # --- Step 7: Supply PR Flow ---
        elif data.startswith('usta:mr:project:'):
             pid = int(data.split(':')[3])
             self._start_mr_draft_input(user, pid)
        elif data == 'usta:mr:back':
             self._handle_mr_draft_back(user)
        elif data == 'usta:mr:confirm':
             self._confirm_mr_draft(user)
             
        
        elif data.startswith('snab:mr:price_batch:'):
             batch_id = int(data.split(':')[3])
             self._start_snab_batch_pricing(user, batch_id)
        elif data.startswith('snab:mr:line:'):
             line_id = int(data.split(':')[3])
             self._handle_snab_select_line(user, line_id)
        elif data == 'snab:mr:back_to_panel':
             self._show_pricing_panel(user)
        elif data == 'snab:mr:exit':
             user.sudo().write({
                 'snab_price_batch_id': False,
                 'snab_price_line_id': False,
                 'construction_bot_state': 'idle'
             })
             self._show_main_menu(user)
        elif data.startswith('snab:mr:send_for_approval:'):
             batch_id = int(data.split(':')[3])
             self._send_batch_for_approval(user, batch_id)
        elif data.startswith('mr:batch:approve:'):
             batch_id = int(data.split(':')[3])
             self._handle_batch_approval(user, batch_id, 'approve')
        elif data.startswith('mr:batch:reject:'):
             batch_id = int(data.split(':')[3])
             self._handle_batch_approval(user, batch_id, 'reject')

        elif data.startswith('worker:mr:project:'): # Legacy or accidentally triggered
             pid = int(data.split(':')[3])
             self._ask_mr_input(user, pid)
        elif data.startswith('snab:mr:price:'):
             mrid = int(data.split(':')[3])
             self._start_snab_pricing(user, mrid)
        elif data.startswith('mr:approve:'):
             mrid = int(data.split(':')[2])
             self._handle_mr_decision(user, mrid, 'approve')
        elif data.startswith('mr:reject:'):
             mrid = int(data.split(':')[2])
             self._handle_mr_decision(user, mrid, 'reject')
        
        
        # --- Client Approvals 2.0 Flow ---
        elif data == 'client:approvals:status_selection':
             self._show_client_approvals_status_selection(user)
        elif data.startswith('client:approvals:status:'):
             status_key = data.split(':')[3]  # draft, approved, rejected
             self._show_client_approvals_list(user, status_key)
        elif data.startswith('client:approvals:open:'):
             batch_id = int(data.split(':')[3])
             self._show_client_approval_detail(user, batch_id)
        elif data.startswith('client:approvals:approve:'):
             batch_id = int(data.split(':')[3])
             self._handle_client_approval_action(user, batch_id, 'approve')
        elif data.startswith('client:approvals:reject:'):
             batch_id = int(data.split(':')[3])
             self._handle_client_approval_action(user, batch_id, 'reject')



        # --- Step 3: Worker Task Flow ---
        elif data.startswith('worker:tasks:project:'):
            project_id = int(data.split(':')[3])
            self._ask_task_filter(user, project_id)
        
        elif data.startswith('worker:tasks:list:'):
            # Format: worker:tasks:list:<proj_id>:<filter>
            parts = data.split(':')
            project_id = int(parts[3])
            filter_type = parts[4]
            self._show_task_list(user, project_id, filter_type)
            
        elif data.startswith('worker:task:'):
            task_id = int(data.split(':')[2])
            self._show_task_detail(user, task_id)
            
        elif data.startswith('worker:done:'):
            task_id = int(data.split(':')[2])
            self._mark_task_state(user, task_id, 'done')
            
        elif data.startswith('worker:inprogress:'):
            task_id = int(data.split(':')[2])
            self._mark_task_state(user, task_id, 'in_progress')
            
        # Task-linked Material Request
        elif data.startswith('tasks:mr:start:'):
            task_id = int(data.split(':')[3])
            self._handle_task_mr_start(user, task_id)
            
        # --- Step 18: Issue Actions ---
        elif data == 'issue:confirm':
            self._confirm_issue_creation(user)
        elif data.startswith('issue:set:'):
            # Format: issue:set:<state>:<id>
            parts = data.split(':')
            new_state = parts[2]
            issue_id = int(parts[3])
            self._handle_issue_status_change(user, issue_id, new_state)

        # --- Step 4: Foreman Report Flow ---
        elif data.startswith('foreman:report:project:'):
            project_id = int(data.split(':')[3])
            self._start_foreman_report_input(user, project_id)
        elif data == 'foreman:report:finish':
            self._finish_foreman_report(user)
        elif data == 'foreman:report:back_to_project':
            self._ask_project_selection_for_report(user)

        # --- Client Dashboard Flow ---
        # menu:client:status and menu:client:money are handled in the menu: block above
        elif data.startswith('client:status:project:'):
             pid = int(data.split(':')[3])
             self._handle_client_project_status(user, pid)
        elif data.startswith('client:money:project:'):
             pid = int(data.split(':')[3])
             self._handle_client_cash_flow(user, pid)

        # --- Snab Requests & Pricing ---
        elif data.startswith('snab:req:open:'):
             batch_id = int(data.split(':')[3])
             self._show_snab_req_detail(user, batch_id)
        elif data.startswith('snab:req:price:'):
             batch_id = int(data.split(':')[3])
             self._start_snab_pricing_flow(user, batch_id)
        elif data.startswith('snab:req:setprice:'):
             line_id = int(data.split(':')[3])
             self._ask_snab_line_price(user, line_id)
        elif data.startswith('snab:req:send:'):
             batch_id = int(data.split(':')[3])
             self._handle_snab_send_approval(user, batch_id)
        elif data.startswith('snab:req:list:'):
             pid = int(data.split(':')[3])
             self._show_snab_pending_list(user, pid)
        elif data.startswith('snab:req:project:'):
             pid = int(data.split(':')[3])
             self._show_snab_pending_list(user, pid)
        elif data.startswith('snab:approved:project:'):
             pid = int(data.split(':')[3])
             self._show_snab_approved_list(user, pid)
        elif data.startswith('snab:approved:list:'):
             pid = int(data.split(':')[3])
             self._show_snab_approved_list(user, pid)
        elif data.startswith('snab:pending:export:'):
             # snab:pending:export:excel:pid
             parts = data.split(':')
             fmt = parts[3]
             pid = int(parts[4])
             self._handle_snab_export(user, pid, 'pending', fmt)
        elif data.startswith('snab:approved:export:'):
             # snab:approved:export:excel:pid
             parts = data.split(':')
             fmt = parts[3]
             pid = int(parts[4])
             self._handle_snab_export(user, pid, 'approved', fmt)
             self._handle_snab_export(user, pid, 'approved', fmt)

        # Voice Pricing
        elif data.startswith('snab:price_voice:'):
             pid = int(data.split(':')[2])
             self._start_snab_voice_pricing(user, pid)

        # --- Prorab Issues ---
        elif data.startswith('prorab:issues:list:'):
             parts = data.split(':')
             pid = int(parts[3])
             flt = parts[4]
             self._show_foreman_issues_list(user, pid, flt)
        elif data.startswith('prorab:issues:filter:'):
             # Format: prorab:issues:filter:type:pid
             parts = data.split(':')
             pid = int(parts[4])
             flt = parts[3] # open/all
             self._show_foreman_issues_list(user, pid, flt)
        elif data.startswith('prorab:issues:open:'):
             iid = int(data.split(':')[3])
             self._show_foreman_issue_detail(user, iid)
        elif data.startswith('prorab:issues:project:'):
             pid = int(data.split(':')[3])
             self._ask_issue_filter(user, pid)

        elif data.startswith('prorab:issues:project:'):
             pid = int(data.split(':')[3])
             self._ask_issue_filter(user, pid)

        # --- Snab Delivery Status ---
        elif data.startswith('dlv|proj|'):
             pid = int(data.split('|')[2])
             self._show_snab_delivery_filter(user, pid)
        elif data.startswith('dlv|flt|'):
             # dlv|flt|<state>|<pid>
             parts = data.split('|')
             state = parts[2]
             pid = int(parts[3])
             self._show_snab_delivery_list(user, pid, state)
        elif data.startswith('dlv|bat|'):
             # dlv|bat|<batch_id>|<pid>
             parts = data.split('|')
             bid = int(parts[2])
             self._show_snab_delivery_detail(user, bid)
        elif data.startswith('dlv|set|'):
             # dlv|set|<bid>|<state>|<pid>
             parts = data.split('|')
             bid = int(parts[2])
             state = parts[3]
             pid = int(parts[4])
             self._handle_snab_delivery_update(user, bid, state, pid)

        # --- Step 5: File Browsing Flow (Bot) ---
        elif data == 'menu:client:files':
            self._start_file_browsing(user)
        
        # --- Usta Files Browsing Callbacks ---
        elif data.startswith('usta:files:project:'):
            pid = int(data.split(':')[3])
            self._handle_usta_files_project_selection(user, pid)
        elif data.startswith('usta:files:cat:'):
            cid = int(data.split(':')[3])
            self._handle_usta_files_category_selection(user, cid)
        elif data.startswith('usta:files:room_idx:'):
            idx = int(data.split(':')[3])
            self._handle_usta_files_room_selection(user, idx)

            
        elif data.startswith('files:prj:'):
            pid = int(data.split(':')[2])
            self._handle_files_project_selection(user, pid)
        elif data.startswith('files:room:'):
            # encoded room is index 2
            encoded = data.split(':')[2]
            self._handle_files_room_selection(user, encoded)
        elif data.startswith('files:cat:'):
            cat_id = int(data.split(':')[2])
            self._handle_files_category_selection(user, cat_id)
        elif data.startswith('files:open:'):
            fid = int(data.split(':')[2])
            self._open_file(user, fid)


    # --- Logic Methods ---
    
    def _handle_nav_home(self, user):
        """Clears all temporary state and shows main menu"""
        _logger.info(f"[BOT_NAV] Nav Home called for {user.name}")
        user.sudo().write({
            'construction_bot_state': 'idle',
            'construction_selected_project_id': False,
            'construction_selected_stage_id': False,
            'construction_selected_task_id': False,
            'construction_selected_product_tmpl_id': False,
            'construction_selected_product_id': False,
            # Snab
            'snab_price_batch_id': False,
            'snab_price_line_id': False,
            # MR Draft
            'mr_draft_project_id': False,
            # Usta Files
            'usta_files_project_id': False,
            'usta_files_category_id': False,
            'usta_files_room_ref': False,
            'usta_files_room_map': False,
            # Legacy
            'file_nav_project_id': False,
            'file_nav_room_ref': False,
            'file_nav_category_id': False,
        })
        _logger.info(f"[BOT_NAV] State cleared for {user.name}, calling _show_main_menu")
        self._show_main_menu(user)

    def _show_main_menu(self, user):
        role = user.construction_role
        
        # Check Project Assignment (Hide menu if no project)
        if role != 'admin' and not user.allowed_project_ids:
            _logger.info(f"[BOT_MENU] Hiding menu for {user.name} (No Projects)")
            self._send_message(user.telegram_chat_id, "⚠️ Sizga hali loyiha biriktirilmagan.\nAdmin siz uchun loyiha biriktirganida, menyu paydo bo'ladi.")
            return

        _logger.info(f"[BOT_MENU] Showing menu for {user.name}, Role: {role}")
        
        if role == 'client':
            self._show_menu_client(user)
        elif role == 'designer':
            self._show_menu_designer(user)
        elif role == 'worker':
            self._show_menu_worker(user)
        elif role == 'foreman':
            self._show_menu_foreman(user)
        elif role == 'supply':
            self._show_menu_supply(user)
        elif role == 'admin':
            self._show_menu_admin(user)
        else:
            _logger.warning(f"[BOT_MENU] Unknown role: {role}")
            self._send_message(user.telegram_chat_id, "⚠️ Sizda aniq rol belgilanmagan.")

    def _get_nav_row(self, back_cb=None, home=True):
        # Universal navigation row
        row = []
        if back_cb:
            row.append({'text': "⬅️ Ortga", 'callback_data': back_cb})
        if home:
            row.append({'text': "🏠 Bosh menyu", 'callback_data': "nav:home"})
        return row

    def _get_dashboard_url(self, user):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        # Use HTTPS from tunnel if base_url is http (common in dev)
        # Actually user said "CloudClusters deployment: upload via FTPS... persistent path...".
        # Assuming web.base.url is correct or I should trust it.
        # But Telegram WebApp requires https. Retrieve the tunnel URL from parameters or config if needed.
        # Let's trust web.base.url but ensure scheme is https if possible, or leave it to Odoo config.
        session = self.env['construction.webapp.session'].sudo().create_session(user.id)
        return f"{base_url}/webapp/dashboard?token={session.token}"

    def _show_menu_client(self, user):
        dashboard_url = self._get_dashboard_url(user)
        buttons = [
            # WebApp Button
            [{'text': "📊 Proyekt paneli", 'web_app': {'url': dashboard_url}}],
            # Legacy Buttons
            [{'text': "📊 Proyekt holati (Bot)", 'callback_data': "menu:client:status"}],
            [{'text': "💰 Pul oqimi", 'callback_data': "menu:client:money"}],
            [{'text': "✅ Tasdiqlashlar", 'callback_data': "client:approvals:status_selection"}],
            [{'text': "🧾 Hisobotlar", 'callback_data': "menu:client:reports"}],
            [{'text': "📎 Fayllar", 'callback_data': "menu:client:files"}],
        ]
        self._send_message(user.telegram_chat_id, "👤 *Mijoz menyusi*", reply_markup={'inline_keyboard': buttons})

    def _show_client_approvals_status_selection(self, user):
        """Step 1: Client Approvals -> Select Status"""
        buttons = [
            [{'text': "🕒 Kutilmoqda", 'callback_data': "client:approvals:status:draft"}],
            [{'text': "✅ Tasdiqlangan", 'callback_data': "client:approvals:status:approved"}],
            [{'text': "❌ Rad etilgan", 'callback_data': "client:approvals:status:rejected"}],
            self._get_nav_row()
        ]
        self._send_message(
            user.telegram_chat_id,
            "✅ *Tasdiqlashlar*\nHolatni tanlang:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _show_menu_designer(self, user):
        buttons = [
            [{'text': "➕ Yangi proyekt", 'callback_data': "menu:designer:new_project"}],
            [{'text': "📁 Chizma/Render yuklash", 'callback_data': "menu:designer:upload"}],
            [{'text': "🔁 Versiya yangilash", 'callback_data': "menu:designer:version"}],
            [{'text': "📝 Izoh/Topshiriq", 'callback_data': "menu:designer:note"}]
        ]
        self._send_message(user.telegram_chat_id, "🎨 *Dizayner menyusi*", reply_markup={'inline_keyboard': buttons})

    def _show_menu_worker(self, user):
        buttons = [
            [{'text': "📌 Vazifalar", 'callback_data': "menu:worker:today_tasks"}],
            [{'text': "✅ Bajarildi", 'callback_data': "menu:worker:done"}],
            [{'text': "⚠️ Muammo/To'siq", 'callback_data': "menu:worker:issue"}],
            [{'text': "🧱 Material so'rovi", 'callback_data': "menu:worker:material_request"}],
            [{'text': "📎 Fayllar", 'callback_data': "menu:worker:files"}]
        ]
        self._send_message(user.telegram_chat_id, "🧱 *Usta menyusi*", reply_markup={'inline_keyboard': buttons})

    def _show_menu_foreman(self, user):
        buttons = [
            [{'text': "📸 Kunlik hisobot", 'callback_data': "menu:foreman:daily_report"}],
            [{'text': "📅 Reja / Fakt", 'callback_data': "menu:foreman:plan_fact"}],
            [{'text': "🧾 Etapni qabulga chiqarish", 'callback_data': "menu:foreman:stage_submit"}],
            [{'text': "⚠️ Risk va kechikish", 'callback_data': "menu:foreman:issues"}],
        ]
        self._send_message(user.telegram_chat_id, "👷 *Prorab menyusi*", reply_markup={'inline_keyboard': buttons})

    def _show_menu_supply(self, user):
        buttons = [
            [{'text': "📨 So‘rovlar", 'callback_data': "menu:supply:pending_requests"}],
            [{'text': "✅ Materiallar ro‘yxati", 'callback_data': "menu:supply:approved_requests"}],
            [{'text': "🚚 Yetkazish statusi", 'callback_data': "menu:supply:delivery_status"}],
            [{'text': "💵 Narxlar va variantlar", 'callback_data': "menu:supply:prices"}],
        ]
        self._send_message(user.telegram_chat_id, "🚚 *Ta'minotchi menyusi*", reply_markup={'inline_keyboard': buttons})

    def _show_menu_admin(self, user):
        buttons = [
            [{'text': "👥 Foydalanuvchilar", 'callback_data': "menu:admin:users"}],
            [{'text': "✅ Tasdiqlashlar", 'callback_data': "menu:admin:approvals"}],
            [{'text': "🧾 Loyihalar", 'callback_data': "menu:admin:projects"}],
            [{'text': "⚙️ Sozlamalar", 'callback_data': "menu:admin:settings"}]
        ]
        self._send_message(user.telegram_chat_id, "🛡 *Admin menyusi*", reply_markup={'inline_keyboard': buttons})

    def _handle_menu_placeholder(self, user, data):
        # Step 3 Override: Redirect Worker Menu
        if data == 'menu:worker:today_tasks':
            self._ask_project_selection_for_tasks(user)
            return
            
        self._send_message(user.telegram_chat_id, "⏳ Bu bo‘lim hali tayyor emas. Tez orada qo‘shiladi.")
        self._show_main_menu(user)


    # --- Step 3: Worker Tasks ---

    def _ensure_project_or_ask(self, user, next_action_cb_prefix):
        """
        Reusable helper to handle project selection.
        Returns: (project_record, status_code)
        status_code: 'auto_selected', 'asked_selection', 'no_projects'
        """
        projects = user.get_allowed_construction_projects()
        
        if not projects:
            self._send_message(user.telegram_chat_id, "🔴 Sizga biriktirilgan loyihalar topilmadi.")
            return None, "no_projects"

        if len(projects) == 1:
            project = projects[0]
            # Store generic context if needed, but mostly caller handles it.
            return project, "auto_selected"

        # Else show selection
        buttons = []
        for p in projects:
            # Callback format: prefix:project:id
            buttons.append([{'text': p.name, 'callback_data': f"{next_action_cb_prefix}:project:{p.id}"}])
        
        buttons.append(self._get_nav_row(back_cb=None))
        
        self._send_message(
            user.telegram_chat_id, 
            "Loyihani tanlang:", 
            reply_markup={'inline_keyboard': buttons}
        )
        return None, "asked_selection"

    def _get_user_projects(self, user):
        return user.get_allowed_construction_projects()

    def _ask_project_selection_for_tasks(self, user):
        project, status = self._ensure_project_or_ask(user, "worker:tasks")
        
        if status == 'auto_selected':
             self._ask_task_filter(user, project.id)

    def _ask_task_filter(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists():
            self._send_message(user.telegram_chat_id, "❌ Loyiha topilmadi.")
            self._show_main_menu(user)
            return

        buttons = [
            [{'text': "📅 Bugungi vazifalar", 'callback_data': f"worker:tasks:list:{project.id}:today"}],
            [{'text': "♾️ Barcha vazifalar", 'callback_data': f"worker:tasks:list:{project.id}:all"}],
            self._get_nav_row(back_cb="menu:worker:today_tasks")
        ]
        
        self._send_message(
            user.telegram_chat_id,
            f"📌 *{project.name}*\nVazifalarni saralash:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _show_task_list(self, user, project_id, filter_type):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return

        domain = [
            ('project_id', '=', project.id),
            ('assignee_id', '=', user.id),
            ('assignee_role', '=', 'worker'),  # Strict check
            ('state', '!=', 'done')
        ]
        
        if filter_type == 'today':
            domain.append(('deadline_date', '=', fields.Date.context_today(self)))
            title = "📅 Bugungi vazifalar"
        else:
            title = "♾️ Barcha vazifalar"

        tasks = self.env['construction.work.task'].search(domain)
        
        if not tasks:
            self._send_message(user.telegram_chat_id, f"✅ *{project.name}*: {title} topilmadi!")
            self._ask_task_filter(user, project.id)
            return

        buttons = []
        for t in tasks:
            name = t.name[:40] + "..." if len(t.name) > 40 else t.name
            # Emoticon for state
            icon = "🆕" if t.state == 'new' else "▶️"
            buttons.append([{'text': f"{icon} {name}", 'callback_data': f"worker:task:{t.id}"}])
            
        buttons.append(self._get_nav_row(back_cb=f"worker:tasks:project:{project.id}"))

        self._send_message(
            user.telegram_chat_id, 
            f"📌 *{project.name}* - {title}:", 
            reply_markup={'inline_keyboard': buttons}
        )

    def _show_task_detail(self, user, task_id):
        task = self.env['construction.work.task'].browse(task_id)
        if not task.exists():
            self._send_message(user.telegram_chat_id, "❌ Vazifa topilmadi.")
            # Fallback
            self._ask_project_selection_for_tasks(user)
            return

        state_label = dict(task._fields['state'].selection).get(task.state, task.state)
        
        msg = (
            f"📋 *Vazifa*: {task.name}\n"
            f"🏗 *Loyiha*: {task.project_id.name}\n"
            f"📅 *Muddat*: {task.deadline_date}\n"
            f"📊 *Holat*: {state_label}\n"
            f"📝 *Tavsif*: {task.description or '-'}"
        )

        buttons = []
        if task.state != 'done':
            buttons.append([{'text': "✅ Bajarildi", 'callback_data': f"worker:done:{task.id}"}])
        
        if task.state == 'new':
             buttons.append([{'text': "▶️ Jarayonda", 'callback_data': f"worker:inprogress:{task.id}"}])
             
        # Material Request button (for all non-done tasks)
        if task.state != 'done':
             buttons.append([{'text': "🧱 Material so'rovi", 'callback_data': f"tasks:mr:start:{task.id}"}])

        # Back returns to list (defaulting to 'all' or we need to track filter? Let's default to today or all. Or pass filter in callback?
        # Simpler: Back to Filter Selection
        buttons.append(self._get_nav_row(back_cb=f"worker:tasks:project:{task.project_id.id}"))

        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    def _mark_task_state(self, user, task_id, new_state):
        task = self.env['construction.work.task'].browse(task_id)
        if not task.exists():
            self._send_message(user.telegram_chat_id, "❌ Vazifa topilmadi.")
            return

        task.sudo().write({'state': new_state})
        
        state_labels = {'done': "Bajarildi", 'in_progress': "Jarayonda"}
        lbl = state_labels.get(new_state, new_state)
        
        self._send_message(user.telegram_chat_id, f"✅ Holat o'zgardi: *{lbl}*")
        
        # Show detail again to confirm
        self._show_task_detail(user, task.id)



    # --- Step 4: Foreman Daily Report ---

    def _ask_project_selection_for_report(self, user):
        project, status = self._ensure_project_or_ask(user, "foreman:report")
        
        if status == 'auto_selected':
             self._start_foreman_report_input(user, project.id)

    def _start_foreman_report_input(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists():
            self._send_message(user.telegram_chat_id, "❌ Loyiha topilmadi.")
            self._ask_project_selection_for_report(user)
            return

        user.write({
            'construction_selected_project_id': project.id,
            'construction_bot_state': 'foreman_input_report_text'
        })
        
        nav = self._get_nav_row(back_cb="foreman:report:back_to_project")
        self._send_message(user.telegram_chat_id, f"📝 *{project.name}*\nBugungi ishlar bo‘yicha qisqa hisobot yozing:", reply_markup={'inline_keyboard': [nav]})

    def _handle_foreman_report_text(self, user, text):
        project_id = user.construction_selected_project_id.id
        daily = self.env['construction.daily.photo'].sudo().get_or_create_today(project_id)
        
        # Update text AND name
        daily.write({
            'daily_report_text': text,
            'name': text[:100] if text else "Kunlik Hisobot"
        })
        daily.message_post(body=f"📝 *Kunlik hisobot:*\n{text}")
        
        user.write({'construction_bot_state': 'foreman_input_report_media'})
        
        self._reply_foreman_media_prompt(user)

    def _reply_foreman_media_prompt(self, user):
        project_id = user.construction_selected_project_id.id
        daily = self.env['construction.daily.photo'].sudo().get_or_create_today(project_id)
        count = self.env['construction.daily.photo.line'].search_count([('photo_id', '=', daily.id)])
        
        btn_text = f"✅ Tayyor ({count} ta rasm)" if count > 0 else "✅ Tayyor"
        
        buttons = [
            [{'text': btn_text, 'callback_data': "foreman:report:finish"}]
        ]
        buttons.append(self._get_nav_row(back_cb="foreman:report:back_to_project"))
        
        msg = "📎 Endi rasm yoki video yuboring.\nTugatgach, *✅ Tayyor* tugmasini bosing."
        if count > 0:
            msg = f"📎 Hozircha {count} ta rasm yuklangan.\nYana yuborishingiz yoki tugatishingiz mumkin."
            
        self._send_message(
            user.telegram_chat_id,
            msg,
            reply_markup={'inline_keyboard': buttons}
        )

    def _download_telegram_file(self, file_id):
        """Download file from Telegram and return bytes"""
        try:
            token = self._get_token()
             # Get file path
            url = f"https://api.telegram.org/bot{token}/getFile"
            # res = requests.get(url, params={'file_id': file_id}, timeout=10)
            res_content = self._curl_request('GET', url, params={'file_id': file_id}, timeout=10)
            
            if not res_content: return None
            
            result = json.loads(res_content)
            
            if not result.get('ok'):
                _logger.error(f"Telegram getFile error: {result}")
                return None
                
            file_path = result['result']['file_path']
            
            # Download content
            dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            # dl_res = requests.get(dl_url, timeout=30)
            dl_content = self._curl_request('GET', dl_url, timeout=30)
            
            return dl_content
            
        except Exception as e:
            _logger.error(f"Download failed for {file_id}: {e}")
            return None

    def _handle_foreman_report_media(self, user, message):
        project_id = user.construction_selected_project_id.id
        daily = self.env['construction.daily.photo'].sudo().get_or_create_today(project_id)
        
        success = False
        item_type = ""

        # 1. Photo
        if 'photo' in message:
            photo_file = message['photo'][-1]
            file_id = photo_file['file_id']
            caption = message.get('caption', '')
            
            image_data = self._download_telegram_file(file_id)
            if image_data:
                import base64
                encoded = base64.b64encode(image_data)
                self.env['construction.daily.photo.line'].create({
                    'photo_id': daily.id,
                    'image': encoded,
                    'caption': caption
                })
                success = True
                item_type = "Rasm"
        
        # 2. Video
        elif 'video' in message:
            video_file = message['video']
            file_id = video_file['file_id']
            
            video_data = self._download_telegram_file(file_id)
            if video_data:
                import base64
                encoded = base64.b64encode(video_data)
                
                attachment_name = f"video_{fields.Date.today()}_{file_id[:10]}.mp4"
                
                self.env['ir.attachment'].create({
                    'name': attachment_name,
                    'type': 'binary',
                    'datas': encoded,
                    'res_model': 'construction.daily.photo',
                    'res_id': daily.id,
                    'mimetype': 'video/mp4'
                })
                daily.message_post(body="📹 Video hisobot yuklandi.")
                success = True
                item_type = "Video"
        
        if success:
             # Recalculate count
             count = self.env['construction.daily.photo.line'].search_count([('photo_id', '=', daily.id)])
             # Add videos separately? Or just count prompt items. 
             # Daily photo lines are just photos. Videos are attachments.
             # If we want to count total media, we should count attachments too.
             # But prompt says "count ta rasm". Let's stick to photo lines for now or sum up.
             # The existing 'construction.daily.photo.line' is for photos.
             # For simplicity, let's just count photos + videos if possible, or just photos if that's what lines track.
             # The user screenshot says "Rasm qabul qilindi".
             
             count_videos = self.env['ir.attachment'].search_count([('res_model', '=', 'construction.daily.photo'), ('res_id', '=', daily.id)])
             total_count = count + count_videos
             
             buttons = [
                [{'text': f"✅ Tayyor ({total_count} ta media)", 'callback_data': "foreman:report:finish"}],
                self._get_nav_row(back_cb="foreman:report:back_to_project")
             ]
             
             self._send_message(
                 user.telegram_chat_id, 
                 f"✅ {item_type} qabul qilindi ({total_count} ta)\n\nYana rasm yuboring yoki 'Tayyor' bosing.", 
                 reply_markup={'inline_keyboard': buttons}
             )
        else:
             self._send_message(user.telegram_chat_id, "❌ Yuklab bo‘lmadi yoki noto‘g‘ri format.")
             
        # Reshow prompt
        # self._reply_foreman_media_prompt(user) # Optional: Don't spam, just ack

    def _finish_foreman_report(self, user):
        user.write({
            'construction_bot_state': 'idle',
            'construction_selected_project_id': False
        })
        self._send_message(user.telegram_chat_id, "✅ Kunlik hisobot muvaffaqiyatli topshirildi.")
        self._show_main_menu(user)


    def _handle_role_cancel(self, user):
        if user.construction_role_status == 'approved':
            self._send_message(user.telegram_chat_id, "✅ Siz allaqachon tasdiqlangan roldasiz.")
            self._show_main_menu(user)
            return

        user.write({
            'construction_role_status': False,
            'requested_construction_role': False
        })
        self._ask_role_selection(user)







    # --- Step 8: Material Request Flow (Usta -> Snab -> Admin/Client) ---
    
    def _handle_task_mr_start(self, user, task_id):
        """Start Material Request from Task context"""
        task = self.env['construction.work.task'].browse(task_id)
        if not task.exists():
            self._send_message(user.telegram_chat_id, "❌ Vazifa topilmadi.")
            return
        
        # Security check
        allowed = user.get_allowed_construction_projects()
        if task.project_id not in allowed:
            self._send_message(user.telegram_chat_id, "⛔ Ruxsat yo'q.")
            return
        
        # Check for existing draft batch for this task today
        today = fields.Date.context_today(self)
        existing_batch = self.env['construction.material.request.batch'].search([
            ('task_id', '=', task_id),
            ('requester_id', '=', user.id),
            ('date', '=', today),
            ('state', '=', 'draft')
        ], limit=1)
        
        if existing_batch:
            # Resume existing batch
            import json
            lines_list = []
            for line in existing_batch.line_ids:
                lines_list.append({'name': line.product_name, 'qty': line.quantity})
            
            user.sudo().write({
                'selected_task_id': task.id,
                'mr_draft_project_id': task.project_id.id,
                'mr_draft_lines_json': json.dumps(lines_list),
                'construction_bot_state': 'usta_mr_draft_input'
            })
            
            self._send_message(user.telegram_chat_id, f"♻️ Bugungi qoralama topildi, davom ettiramiz...\n📋 Vazifa: {task.name}")
            self._send_mr_draft_interface(user)
        else:
            # Start new batch with task context
            user.sudo().write({
                'selected_task_id': task.id,
                'mr_draft_project_id': task.project_id.id,
                'mr_draft_lines_json': json.dumps([]),
                'construction_bot_state': 'usta_mr_draft_input'
            })
            
            self._send_message(user.telegram_chat_id, f"🧱 *Material so'rovi*\n📋 Vazifa: {task.name}\n🏗 Loyiha: {task.project_id.name}")
            self._send_mr_draft_interface(user)

    def _show_client_approvals(self, user):
        partner = user.partner_id
        if not partner:
            self._send_message(user.telegram_chat_id, "❌ Sizning akkauntingizga mijoz biriktirilmagan.")
            return

        # Get projects where this user is the customer
        projects = self.env['construction.project'].search([
            ('customer_id', '=', partner.id)
        ])
        
        if not projects:
            self._send_message(user.telegram_chat_id, "❌ Sizning loyihalaringiz topilmadi.")
            return

        # Get priced batches for these projects
        batches = self.env['construction.material.request.batch'].search([
            ('project_id', 'in', projects.ids),
            ('state', '=', 'priced')
        ], order='date desc')

        if not batches:
            self._send_message(user.telegram_chat_id, "✅ Hozirda tasdiqlash kerak bo'lgan so'rovlar yo'q.")
            return

        msg = "🧾 *Tasdiqlash kerak*\n\nQuyidagi so'rovlarni ko'rib chiqing:"
        buttons = []
        
        for batch in batches:
            # Show batch summary
            priced_count = len(batch.line_ids.filtered(lambda l: l.unit_price > 0))
            total_count = len(batch.line_ids)
            label = f"{batch.name} - {batch.project_id.name} ({priced_count}/{total_count} narxlangan)"
            buttons.append([{'text': label, 'callback_data': f"client:batch:detail:{batch.id}"}])

        buttons.append(self._get_nav_row())
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})


    # --- Issue Reporting Flow (Usta) ---
    
    def _start_issue_flow(self, user):
        """Entry point for Muammo/To'siq reporting"""
        # Auto-select project if only 1
        project, status = self._ensure_project_or_ask(user, "issue")
        
        if status == 'needs_selection':
            # Project selection menu will be shown
            return
        elif status == 'auto_selected':
            # Continue with text input
            self._request_issue_text(user)
    
    def _request_issue_text(self, user):
        """Ask user to enter issue description"""
        user.sudo().write({
            'construction_bot_state': 'worker_issue_input_text',
            'issue_draft_text': False,
            'issue_draft_photo_ids': '[]'
        })
        
        buttons = [
            self._get_nav_row(back_cb="nav:home")
        ]
        
        self._send_message(
            user.telegram_chat_id,
            "⚠️ *Muammo/To'siq*\n\nMuammo tavsifini yozing:",
            reply_markup={'inline_keyboard': buttons}
        )
    
    def _handle_issue_text_input(self, user, text):
        """Save issue text and ask for photos"""
        user.sudo().write({
            'issue_draft_text': text,
            'construction_bot_state': 'worker_issue_input_photos'
        })
        
        buttons = [
            [{'text': "✅ Tayyor (rasmlar kiritilmadi)", 'callback_data': "issue:confirm"}],
            self._get_nav_row(back_cb="nav:home")
        ]
        
        self._send_message(
            user.telegram_chat_id,
            "📸 *Rasm yuboring* (ixtiyoriy)\n\nBir nechta rasm yuborishingiz mumkin.\nTugatgach '✅ Tayyor' bosing.",
            reply_markup={'inline_keyboard': buttons}
        )
    
    def _handle_issue_photo(self, user, message):
        """Process photo and add to draft list"""
        import json
        
        # Extract file_id from photo
        photos = message.get('photo', [])
        if not photos:
            self._send_message(user.telegram_chat_id, "❌ Rasm topilmadi. Qayta yuboring.")
            return
        
        # Get highest resolution photo
        photo = max(photos, key=lambda p: p['file_size'])
        file_id = photo['file_id']
        
        # Load existing list
        try:
            photo_list = json.loads(user.issue_draft_photo_ids or '[]')
        except:
            photo_list = []
        
        # Add new photo
        photo_list.append(file_id)
        
        # Save
        user.sudo().write({'issue_draft_photo_ids': json.dumps(photo_list)})
        
        # Update buttons with new count
        count = len(photo_list)
        buttons = [
            [{'text': f"✅ Tayyor ({count} ta rasm)", 'callback_data': "issue:confirm"}],
            self._get_nav_row(back_cb="nav:home")
        ]
        
        self._send_message(
            user.telegram_chat_id,
            f"✅ Rasm qabul qilindi ({count} ta)\n\nYana rasm yuboring yoki 'Tayyor' bosing.",
            reply_markup={'inline_keyboard': buttons}
        )
    
    def _confirm_issue_creation(self, user):
        """Create issue record with attachments"""
        import json
        
        if not user.issue_draft_text:
            self._send_message(user.telegram_chat_id, "❌ Muammo tavsifi kiritilmagan.")
            return
        
        # Safety Check: Ensure project is selected
        project = user.construction_selected_project_id
        if not project:
            _logger.info("ISSUE FLOW: Project missing, retrying auto-select for user %s", user.id)
            project, status = self._ensure_project_or_ask(user, "issue")
            if status == 'needs_selection':
                return
            if not project:
                self._send_message(user.telegram_chat_id, "❌ Loyiha tanlanmagan.")
                self._show_main_menu(user)
                return

        _logger.info("ISSUE FLOW project=%s user=%s", project.id, user.id)
        
        # Create issue
        issue = self.env['construction.issue'].sudo().create({
            'project_id': project.id,
            'reported_by': user.id,
            'description': user.issue_draft_text,
            'state': 'new'
        })
        
        # Handle photos
        try:
            photo_list = json.loads(user.issue_draft_photo_ids or '[]')
        except:
            photo_list = []
        
        if photo_list:
            attachments = self._download_telegram_photos(user, photo_list, issue)
            if attachments:
                issue.sudo().write({'attachment_ids': [(6, 0, attachments.ids)]})
        
        # Notify Prorab/Admin
        self._notify_issue_created(issue)
        
        # Clear state
        user.sudo().write({
            'construction_bot_state': 'idle',
            'issue_draft_text': False,
            'issue_draft_photo_ids': '[]'
        })
        
        # Confirm to user
        photo_text = f" ({len(photo_list)} ta rasm bilan)" if photo_list else ""
        self._send_message(user.telegram_chat_id, f"✅ Muammo ({issue.name}) yuborildi{photo_text}.")
        self._show_main_menu(user)
    
    def _download_telegram_photos(self, user, file_ids, issue):
        """Download photos from Telegram and create attachments"""
        token = self._get_token()
        attachments = self.env['ir.attachment']
        
        for idx, file_id in enumerate(file_ids, 1):
            try:
                # Get file info
                url = f"https://api.telegram.org/bot{token}/getFile"
                response = requests.get(url, params={'file_id': file_id}, timeout=10)
                response.raise_for_status()
                file_info = response.json()
                
                if not file_info.get('ok'):
                    continue
                
                file_path = file_info['result']['file_path']
                
                # Download file
                download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                file_response = requests.get(download_url, timeout=30)
                file_response.raise_for_status()
                
                # Create attachment
                import base64
                attachment = self.env['ir.attachment'].sudo().create({
                    'name': f"Issue_{issue.name}_Photo_{idx}.jpg",
                    'type': 'binary',
                    'datas': base64.b64encode(file_response.content),
                    'res_model': 'construction.issue',
                    'res_id': issue.id,
                    'description': f"Telegram file_id: {file_id}"
                })
                attachments |= attachment
                
            except Exception as e:
                _logger.error(f"[Bot] Failed to download photo {file_id}: {e}")
                continue
        
        return attachments
    
    def _notify_issue_created(self, issue):
        """Notify Prorab/Admin about new issue with photos"""
        recipients = self.env['res.users'].search([
            '|',
            ('construction_role', '=', 'foreman'),
            ('construction_role', '=', 'admin'),
            ('telegram_chat_id', '!=', False)
        ])
        
        msg = (
            f"⚠️ *Yangi muammo!*\n\n"
            f"🏗 Loyiha: {issue.project_id.name}\n"
            f"📋 Muammo: {issue.name}\n"
        )
        if issue.task_id:
            msg += f"📌 Vazifa: {issue.task_id.name}\n"
        if issue.stage_id:
            msg += f"🧱 Bosqich: {issue.stage_id.name}\n"
        
        msg += f"👤 Kim: {issue.reported_by.name}\n\n"
        msg += f"📝 *Matn:*\n{issue.description}"
        
        buttons = [
            [{'text': "👀 Ko'rib chiqyapman", 'callback_data': f"issue:set:in_progress:{issue.id}"}],
            [{'text': "✅ Hal bo'ldi", 'callback_data': f"issue:set:resolved:{issue.id}"}],
            [{'text': "❌ Bekor", 'callback_data': f"issue:set:canceled:{issue.id}"}],
            self._get_nav_row()
        ]
        
        # Get photos
        photos = issue.attachment_ids.filtered(lambda a: a.mimetype.startswith('image'))
        first_photo = photos[0] if photos else None
        
        notify_chat_id = False
        notify_msg_id = False
        
        for recipient in recipients:
            allowed = recipient.get_allowed_construction_projects()
            if issue.project_id in allowed:
                chat_id = recipient.telegram_chat_id
                res = None
                
                if first_photo:
                    # Send first photo with caption and buttons
                    photo_bytes = base64.b64decode(first_photo.datas)
                    res = self._send_photo(chat_id, photo_bytes, caption=msg, reply_markup={'inline_keyboard': buttons})
                    
                    # Send other photos
                    for other_photo in photos[1:]:
                        photo_bytes = base64.b64decode(other_photo.datas)
                        self._send_photo(chat_id, photo_bytes)
                
                else:
                    # Send text message
                    res = self._send_message(chat_id, msg, reply_markup={'inline_keyboard': buttons})
                
                # capture ID (prioritize first successful send)
                if not notify_msg_id and res and res.get('ok'):
                    notify_chat_id = chat_id
                    notify_msg_id = res['result']['message_id']
        
        # Store notification info
        if notify_chat_id and notify_msg_id:
            issue.sudo().write({
                'notify_chat_id': str(notify_chat_id),
                'notify_message_id': str(notify_msg_id)
            })
    
    def _handle_issue_status_change(self, user, issue_id, new_state):
        """Handle status change request from Prorab/Admin"""
        issue = self.env['construction.issue'].browse(issue_id)
        if not issue.exists():
            self._send_message(user.telegram_chat_id, "❌ Muammo topilmadi.")
            return
        
        # Security check
        allowed = user.get_allowed_construction_projects()
        if issue.project_id not in allowed:
            self._send_message(user.telegram_chat_id, "⛔ Ruxsat yo'q.")
            return
        
        # Update state
        state_map = {
            'in_progress': 'Ko\'rib chiqilmoqda',
            'resolved': 'Hal bo\'ldi',
            'canceled': 'Bekor'
        }
        state_label = state_map.get(new_state, new_state)
        
        issue.sudo().write({'state': new_state})
        
        # Update the notification message (Edit Caption/Text)
        # 1. Provide info about who changed it
        now = fields.Datetime.now().strftime("%H:%M")
        update_text = f"\n\n👀 *Holat:* {state_label}\n👷 *{user.name}* ({now})"
        
        # Reconstruct original message to append status (or just append)
        # We need the original text. We can reconstruct it from issue data.
        msg = (
            f"⚠️ *Muammo Report*\n\n"
            f"🏗 Loyiha: {issue.project_id.name}\n"
            f"📋 Muammo: {issue.name}\n"
        )
        if issue.task_id:
            msg += f"📌 Vazifa: {issue.task_id.name}\n"
        if issue.stage_id:
            msg += f"🧱 Bosqich: {issue.stage_id.name}\n"
        
        msg += f"👤 Kim: {issue.reported_by.name}\n\n"
        msg += f"📝 *Matn:*\n{issue.description}"
        msg += update_text

        # 2. Update the buttons (maybe remove them or update them? Prompt says 'Keep same photo and keyboard')
        # We'll keep the keyboard but maybe update it? For now, keep as is or maybe remove the clicked button?
        # Prompt says: "keep the same photo and keyboard (keyboard can be updated too)"
        # Use same buttons.
        buttons = [
            [{'text': "👀 Ko'rib chiqyapman", 'callback_data': f"issue:set:in_progress:{issue.id}"}],
            [{'text': "✅ Hal bo'ldi", 'callback_data': f"issue:set:resolved:{issue.id}"}],
            [{'text': "❌ Bekor", 'callback_data': f"issue:set:canceled:{issue.id}"}],
            self._get_nav_row()
        ]
        reply_markup = {'inline_keyboard': buttons}

        # 3. Perform Edit
        # Try to edit the message stored in issue
        if issue.notify_chat_id and issue.notify_message_id:
             # Check if it has photos to decide caption vs text
             has_photos = bool(issue.attachment_ids.filtered(lambda a: a.mimetype.startswith('image')))
             if has_photos:
                 self._edit_message_caption(issue.notify_chat_id, issue.notify_message_id, msg, reply_markup)
             else:
                 self._edit_message_text(issue.notify_chat_id, issue.notify_message_id, msg, reply_markup)

        # 4. Notify reporter (Usta)
        if issue.reported_by and issue.reported_by.telegram_chat_id:
            reporter_msg = (
                f"🔔 *Yangilik*\n\n"
                f"Muammo: *{issue.name}*\n"
                f"Holat yangilandi: *{state_label}*"
            )
            self._send_message(issue.reported_by.telegram_chat_id, reporter_msg)
        
        # Confirm to Prorab (Ephemeral notification or AnswerCallbackQuery would be better, but we send message)
        # Since we edited the message, we might not need to send a new "Success" message to avoid clutter, 
        # but the prompt says "Edit caption...". 
        # Sending a confirmation message is fine too.
        # self._send_message(user.telegram_chat_id, f"✅ Holat yangilandi: *{state_label}*") 
        # (Commented out to reduce clutter since we edit the message in place)


    def _start_mr_batch_flow(self, user):
        project, status = self._ensure_project_or_ask(user, "usta:mr")
        
        if status == 'auto_selected':
             self._start_usta_ai_request(user, project.id)

    def _start_mr_draft_input(self, user, project_id):
        project = self.env['construction.project'].sudo().browse(project_id)
        if not project.exists():
            self._send_message(user.telegram_chat_id, "❌ Loyiha topilmadi.")
            return

        # Initialize Draft
        user.write({
            'construction_bot_state': 'usta_mr_draft_input',
            'mr_draft_project_id': project.id,
            'mr_draft_lines_json': json.dumps([])
        })

        self._send_mr_draft_interface(user)

    def _send_mr_draft_interface(self, user):
        """Sends or Updates the Draft Interface"""
        msg = self._get_mr_draft_message(user)
        kb = self._get_mr_draft_buttons()
        self._send_message(user.telegram_chat_id, msg, reply_markup=kb)

    def _handle_mr_draft_input(self, user, text):
        # 1. Parse
        parts = text.strip().split()
        valid = False
        product_name = ""
        quantity = 0.0

        if len(parts) >= 2:
            try:
                # Logic: last tokens are qty?
                # "Gipsokarton 12" -> name="Gipsokarton", qty=12.0
                # "Gipsokarton 12.5" -> name="Gipsokarton", qty=12.5
                # "Gipsokarton" -> name="Gipsokarton", qty=1.0 (handled in else)
                
                # Check if last part is a number
                qty_str = parts[-1].replace(',', '.')
                quantity = float(qty_str)
                product_name = ' '.join(parts[:-1])
                valid = True
            except ValueError:
                # Last part is NOT a number. Assume entire string is name, Default Qty = 1
                product_name = text.strip()
                quantity = 1.0
                valid = True
        else:
             # Single word or empty
             if text.strip():
                 # Attempt to parse regex for "12 items"? No, usually "Name Qty"
                 # Just use as name, Qty=1
                 product_name = text.strip()
                 quantity = 1.0
                 valid = True

        if not valid:
            self._send_message(user.telegram_chat_id, "❌ Format xato. To‘g‘ri format: *Nomi Miqdor* (Masalan: Gipsokarton 12)")
            # Re-send interface so they don't get lost
            self._send_mr_draft_interface(user)
            return

        # 2. Add to JSON
        draft_list = self._get_mr_draft_list(user)
        draft_list.append({'name': product_name, 'qty': quantity})
        self._save_mr_draft_list(user, draft_list)

        # 3. Re-send Interface
        self._send_mr_draft_interface(user)

    def _handle_mr_draft_back(self, user):
        # Clear fields
        user.write({
            'construction_bot_state': 'idle',
            'mr_draft_project_id': False,
            'mr_draft_lines_json': '[]'
        })
        # Go back to project selection
        self._start_mr_batch_flow(user)

    def _confirm_mr_draft(self, user):
        draft_list = self._get_mr_draft_list(user)
        if not draft_list:
            self._send_message(user.telegram_chat_id, "❌ Ro‘yxat bo‘sh. Kamida bitta material kiriting.")
            self._send_mr_draft_interface(user)
            return

        project = user.mr_draft_project_id
        if not project:
            self._send_message(user.telegram_chat_id, "❌ Loyiha tanlanmagan.")
            self._show_main_menu(user)
            return

        # Create Batch
        batch = self.env['construction.material.request.batch'].sudo().create({
            'project_id': project.id,
            'requester_id': user.id,
            'task_id': user.selected_task_id.id if user.selected_task_id else False,
            'state': 'draft'
        })

        # Create Lines
        for item in draft_list:
            self.env['construction.material.request.line'].sudo().create({
                'batch_id': batch.id,
                'product_name': item['name'],
                'quantity': item['qty']
            })

        # Notify Snab
        self._notify_snab_new_batch_mr(batch, draft_list)

        # Confirm to Usta
        self._send_message(user.telegram_chat_id, f"✅ So‘rov ({batch.name}) snabga yuborildi.")

        # Cleanup
        user.write({
            'construction_bot_state': 'idle',
            'mr_draft_project_id': False,
            'mr_draft_lines_json': '[]'
        })
        self._show_main_menu(user)

    def _notify_snab_new_batch_mr(self, batch, lines):
        snabs = self.env['res.users'].search([
            ('construction_role', '=', 'supply'),
            ('telegram_chat_id', '!=', False)
        ])
        _logger.info(f"[SYSTEM] Found {len(snabs)} snabs to notify for new batch {batch.id}")
        
        # Build List String
        list_str = ""
        for i, item in enumerate(lines, 1):
            list_str += f"{i}) {item['name']} — {item['qty']}\n"

        msg = (
            f"🧱 *Yangi material so‘rovi* {batch.name}\n\n"
            f"🏗 Loyiha: {batch.project_id.name}\n"
            f"👤 Usta: {batch.requester_id.name}\n"
        )
        
        if batch.task_id:
            msg += f"📋 Vazifa: {batch.task_id.name}\n"
        
        msg += f"\n📜 *Ro‘yxat:*\n{list_str}"

        buttons = [[{'text': "💰 Narx qo‘yish", 'callback_data': f"snab:mr:price_batch:{batch.id}"}]]
        
        for snab in snabs:
            allowed = snab.get_allowed_construction_projects()
            if batch.project_id in allowed:
                self._send_message(snab.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    # --- Helpers ---

    def _get_mr_draft_list(self, user):
        try:
            return json.loads(user.mr_draft_lines_json or "[]")
        except:
            return []

    def _save_mr_draft_list(self, user, data):
        user.sudo().write({'mr_draft_lines_json': json.dumps(data)})

    def _get_mr_draft_message(self, user):
        draft_list = self._get_mr_draft_list(user)
        
        list_str = "—"
        if draft_list:
            lines = []
            for i, item in enumerate(draft_list, 1):
                lines.append(f"{i}) {item['name']} — {item['qty']}")
            list_str = "\n".join(lines)

        return (
            "📦 *Materiallar ro‘yxatini kiriting (bitta qatorda).*\n"
            "Format: Nomi Miqdor\n\n"
            "✅ *Tasdiqlash* bosilganda snabga yuboriladi.\n\n"
            f"Hozirgi ro‘yxat:\n{list_str}"
        )

    def _get_mr_draft_buttons(self):
        # Confirm row
        rows = [[{'text': "✅ Tasdiqlash", 'callback_data': "usta:mr:confirm"}]]
        # Nav row
        rows.append(self._get_nav_row(back_cb="usta:mr:back"))
        return {'inline_keyboard': rows}

    # --- Step 8: Snab Batch Pricing Flow---

    def _start_snab_batch_pricing(self, user, batch_id):
        """Entry point: Snab clicks 'Narx qo'yish' button"""
        # Role check
        if user.construction_role != 'supply':
            self._send_message(user.telegram_chat_id, "⛔ Siz snab emassiz.")
            return
        
        batch = self.env['construction.material.request.batch'].sudo().browse(batch_id)
        if not batch.exists():
            self._send_message(user.telegram_chat_id, "❌ So'rov topilmadi.")
            return
        
        # Check project access
        allowed = user.get_allowed_construction_projects()
        if batch.project_id not in allowed:
            self._send_message(user.telegram_chat_id, "⛔ Siz ushbu loyihaga kirish huquqiga ega emassiz.")
            return
        
        # Save context
        user.sudo().write({
            'snab_price_batch_id': batch.id,
            'snab_price_line_id': False,
            'construction_bot_state': 'snab_price_select_line'
        })
        
        self._show_pricing_panel(user)

    def _show_pricing_panel(self, user):
        """Display batch pricing panel with all lines"""
        batch = user.snab_price_batch_id
        if not batch:
            self._send_message(user.telegram_chat_id, "❌ Xatolik: batch topilmadi.")
            self._show_main_menu(user)
            return
        
        # Build lines status list
        lines_status = []
        for i, line in enumerate(batch.line_ids, 1):
            if line.unit_price > 0:
                lines_status.append(
                    f"{i}) {line.product_name} — {line.quantity} × {line.unit_price:,.0f} so'm = {line.total_price:,.0f} so'm ✅"
                )
            else:
                lines_status.append(
                    f"{i}) {line.product_name} — {line.quantity}  | Narx: —"
                )
        
        msg = (
            f"💰 *Narx qo'yish*\n\n"
            f"So'rov: {batch.name}\n"
            f"Loyiha: {batch.project_id.name}\n\n"
            f"*Ro'yxat:*\n" + "\n".join(lines_status) + "\n\n"
            "Material tanlang yoki ✅ Tasdiqlashga yuborish ni bosing."
        )
        
        # Build inline keyboard
        buttons = []
        for line in batch.line_ids:
            # Short name (first 20 chars)
            short_name = line.product_name[:20] + ('...' if len(line.product_name) > 20 else '')
            status_icon = "✅" if line.unit_price > 0 else "—"
            label = f"{short_name} ({line.quantity}) {status_icon}"
            buttons.append([{'text': label, 'callback_data': f"snab:mr:line:{line.id}"}])
        
        # Navigation row
        buttons.append(self._get_nav_row(back_cb="snab:mr:exit"))
        
        # Send for approval button
        buttons.append([
            {'text': "✅ Tasdiqlashga yuborish", 'callback_data': f"snab:mr:send_for_approval:{batch.id}"}
        ])
        
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    def _handle_snab_select_line(self, user, line_id):
        """Snab selects a line to price"""
        if user.construction_role != 'supply':
            self._send_message(user.telegram_chat_id, "⛔ Siz snab emassiz.")
            return
        
        line = self.env['construction.material.request.line'].sudo().browse(line_id)
        if not line.exists():
            self._send_message(user.telegram_chat_id, "❌ Qator topilmadi.")
            return
        
        # Verify line belongs to user's batch
        if user.snab_price_batch_id and line.batch_id.id != user.snab_price_batch_id.id:
            self._send_message(user.telegram_chat_id, "❌ Bu qator boshqa so'rovga tegishli.")
            return
        
        # Save line and change state
        user.sudo().write({
            'snab_price_line_id': line.id,
            'construction_bot_state': 'snab_price_input'
        })
        
        msg = (
            f"🧾 *{line.product_name}*\n"
            f"Miqdor: {line.quantity}\n\n"
            "Birlik narxini kiriting (so'm):"
        )
        
        buttons = [[{'text': "⬅️ Ortga", 'callback_data': "snab:mr:back_to_panel"}]]
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    def _handle_snab_price_input(self, user, text):
        """Handle unit price input from Snab"""
        try:
            price = float(text.replace(',', '.').replace(' ', ''))
            if price <= 0:
                raise ValueError
        except ValueError:
            self._send_message(user.telegram_chat_id, "❌ Narx raqam bo'lishi kerak. Qayta kiriting (so'm):")
            return
        
        line = user.snab_price_line_id
        if not line or not line.exists():
            self._send_message(user.telegram_chat_id, "❌ Xatolik: qator topilmadi.")
            user.sudo().write({'construction_bot_state': 'idle'})
            self._show_main_menu(user)
            return
        
        # Save unit price (total_price is computed automatically)
        line.sudo().write({'unit_price': price})
        
        # Confirm
        self._send_message(
            user.telegram_chat_id,
            f"✅ Saqlandi: {line.product_name} — {price:,.0f} so'm"
        )
        
        # Return to pricing panel
        user.sudo().write({
            'snab_price_line_id': False,
            'construction_bot_state': 'snab_price_select_line'
        })
        self._show_pricing_panel(user)

    def _send_batch_for_approval(self, user, batch_id):
        """Send batch to Admin + Client for approval (partial pricing allowed)"""
        if user.construction_role != 'supply':
            self._send_message(user.telegram_chat_id, "⛔ Siz snab emassiz.")
            return
        
        batch = self.env['construction.material.request.batch'].sudo().browse(batch_id)
        if not batch.exists():
            self._send_message(user.telegram_chat_id, "❌ So'rov topilmadi.")
            return
        
        # Validate: at least ONE line must have price
        priced_lines = batch.line_ids.filtered(lambda l: l.unit_price > 0)
        if not priced_lines:
            _logger.info(f"[SNAB APPROVAL] Batch {batch.name}: {len(priced_lines)}/{len(batch.line_ids)} lines priced")
            self._send_message(user.telegram_chat_id, "❌ Hech bo'lmasa bitta materialga narx qo'ying, keyin yuboring.")
            self._show_pricing_panel(user)
            return
        
        # Call system method
        self._system_send_batch_approval(batch)
        
        # Confirm to Snab
        self._send_message(user.telegram_chat_id, "✅ Tasdiqlashga yuborildi.")
        
        # Clear context and return to menu
        user.sudo().write({
            'snab_price_batch_id': False,
            'snab_price_line_id': False,
            'construction_bot_state': 'idle'
        })
        self._show_main_menu(user)

    def _handle_batch_approval(self, user, batch_id, decision):
        """Handle batch approval or rejection"""
        batch = self.env['construction.material.request.batch'].sudo().browse(batch_id)
        if not batch.exists():
            self._send_message(user.telegram_chat_id, "❌ So'rov topilmadi.")
            return
        
        # Permission check: Admin OR Client of project
        is_admin = (user.construction_role == 'admin')
        is_client = (user.partner_id == batch.project_id.customer_id)
        
        if not (is_admin or is_client):
            self._send_message(user.telegram_chat_id, "⛔ Sizga ruxsat yo'q.")
            return
        
        if batch.state != 'priced':
            self._send_message(user.telegram_chat_id, f"⚠️ Bu so'rov holati: {batch.state}")
            return
        
        # Update state
        if decision == 'approve':
            batch.sudo().write({
                'state': 'approved',
                'approve_user_id': user.id,
                'approve_date': fields.Datetime.now()
            })
            approver_msg = "✅ Tasdiqlandi."
            notification_msg = f"✅ So'rov tasdiqlandi: {batch.name} ({batch.project_id.name})"
        else:  # reject
            batch.sudo().write({
                'state': 'rejected',
                'approve_user_id': user.id,
                'approve_date': fields.Datetime.now()
            })
            approver_msg = "❌ Rad etildi."
            notification_msg = f"❌ So'rov rad etildi: {batch.name} ({batch.project_id.name})"
        
        # Reply to approver
        self._send_message(user.telegram_chat_id, approver_msg)
        
        # Notify Snab and Usta
        users_to_notify = []
        
        # Add requester (Usta)
        if batch.requester_id and batch.requester_id.telegram_chat_id:
            users_to_notify.append(batch.requester_id.telegram_chat_id)
        
        # Find Snab who priced it (last user who set state to 'priced')
        # We don't track snab_id on batch, so notify all supply users with access
        snabs = self.env['res.users'].search([
            ('construction_role', '=', 'supply'),
            ('telegram_chat_id', '!=', False)
        ])
        for snab in snabs:
            allowed = snab.get_allowed_construction_projects()
            if batch.project_id in allowed and snab.telegram_chat_id:
                users_to_notify.append(snab.telegram_chat_id)
        
        # Send notifications (unique)
        for chat_id in set(users_to_notify):
            self._send_message(chat_id, notification_msg)


    def _show_client_batch_detail(self, user, batch_id):
        """Show batch detail for client approval"""
        batch = self.env['construction.material.request.batch'].sudo().browse(batch_id)
        if not batch.exists():
            self._send_message(user.telegram_chat_id, "❌ So'rov topilmadi.")
            return
        
        # Build lines text
        lines_text = []
        total_sum = 0.0
        for i, line in enumerate(batch.line_ids, 1):
            if line.unit_price > 0:
                lines_text.append(
                    f"{i}) {line.product_name} — {line.quantity} × {line.unit_price:,.0f} so'm = {line.total_price:,.0f} so'm"
                )
                total_sum += line.total_price
            else:
                lines_text.append(
                    f"{i}) {line.product_name} — {line.quantity}  | Narx: kiritilmagan"
                )
        
        msg = (
            f"🧾 *Tasdiqlash kerak*\n\n"
            f"So'rov: {batch.name}\n"
            f"Loyiha: {batch.project_id.name}\n\n"
            f"*Ro'yxat:*\n" + "\n".join(lines_text) + "\n\n"
            f"*Umumiy jami (faqat narx qo'yilganlar):* {total_sum:,.0f} so'm"
        )
        
        buttons = [[
            {'text': "✅ Tasdiqlash", 'callback_data': f"mr:batch:approve:{batch.id}"},
            {'text': "❌ Rad etish", 'callback_data': f"mr:batch:reject:{batch.id}"}
        ]]
        buttons.append(self._get_nav_row())
        
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    def _system_send_batch_approval(self, batch):
        """System method to send batch for approval - called by model or Snab"""
        import logging
        _logger = logging.getLogger(__name__)
        
        try:
            # Note: State should be set by caller (model or snab handler)
            # But let's ensure it's priced if not already
            if batch.state != 'priced':
                batch.sudo().write({'state': 'priced'})
                
            # Step 4: Inventory Check (Placeholder)
            try:
                inv_service = InventoryLiteService(self.env)
                inv_result = inv_service.check_inventory(batch.project_id.id, [])
                _logger.info(f"[Inventory] Result for Batch {batch.id}: {inv_result}")
            except Exception as e_inv:
                _logger.error(f"[Inventory] Error in check: {e_inv}")
            
            # Build approval message
            lines_text = []
            total_sum = 0.0
            for i, line in enumerate(batch.line_ids, 1):
                if line.unit_price > 0:
                    lines_text.append(
                        f"{i}) {line.product_name} — {line.quantity} × {line.unit_price:,.0f} so'm = {line.total_price:,.0f} so'm"
                    )
                    total_sum += line.total_price
                else:
                    lines_text.append(
                        f"{i}) {line.product_name} — {line.quantity}  | Narx: kiritilmagan"
                    )
            
            msg = (
                f"🔄 *Qayta yuborildi: Tasdiqlash kerak*\n" if batch.state == 'rejected' else f"🧾 *Tasdiqlash kerak*\n"
                f"\n"
                f"So'rov: {batch.name}\n"
                f"Loyiha: {batch.project_id.name}\n\n"
                f"*Ro'yxat:*\n" + "\n".join(lines_text) + "\n\n"
                f"*Umumiy jami (faqat narx qo'yilganlar):* {total_sum:,.0f} so'm"
            )
            
            buttons = [[
                {'text': "✅ Tasdiqlash", 'callback_data': f"mr:batch:approve:{batch.id}"},
                {'text': "❌ Rad etish", 'callback_data': f"mr:batch:reject:{batch.id}"}
            ]]
            
            # Notify Admins
            admins = self.env['res.users'].search([
                ('construction_role', '=', 'admin'),
                ('telegram_chat_id', '!=', False)
            ])
            _logger.info(f"[SYSTEM] Found {len(admins)} admins to notify")
            for admin in admins:
                self._send_message(admin.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})
            
            # Notify Client
            client_partner = batch.project_id.customer_id
            if client_partner:
                clients = self.env['res.users'].search([
                    ('partner_id', '=', client_partner.id),
                    ('telegram_chat_id', '!=', False)
                ])
                _logger.info(f"[SYSTEM] Found {len(clients)} clients to notify for project {batch.project_id.name}")
                for client in clients:
                    self._send_message(client.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})
            else:
                 _logger.info(f"[SYSTEM] No customer set for project {batch.project_id.name}")
                    
            _logger.info(f"[SYSTEM] Sent batch {batch.id} for approval")

        except Exception as e:
            _logger.error(f"[SYSTEM] Error sending batch approval: {e}", exc_info=True)

    def _system_notify_snab_new_batch(self, batch):
        """System method to notify Snab about new/resent batch"""
        import logging
        _logger = logging.getLogger(__name__)
        
        try:
            snabs = self.env['res.users'].search([
                ('construction_role', '=', 'supply'),
                ('telegram_chat_id', '!=', False)
            ])
            
            msg = (
                f"🔄 *Qayta yuborildi: Narx qo'yish*\n\n"
                f"So'rov: {batch.name}\n"
                f"Loyiha: {batch.project_id.name}\n"
                f"Usta: {batch.requester_id.name}\n\n"
                f"Iltimos, qaytadan ko'rib chiqing va narx qo'ying."
            )
            
            buttons = [[{'text': "💰 Narx qo'yish", 'callback_data': f"snab:mr:price_batch:{batch.id}"}]]
            
            sent_count = 0
            for snab in snabs:
                allowed = snab.get_allowed_construction_projects()
                if batch.project_id in allowed:
                    self._send_message(snab.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})
                    sent_count += 1
            
            _logger.info(f"[SYSTEM] Notified {sent_count} snabs about batch {batch.id}")

        except Exception as e:
            _logger.error(f"[SYSTEM] Error notifying snab: {e}", exc_info=True)


    # --- Step 5: File Browsing Logic ---

    def _encode_room_ref(self, room_ref):
        if not room_ref: return "NA"
        # base64url encoding without padding
        return base64.urlsafe_b64encode(room_ref.encode('utf-8')).decode('utf-8').rstrip('=')

    def _decode_room_ref(self, encoded):
        if encoded == "NA": return ""
        # add padding back
        padding = 4 - (len(encoded) % 4)
        if padding != 4:
            encoded += '=' * padding
        return base64.urlsafe_b64decode(encoded).decode('utf-8')

    def _start_file_browsing(self, user):
        projects = user.get_allowed_construction_projects()
        if not projects:
            self._send_message(user.telegram_chat_id, "🔴 Sizga biriktirilgan loyihalar topilmadi.")
            return

        buttons = []
        for p in projects:
            buttons.append([{'text': p.name, 'callback_data': f"files:prj:{p.id}"}])
        
        buttons.append(self._get_nav_row())
        
        self._send_message(
            user.telegram_chat_id, 
            "📎 *Fayllar*\nLoyihani tanlang:", 
            reply_markup={'inline_keyboard': buttons}
        )

    def _handle_files_project_selection(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return
        
        # Save state
        user.sudo().write({
            'file_nav_project_id': project.id,
            'file_nav_room_ref': False,
            'file_nav_category_id': False
        })
        
        # Query distinct rooms with latest files
        # We use strict SQL for distinct or search read
        # Filter: project_id, is_latest=True
        files = self.env['construction.project.file'].search([
            ('project_id', '=', project.id),
            ('is_latest', '=', True)
        ])
        
        rooms = list(set(files.mapped('room_ref')))
        rooms.sort()
        
        if not rooms:
            self._send_message(user.telegram_chat_id, f"📂 {project.name}: Hozircha fayllar yo'q.")
            # Show buttons?
            self._start_file_browsing(user) # Back to project list
            return

        buttons = []
        row = []
        for room in rooms:
            encoded = self._encode_room_ref(room)
            # Limit callback length (64 chars max usually, but 64 bytes is strictly checked?)
            # Room ref might be long. Warn if too long?
            # base64 expands slightly.
            # If room name is very long (>30 chars), callback might fail.
            # But usually room names are short (e.g. "Kitchen", "101").
            row.append({'text': room, 'callback_data': f"files:room:{encoded}"})
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        
        # Back button: back to project list is basically "files root"
        nav_row = self._get_nav_row(back_cb="menu:worker:files")
        buttons.append(nav_row)
        
        self._send_message(
            user.telegram_chat_id,
            f"📂 *{project.name}*\nXonani tanlang:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _handle_files_room_selection(self, user, encoded_room):
        room_ref = self._decode_room_ref(encoded_room)
        
        # Verify Context
        project = user.file_nav_project_id
        if not project:
            self._start_file_browsing(user)
            return
            
        user.sudo().write({
            'file_nav_room_ref': room_ref,
            'file_nav_category_id': False
        })
        
        # Find categories for this room
        files = self.env['construction.project.file'].search([
            ('project_id', '=', project.id),
            ('room_ref', '=', room_ref),
            ('is_latest', '=', True)
        ])
        
        categories = files.mapped('category_id')
        # sort by name/order
        
        buttons = []
        for cat in categories:
            buttons.append([{'text': cat.name, 'callback_data': f"files:cat:{cat.id}"}])
            
        # Back button: back to room list (needs project id)
        # We can implement specific back callback or reuse files:prj:<id>
        nav_row = self._get_nav_row(back_cb=f"files:prj:{project.id}")
        buttons.append(nav_row)
        
        self._send_message(
            user.telegram_chat_id,
            f"🏠 *{project.name}* > *{room_ref}*\nBo'limni tanlang:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _handle_files_category_selection(self, user, category_id):
        project = user.file_nav_project_id
        room_ref = user.file_nav_room_ref
        
        if not project or not room_ref:
            self._start_file_browsing(user)
            return
            
        category = self.env['construction.file.category'].browse(category_id)
        
        user.sudo().write({'file_nav_category_id': category.id})
        
        # List Files
        files = self.env['construction.project.file'].search([
            ('project_id', '=', project.id),
            ('room_ref', '=', room_ref),
            ('category_id', '=', category.id),
            ('is_latest', '=', True)
        ])
        
        buttons = []
        for f in files:
            label = f.name
            if f.version > 1:
                label += f" (v{f.version})"
            buttons.append([{'text': f"📄 {label}", 'callback_data': f"files:open:{f.id}"}])
            
        # Back: to categories list. 
        # But we don't have direct callback for "list categories" except re-calling room selection
        encoded_room = self._encode_room_ref(room_ref)
        nav_row = [{'text': "⬅️ Ortga", 'callback_data': f"files:room:{encoded_room}"}, {'text': "�� Bosh menyu", 'callback_data': "nav:home"}]
        buttons.append(nav_row)
        
        self._send_message(
            user.telegram_chat_id,
            f"📂 *{room_ref}* > *{category.name}*\nFaylni tanlang:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _open_file(self, user, file_id):
        file_rec = self.env['construction.project.file'].sudo().browse(file_id)
        if not file_rec.exists():
            self._send_message(user.telegram_chat_id, "❌ Fayl topilmadi.")
            return
            
        # Access Check
        allowed = user.get_allowed_construction_projects()
        if file_rec.project_id not in allowed:
            self._send_message(user.telegram_chat_id, "⛔ Sizga bu faylga ruxsat yo'q.")
            return

        # Send Document
        token = self._get_token()
        attachment = file_rec.attachment_id
        if not attachment:
             self._send_message(user.telegram_chat_id, "❌ Fayl biriktirilmagan.")
             return
             
        # We can send by URL if public, or by multipart upload
        # Usually internal attachments are not public.
        # So we download content and send multipart
        
        try:
            file_content = base64.b64decode(attachment.datas)
            url = f"https://api.telegram.org/bot{token}/sendDocument"
            
            files = {
                'document': (attachment.name, file_content)
            }
            data = {
                'chat_id': user.telegram_chat_id,
                'caption': f"📄 {file_rec.name}\nVersiya: {file_rec.version}\nYukladi: {file_rec.uploaded_by.name if file_rec.uploaded_by else 'Admin'}"
            }
            
            res = requests.post(url, data=data, files=files, timeout=30)
            res.raise_for_status()
            
            # Re-show list?
            # Users might want to download multiple files.
            # Just send the menu again?
            # Or just let them click previous message buttons?
            # Better to not spam menu again immediately unless requested?
            # But strictly speaking, updating the previous message or sending menu again is good UX.
            # Since we can't edit the "Faylni tanlang" message easily (we didn't store message_id),
            # let's just do nothing. The previous menu buttons are still there and clickable!
            
        except Exception as e:
            _logger.error(f"[BOT] Send document error: {e}")
            self._send_message(user.telegram_chat_id, "❌ Faylni yuborishda xatolik yuz berdi.")

    def _show_client_approvals_list(self, user, status_key):
        """Step 2: List Batches based on status"""
        # Map status
        domain = []
        if status_key == 'draft':
            # Client 'draft' is Snab 'priced'
            domain.append(('state', '=', 'priced'))
            title = "🕒 Kutilayotgan tasdiqlar"
        elif status_key == 'approved':
            domain.append(('state', '=', 'approved'))
            title = "✅ Tasdiqlangan so‘rovlar"
        elif status_key == 'rejected':
            domain.append(('state', '=', 'rejected'))
            title = "❌ Rad etilgan so‘rovlar"
        
        # Filter by allowed projects
        projects = user.get_allowed_construction_projects()
        if projects:
            domain.append(('project_id', 'in', projects.ids))
        
        batches = self.env['construction.material.request.batch'].search(domain, order='create_date desc', limit=20)
        
        buttons = []
        if not batches:
             self._send_message(user.telegram_chat_id, "📭 Hozircha bo‘sh.")
             self._show_client_approvals_status_selection(user)
             return

        for batch in batches:
            # Format: Date | Project | Total
            total = sum(l.total_price for l in batch.line_ids)
            label = f"{batch.date} | {batch.project_id.name} | {total:,.0f} so‘m"
            buttons.append([{'text': label, 'callback_data': f"client:approvals:open:{batch.id}"}])
            
        buttons.append(self._get_nav_row(back_cb="client:approvals:status_selection"))
        
        self._send_message(
            user.telegram_chat_id,
            f"💰 *{title}*\nTanlang:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _show_client_approval_detail(self, user, batch_id):
        """Step 3: Show Detail + Action Buttons"""
        batch = self.env['construction.material.request.batch'].browse(batch_id)
        if not batch.exists():
            self._send_message(user.telegram_chat_id, "❌ So‘rov topilmadi.")
            return

        # Build Message
        total = sum(l.total_price for l in batch.line_ids)
        state_label = dict(batch._fields['state'].selection).get(batch.state, batch.state)
        
        lines_text = ""
        for i, line in enumerate(batch.line_ids, 1):
             lines_text += f"{i}. {line.product_name} ({line.quantity}) - {line.total_price:,.0f} s.\n"
        
        msg = (
            f"🧾 *So'rov*: {batch.name}\n"
            f"🏗 *Loyiha*: {batch.project_id.name}\n"
        )
        
        if batch.task_id:
            msg += f"� *Vazifa*: {batch.task_id.name}\n"
        
        msg += (
            f"�📅 *Sana*: {batch.date}\n"
            f"📊 *Holat*: {state_label}\n"
            f"💰 *Jami*: {total:,.0f} so'm\n\n"
            f"*Materiallar:*\n{lines_text}\n"
        )
        
        if batch.approve_user_id:
            msg += f"\n✍️ Tasdiqladi: {batch.approve_user_id.name}\n🕒 Vaqt: {batch.approve_date}"
        
        buttons = []
        # Action Buttons only if 'priced' (Client Pending)
        if batch.state == 'priced':
            buttons.append([{'text': "✅ Tasdiqlash", 'callback_data': f"client:approvals:approve:{batch.id}"}])
            buttons.append([{'text': "❌ Rad etish", 'callback_data': f"client:approvals:reject:{batch.id}"}])
            
        # Navigation
        # Back to list? Need status key. Or just Back to Status Selection for simplicity, 
        # OR we could persist status in callback usually. SImplest: Back to Status Selection.
        buttons.append(self._get_nav_row(back_cb="client:approvals:status_selection"))
        
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    def _handle_client_approval_action(self, user, batch_id, action):
        """Step 4: Execute Approve/Reject"""
        batch = self.env['construction.material.request.batch'].browse(batch_id)
        if not batch.exists() or batch.state != 'priced':
             self._send_message(user.telegram_chat_id, "❌ Bu so‘rovni o‘zgartirib bo‘lmaydi (Ehtimol allaqachon tasdiqlangan).")
             # Refresh detail
             self._show_client_approval_detail(user, batch_id)
             return

        if action == 'approve':
            batch.write({
                'state': 'approved',
                'approve_user_id': user.id,
                'approve_date': fields.Datetime.now()
            })
            self._send_message(user.telegram_chat_id, f"✅ So‘rov ({batch.name}) tasdiqlandi.")
            self._notify_batch_status_change(batch, 'approved')
            
        elif action == 'reject':
            batch.write({'state': 'rejected'})
            self._send_message(user.telegram_chat_id, f"❌ So‘rov ({batch.name}) rad etildi.")
            self._notify_batch_status_change(batch, 'rejected')
            
        # Refresh detail (it will show non-editable state now)
        self._show_client_approval_detail(user, batch_id)

    def _notify_batch_status_change(self, batch, new_state):
        """Notify Snab and Requester (Usta) about status change"""
        # 1. Notify Requester (Usta)
        if batch.requester_id and batch.requester_id.telegram_chat_id:
            status_map = {'approved': "✅ Tasdiqlandi", 'rejected': "❌ Rad etildi"}
            status_text = status_map.get(new_state, new_state)
            msg = f"🔔 *Yangilik* ({batch.project_id.name})\nSo‘rov: *{batch.name}*\nHolat: *{status_text}*"
            self._send_message(batch.requester_id.telegram_chat_id, msg)
            
        # 2. Notify Supply (Snab)
        snabs = self.env['res.users'].search([('construction_role', '=', 'supply'), ('telegram_chat_id', '!=', False)])
        for snab in snabs:
            status_map = {'approved': "✅ Tasdiqlandi (Xaridga ruxsat)", 'rejected': "❌ Rad etildi"}
            status_text = status_map.get(new_state, new_state)
            msg = f"🔔 *Yangilik* ({batch.project_id.name})\nSo‘rov: *{batch.name}*\nHolat: *{status_text}*"
            self._send_message(snab.telegram_chat_id, msg)

    # --- USTA File Browsing (Step 198 Improvement - Locked Order) ---

    def _start_usta_file_browsing(self, user):
        """Entry point for Usta Files menu"""
        _logger.info(f"[BOT_FILES] Starting browsing for {user.name}")
        project, status = self._ensure_project_or_ask(user, "usta:files")
        _logger.info(f"[BOT_FILES] Ensure Project Result: {status}, Project: {project.id if project else None}")
        
        if status == 'auto_selected':
             self._handle_usta_files_project_selection(user, project.id)

    def _handle_usta_files_project_selection(self, user, project_id):
        """Step 2: Project Selected -> Show Categories"""
        project = self.env['construction.project'].browse(project_id)
        if not project.exists():
            _logger.warning(f"[BOT_FILES] Project {project_id} not found")
            return
        
        # Save state
        user.sudo().write({
            'usta_files_project_id': project.id,
            'usta_files_category_id': False,
            'usta_files_room_ref': False,
            'usta_files_room_map': False,
        })
        
        # Query distinct categories from latest files
        files = self.env['construction.project.file'].search([
            ('project_id', '=', project.id),
            ('is_latest', '=', True)
        ])
        
        _logger.info(f"[BOT_FILES] Found {len(files)} files for project {project.name}")
        
        categories = files.mapped('category_id').sorted('name')
        
        buttons = []
        for cat in categories:
            buttons.append([{'text': cat.name, 'callback_data': f"usta:files:cat:{cat.id}"}])
            
        nav_row = self._get_nav_row(back_cb="menu:worker:files")
        buttons.append(nav_row)
        
        self._send_message(
            user.telegram_chat_id,
            f"📎 *Fayllar*\nLoyiha: {project.name}\nBo‘limni tanlang:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _handle_usta_files_category_selection(self, user, category_id):
        """Step 3: Category Selected -> Show Rooms"""
        category = self.env['construction.file.category'].browse(category_id)
        project = user.usta_files_project_id
        
        if not category.exists() or not project:
            return
            
        user.sudo().write({'usta_files_category_id': category.id})
        
        # Query distinct rooms
        files = self.env['construction.project.file'].search([
            ('project_id', '=', project.id),
            ('category_id', '=', category.id),
            ('is_latest', '=', True)
        ])
        
        # Accessing 'room_ref' directly - expecting it to be a Char field
        # Use set to get unique, then list and sort
        rooms = sorted(list(set(files.mapped('room_ref'))))
        
        # Create map and buttons
        import json
        room_map = {str(i): room for i, room in enumerate(rooms)}
        user.sudo().write({'usta_files_room_map': json.dumps(room_map)})
        
        buttons = []
        for i, room in enumerate(rooms):
            # Callback uses index
            buttons.append([{'text': room, 'callback_data': f"usta:files:room_idx:{i}"}])
            
        nav_row = self._get_nav_row(back_cb=f"usta:files:project:{project.id}")
        buttons.append(nav_row)
        
        self._send_message(
            user.telegram_chat_id,
            f"📎 *Fayllar*\nLoyiha: {project.name}\nBo‘lim: {category.name}\nXonani tanlang:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _handle_usta_files_room_selection(self, user, room_idx):
        """Step 4: Room Selected -> Auto-Send Latest File"""
        import json
        if not user.usta_files_room_map:
            self._send_message(user.telegram_chat_id, "⚠️ Seans eskirgan. Iltimos qaytadan tanlang.")
            return

        try:
            room_map = json.loads(user.usta_files_room_map)
            room_ref = room_map.get(str(room_idx))
        except:
            room_ref = None
            
        if not room_ref:
             self._send_message(user.telegram_chat_id, "⚠️ Xona topilmadi.")
             return

        user.sudo().write({'usta_files_room_ref': room_ref})
        project = user.usta_files_project_id
        category = user.usta_files_category_id
        
        # Query ONE Latest File
        file_rec = self.env['construction.project.file'].search([
            ('project_id', '=', project.id),
            ('category_id', '=', category.id),
            ('room_ref', '=', room_ref),
            ('is_latest', '=', True)
        ], limit=1)
        
        nav_row = self._get_nav_row(back_cb=f"usta:files:cat:{category.id}")

        if not file_rec:
            self._send_message(user.telegram_chat_id, "❌ Bu xonada fayl topilmadi.", reply_markup={'inline_keyboard': [nav_row]})
            return

        # Auto-Send
        success = self._send_file_doc(user, file_rec)
        
        if success:
             self._send_message(user.telegram_chat_id, f"✅ Fayl yuborildi: *{file_rec.name}*")
             self._handle_usta_files_category_selection(user, category.id)

    def _send_file_doc(self, user, file_rec):
        """Helper to send document via Telegram API"""
        # Security check
        allowed = user.get_allowed_construction_projects()
        if file_rec.project_id not in allowed:
             self._send_message(user.telegram_chat_id, "⛔ Ruxsat yo‘q.")
             return False
             
        # Send Document
        token = self._get_token()
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        
        attachment = file_rec.attachment_id
        if not attachment:
            self._send_message(user.telegram_chat_id, "❌ Fayl manbai topilmadi (Attachment Missing).")
            return False

        try:
            import base64
            file_content = base64.b64decode(attachment.datas)
            
            files = {
                'document': (attachment.name, file_content)
            }
            data = {'chat_id': user.telegram_chat_id}
            
            res = requests.post(url, data=data, files=files, timeout=30)
            res.raise_for_status()
            return True
            
        except Exception as e:
            _logger.error(f"[Bot] Send doc error: {e}")
            self._send_message(user.telegram_chat_id, "❌ Yuborishda xatolik.")
            return False


    # --- Client Dashboard Helpers ---

    def _format_money_uzs(self, amount):
        """Formats e.g. 1200000.0 to '1 200 000 so‘m'"""
        if not amount:
            return "0 so‘m"
        return "{:,.0f}".format(amount).replace(",", " ") + " so‘m"

    # --- Client: Project Status ---

    def _start_client_project_status(self, user):
        project, status = self._ensure_project_or_ask(user, "client:status")
        if status == 'auto_selected':
            self._handle_client_project_status(user, project.id)

    def _handle_client_project_status(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return

        msg = f"📊 *Loyiha Holati: {project.name}*\n\n"

        # 1. Stages Progress
        st_icon_map = {
            'draft': '⚪️',
            'in_progress': '🟡',
            'completed': '✅',
        }
        
        stages = self.env['construction.stage'].search([('project_id', '=', project.id)], order='id asc')
        if not stages:
            msg += "⚠️ Bosqichlar topilmadi."
        else:
            for st in stages:
                # Calc percentage
                # Tasks: done / total
                # Note: Assuming stage has task_ids (construction.stage -> construction.stage.task or construction.work.task?)
                # Wait, construction.work.task has no stage_id. It's construction.stage.task
                # BUT user requirement says: "task completion from construction.work.task (new/in_progress/done/blocked) grouped by stage_id"
                # Let's check construction.work.task model first. It might have stage_id?
                # Actually earlier task.md said "create construction.work.task model".
                # If work.task is not linked to stage, we can't group by stage.
                # Standard Odoo project.task is linked to stage.
                # Assuming construction.work.task MIGHT NOT have stage_id based on previous steps?
                # Let's assume user means construction.stage.task (the checklist items) OR we added stage_id to work.task.
                # Existing code shows 'construction.stage.task' used in 'action_view_stages'.
                # Let's check 'construction.stage' model to see if it has 'task_ids' (One2many).
                # Yes, construction_project.py line 152 creates 'construction.stage.task'.
                # So we use st.task_ids.
                
                # User Request: Progress based on Services (Vazifalar) completion
                # construction.stage.task are just containers. Real work is in service_ids.
                # However, stage has service_ids (One2many).
                services = st.service_ids
                total = len(services)
                done = len(services.filtered(lambda s: s.is_done))
                
                percent = 0
                if total > 0:
                    percent = int((done / total) * 100)
                    
                icon = st_icon_map.get(st.state, '⚪️')
                if percent == 100: icon = '✅'
                
                msg += f"{icon} *{st.name}*: {percent}% ({done}/{total})\n"

        # 2. Today's Updates
        msg += "\n📅 *Bugun yangilangan:*\n"
        
        # Tasks done today (construction.work.task)
        # Using work.task for "Work Tasks" (Vazifalar) vs Stage Tasks (Texnik checklist)
        # Requirement says "task completion from construction.work.task".
        # If work tasks are NOT stage-linked, we can't show per-stage progress for THEM.
        # But we CAN show total Done Today.
        
        today = fields.Date.context_today(self)
        # Search work.task done today (assuming write_date is today and state='done' or specific date field)
        # Assuming we check write_date for simplicity since we don't have 'done_date'
        done_work_tasks = self.env['construction.work.task'].search_count([
            ('project_id', '=', project.id),
            ('state', '=', 'done'),
            ('write_date', '>=', today) 
        ])
        msg += f"✅ Bajarilgan vazifalar: {done_work_tasks}\n"

        # Issues created today
        new_issues = self.env['construction.issue'].search_count([
            ('project_id', '=', project.id),
            ('create_date', '>=', today)
        ])
        msg += f"⚠️ Yangi muammolar: {new_issues}\n"

        nav = self._get_nav_row(back_cb="menu:client:status", home=True)
        # Back button goes to project selection if multiple, or menu if single.
        # Simplification: Go to client menu? Or re-trigger selection?
        # Let's go to main menu for 'back' effectively, or better, back to project list?
        # If auto-selected, back should go to main menu.
        # We can detect this. For now safely back to Main Menu (Client Menu).
        buttons = [[{'text': "🏠 Bosh menyu", 'callback_data': "nav:home"}]]
        
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    # --- Client: Cash Flow ---

    def _start_client_cash_flow(self, user):
        project, status = self._ensure_project_or_ask(user, "client:money")
        if status == 'auto_selected':
            self._handle_client_cash_flow(user, project.id)

    def _handle_client_cash_flow(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return

        msg = f"💰 *Pul Oqimi: {project.name}*\n\n"
        
        # Project Financials
        msg += f"💵 *Jami Kirim:* {self._format_money_uzs(project.total_income)}\n"
        msg += f"💸 *Jami Chiqim:* {self._format_money_uzs(project.total_expense)}\n"
        
        lbl = "🟢" if project.balance >= 0 else "🔴"
        msg += f"{lbl} *Balans:* {self._format_money_uzs(project.balance)}\n\n"

        # Approval Batches (Material Requests)
        # Approved Today
        today = fields.Date.context_today(self)
        approved_today = self.env['construction.material.request.batch'].search([
            ('project_id', '=', project.id),
            ('state', '=', 'approved'),
            ('write_date', '>=', today) # Approximation for approved_at
        ])
        # Manually calc sum since batch has no total field
        approved_sum = sum(sum(b.line_ids.mapped('total_price')) for b in approved_today)
        msg += f"✅ Bugun tasdiqlandi: {self._format_money_uzs(approved_sum)}\n"

        # Pending Total
        pending = self.env['construction.material.request.batch'].search([
            ('project_id', '=', project.id),
            ('state', 'in', ['draft', 'pending'])
        ])
        pending_sum = sum(sum(b.line_ids.mapped('total_price')) for b in pending)
        msg += f"⏳ Tasdiq kutilmoqda: {self._format_money_uzs(pending_sum)}\n"

        buttons = [[{'text': "🏠 Bosh menyu", 'callback_data': "nav:home"}]]
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    # --- SNAB: Pending Requests & Pricing ---
    
    def _start_snab_pending_requests(self, user):
        project, status = self._ensure_project_or_ask(user, "snab:req")
        if status == 'auto_selected':
             self._show_snab_pending_list(user, project.id)

    def _show_snab_pending_list(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return

        # Definition: Pending for Snab = Not Approved (Draft or Priced)
        domain = [
            ('project_id', '=', project.id),
            ('state', 'in', ['draft', 'priced']) 
        ]
        # Fetch ALL relevant batches for the list display
        batches = self.env['construction.material.request.batch'].search(domain, order='create_date desc', limit=20)

        if not batches:
             self._send_message(user.telegram_chat_id, f"✅ *{project.name}*\nSiz uchun kutilayotgan so‘rovlar yo‘q.", reply_markup={'inline_keyboard': [self._get_nav_row()]})
             return

        # Build Merged List Text
        msg_lines = []
        msg_lines.append(f"📨 *{project.name}*")
        msg_lines.append(f"Kutilayotgan so‘rovlar (Jami {len(batches)} ta paket):")
        msg_lines.append("")
        
        total_items = 0
        idx = 1
        for batch in batches:
             for line in batch.line_ids:
                 price_txt = f"{line.unit_price:,.0f} so‘m" if line.unit_price > 0 else "Narx yo‘q"
                 usta_name = line.batch_id.requester_id.name or "Noma'lum"
                 # Format: Name | Qty | Price | Usta
                 msg_lines.append(f"{idx}. {line.product_name} | {line.quantity} | {price_txt} | {usta_name}")
                 idx += 1
                 total_items += 1
                 if len(msg_lines) > 50: # Limit to avoid message too long
                      msg_lines.append("... va boshqalar")
                      break
             if len(msg_lines) > 50: break

        # If no items in batches?
        if total_items == 0:
             msg_lines.append("❌ Mahsulotlar topilmadi (to‘ldirilmagan).")

        text = "\n".join(msg_lines)

        # Buttons
        buttons = []
        # Voice Pricing
        buttons.append([{'text': "🎙 Ovozli narxlash", 'callback_data': f"snab:price_voice:{project.id}"}])
        
        # Export Buttons
        buttons.append([
            {'text': "📊 Excel", 'callback_data': f"snab:pending:export:excel:{project.id}"},
            {'text': "📄 PDF", 'callback_data': f"snab:pending:export:pdf:{project.id}"}
        ])
        buttons.append(self._get_nav_row())

        self._send_message(user.telegram_chat_id, text, reply_markup={'inline_keyboard': buttons})

    def _show_snab_req_detail(self, user, batch_id):
        batch = self.env['construction.material.request.batch'].browse(batch_id)
        if not batch.exists():
            self._send_message(user.telegram_chat_id, "❌ So‘rov topilmadi.")
            return

        # Prepare Text
        status_map = {
            'draft': 'Yangi (Narx kutilmoqda)',
            'priced': 'Narx qo‘yilgan (Yuborish kutilmoqda)',
            'approved': 'Tasdiqlangan',
            'rejected': 'Rad etilgan'
        }
        status_text = status_map.get(batch.state, batch.state)
        
        text = (
            f"🧾 *So‘rov №{batch.name or batch.id}*\n"
            f"🏗 Loyiha: {batch.project_id.name}\n"
            f"📅 Sana: {batch.date}\n"
            f"👤 Usta: {batch.requester_id.name}\n"
            f"📌 Holat: {status_text}\n"
        )
        if batch.task_id:
            text += f"🔨 Vazifa: {batch.task_id.name}\n"

        text += "\n*Mahsulotlar:*\n"
        for i, line in enumerate(batch.line_ids, 1):
            price_txt = f" - {line.unit_price:,.0f} so‘m" if line.unit_price > 0 else ""
            text += f"{i}. {line.product_name}: {line.quantity} {price_txt}\n"
            
        if batch.state == 'approved':
             # Show Total
             total = sum(batch.line_ids.mapped('total_price'))
             text += f"\n💰 *Jami:* {total:,.0f} so‘m"

        # Buttons
        buttons = []
        if batch.state in ['draft', 'priced']:
            buttons.append([{'text': "💵 Narx qo‘shish / O‘zgartirish", 'callback_data': f"snab:req:price:{batch.id}"}])
            buttons.append([{'text': "📩 Tasdiqlashga yuborish", 'callback_data': f"snab:req:send:{batch.id}"}])
            back_cb = f"snab:req:list:{batch.project_id.id}"
        else:
            # Assumed valid back for approved/rejected
            back_cb = f"snab:approved:list:{batch.project_id.id}"
        
        buttons.append([{'text': "⬅️ Ortga", 'callback_data': back_cb}]) 
        buttons.append([{'text': "🏠 Bosh menyu", 'callback_data': "nav:home"}])

        self._send_message(user.telegram_chat_id, text, reply_markup={'inline_keyboard': buttons})

    def _start_snab_pricing_flow(self, user, batch_id):
        batch = self.env['construction.material.request.batch'].browse(batch_id)
        if not batch.exists(): return
        
        buttons = []
        for line in batch.line_ids:
            price_lbl = f" ({line.unit_price:,.0f})" if line.unit_price > 0 else ""
            buttons.append([{'text': f"{line.product_name}{price_lbl}", 'callback_data': f"snab:req:setprice:{line.id}"}])
            
        buttons.append([{'text': "⬅️ Ortga", 'callback_data': f"snab:req:open:{batch.id}"}])
        
        self._send_message(
            user.telegram_chat_id,
            f"💵 *Narxlash: {batch.name}*\nQaysi mahsulotga narx kiritasiz?",
            reply_markup={'inline_keyboard': buttons}
        )

    def _ask_snab_line_price(self, user, line_id):
        line = self.env['construction.material.request.line'].browse(line_id)
        if not line.exists(): return
        
        # Save state
        user.sudo().write({
            'construction_bot_state': 'snab_price_input_line',
            'snab_price_line_id': line.id 
        })
        
        self._send_message(
            user.telegram_chat_id,
            f"✍️ *{line.product_name}* uchun narxni kiriting (so‘m):\nNamuna: 50000"
        )
    
    def _handle_snab_line_price_input(self, user, text):
        try:
            clean = text.replace(' ', '').replace(',', '').replace("'", "")
            price = float(clean)
            if price <= 0: raise ValueError
        except:
             self._send_message(user.telegram_chat_id, "⚠️ Iltimos, to‘g‘ri raqam kiriting.")
             return

        line = user.snab_price_line_id
        if not line or not line.exists():
            self._send_message(user.telegram_chat_id, "❌ Xatolik: qator topilmadi.")
            user.sudo().write({'construction_bot_state': 'idle'})
            self._show_main_menu(user)
            return
        
        # Save unit price
        line.sudo().write({'unit_price': price})
        
        # Confirm
        self._send_message(
            user.telegram_chat_id,
            f"✅ Saqlandi: {line.product_name} — {price:,.0f} so'm"
        )
        
        # Return to pricing panel
        user.sudo().write({
            'snab_price_line_id': False,
            'construction_bot_state': 'snab_price_select_line'
        })
        self._show_pricing_panel(user)

    def _start_snab_voice_pricing(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return
        
        user.sudo().write({
            'construction_bot_state': 'snab_voice_price_wait',
            'snab_price_batch_id': False, # Clear batch context
            'construction_selected_project_id': project.id
        })
        
        self._send_message(
            user.telegram_chat_id,
            f"🎙 *Ovozli Narxlash ({project.name})*\n\n"
            "Material nomi va narxini aytib ovozli xabar yuboring.\n"
            "Masalan: *\"Gipsokarton 50 ming, Rotband 80 ming\"*"
        )

    def _handle_snab_voice_pricing(self, user, message):
        """Handle voice message for pricing"""
        project = user.construction_selected_project_id
        if not project:
            self._show_main_menu(user)
            return

        api_key = self.env['ir.config_parameter'].sudo().get_param('construction_bot.gemini_api_key')
        
        # 1. Download Voice
        voice_data = None
        mime_type = None
        
        if 'voice' in message:
            file_id = message['voice']['file_id']
            voice_data = self._download_telegram_file(file_id)
            mime_type = message['voice'].get('mime_type', 'audio/ogg')
        elif 'audio' in message:
            file_id = message['audio']['file_id']
            voice_data = self._download_telegram_file(file_id)
            mime_type = message['audio'].get('mime_type', 'audio/mpeg')
        elif 'text' in message:
             # Allow text input too
             voice_data = message['text']
             mime_type = 'text/plain'
        else:
            self._send_message(user.telegram_chat_id, "❌ Iltimos, ovozli xabar yoki matn yuboring.")
            return

        if not voice_data:
            self._send_message(user.telegram_chat_id, "❌ Faylni yuklab bo'lmadi.")
            return

        self._send_message(user.telegram_chat_id, "⏳ AI tahlil qilmoqda...")

        # 2. Process with Gemini
        result = GeminiService.process_pricing_request(api_key, voice_data, mime_type)
        
        if result.get('error'):
            self._send_message(user.telegram_chat_id, f"❌ Xatolik: {result['error']}")
            return
            
        items = result.get('items', [])
        if not items:
            self._send_message(user.telegram_chat_id, "⚠️ Hech qanday narx topilmadi. Aniqroq gapiring.")
            return
            
        # 3. Match and Update
        # Find all pending lines for this project
        pending_lines = self.env['construction.material.request.line'].search([
            ('batch_id.project_id', '=', project.id),
            ('batch_id.state', 'in', ['draft', 'priced'])
        ])
        
        updated_count = 0
        not_found = []
        
        for item in items:
            name_spoken = item.get('name', '').lower()
            price = item.get('price', 0)
            
            if not name_spoken or price <= 0: continue
            
            # Fuzzy match attempt
            # Simple strategy: Check if spoken name is contained in product name (or vice versa)
            # Better: Jaccard similarity or fuzzywuzzy. But we only have standard lib + odoo.
            # Let's use ILIKE logic and word intersection.
            
            best_match = None
            
            # Strategy A: Direct substring
            candidates = pending_lines.filtered(lambda l: name_spoken in l.product_name.lower())
            
            # Strategy B: Reverse substring (product name inside spoken text - less likely for short voice commands)
            if not candidates:
                 candidates = pending_lines.filtered(lambda l: l.product_name.lower() in name_spoken)
                 
            if candidates:
                # Pick first or best? If multiple, maybe closest length?
                # Just pick first for now
                best_match = candidates[0]
            else:
                # Strategy C: Word intersection
                spoken_words = set(name_spoken.split())
                best_score = 0
                
                for line in pending_lines:
                    line_words = set(line.product_name.lower().split())
                    common = spoken_words.intersection(line_words)
                    if len(common) > 0:
                        score = len(common) / len(line_words) # % of line words matched
                        if score > best_score:
                            best_score = score
                            best_match = line
                
                if best_score < 0.3: # Threshold
                    best_match = None

            if best_match:
                # Update Price
                best_match.sudo().write({'unit_price': price})
                
                # If batch was draft, move to priced?
                # Using _system_send_batch_approval logic? No, just update price.
                # But state should ideally reflect 'priced' if it has price.
                if best_match.batch_id.state == 'draft':
                     best_match.batch_id.sudo().write({'state': 'priced'})
                     
                updated_count += 1
            else:
                not_found.append(f"{item['name']} ({price})")

        # 4. Report
        msg = f"✅ *Natija*\nYangilandi: {updated_count} ta\n"
        if not_found:
            msg += f"\n⚠️ Topilmadi:\n" + "\n".join(not_found)
            
        self._send_message(user.telegram_chat_id, msg)
        
        # Show list again
        self._show_snab_pending_list(user, project.id)



    def _handle_snab_send_approval(self, user, batch_id):
        batch = self.env['construction.material.request.batch'].browse(batch_id)
        if not batch.exists(): return

        missing_price = batch.line_ids.filtered(lambda l: l.unit_price <= 0)
        if missing_price:
            self._send_message(user.telegram_chat_id, "❌ Avval barcha mahsulotlarga narx kiriting.")
            return

        batch.sudo().write({'state': 'priced'})
        self._send_message(user.telegram_chat_id, "✅ So‘rov tasdiqlash uchun yuborildi.")
        
        # Call system method
        if hasattr(self, '_system_send_batch_approval'):
            self._system_send_batch_approval(batch)

     # --- PRORAB: Issues & Risk ---

    def _start_foreman_issues(self, user):
        project, status = self._ensure_project_or_ask(user, "prorab:issues")
        if status == 'auto_selected':
              self._ask_issue_filter(user, project.id)
              
    def _ask_issue_filter(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        
        buttons = [
            [{'text': "🔥 Ochiq muammolar", 'callback_data': f"prorab:issues:list:{project.id}:open"}],
            [{'text': "📚 Barchasi", 'callback_data': f"prorab:issues:list:{project.id}:all"}],
            [self._get_nav_row()]
        ] # wait, nested nav row... check current state
        # I fixed nav row nesting in previous turn!
        # This replaces lines 2658 to 2943.
        # So I must be careful not to reintroduce nesting.
        # I'll check what I am replacing.
        
        self._send_message(
            user.telegram_chat_id,
            f"⚠️ *{project.name}*\nMuammolarni saralash:",
            reply_markup={'inline_keyboard': buttons}
        )

    def _show_foreman_issues_list(self, user, project_id, filter_type):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return
        
        domain = [('project_id', '=', project.id)]
        
        if filter_type == 'open':
             domain.append(('state', 'in', ['new', 'in_progress']))
             title = "🔥 Ochiq muammolar"
        else:
             title = "📚 Barcha muammolar"
             
        # Apply domain
        issues = self.env['construction.issue'].search(domain, order='priority desc, create_date desc', limit=10)
        
        # Filter strictly for Workers? 
        issues = issues.filtered(lambda i: i.reported_by.construction_role == 'worker')
        
        if not issues:
             self._send_message(user.telegram_chat_id, f"✅ {title} topilmadi ({project.name})", reply_markup={'inline_keyboard': [self._get_nav_row()]})
             return

        buttons = []
        state_icons = {'new': '🆕', 'in_progress': '👀', 'resolved': '✅', 'canceled': '❌'}
        
        for issue in issues:
            icon = state_icons.get(issue.state, '⚠️')
            short_desc = (issue.description or "")[:20] + "..."
            label = f"{icon} {short_desc}"
            buttons.append([{'text': label, 'callback_data': f"prorab:issues:open:{issue.id}"}])
            
        buttons.append([{'text': "⬅️ Ortga", 'callback_data': f"prorab:issues:project:{project.id}"}]) 
        buttons.append(self._get_nav_row())
        
        self._send_message(user.telegram_chat_id, f"⚠️ *{title}*\nTanlang:", reply_markup={'inline_keyboard': buttons})

    def _show_foreman_issue_detail(self, user, issue_id):
        issue = self.env['construction.issue'].browse(issue_id)
        if not issue.exists():
            self._send_message(user.telegram_chat_id, "❌ Muammo topilmadi.")
            return
            
        # Info
        state_map = {'new': 'Yangi', 'in_progress': 'Jarayonda', 'resolved': 'Hal bo‘ldi', 'canceled': 'Bekor'}
        st_txt = state_map.get(issue.state, issue.state)
        
        text = (
            f"⚠️ *Muammo №{issue.id}*\n"
            f"🏗 Loyiha: {issue.project_id.name}\n"
            f"👤 Yubordi: {issue.reported_by.name}\n"
            f"📅 Sana: {issue.create_date}\n"
            f"📌 Holat: {st_txt}\n\n"
            f"📝 *Tavsif:*\n{issue.description}"
        )
        
        # Actions
        buttons = []
        if issue.state in ['new', 'in_progress']:
             if issue.state == 'new':
                 buttons.append([{'text': "👀 Ko‘rib chiqyapman", 'callback_data': f"issue:set:in_progress:{issue.id}"}])
             buttons.append([{'text': "✅ Hal bo‘ldi", 'callback_data': f"issue:set:resolved:{issue.id}"}])
             buttons.append([{'text': "❌ Bekor qilish", 'callback_data': f"issue:set:canceled:{issue.id}"}])
             
        buttons.append([{'text': "⬅️ Ortga", 'callback_data': f"prorab:issues:list:{issue.project_id.id}:all"}]) 
        buttons.append(self._get_nav_row())
        
        # Photo handling
        sent_photo = False
        if issue.attachment_ids and issue.attachment_ids[0].datas:
             import base64
             try:
                 photo_data = base64.b64decode(issue.attachment_ids[0].datas)
                 self._send_photo(user.telegram_chat_id, photo_data, caption=text, reply_markup={'inline_keyboard': buttons})
                 sent_photo = True
             except:
                 pass

        if not sent_photo:
             self._send_message(user.telegram_chat_id, text, reply_markup={'inline_keyboard': buttons})
 
    # --- SNAB: Approved List ---
    
    def _start_snab_approved_requests(self, user):
        project, status = self._ensure_project_or_ask(user, "snab:approved")
        if status == 'auto_selected':
             self._show_snab_approved_list(user, project.id)

    def _show_snab_approved_list(self, user, project_id):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return

        batches = self.env['construction.material.request.batch'].search([
            ('project_id', '=', project.id),
            ('state', '=', 'approved')
        ], order='approve_date desc, date desc', limit=20)

        if not batches:
             self._send_message(user.telegram_chat_id, f"✅ *{project.name}*\nTasdiqlangan so‘rovlar yo‘q.", reply_markup={'inline_keyboard': [self._get_nav_row()]})
             return

        # Merged Text
        msg_lines = []
        msg_lines.append(f"✅ *{project.name}*")
        msg_lines.append(f"Tasdiqlangan materiallar (Jami: {len(batches)} ta paket):")
        msg_lines.append("")
        
        grand_total = 0
        idx = 1
        for batch in batches:
             for line in batch.line_ids:
                 grand_total += line.total_price
                 usta_name = line.batch_id.requester_id.name or "Noma'lum"
                 msg_lines.append(f"{idx}. {line.product_name} | {line.quantity} | {self._format_money_uzs(line.total_price)} | {usta_name}")
                 idx += 1
                 if len(msg_lines) > 50:
                      msg_lines.append("... va boshqalar")
                      break
             if len(msg_lines) > 50: break
             
        msg_lines.append("")
        msg_lines.append(f"💰 *Jami summa:* {self._format_money_uzs(grand_total)}")
        
        text = "\n".join(msg_lines)

        # Buttons
        buttons = []
        # Export Buttons
        buttons.append([
            {'text': "📊 Excel", 'callback_data': f"snab:approved:export:excel:{project.id}"},
            {'text': "📄 PDF", 'callback_data': f"snab:approved:export:pdf:{project.id}"}
        ])
        buttons.append(self._get_nav_row())

        self._send_message(user.telegram_chat_id, text, reply_markup={'inline_keyboard': buttons})

    def _handle_snab_export(self, user, project_id, list_type, fmt):
        project = self.env['construction.project'].browse(project_id)
        if not project.exists(): return
        
        domain = [('project_id', '=', project.id)]
        if list_type == 'pending':
            domain.append(('state', 'in', ['draft', 'priced']))
        else: # approved
            domain.append(('state', '=', 'approved'))
            
        batches = self.env['construction.material.request.batch'].search(domain, order='create_date desc', limit=20)
        
        if not batches:
             self._send_message(user.telegram_chat_id, "❌ Eksport qilish uchun ma'lumot yo‘q.")
             return
             
        attachment = None
        if fmt == 'excel':
             if hasattr(batches, 'action_export_excel'):
                 attachment = batches.action_export_excel()
        elif fmt == 'pdf':
             if hasattr(batches, 'action_export_pdf'):
                 attachment = batches.action_export_pdf()
                 
        if attachment:
             # Send document
             # We need to read datas back
             import base64
             file_data = base64.b64decode(attachment.datas)
             
             # Prepare buttons for post-export navigation
             buttons = []
             if list_type == 'pending':
                 buttons.append([{'text': "⬅️ Ro‘yxatga qaytish", 'callback_data': f"snab:req:list:{project.id}"}])
             else:
                 buttons.append([{'text': "⬅️ Ro‘yxatga qaytish", 'callback_data': f"snab:approved:list:{project.id}"}])
             buttons.append(self._get_nav_row())
             
             self._send_document(
                 user.telegram_chat_id, 
                 file_data, 
                 filename=attachment.name, 
                 caption=f"✅ Hisobot tayyor. Fayl yuborildi.\nLoyiha: {project.name}",
                 reply_markup={'inline_keyboard': buttons}
             )
        else:
             lib_name = "openpyxl" if fmt == 'excel' else "reportlab"
             self._send_message(user.telegram_chat_id, f"❌ {fmt.upper()} yaratib bo‘lmadi: serverda {lib_name} o‘rnatilmagan.")

    # --- AI Material Request Flow ---

    def _start_usta_ai_request(self, user, project_id):
        project = self.env['construction.project'].sudo().browse(project_id)
        
        user.sudo().write({
            'construction_bot_state': 'usta_ai_input',
            'usta_ai_project_id': project.id,
            'mr_draft_project_id': project.id, # Sync for compatibility
            'mr_draft_lines_json': json.dumps([]) # Clear draft
        })
        
        msg = (
            f"🧱 *Material So'rovi* (Loyiha: {project.name})\n\n"
            "📸 *Rasm*, 🎤 *Ovoz* yoki ✍️ *Matn* yuboring.\n"
            "_Sun'iy intellekt (AI) ro'yxatni avtomatik aniqlaydi._"
        )
        
        buttons = [
            [{'text': "⏮ Ortga (Bosh menyu)", 'callback_data': "menu:main"}]
        ]
        
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})

    def _handle_usta_ai_input(self, user, message):
        chat_id = user.telegram_chat_id
        
        # 1. Get Content
        text = message.get('text', '')
        voice = message.get('voice')
        photo = message.get('photo')
        
        # If Text ONLY -> Use Manual Logic (No AI)
        if text and not voice and not photo:
            self._handle_mr_draft_input(user, text)
            return

        # Feedback
        self._send_message(chat_id, "⏳ _Tahlil qilinmoqda..._")
        
        gemini_text = text if text else None
        gemini_media = None
        gemini_mime = None
        
        api_key = self.env['ir.config_parameter'].sudo().get_param('construction.gemini_api_key')
        
        try:
            if voice:
                file_id = voice['file_id']
                content = self._download_file(file_id)
                if content:
                    gemini_media = content
                    gemini_mime = 'audio/ogg'
            elif photo:
                # Get largest photo
                file_id = photo[-1]['file_id']
                content = self._download_file(file_id)
                caption = message.get('caption', '')
                if content:
                    gemini_media = content
                    gemini_mime = 'image/jpeg'
                    if caption:
                        gemini_text = caption
                # If there's text with photo (caption), we treat it as AI prompt.
                if not content and not caption:
                     return # Should not happen if photo exists
        except Exception as e:
            _logger.error(f"Download Error: {e}")
            self._send_message(chat_id, "❌ Faylni yuklashda xatolik bo'ldi.")
            return

        # 2. Call Gemini
        except Exception as e:
            _logger.error(f"Download Error: {e}")
            self._send_message(chat_id, "❌ Faylni yuklashda xatolik bo'ldi.")
            return

        # 2. Call Gemini
        result = GeminiService.process_request(api_key, text_prompt=gemini_text, media_data=gemini_media, mime_type=gemini_mime)
        
        if not result or 'error' in result:
            err = result.get('error', "Noma'lum xatolik") if result else "Javob yo'q"
            # Send error as plain text to avoid Markdown parsing issues with API error dumps
            self._send_message(chat_id, f"❌ AI Xatolik: {err}\n\nQaytadan urinib ko'ring.", parse_mode=None)
            return
            
        # 3. Process Result
        items = result.get('items', [])
        warnings = result.get('warnings', [])
        
        if not items:
            self._send_message(chat_id, "⚠️ Hech qanday material aniqlanmadi. Iltimos, aniqroq yuboring.")
            return

        # Show Warnings
        if warnings:
            warn_msg = "⚠️ *Ogohlantirish:*\n" + "\n".join(warnings)
            self._send_message(chat_id, warn_msg)
            
        # 4. Map to Draft Schema & Store
        # Draft schema: [{'name': str, 'qty': float}]
        # New items: [{'name_clean': str, 'qty': float, 'uom': str}]
        
        draft_list = []
        for item in items:
            name = item.get('name_clean') or item.get('name_raw') or "Noma'lm"
            qty = item.get('qty', 1)
            uom = item.get('uom', 'dona')
            
            # Combine formatting: "Name (UoM)"
            formatted_name = f"{name} ({uom})"
            draft_list.append({
                'name': formatted_name,
                'qty': qty
            })
            
        # Use simple list append if you want to accumulate? 
        # Or overwrite? User said "list of materials". 
        # Usually one voice note = one batch. 
        # But if they send multiple messages, maybe append? 
        # Existing logic overwrites: 'mr_draft_lines_json': json.dumps(draft_list)
        # Requirement "when i send one message it is sending multiple message" fix implies 
        # we process one message at a time.
        # But if they want to BUILD a list, we might want to append.
        # Let's keep overwrite for now as per previous logic, or append if key exists?
        # The prompt says: "Hozirgi ro'yxat: ...". If we overwrite each time, they can't build a list.
        # Let's try to APPEND.
        
        current_draft = []
        try:
             current_draft = json.loads(user.mr_draft_lines_json or "[]")
        except:
             pass
        
        # Merge
        current_draft.extend(draft_list)
        
        user.sudo().write({
            'mr_draft_lines_json': json.dumps(current_draft),
            'construction_bot_state': 'usta_mr_draft_input'
        })
        
        # 5. Show Confirmation
        self._send_mr_draft_interface(user)


    # --- Snab Delivery Status Flow ---
    
    def _start_snab_delivery_status(self, user):
        """Entry point for Snab Delivery Status"""
        # Get allowed projects (reuse logic)
        projects = user.allowed_project_ids
        if not projects:
             self._send_message(user.telegram_chat_id, "⛔ Sizga biriktirilgan loyihalar yo‘q.")
             return
             
        if len(projects) == 1:
             self._show_snab_delivery_filter(user, projects[0].id)
        else:
             # Show Project Picker
             buttons = []
             for p in projects:
                 buttons.append([{'text': p.name, 'callback_data': f"dlv|proj|{p.id}"}])
             
             buttons.append(self._get_nav_row())
             self._send_message(user.telegram_chat_id, "🏗 *Loyihani tanlang:*", reply_markup={'inline_keyboard': buttons})

    def _show_snab_delivery_filter(self, user, project_id):
        """Show Filter (Purchased/InTransit/Delivered)"""
        p_id = str(project_id)
        buttons = [
            [{'text': "🟠 Sotib olindi", 'callback_data': f"dlv|flt|purchased|{p_id}"}],
            [{'text': "🔵 Yo‘lda", 'callback_data': f"dlv|flt|in_transit|{p_id}"}],
            [{'text': "🟢 Yetkazildi", 'callback_data': f"dlv|flt|delivered|{p_id}"}],
            [{'text': "📋 Barchasi", 'callback_data': f"dlv|flt|all|{p_id}"}],
            self._get_nav_row(back_cb=f"menu:supply:delivery_status" if len(user.allowed_project_ids) > 1 else None)
        ]
        
        self._send_message(
            user.telegram_chat_id, 
            "🚚 *Yetkazib berish holati*\nKerakli bo‘limni tanlang:", 
            reply_markup={'inline_keyboard': buttons}
        )

    def _show_snab_delivery_list(self, user, project_id, filter_state):
        """Show list of batches matching filter"""
        domain = [
            ('project_id', '=', project_id),
            ('state', '=', 'approved') # Only approved batches
        ]
        batches = self.env['construction.material.request.batch'].search(domain, order='create_date desc', limit=20)
        
        filtered_items = []
        
        Delivery = self.env['construction.material.delivery']
        
        for batch in batches:
            delivery = Delivery.search([('batch_id', '=', batch.id)], limit=1)
            
            # Default state
            state = 'purchased'
            if delivery:
                state = delivery.state
                
            if filter_state != 'all' and state != filter_state:
                continue
                
            icon = "🟠"
            if state == 'in_transit': icon = "🔵"
            elif state == 'delivered': icon = "🟢"
            
            # Formatting
            total_sum = sum(l.total_price for l in batch.line_ids)
            sum_str = "{:,.0f}".format(total_sum).replace(',', ' ')
            
            text = f"{batch.name} | {batch.date} | {sum_str} so'm | {icon}"
            
            filtered_items.append({
                'text': text,
                'callback_data': f"dlv|bat|{batch.id}|{project_id}"
            })
            
        if not filtered_items:
             msg = "📭 Bu bo‘limda ma'lumot yo‘q."
             buttons = [self._get_nav_row(back_cb=f"dlv|proj|{project_id}")]
             self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})
             return
             
        buttons = [[item] for item in filtered_items]
        buttons.append(self._get_nav_row(back_cb=f"dlv|proj|{project_id}"))
        
        self._send_message(
            user.telegram_chat_id,
            f"📋 *Ro‘yxat ({len(filtered_items)} ta)*",
            reply_markup={'inline_keyboard': buttons}
        )

    def _show_snab_delivery_detail(self, user, batch_id):
        """Show detail and update buttons"""
        batch = self.env['construction.material.request.batch'].browse(batch_id)
        if not batch.exists():
            self._send_message(user.telegram_chat_id, "⛔ Ma'lumot topilmadi.")
            return
            
        # Get Delivery Record
        Delivery = self.env['construction.material.delivery']
        delivery = Delivery.search([('batch_id', '=', batch.id)], limit=1)
        
        current_state = 'purchased'
        if delivery:
            current_state = delivery.state
        else:
            # Auto-create if missing (lazy init)
            try:
                delivery = Delivery.create({'batch_id': batch.id, 'state': 'purchased'})
            except Exception as e:
                _logger.error(f"Failed to create delivery: {e}")
                pass
        
        # Text
        project_name = batch.project_id.name
        usta = batch.requester_id.name or "Noma'lum"
        total_sum = sum(l.total_price for l in batch.line_ids)
        sum_str = "{:,.0f}".format(total_sum).replace(',', ' ')
        
        state_labels = {
            'purchased': "🟠 Sotib olindi",
            'in_transit': "🔵 Yo‘lda",
            'delivered': "🟢 Yetkazildi"
        }
        
        status_text = state_labels.get(current_state, current_state)
        
        msg = (
            f"📄 *So‘rov:* {batch.name}\n"
            f"🏗 *Loyiha:* {project_name}\n"
            f"👤 *Usta:* {usta}\n"
            f"📅 *Sana:* {batch.date}\n"
            f"💰 *Jami:* {sum_str} so'm\n\n"
            f"🚚 *Hozirgi holat:* {status_text}"
        )
        
        pid = batch.project_id.id
        buttons = []
        
        # Purchased
        btn_purchased = "🛒 Sotib olindi"
        if current_state == 'purchased': btn_purchased = "🔘 Sotib olindi"
        buttons.append([{'text': btn_purchased, 'callback_data': f"dlv|set|{batch.id}|purchased|{pid}"}])
        
        # In Transit
        btn_transit = "🚚 Yo‘lda"
        if current_state == 'in_transit': btn_transit = "🔘 Yo‘lda"
        buttons.append([{'text': btn_transit, 'callback_data': f"dlv|set|{batch.id}|in_transit|{pid}"}])
        
        # Delivered
        btn_delivered = "📦 Yetkazildi"
        if current_state == 'delivered': btn_delivered = "🔘 Yetkazildi"
        buttons.append([{'text': btn_delivered, 'callback_data': f"dlv|set|{batch.id}|delivered|{pid}"}])
        
        # Nav
        buttons.append(self._get_nav_row(back_cb=f"dlv|proj|{pid}")) 
        
        self._send_message(user.telegram_chat_id, msg, reply_markup={'inline_keyboard': buttons})


    def _handle_snab_delivery_update(self, user, batch_id, new_state, project_id):
        """Update status"""
        Delivery = self.env['construction.material.delivery']
        delivery = Delivery.search([('batch_id', '=', int(batch_id))], limit=1)
        
        if not delivery:
             Delivery.create({'batch_id': int(batch_id), 'state': new_state})
        else:
             if delivery.state == new_state:
                 self._send_message(user.telegram_chat_id, "ℹ️ Holat allaqachon o'rnatilgan.")
                 return
                 
             delivery.write({'state': new_state, 'source': 'telegram'})
             
        self._send_message(user.telegram_chat_id, "✅ Holat yangilandi!")
        self._show_snab_delivery_detail(user, batch_id)
        self._notify_prorab_delivery_change(delivery, new_state)

    def _notify_prorab_delivery_change(self, delivery, new_state):
        """Notify Foreman"""
        project = delivery.project_id
        foreman = project.foreman_id
        if not foreman or not foreman.telegram_chat_id:
            return
            
        state_labels = {
            'purchased': "🟠 Sotib olindi",
            'in_transit': "🔵 Yo‘lda",
            'delivered': "🟢 Yetkazildi"
        }
        lbl = state_labels.get(new_state, new_state)
        
        msg = (
            f"🚚 *Material holati yangilandi*\n\n"
            f"🏗 *Loyiha:* {project.name}\n"
            f"📄 *So‘rov:* {delivery.batch_id.name}\n"
            f"🆕 *Yangi holat:* {lbl}\n"
            f"👤 *Yangiladi:* {self.env.user.name}"
        )
        self._send_message(foreman.telegram_chat_id, msg)
