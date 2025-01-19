from odoo import api, SUPERUSER_ID

from odoo.sql_db import Cursor
from odoo.upgrade import util


def migrate(cr: Cursor, version: str) -> None:
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    if not env:
        return

    util.rename_custom_column(cr, "motor_product_template_condition", "template", "excluded_template")
