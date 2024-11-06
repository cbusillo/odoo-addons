from odoo import fields, models


class Users(models.Model):
    _name = "res.users"
    _inherit = "res.users"

    is_technician = fields.Boolean(default=True)
    folded_motor_stages = fields.Many2many("motor.stage", "motor_stage_user_rel", "user_id", "setting_id")

    def __str__(self) -> str:
        return self.name if self.name else ""
