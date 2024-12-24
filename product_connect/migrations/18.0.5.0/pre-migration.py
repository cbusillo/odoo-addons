from odoo.sql_db import Cursor


def migrate(cr: Cursor, version) -> None:
    if not version:
        return

    # Rename field from dismantle_results to tech_result
    cr.execute(
        """
        ALTER TABLE product_template 
        RENAME COLUMN dismantle_results TO tech_result;
    """
    )
