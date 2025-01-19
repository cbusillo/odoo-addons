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
    MotorProductTemplate = env["motor.product.template"]
    MotorDismantleResult = env["motor.dismantle.result"]

    results_to_set_true = MotorDismantleResult.search([("name", "not in", ["Missing", "Needs Cleaning"])])
    results_to_set_false = MotorDismantleResult.search([]) - results_to_set_true

    for result in results_to_set_false:
        result.write({"mark_for_repair": False})

    templates = MotorProductTemplate.search([])

    print(f"Found {len(templates)} templates and {len(results_to_set_true)} results to update")

    for template in templates:
        template.write({"repair_by_tech_results": [(6, 0, results_to_set_true.ids)]})

    print(f"Updated {len(templates)} templates with repair by tech results")
