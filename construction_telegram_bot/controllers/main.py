from odoo import http
from odoo.http import request
import json
import logging
import traceback

_logger = logging.getLogger(__name__)

# Security: Allowed User IDs (Replace or extend as needed)
ALLOWED_USER_IDS = [] # Empty list = All allowed (or specific IDs: [123456, 789012])



class ConstructionBotController(http.Controller):
    
    def __init__(self):
        _logger.info(">>> ConstructionBotController INITIALIZED <<<")

    @http.route('/telegram/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def telegram_webhook(self, **kwargs):
        _logger.info(f">>> WEBHOOK ENDPOINT HIT! Path: {request.httprequest.path}")
        """
        Robust Telegram Webhook Endpoint
        Handles raw JSON from Telegram, avoids jsonrequest attribute errors.
        """
        try:
            # 1. Parse Data safely
            try:
                data_bytes = request.httprequest.get_data()
                data_str = data_bytes.decode('utf-8')
                data = json.loads(data_str)
            except Exception as e:
                _logger.warning(f"Failed to parse Telegram JSON: {e}")
                return request.make_response("OK") # Ack to stop retries

            # 2. Extract Basic Info for Logging
            update_id = data.get('update_id')
            message = data.get('message', {})
            chat_id = message.get('chat', {}).get('id')
            user_id = message.get('from', {}).get('id')
            text = message.get('text', '')

            _logger.info(f"Telegram Webhook: UpdateID={update_id}, User={user_id}, Text='{text}'")

            # 3. Security Check
            if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
                _logger.warning(f"Blocked Telegram User: {user_id}")
                return request.make_response("OK")

            # 4. Optional: Placeholder for custom logic
            if text:
                self.process_message(text, chat_id, user_id)

            # 5. Dispatch to Odoo Model
            request.env['construction.telegram.bot'].sudo().handle_update(data)
            
            return request.make_response("OK")

        except Exception as e:
            # Log full traceback but return 200 to Telegram
            tb = traceback.format_exc()
            _logger.error(f"Webhook Fatal Error: {e}\n{tb}")
            return request.make_response("OK")

    def process_message(self, text, chat_id, user_id):
        """
        Placeholder for direct processing if needed.
        Currently logic is handled by the model 'construction.telegram.bot'.
        """
        # _logger.info(f"Processing message: {text}")
        pass

