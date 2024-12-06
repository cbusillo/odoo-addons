import logging

from odoo import api, SUPERUSER_ID
from odoo.api import Environment
from odoo.sql_db import Cursor
from odoo.upgrade import util
from psycopg2.extras import execute_values

_logger = logging.getLogger(__name__)


def execute_with_log(cr: Cursor, query: str, params: tuple | list | dict = None) -> list | None:
    try:
        if isinstance(params, (list, tuple)) and len(params) > 1000:
            execute_values(cr, query, params)
            return

        if params:
            cr.execute(query, params)
        else:
            cr.execute(query)
        return cr.fetchall() if query.strip().upper().startswith("SELECT") else None
    except Exception as e:
        _logger.error(f"Failed to execute query: {query}")
        _logger.error(f"Error: {str(e)}")
        raise


def clean_up_reference_relations(cr: Cursor) -> None:
    _logger.info("Cleaning up invalid references in motor_product_with_reference_product_rel")

    cr.execute(
        """
        SELECT DISTINCT mpr.product_id, count(*) as count
        FROM motor_product_with_reference_product_rel mpr
        LEFT JOIN product_template pt ON pt.id = mpr.product_id
        WHERE pt.id IS NULL
        GROUP BY mpr.product_id
    """
    )
    invalid_refs = cr.fetchall()

    if invalid_refs:
        _logger.warning(f"Found {len(invalid_refs)} invalid product references to clean up")
        for product_id, count in invalid_refs:
            _logger.info(f"Removing {count} invalid references for product_id: {product_id}")

        cr.execute(
            """
            DELETE FROM motor_product_with_reference_product_rel mpr
            WHERE NOT EXISTS (
                SELECT 1
                FROM product_template pt
                WHERE pt.id = mpr.product_id
            )
        """
        )
        cr.commit()
        _logger.info("Invalid references cleanup completed")
    else:
        _logger.info("No invalid references found")


