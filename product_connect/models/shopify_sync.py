import base64
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Self
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import odoo
import requests
import shopify
from dateutil.parser import parse
from odoo import api, fields, models
from requests.exceptions import RequestException

shopify_original_execute_function = shopify.GraphQL.execute
MAX_RETRIES = 5
MIN_SHOPIFY_REMAINING_API_POINTS = 500
MIN_RETRY_DELAY = 5
MAX_RETRY_DELAY = 60
_logger = logging.getLogger(__name__)


class MemoryHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.logs: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.logs.append(self.format(record))


memory_handler = MemoryHandler()
logging.getLogger().addHandler(memory_handler)


def apply_rate_limit_patch_to_shopify_execute() -> None:
    class ThrottledError(Exception):
        pass

    def parse_and_raise_error(error_data: dict[str, Any]) -> None:
        error_code = error_data.get("extensions", {}).get("code")
        error_message = error_data.get("message", "Unknown error")
        if error_code == "THROTTLED":
            _logger.debug("Throttled by Shopify: %s", error_message)
            raise ThrottledError("Throttled by Shopify")
        else:
            _logger.error("Error from Shopify: %s", error_message)
            raise Exception("Error from Shopify")

    def delay_if_near_rate_limit(response_json: dict[str, Any]) -> None:
        throttle_status = response_json.get("extensions", {}).get("cost", {}).get("throttleStatus", {})
        currently_available = throttle_status.get("currentlyAvailable")
        restore_rate = throttle_status.get("restoreRate")

        if currently_available < MIN_SHOPIFY_REMAINING_API_POINTS:
            sleep_time = (MIN_SHOPIFY_REMAINING_API_POINTS - currently_available) / restore_rate
            time.sleep(sleep_time)

    def handle_and_retry_on_error(error: HTTPError, attempt: int) -> None:
        if isinstance(error, ThrottledError):
            retry_after = min(2**attempt, MAX_RETRY_DELAY)
        elif isinstance(error, HTTPError):
            retry_after = max(
                float(error.headers.get("Retry-After", 4)),
                min(attempt * 2, MAX_RETRY_DELAY),
            )
        else:
            raise RuntimeError(f"Unexpected error: {error}")

        _logger.debug("Exceeded Shopify API limit. Retrying in %s seconds", retry_after)
        time.sleep(retry_after)

    def rate_limited_execute(self, *args, **kwargs) -> str:
        for attempt in range(MAX_RETRIES):
            try:
                response = shopify_original_execute_function(self, *args, **kwargs)
                response_json = json.loads(response)

                if "errors" in response_json:
                    for error in response_json.get("errors", []):
                        parse_and_raise_error(error)

                delay_if_near_rate_limit(response_json)

                return response

            except HTTPError as error:
                handle_and_retry_on_error(error, attempt)
        raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")

    shopify.GraphQL.execute = rate_limited_execute


apply_rate_limit_patch_to_shopify_execute()

UTC = ZoneInfo("UTC")


def parse_to_utc(date_str: str) -> datetime:
    return parse(date_str).astimezone(UTC)


def current_utc_time() -> datetime:
    return datetime.now(UTC)


