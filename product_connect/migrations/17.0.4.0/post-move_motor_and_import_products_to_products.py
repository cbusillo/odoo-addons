import logging

from odoo import api, SUPERUSER_ID
from odoo.api import Environment
from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)

_logger.info("Starting post-migration of products")


def migrate_messages(env: Environment, old_model: str, old_id: int, new_id: int):
    env.cr.execute(
        """
        UPDATE mail_message 
        SET model = 'product.template',
            res_id = %s
        WHERE model = %s 
        AND res_id = %s
        """,
        (new_id, old_model, old_id),
    )


def cleanup_old_data(cr: Cursor, env: Environment):
    _logger.info("Cleaning up old data")

    env["ir.attachment"].search(
        [("res_model", "in", ["motor.product", "product.import", "motor.product.image", "product.import.image"])]
    ).unlink()

    tables = [
        "motor_product_image",
        "motor_product",
        "product_import_image",
        "product_import",
        "motor_product_with_reference_product_rel",
    ]
    for table in tables:
        if util.table_exists(cr, table):
            cr.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    cr.execute(
        """
        DELETE FROM ir_model_fields WHERE model = 'motor.product';
        DELETE FROM ir_model WHERE model = 'motor.product';
        DELETE FROM ir_model_fields WHERE model = 'product.import';
        DELETE FROM ir_model WHERE model = 'product.import';
        
        DELETE FROM ir_model_data WHERE model = 'ir.model' AND name LIKE '%motor_product%';
        DELETE FROM ir_model_data WHERE model = 'ir.model.fields' AND name LIKE '%motor_product%';
        DELETE FROM ir_model_data WHERE model = 'ir.model' AND name LIKE '%product_import%';
        DELETE FROM ir_model_data WHERE model = 'ir.model.fields' AND name LIKE '%product_import%';
"""
    )


# noinspection SqlResolve
def migrate(cr: Cursor, version: str):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False, "tracking_disable": True})

    _logger.info("Starting post-migration of products")

    default_vals: "odoo.values.product_template" = {
        "is_ready_for_sale": False,
        "type": "consu",
    }

    try:
        ProductTemplate = env["product.template"]

        _logger.info("Migrating motor products")
        env.cr.execute(
            """
            SELECT 
                id, name, motor, default_code, mpn, manufacturer, part_type, condition, length,
                width, height, bin, qty_available, list_price, standard_price, website_description,
                is_dismantled, is_dismantled_qc, is_cleaned, is_cleaned_qc, is_picture_taken,
                is_pictured, is_pictured_qc, is_listable, dismantle_notes, template
            FROM motor_product
            """
        )
        motor_rows = env.cr.fetchall()

        for row in motor_rows:
            (
                old_id,
                name,
                motor,
                default_code,
                mpn,
                manufacturer,
                part_type,
                condition,
                length,
                width,
                height,
                bin_val,
                qty_available,
                list_price,
                standard_price,
                website_description,
                is_dismantled,
                is_dismantled_qc,
                is_cleaned,
                is_cleaned_qc,
                is_picture_taken,
                is_pictured,
                is_pictured_qc,
                is_listable,
                dismantle_notes,
                template_id,
            ) = row

            vals: "odoo.values.product_template" = {
                **default_vals,
                "name": name,
                "default_code": default_code,
                "mpn": mpn,
                "manufacturer": manufacturer,
                "part_type": part_type,
                "condition": condition,
                "length": length,
                "width": width,
                "height": height,
                "bin": bin_val,
                "initial_quantity": qty_available,
                "list_price": list_price,
                "standard_price": standard_price,
                "website_description": website_description,
                "motor": motor,
                "is_dismantled": is_dismantled,
                "is_dismantled_qc": is_dismantled_qc,
                "is_cleaned": is_cleaned,
                "is_cleaned_qc": is_cleaned_qc,
                "is_picture_taken": is_picture_taken,
                "is_pictured": is_pictured,
                "is_pictured_qc": is_pictured_qc,
                "is_listable": is_listable,
                "dismantle_notes": dismantle_notes,
                "motor_product_template": template_id,
                "source": "motor",
            }

            existing = ProductTemplate.search([("default_code", "=", default_code)], limit=1)
            if not existing:
                new_product = ProductTemplate.create(vals)
                migrate_messages(env, "motor.product", old_id, new_product.id)
            else:
                vals["is_ready_for_sale"] = True
                parent_class: type[ProductTemplate] = next(
                    cls for cls in ProductTemplate.__class__.mro() if cls.__name__ == "Model"
                )
                parent_class.write(existing, vals)
                migrate_messages(env, "motor.product", old_id, existing.id)

        _logger.info("Migrating import products")
        env.cr.execute(
            """

            SELECT
                id, name, default_code, mpn, manufacturer, part_type, condition, length,
                width, height, bin, qty_available, list_price, standard_price, website_description
            FROM product_import
            """
        )
        import_rows = env.cr.fetchall()

        for row in import_rows:
            (
                old_id,
                name,
                default_code,
                mpn,
                manufacturer,
                part_type,
                condition,
                length,
                width,
                height,
                bin_val,
                qty_available,
                list_price,
                standard_price,
                website_description,
            ) = row

            vals: "odoo.values.product_template" = {
                **default_vals,
                "name": name or "Unnamed",
                "default_code": default_code,
                "mpn": mpn,
                "manufacturer": manufacturer,
                "part_type": part_type,
                "condition": condition,
                "length": length,
                "width": width,
                "height": height,
                "bin": bin_val,
                "initial_quantity": qty_available,
                "list_price": list_price,
                "standard_price": standard_price,
                "website_description": website_description,
                "source": "import",
                "is_ready_to_list": True,
            }

            existing = ProductTemplate.search([("default_code", "=", default_code)], limit=1)
            if not existing:
                new_product = ProductTemplate.create(vals)
                migrate_messages(env, "product.import", old_id, new_product.id)
            else:
                vals["is_ready_for_sale"] = True
                existing.write(vals)
                migrate_messages(env, "product.import", old_id, existing.id)

        cleanup_old_data(cr, env)
        _logger.info("Post-migration completed successfully")

    except Exception as e:
        env.cr.rollback()
        _logger.error(f"Post-migration failed: {str(e)}")
        raise
