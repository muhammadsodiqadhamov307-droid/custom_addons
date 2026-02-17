from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class ConstructionProject(models.Model):
    _inherit = 'construction.project'

    @api.model_create_multi
    def create(self, vals_list):
        projects = super(ConstructionProject, self).create(vals_list)
        for project in projects:
            self._notify_project_assignees(project)
        return projects

    def write(self, vals):
        # 1. Capture old assignees
        # We are interested in fields: user_id, designer_id, foreman_id, supply_id, worker_ids
        relevant_fields = ['user_id', 'designer_id', 'foreman_id', 'supply_id', 'worker_ids']
        if not any(f in vals for f in relevant_fields):
            return super(ConstructionProject, self).write(vals)

        # Pre-fetch old values for potentially affected users
        # Map: User ID -> Set of Project IDs they access?
        # Actually easier: Just collect all users involved before and after, and notify them.
        # Since notification sends "Current State", it's distinct enough.
        
        users_to_check = set()
        for project in self:
            if project.user_id: users_to_check.add(project.user_id.id)
            if project.designer_id: users_to_check.add(project.designer_id.id)
            if project.foreman_id: users_to_check.add(project.foreman_id.id)
            if project.supply_id: users_to_check.add(project.supply_id.id)
            users_to_check.update(project.worker_ids.ids)

        res = super(ConstructionProject, self).write(vals)

        # Post-fetch
        for project in self:
            if project.user_id: users_to_check.add(project.user_id.id)
            if project.designer_id: users_to_check.add(project.designer_id.id)
            if project.foreman_id: users_to_check.add(project.foreman_id.id)
            if project.supply_id: users_to_check.add(project.supply_id.id)
            users_to_check.update(project.worker_ids.ids)
            
        # Notify all unique users involved
        if users_to_check:
            try:
                users = self.env['res.users'].browse(list(users_to_check))
                self.env['construction.telegram.bot'].sudo()._system_notify_user_role_update(users, is_new_access=False)
            except Exception as e:
                _logger.error(f"[PROJECT_NOTIFY] Error: {e}")

        return res

    def _notify_project_assignees(self, project):
        """Notify all assignees of a new project"""
        users = self.env['res.users']
        if project.user_id: users |= project.user_id
        if project.designer_id: users |= project.designer_id
        if project.foreman_id: users |= project.foreman_id
        if project.supply_id: users |= project.supply_id
        if project.worker_ids: users |= project.worker_ids
        
        if users:
            try:
                 self.env['construction.telegram.bot'].sudo()._system_notify_user_role_update(users, is_new_access=False)
            except Exception as e:
                _logger.error(f"[PROJECT_NOTIFY] Error: {e}")