def handle_module_data_references(cr: Cursor, model_name: str) -> None:
    _logger.info(f"Checking for module data references for {model_name}")

    cr.execute("SELECT count(*) FROM ir_model_data WHERE model = %s", (model_name,))
    model_data_count = cr.fetchone()[0]
    _logger.info(f"Found {model_data_count} ir.model.data records to process")

    if model_data_count > 0:
        cr.execute(
            """
            DELETE FROM ir_model_data
            WHERE model = %s
        """,
            (model_name,),
        )
        cr.commit()

    cr.execute(
        """
        SELECT COUNT(*) 
        FROM ir_model_fields 
        WHERE model = %s
    """,
        (model_name,),
    )
    field_count = cr.fetchone()[0]

    if field_count > 0:
        _logger.info(f"Found {field_count} fields to process")

        cr.execute(
            """
            UPDATE ir_model_fields 
            SET depends = NULL
            WHERE model = %s
        """,
            (model_name,),
        )
        cr.commit()

        cr.execute(
            """
            DELETE FROM ir_model_fields
            WHERE model = %s
        """,
            (model_name,),
        )
        cr.commit()

    cr.execute(
        """
        DELETE FROM ir_rule
        WHERE model_id IN (
            SELECT id FROM ir_model WHERE model = %s
        )
    """,
        (model_name,),
    )
    cr.commit()

    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE model = 'ir.model' AND name = %s
    """,
        (model_name.replace(".", "_"),),
    )
    cr.commit()

    cr.execute(
        """
        DELETE FROM ir_model
        WHERE model = %s
    """,
        (model_name,),
    )
    cr.commit()

    _logger.info(f"Finished handling module data references for {model_name}")


def prepare_database(cr: Cursor) -> None:
    _logger.info("Starting database preparation")

    cr.execute(
        """
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public'
    """
    )
    existing_tables = {row[0] for row in cr.fetchall()}

    tables_to_analyze = [
        "motor_product",
        "motor_product_image",
        "product_import",
        "product_import_image",
        "product_template",
        "ir_model",
        "ir_model_fields",
        "ir_model_data",
        "ir_attachment",
    ]

    for table in tables_to_analyze:
        if table in existing_tables:
            _logger.info(f"Analyzing table: {table}")
            cr.execute(f"ANALYZE {table}")
            cr.commit()
        else:
            _logger.info(f"Skipping analysis of non-existent table: {table}")

    cr.execute("CREATE INDEX IF NOT EXISTS ir_attachment_res_model_idx ON ir_attachment(res_model);")
    cr.commit()

    _logger.info("Database preparation completed")


def delete_attachments_in_batches(cr: Cursor, model_name: str, batch_size: int = 1000) -> None:
    _logger.info(f"Starting batched deletion of attachments for {model_name}")

    while True:
        cr.execute(
            """
            WITH batch AS (
                SELECT id 
                FROM ir_attachment 
                WHERE res_model = %s
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            DELETE FROM ir_attachment a
            USING batch
            WHERE a.id = batch.id
            RETURNING a.id
        """,
            (model_name, batch_size),
        )

        deleted_count = cr.rowcount
        _logger.info(f"Deleted {deleted_count} attachments for {model_name}")
        cr.commit()

        if deleted_count < batch_size:
            break


# noinspection SqlResolve
def migrate_data(cr: Cursor, env: Environment, source_table: str, target_table: str, batch_size: int = 1000) -> None:
    cr.execute(f"SELECT COUNT(*) FROM {source_table}")
    total_records = cr.fetchone()[0]

    _logger.info(f"Migrating {total_records} records from {source_table} to {target_table}")

    product_category = env.ref("product.product_category_all", raise_if_not_found=False)
    default_categ_id = product_category.id if product_category else 1
    uom_unit = env.ref("uom.product_uom_unit", raise_if_not_found=False)
    default_uom_id = uom_unit.id if uom_unit else 1

    for offset in range(0, total_records, batch_size):
        _logger.info(f"Processing batch {offset // batch_size + 1}/{(total_records + batch_size - 1) // batch_size}")

        if source_table == "motor_product":
            execute_with_log(
                cr,
                """
                WITH source AS (
                    SELECT 
                        default_code,
                        motor, mpn, manufacturer,
                        part_type, condition, length, width, height, bin, qty_available, 
                        list_price, name, website_description, active,
                        is_dismantled, is_dismantled_qc, is_cleaned, 
                        is_cleaned_qc, is_picture_taken, is_pictured,
                        is_pictured_qc, is_listable, dismantle_notes,
                        template, id as old_id
                    FROM motor_product
                    OFFSET %s
                    LIMIT %s
                ),
                upsert AS (
                    INSERT INTO product_template (
                        name, motor, default_code, mpn, manufacturer, part_type,
                        condition, length, width, height, bin, initial_quantity,
                        list_price, website_description, active,
                        is_dismantled, is_dismantled_qc, is_cleaned, is_cleaned_qc,
                        is_picture_taken, is_pictured, is_pictured_qc, is_listable,
                        dismantle_notes, motor_product_template, source,
                        base_unit_count, tracking, categ_id, detailed_type, 
                        sale_line_warn, uom_po_id, uom_id,
                        create_uid, create_date, write_uid, write_date
                    )
                    SELECT 
                        jsonb_build_object('en_US', s.name),
                        s.motor, s.default_code, s.mpn, s.manufacturer,
                        s.part_type, s.condition, s.length, s.width, s.height, 
                        s.bin, s.qty_available, s.list_price, 
                        jsonb_build_object('en_US', s.website_description), 
                        s.active, s.is_dismantled, s.is_dismantled_qc, s.is_cleaned, 
                        s.is_cleaned_qc, s.is_picture_taken, s.is_pictured,
                        s.is_pictured_qc, s.is_listable, s.dismantle_notes,
                        s.template, 'motor',
                        1.0, 'none', %s, 'product', 'no-message', %s, %s,
                        mp.create_uid, mp.create_date, mp.write_uid, mp.write_date
                    FROM source s
                    JOIN motor_product mp ON mp.id = s.old_id
                    ON CONFLICT (default_code) DO UPDATE SET
                        name = EXCLUDED.name,
                        motor = EXCLUDED.motor,
                        mpn = EXCLUDED.mpn,
                        manufacturer = EXCLUDED.manufacturer,
                        part_type = EXCLUDED.part_type,
                        condition = EXCLUDED.condition,
                        length = EXCLUDED.length,
                        width = EXCLUDED.width,
                        height = EXCLUDED.height,
                        bin = EXCLUDED.bin,
                        initial_quantity = EXCLUDED.initial_quantity,
                        list_price = EXCLUDED.list_price,
                        website_description = EXCLUDED.website_description,
                        active = EXCLUDED.active,
                        is_dismantled = EXCLUDED.is_dismantled,
                        is_dismantled_qc = EXCLUDED.is_dismantled_qc,
                        is_cleaned = EXCLUDED.is_cleaned,
                        is_cleaned_qc = EXCLUDED.is_cleaned_qc,
                        is_picture_taken = EXCLUDED.is_picture_taken,
                        is_pictured = EXCLUDED.is_pictured,
                        is_pictured_qc = EXCLUDED.is_pictured_qc,
                        is_listable = EXCLUDED.is_listable,
                        dismantle_notes = EXCLUDED.dismantle_notes,
                        motor_product_template = EXCLUDED.motor_product_template,
                        source = 'motor'
                    RETURNING id, default_code
                )
                INSERT INTO id_mapping (old_id, new_id, model)
                SELECT s.old_id, u.id, 'motor_product'
                FROM source s
                JOIN upsert u ON u.default_code = s.default_code
                """,
                (offset, batch_size, default_categ_id, default_uom_id, default_uom_id),
            )
        else:
            execute_with_log(
                cr,
                """
                WITH source AS (
                    SELECT 
                        default_code,
                        mpn, manufacturer, part_type,
                        condition, length, width, height, bin, qty_available, 
                        list_price, name, website_description, active,
                        id as old_id,
                        create_uid, create_date, write_uid, write_date
                    FROM product_import
                    OFFSET %s
                    LIMIT %s
                ),
                upsert AS (
                    INSERT INTO product_template (
                        name, default_code, mpn, manufacturer, part_type,
                        condition, length, width, height, bin, initial_quantity,
                        list_price, website_description, active, source,
                        base_unit_count, tracking, categ_id, detailed_type,
                        sale_line_warn, uom_po_id, uom_id,
                        create_uid, create_date, write_uid, write_date
                    )
                    SELECT 
                        jsonb_build_object('en_US', s.name),
                        s.default_code, s.mpn, s.manufacturer,
                        s.part_type, s.condition, s.length, s.width, s.height, 
                        s.bin, s.qty_available, s.list_price,
                        jsonb_build_object('en_US', s.website_description),
                        s.active, 'import',
                        1.0, 'none', %s, 'product', 'no-message', %s, %s,
                        s.create_uid, s.create_date, s.write_uid, s.write_date
                    FROM source s
                    ON CONFLICT (default_code) DO UPDATE SET
                        name = EXCLUDED.name,
                        mpn = EXCLUDED.mpn,
                        manufacturer = EXCLUDED.manufacturer,
                        part_type = EXCLUDED.part_type,
                        condition = EXCLUDED.condition,
                        length = EXCLUDED.length,
                        width = EXCLUDED.width,
                        height = EXCLUDED.height,
                        bin = EXCLUDED.bin,
                        initial_quantity = EXCLUDED.initial_quantity,
                        list_price = EXCLUDED.list_price,
                        website_description = EXCLUDED.website_description,
                        active = EXCLUDED.active,
                        source = 'import'
                    RETURNING id, default_code
                )
                INSERT INTO id_mapping (old_id, new_id, model)
                SELECT s.old_id, u.id, 'product_import'
                FROM source s
                JOIN upsert u ON u.default_code = s.default_code
                """,
                (offset, batch_size, default_categ_id, default_uom_id, default_uom_id),
            )

        cr.commit()

    _logger.info(f"Completed migration of {total_records} records from {source_table}")


def migrate(cr: Cursor, version: str) -> None:
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    batch_size = 1000

    try:
        _logger.info("Starting migration")

        prepare_database(cr)

        _logger.info("Dropping constraints...")
        cr.execute(
            """
            DO $$ 
            BEGIN
                -- Drop foreign key constraints on the relation table
                EXECUTE (
                    SELECT string_agg('ALTER TABLE ' || table_name || ' DROP CONSTRAINT ' || constraint_name || ';', ' ')
                    FROM information_schema.table_constraints 
                    WHERE table_name = 'motor_product_with_reference_product_rel'
                    AND constraint_type = 'FOREIGN KEY'
                );
            END $$;
        """
        )
        cr.commit()

        if not util.column_exists(cr, "product_template", "source"):
            cr.execute(
                """
                ALTER TABLE product_template 
                ADD COLUMN source varchar DEFAULT 'standard'
            """
            )

        motor_columns = [
            ("is_dismantled", "boolean DEFAULT false"),
            ("is_dismantled_qc", "boolean DEFAULT false"),
            ("is_cleaned", "boolean DEFAULT false"),
            ("is_cleaned_qc", "boolean DEFAULT false"),
            ("is_picture_taken", "boolean DEFAULT false"),
            ("is_pictured", "boolean DEFAULT false"),
            ("is_pictured_qc", "boolean DEFAULT false"),
            ("is_ready_to_list", "boolean DEFAULT false"),
            ("is_listable", "boolean DEFAULT false"),
            ("is_ready_for_sale", "boolean DEFAULT false"),
            ("dismantle_notes", "text"),
            ("motor_product_template", "integer"),
            ("initial_quantity", "numeric"),
            ("bin", "varchar"),
            ("motor", "integer"),
        ]

        for column, column_type in motor_columns:
            if not util.column_exists(cr, "product_template", column):
                cr.execute(
                    f"""
                    ALTER TABLE product_template 
                    ADD COLUMN {column} {column_type}
                """
                )

        # Create temporary mapping table
        cr.execute(
            """
            CREATE TEMP TABLE id_mapping (
                old_id integer,
                new_id integer,
                model varchar,
                new_product_id integer
            )
        """
        )

        migrate_data(cr, env, "motor_product", "product_template", batch_size)
        migrate_data(cr, env, "product_import", "product_template", batch_size)

        handle_module_data_references(cr, "motor.product")
        handle_module_data_references(cr, "product.import")

        clean_up_reference_relations(cr)

        _logger.info("Re-adding foreign key constraints")
        cr.execute(
            """
            ALTER TABLE motor_product_with_reference_product_rel
            ADD CONSTRAINT motor_product_with_reference_product_rel_product_id_fkey
            FOREIGN KEY (product_id) REFERENCES product_template(id) ON DELETE CASCADE;
        """
        )
        cr.commit()

        _logger.info("Cleaning up temporary tables and finalizing migration")
        cr.execute("DROP TABLE IF EXISTS id_mapping")

        for model in ["product.import.image", "motor.product.image"]:
            delete_attachments_in_batches(cr, model, batch_size)

        for table in ["motor_product_image", "motor_product", "product_import_image", "product_import"]:
            if util.table_exists(cr, table):
                cr.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

        prepare_database(cr)

        _logger.info("Migration completed successfully")

    except Exception as e:
        _logger.error(f"Migration failed: {str(e)}")
        _logger.error("Traceback:", exc_info=True)
        raise
