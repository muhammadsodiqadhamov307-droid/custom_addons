# Notification Manager (Skeleton)

import logging

_logger = logging.getLogger(__name__)

class NotificationManager:
    def __init__(self, env):
        self.env = env

    def notify(self, recipients_users, text, keyboard=None):
        """
        Wrapper around existing telegram send method.
        Must not duplicate code everywhere.
        """
        # Placeholder: call existing telegram_send call via bot service if available
        # For now, just log
        _logger.info(f"[NotificationManager] Would notify {len(recipients_users)} users: {text[:20]}...")
        pass

    def schedule_escalation(self, obj_model, obj_id, level=1):
        """
        Placeholder for future L1/L2/L3 escalation.
        Current behavior: only log.
        """
        _logger.info("ESCALATION PLACEHOLDER model=%s id=%s level=%s", obj_model, obj_id, level)

    def maybe_escalate_overdue_tasks(self):
        """
        Placeholder cron entry:
        Later will check overdue construction.work.task and notify.
        Current behavior: do nothing (only log once).
        """
        _logger.info("[NotificationManager] maybe_escalate_overdue_tasks called (Placeholder)")
