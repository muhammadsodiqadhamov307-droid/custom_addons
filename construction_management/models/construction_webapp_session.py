from odoo import models, fields, api
import secrets
from datetime import datetime, timedelta

class ConstructionWebAppSession(models.Model):
    _name = 'construction.webapp.session'
    _description = 'Construction WebApp Session'

    token = fields.Char(required=True, index=True)
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade')
    expiry = fields.Datetime(required=True)
    active = fields.Boolean(default=True)

    @api.model
    def create_session(self, user_id):
        # Clean up expired sessions for this user
        self.search([('user_id', '=', user_id), ('expiry', '<', fields.Datetime.now())]).unlink()
        
        token = secrets.token_urlsafe(32)
        expiry = fields.Datetime.now() + timedelta(minutes=30) # 30 min expiry
        
        return self.create({
            'token': token,
            'user_id': user_id,
            'expiry': expiry
        })

    def is_valid(self):
        self.ensure_one()
        if not self.active:
            return False
        if self.expiry < fields.Datetime.now():
            self.active = False
            return False
        return True
