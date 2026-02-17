# Inventory Lite Service (Placeholder)

import logging

_logger = logging.getLogger(__name__)

class InventoryLiteService:
    def __init__(self, env):
        self.env = env

    def check_other_warehouses(self, project_id, lines):
        """
        Placeholder: in future will check leftover stock from other projects/warehouses.
        lines: list of dicts: [{'name': str, 'qty': float}, ...]
        Returns: dict result with keys:
          - 'available': bool
          - 'suggestions': list
          - 'message_uz': str
        Current implementation MUST be DUMMY:
          - Always return available=False
          - message_uz = "ℹ️ Ombor tekshiruvi hozircha yoqilmagan."
        """
        _logger.info(f"[InventoryLite] Checking warehouses for Project {project_id} (Dummy)")
        return {
            'available': False, 
            'suggestions': [], 
            'message_uz': "ℹ️ Ombor tekshiruvi hozircha yoqilmagan."
        }

    def check_inventory(self, project_id, lines):
        """
        Alias placeholder. Calls check_other_warehouses for now.
        """
        return self.check_other_warehouses(project_id, lines)