class ShopifySync(models.AbstractModel):
    _name = "shopify.sync"
    _description = "Shopify Sync"
    _inherit = "notification.manager.mixin"

    MAX_SHOPIFY_PRODUCTS_PER_FETCH = 250
    COMMIT_AFTER = 1000
    DEFAULT_DATETIME = datetime(2000, 1, 1, tzinfo=UTC)
    ONLINE_STORE_ID = 19453116480
    POINT_OF_SALE_ID = 42683596853
    GOOGLE_ID = 88268636213
    SHOP_ID = 99113467957

    session = requests.Session()

    def now_in_localtime_formatted(self) -> str:
        user_timezone = ZoneInfo(self.env.user.tz or "UTC")
        current_time = datetime.now(user_timezone)
        formatted_time = current_time.strftime("%Y-%m-%d %I:%M:%S %p")
        return formatted_time

    @api.model
    def sync_with_shopify(self) -> None:
        try:
            self.initialize_shopify_session()
            self.import_from_shopify()
            self.export_to_shopify()
        except Exception as error:
            self.notify_channel_on_error(
                "Shopify sync failed",
                str(error),
                logs=memory_handler.logs,
            )
            raise error

    @api.model
    def initialize_shopify_session(self) -> None:
        shop_url = self.env["ir.config_parameter"].sudo().get_param("shopify.shop_url")
        token = self.env["ir.config_parameter"].sudo().get_param("shopify.api_token")
        shopify_session = shopify.Session(f"{shop_url}.myshopify.com", token=token, version="2024-01")
        shopify.ShopifyResource.activate_session(shopify_session)

    def fetch_import_timestamps(self) -> tuple[str, datetime, datetime]:
        last_import_time_str = str(self.env["ir.config_parameter"].sudo().get_param("shopify.last_import_time"))
        current_import_start_time = current_utc_time()
        last_import_time = parse_to_utc(last_import_time_str)
        return last_import_time_str, current_import_start_time, last_import_time

    @staticmethod
    def extract_id_from_gid(gid: str) -> int:
        return int(gid.split("/")[-1])

    def fetch_shopify_product_edges(
        self,
        cursor: str | None,
        last_import_time_str: str,
        graphql_client: shopify.GraphQL,
        graphql_document: str,
        custom_query: str = "",
        operation_name: str = "GetProducts",
    ) -> list[dict[str, Any]]:
        result = self.execute_graphql_query(
            cursor,
            last_import_time_str,
            graphql_client,
            graphql_document,
            operation_name,
            custom_query,
        )
        shopify_response_data = self.parse_and_validate_shopify_response(result)
        return shopify_response_data.get("data", {}).get("products", {}).get("edges", [])

    def execute_graphql_query(
        self,
        cursor: str | None,
        time_filter: str,
        graphql_client: shopify.GraphQL,
        graphql_document: str,
        operation_name,
        custom_query=None,
    ) -> str:
        if not time_filter:
            time_filter = self.DEFAULT_DATETIME.isoformat(timespec="seconds")
        limit = (
            self.MAX_SHOPIFY_PRODUCTS_PER_FETCH
            if "Ids" not in operation_name
            else self.MAX_SHOPIFY_PRODUCTS_PER_FETCH * 10
        )

        base_query = f"updated_at:>{time_filter}"
        if custom_query:
            base_query = f" {custom_query}"

        match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", base_query)
        if not match:
            # noinspection SpellCheckingInspection
            raise ValueError(f"Invalid date format in query: '{base_query}'. Expected format: 'YYYY-MM-DDTHH:MM:SSZ'")
        _logger.debug("Executing GraphQL query: %s", base_query)
        # noinspection Annotator
        return graphql_client.execute(
            query=graphql_document,
            variables={
                "query": base_query,
                "cursor": cursor,
                "limit": limit,
            },
            operation_name=operation_name,
        )

    @staticmethod
    def extract_sku_bin_from_shopify_product(shopify_product: dict) -> tuple[str, str]:
        variant_edges = shopify_product.get("variants", {}).get("edges", [])
        if not variant_edges:
            _logger.warning("No variants found for product: %s", shopify_product["id"])
            return "", ""
        product_variant = variant_edges[0].get("node", {})
        sku_field = product_variant.get("sku", "") or ""

        sku_bin = [value.strip() if value else "" for value in sku_field.split(" - " if " - " in sku_field else " ", 1)]

        if len(sku_bin) == 0:
            _logger.warning(
                "Received unexpected SKU format from Shopify for product: %s",
                shopify_product["id"],
            )
            return "", ""

        sku = sku_bin[0]
        bin_location = sku_bin[1] if len(sku_bin) > 1 else ""
        return sku, bin_location

    def import_or_update_shopify_product(self, shopify_product: dict, last_import_time: datetime) -> str:
        shopify_updated_at = parse_to_utc(shopify_product.get("updatedAt", ""))
        shopify_sku, _ = self.extract_sku_bin_from_shopify_product(shopify_product)

        odoo_product_product = self.env["product.product"].search(
            [
                "|",
                ("shopify_product_id", "=", self.extract_id_from_gid(shopify_product["id"])),
                ("default_code", "=", shopify_sku),
                ("active", "in", [True, False]),
            ],
            limit=1,
        )
        status = "unchanged"
        try:
            if odoo_product_product:
                latest_write_date = self.determine_latest_product_modification_time(
                    odoo_product_product, last_import_time
                )
                if shopify_updated_at > latest_write_date:
                    status = self.create_or_update_odoo_product(shopify_product, existing_product=odoo_product_product)
            elif not odoo_product_product:
                status = self.create_or_update_odoo_product(shopify_product)
        except ValueError as error:
            self.notify_channel_on_error(
                "Import from Shopify failed",
                str(error),
                record=odoo_product_product,
                logs=memory_handler.logs,
            )
            raise error
        if status == "no_sku":
            self.notify_channel_on_error(
                f"Failed importing {shopify_product['title']} due to bad SKU in Shopify",
                str(self.extract_id_from_gid(shopify_product["id"])),
            )
        return status

    def determine_latest_product_modification_time(self, odoo_product_product, last_import_time) -> datetime:
        if last_import_time.year < 2001:  # set the import time to 2001 in Odoo to import all products
            return self.DEFAULT_DATETIME
        odoo_product_template = odoo_product_product.product_tmpl_id
        odoo_product_product_write_date = (
            odoo_product_product.write_date.replace(tzinfo=UTC) if odoo_product_product.write_date else None
        )
        odoo_product_template_write_date = (
            odoo_product_template.write_date.replace(tzinfo=UTC) if odoo_product_template.write_date else None
        )
        odoo_product_product_shopify_last_exported = (
            odoo_product_product.shopify_last_exported.replace(tzinfo=UTC)
            if odoo_product_product.shopify_last_exported
            else None
        )

        dates = [
            odoo_product_product_write_date,
            odoo_product_template_write_date,
            odoo_product_product_shopify_last_exported,
            self.DEFAULT_DATETIME,
        ]
        return max(filter(None, dates))

    def finalize_import_and_commit_changes(self, current_import_start_time: datetime) -> None:
        self.env.cr.commit()
        last_import_time = current_import_start_time.isoformat(timespec="seconds").replace("+00:00", "Z")
        self.env["ir.config_parameter"].sudo().set_param("shopify.last_import_time", last_import_time)
        self.env.cr.commit()

    @api.model
    def import_from_shopify(self) -> None:
        _logger.debug("Starting import from Shopify.")

        last_import_time_str, current_import_start_time, last_import_time = self.fetch_import_timestamps()
        graphql_client, graphql_document, _, _ = self.setup_sync_environment()

        updated_count, total_count, cursor, has_more_data = 0, 0, None, True
        while has_more_data:
            shopify_products = self.fetch_shopify_product_edges(
                cursor, last_import_time_str, graphql_client, graphql_document
            )

            for shopify_product_node in shopify_products:
                shopify_product = shopify_product_node.get("node", {})
                total_count += 1
                status = self.import_or_update_shopify_product(shopify_product, last_import_time)
                if status in ["created", "updated"]:
                    updated_count += 1
                _logger.debug(
                    "Imported %s products from Shopify so far. "
                    "Last product ID: %s has status: %s and was updated at %s start time: %s",
                    total_count,
                    self.extract_id_from_gid(shopify_product["id"]),
                    shopify_product.get("status"),
                    shopify_product.get("updatedAt"),
                    last_import_time_str,
                )
                if total_count % self.COMMIT_AFTER == 0:
                    self.env.cr.commit()

            if shopify_products:
                cursor = shopify_products[-1].get("cursor")
                has_more_data = bool(cursor)
            else:
                has_more_data = False

        self.finalize_import_and_commit_changes(current_import_start_time)
        message = (
            f"Shopify imported {updated_count} out of {total_count} items successfully at "
            f"{self.now_in_localtime_formatted()}"
        )
        self.notify_channel("Shopify sync", message, "shopify_sync")

    def parse_shopify_product_data(self, product) -> dict[str, Any]:
        product_variant = product.get("variants", {}).get("edges", [])[0].get("node", {})
        product_metafields = product.get("metafields", {}).get("edges", [])
        sku, bin_location = self.extract_sku_bin_from_shopify_product(product)
        quantity = int(product.get("totalInventory", 0))

        return {
            "id": self.extract_id_from_gid(product.get("id")),
            "variant_id": self.extract_id_from_gid(product_variant.get("id")),
            "sku": sku,
            "bin": bin_location,
            "qty_available": quantity,
            "metafields": product_metafields,
            "title": product.get("title") or "",
            "description_html": product.get("descriptionHtml") or "",
            "created_at": product.get("createdAt") or "",
            "price": float(product_variant.get("price") or 0.0),
            "cost": (
                float(product_variant.get("inventoryItem", {}).get("unitCost", {}).get("amount") or 0.0)
                if product_variant.get("inventoryItem", {}).get("unitCost")
                else 0.0
            ),
            "barcode": product_variant.get("barcode") or "",
            "weight": float(product_variant.get("weight") or 0.0),
            "status": product.get("status") or "",
            "vendor": product.get("vendor") or "",
            "part_type": product.get("productType") or "",
        }

    def map_shopify_to_odoo_product_data(
        self, shopify_product_data, odoo_product: "odoo.model.product_product"
    ) -> dict[str, Any]:
        metafields_data = shopify_product_data["metafields"]

        odoo_product_data: "odoo.values.product_product" = {
            "name": shopify_product_data["title"],
            "default_code": shopify_product_data["sku"],
            "website_description": shopify_product_data["description_html"],
            "shopify_product_id": shopify_product_data["id"],
            "shopify_variant_id": shopify_product_data["variant_id"],
            "shopify_created_at": parse_to_utc(shopify_product_data["created_at"])
            .replace(tzinfo=None)
            .strftime("%Y-%m-%d %H:%M:%S"),
            "barcode": "",
            "list_price": shopify_product_data["price"],
            "standard_price": shopify_product_data["cost"],
            "mpn": shopify_product_data["barcode"],
            "bin": shopify_product_data["bin"],
            "weight": shopify_product_data["weight"],
            "type": "consu",
            "is_storable": True,
            "manufacturer": (
                self.find_or_add_manufacturer(shopify_product_data["vendor"]).id
                if shopify_product_data["vendor"]
                else None
            ),
            "is_published": shopify_product_data["status"].lower() == "active",
            "is_ready_for_sale": True,
        }

        shopify_condition = ""
        for metafield_data in metafields_data:
            metafield = metafield_data.get("node", {})
            if metafield.get("key") == "condition":
                shopify_condition = metafield.get("value")
                odoo_product_data["shopify_condition_id"] = self.extract_id_from_gid(metafield.get("id"))
            if metafield.get("key") == "ebay_category_id":
                odoo_product_data["shopify_ebay_category_id"] = self.extract_id_from_gid(metafield.get("id"))
                part_type = self.find_or_add_part_type(
                    shopify_product_data["part_type"],
                    metafield.get("value"),
                )
                if part_type:
                    odoo_product_data["part_type"] = part_type.id

        if shopify_condition and (
            odoo_condition := self.env["product.condition"].search([("code", "=", shopify_condition)], limit=1)
        ):
            odoo_product_data["condition"] = odoo_condition.id
        elif odoo_product:
            odoo_product_data["condition"] = odoo_product.condition.code
        return odoo_product_data

    def import_product_images_from_shopify(self, shopify_product, odoo_product) -> None:
        odoo_product_template = self.env["product.template"].search(
            [("id", "=", odoo_product.product_tmpl_id.id)], limit=1
        )

        if not odoo_product_template.image_1920:
            shopify_image_edges = shopify_product.get("images", {}).get("edges", [])
            for index, shopify_image_edge in enumerate(shopify_image_edges):
                shopify_image = shopify_image_edge.get("node", {})
                self.fetch_and_store_product_image(index, shopify_image.get("url", ""), odoo_product_template)

    @staticmethod
    def update_product_stock_in_odoo(shopify_quantity: int, odoo_product) -> None:
        if shopify_quantity is not None:
            odoo_product.update_quantity(shopify_quantity)

    @api.model
    def create_or_update_odoo_product(self, shopify_product, existing_product=None) -> str:

        shopify_product_data = self.parse_shopify_product_data(shopify_product)

        sku_pattern = r"^\d{4,8}$"
        sku_value = shopify_product_data.get("sku", "")
        variant_edges = shopify_product.get("variants", {}).get("edges", [])

        if not re.match(sku_pattern, sku_value):
            return "no_sku"

        if not variant_edges or not variant_edges[0].get("node"):
            return "no_sku"

        odoo_product_data = self.map_shopify_to_odoo_product_data(shopify_product_data, existing_product)
        if existing_product:
            existing_product.write(odoo_product_data)
            status = "updated"
        else:
            existing_product = self.env["product.product"].create(odoo_product_data)
            status = "created"

        self.import_product_images_from_shopify(shopify_product, existing_product)
        self.update_product_stock_in_odoo(shopify_product_data["qty_available"], existing_product)
        return status

    @api.model
    def find_or_add_manufacturer(self, manufacturer_name: str):
        manufacturer = self.env["product.manufacturer"].search([("name", "=", manufacturer_name)], limit=1)

        if not manufacturer:
            manufacturer = self.env["product.manufacturer"].create({"name": manufacturer_name})

        return manufacturer

    @api.model
    def find_or_add_part_type(self, part_type_name: str, ebay_category_id: str) -> Self | None:
        try:
            if int(ebay_category_id) < 1 or not part_type_name:
                return None
        except ValueError:
            return None
        part_type = self.env["product.type"].search(
            [
                ("name", "=", part_type_name),
                ("ebay_category_id", "=", ebay_category_id),
            ],
            limit=1,
        )

        if not part_type:
            part_type = self.env["product.type"].create({"name": part_type_name, "ebay_category_id": ebay_category_id})

        return part_type

    @api.model
    def update_product_quantity_in_odoo(self, shopify_quantity, odoo_product) -> None:
        if shopify_quantity:
            odoo_product.update_quantity(shopify_quantity)

    @api.model
    def fetch_and_store_product_image(self, index, shopify_image_url, odoo_product_template) -> None:
        retries = 0
        while retries < MAX_RETRIES:
            try:
                response = self.session.get(shopify_image_url, timeout=10)
                response.raise_for_status()

                image_base64 = base64.b64encode(response.content)
                self.env["product.image"].create(
                    {
                        "product_tmpl_id": odoo_product_template.id,
                        "name": index,
                        "image_1920": image_base64,
                    }
                )
                return
            except RequestException as error:
                _logger.warning(
                    "Failed to fetch image from Shopify. Attempt %s/%s. Reason: %s",
                    retries + 1,
                    MAX_RETRIES,
                    error,
                )
                retries += 1
                time.sleep(MIN_RETRY_DELAY * (2**retries))

        _logger.error("Failed to fetch image from Shopify after %s attempts.", MAX_RETRIES)

    @staticmethod
    def convert_to_shopify_gid(resource_type, numeric_id) -> str:
        """Convert a numeric ID to Shopify GraphQL format."""
        return f"gid://shopify/{resource_type}/{numeric_id}"

    def fetch_first_store_location_id(self, graphql_client, graphql_document) -> str:
        """Retrieve Shopify location."""
        result = graphql_client.execute(query=graphql_document, operation_name="GetLocations")
        shopify_locations_dict = self.parse_and_validate_shopify_response(result)
        return shopify_locations_dict["data"]["locations"]["edges"][0]["node"]["id"]

    @staticmethod
    def prepare_odoo_product_image_data_for_export(base_url, odoo_product) -> list[dict[str, str]]:
        """Construct image data for each Odoo product."""
        media_list = []
        for odoo_image in sorted(
            odoo_product.product_tmpl_id.product_template_image_ids,
            key=lambda image: image.name,
        ):
            image_data = {
                "mediaContentType": "IMAGE",
                "alt": odoo_product.name,
                "originalSource": base_url + "/web/image/product.image/" + str(odoo_image.id) + "/image_1920",
            }
            media_list.append(image_data)
        return media_list

    @staticmethod
    def check_for_shopify_errors(result_dict) -> None:
        """Handle errors from the Shopify response."""
        top_level_errors = result_dict.get("errors", [])
        product_update_errors = result_dict.get("data", {}).get("productUpdate", {}).get("userErrors", [])
        product_create_errors = result_dict.get("data", {}).get("productCreate", {}).get("userErrors", [])

        errors = top_level_errors + product_update_errors + product_create_errors

        if errors:
            error_messages = []
            for error in errors:
                error_message = (
                    f"Error updating/creating product: "
                    f"(Message: {error.get('message')}) "
                    f"(Extension: {error.get('extensions')}) "
                    f"(Field: {error.get('field')})"
                )
                error_messages.append(error_message)
                _logger.error(error_message)
            raise ValueError(f"Shopify GraphQL Errors: {' | '.join(error_messages)}")

    def parse_and_validate_shopify_response(self, result: str) -> dict[str, Any]:
        """Process the result, log any errors, and return the parsed dictionary."""
        result_dict = json.loads(result)
        self.check_for_shopify_errors(result_dict)
        return result_dict

    def setup_sync_environment(self) -> tuple[shopify.GraphQL, str, str, str]:
        """Set up and return context objects necessary for Shopify synchronization."""
        graphql_client = shopify.GraphQL()
        graphql_query_path = Path(__file__).parent.parent / "graphql" / "shopify_product.graphql"
        graphql_document = graphql_query_path.read_text()
        shopify_location_gid = self.fetch_first_store_location_id(graphql_client, graphql_document)
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return graphql_client, graphql_document, shopify_location_gid, base_url

    @staticmethod
    def fetch_start_timestamp() -> datetime:
        current_export_start_time = current_utc_time()
        return current_export_start_time

    @api.model
    def export_to_shopify(self) -> None:
        _logger.debug("Starting export to Shopify...")

        odoo_products = self.env["product.product"].search(
            [
                ("sale_ok", "=", True),
                ("is_ready_for_sale", "=", True),
                ("website_description", "!=", False),
                ("website_description", "!=", ""),
            ]
        )

        odoo_products = odoo_products.filtered(
            lambda p: p.shopify_next_export is True
            or (
                p.write_date > (p.shopify_last_exported or datetime.min)
                or p.product_tmpl_id.write_date > (p.shopify_last_exported or datetime.min)
            )
        )

        graphql_client, graphql_document, shopify_location_gid, base_url = self.setup_sync_environment()
        total_count = 0
        for odoo_product in odoo_products:
            _logger.debug(f"Starting export of Odoo product ID: {odoo_product.default_code} - {odoo_product.name}")
            if odoo_product.bin:
                sku_field = f"{odoo_product.default_code} - {odoo_product.bin}"
            else:
                sku_field = odoo_product.default_code
            variant_data = {
                "price": odoo_product.list_price,
                "sku": sku_field,
                "barcode": odoo_product.mpn or "",
                "inventoryManagement": "SHOPIFY",
                "weight": odoo_product.weight,
                "inventoryItem": {
                    "cost": odoo_product.standard_price,
                },
            }
            if odoo_product.shopify_variant_id:
                variant_data["id"] = self.convert_to_shopify_gid("ProductVariant", odoo_product.shopify_variant_id)

            if not odoo_product.shopify_product_id:
                variant_data["inventoryQuantities"] = [
                    {
                        "availableQuantity": int(odoo_product.qty_available),
                        "locationId": shopify_location_gid,
                    }
                ]

            condition_metafield = {"value": odoo_product.condition.code or ""}
            if odoo_product.shopify_condition_id:
                condition_metafield["id"] = self.convert_to_shopify_gid("Metafield", odoo_product.shopify_condition_id)
            else:
                condition_metafield.update(
                    {
                        "key": "condition",
                        "type": "single_line_text_field",
                        "namespace": "custom",
                    }
                )

            ebay_category_id_metafield = {"value": str(odoo_product.part_type.ebay_category_id) or ""}
            if odoo_product.shopify_ebay_category_id:
                ebay_category_id_metafield["id"] = self.convert_to_shopify_gid(
                    "Metafield", odoo_product.shopify_ebay_category_id
                )
            else:
                ebay_category_id_metafield.update(
                    {
                        "key": "ebay_category_id",
                        "type": "number_integer",
                        "namespace": "custom",
                    }
                )

            try:
                shopify_product_data = {
                    "title": odoo_product.name,
                    "bodyHtml": odoo_product.website_description,
                    "vendor": (odoo_product.manufacturer.name if odoo_product.manufacturer else None),
                    "productType": (odoo_product.part_type.name if odoo_product.part_type else None),
                    "status": "ACTIVE" if odoo_product.qty_available > 0 else "DRAFT",
                    "variants": [variant_data],
                    "metafields": [condition_metafield, ebay_category_id_metafield],
                }

                if odoo_product.shopify_product_id:
                    shopify_product_data["id"] = self.convert_to_shopify_gid("Product", odoo_product.shopify_product_id)
                    result = graphql_client.execute(
                        query=graphql_document,
                        variables={"input": shopify_product_data},
                        operation_name="UpdateProduct",
                    )
                else:
                    result = graphql_client.execute(
                        query=graphql_document,
                        variables={"input": shopify_product_data},
                        operation_name="CreateProduct",
                    )
                    result_dict = self.parse_and_validate_shopify_response(result)
                    shopify_product_id = (
                        result_dict.get("data", {}).get("productCreate", {}).get("product", {}).get("id")
                    )
                    images = self.prepare_odoo_product_image_data_for_export(base_url, odoo_product)
                    try:
                        graphql_client.execute(
                            query=graphql_document,
                            variables={
                                "productId": shopify_product_id,
                                "media": images,
                            },
                            operation_name="createProductMedia",
                        )
                    except ValueError as error:
                        _logger.error("Failed to export images to Shopify: %s", error)
                        graphql_client.execute(
                            query=graphql_document,
                            variables={"input": {"id": shopify_product_id}},
                            operation_name="DeleteProduct",
                        )
                        raise error

                _logger.debug("Shopify export result: %s", shopify_product_data)
                result_dict = self.parse_and_validate_shopify_response(result)

            except ValueError as error:
                self.notify_channel_on_error(
                    "Export from Shopify failed",
                    f"{str(error)}",
                    record=odoo_product,
                    logs=memory_handler.logs,
                )
                raise error

            shopify_product = result_dict.get("data", {}).get("productUpdate", {}).get("product") or result_dict.get(
                "data", {}
            ).get("productCreate", {}).get("product")
            publications_data = {
                "id": shopify_product.get("id"),
                "input": [
                    {"publicationId": self.convert_to_shopify_gid("Publication", self.ONLINE_STORE_ID)},
                    {"publicationId": self.convert_to_shopify_gid("Publication", self.POINT_OF_SALE_ID)},
                    {"publicationId": self.convert_to_shopify_gid("Publication", self.GOOGLE_ID)},
                    {"publicationId": self.convert_to_shopify_gid("Publication", self.SHOP_ID)},
                ],
            }
            graphql_client.execute(
                query=graphql_document,
                variables=publications_data,
                operation_name="UpdatePublications",
            )

            shopify_metafields = shopify_product.get("metafields", {}).get("edges", [])
            shopify_ebay_category_id = ""
            shopify_condition_id = ""
            for metafield in shopify_metafields:
                if metafield.get("node", {}).get("key") == "condition":
                    shopify_condition_id = str(self.extract_id_from_gid(metafield.get("node", {}).get("id")))
                elif metafield.get("node", {}).get("key") == "ebay_category_id":
                    shopify_ebay_category_id = str(self.extract_id_from_gid(metafield.get("node", {}).get("id")))

            odoo_product.write(
                {
                    "shopify_last_exported": fields.Datetime.now(),
                    "shopify_product_id": self.extract_id_from_gid(shopify_product.get("id")),
                    "shopify_next_export": False,
                    "shopify_ebay_category_id": shopify_ebay_category_id,
                    "shopify_condition_id": shopify_condition_id,
                }
            )
            total_count += 1
            _logger.debug(
                "Exported %s of %s products from Shopify so far. "
                "Last product ID: %s has status: %s and was updated at %s",
                total_count,
                len(odoo_products),
                shopify_product_data.get("id") or odoo_product.id,
                shopify_product_data["status"],
                shopify_product.get("updatedAt"),
            )
            if total_count % self.COMMIT_AFTER == 0:
                self.env.cr.commit()
        message = f"Shopify exported {total_count} items successfully at {self.now_in_localtime_formatted()}"
        self.notify_channel("Shopify sync", message, "shopify_sync")
