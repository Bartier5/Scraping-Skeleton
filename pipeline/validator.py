# ── pipeline/validator.py ─────────────────────────────────────────────────────
# Data validator — the third and final pipeline stage.
#
# What does the validator do?
#   Takes transformed dicts and checks them against a Pydantic schema.
#   Any item that doesn't match the schema is either:
#   - Rejected entirely (strict mode)
#   - Flagged with errors and passed through (lenient mode)
#
# Pipeline position:
#   Parser → Cleaner → Transformer → [Validator] → Storage
#
# Why Pydantic?
#   Pydantic lets you define your expected data shape as a Python class.
#   It handles type coercion, required vs optional fields, value constraints,
#   and produces clear error messages when something doesn't match.
#   This catches bad scrapes BEFORE they corrupt your database.

from typing import Any, Optional, Type
from dataclasses import dataclass, field
from pydantic import BaseModel, ValidationError, ConfigDict
from utils.logger import log


# ── ValidationResult ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """
    Result of validating a single item against a schema.

    Fields:
        valid:    True if item passed validation
        item:     the validated item (may have type coercions applied by Pydantic)
        errors:   list of validation error messages if invalid
        original: the original item before validation
    """
    valid: bool
    item: dict
    errors: list[str] = field(default_factory=list)
    original: dict = field(default_factory=dict)

    def __str__(self) -> str:
        if self.valid:
            return f"ValidationResult[PASS] {list(self.item.keys())}"
        return f"ValidationResult[FAIL] {len(self.errors)} errors: {self.errors[:2]}"


@dataclass
class BatchValidationResult:
    """
    Result of validating a list of items.

    Fields:
        valid_items:    items that passed validation
        invalid_items:  items that failed with their errors
        total:          total items checked
        pass_rate:      percentage that passed (0.0-1.0)
    """
    valid_items: list[dict] = field(default_factory=list)
    invalid_items: list[ValidationResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.valid_items) + len(self.invalid_items)

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return len(self.valid_items) / self.total

    def __str__(self) -> str:
        return (
            f"BatchValidationResult: {len(self.valid_items)}/{self.total} valid "
            f"({self.pass_rate:.1%} pass rate)"
        )


# ── DataValidator ─────────────────────────────────────────────────────────────

class DataValidator:
    """
    Validates scraped items against a Pydantic schema.

    Usage:
        # Define your schema
        class BookSchema(BaseModel):
            title: str
            price: float
            url: str
            scraped_at: Optional[str] = None

        # Create validator
        validator = DataValidator(schema=BookSchema)

        # Validate items
        result = validator.validate_batch(transformed_items)
        storage.save(result.valid_items)
    """

    def __init__(
        self,
        schema: Type[BaseModel],
        strict: bool = False,
    ):
        """
        Args:
            schema: Pydantic model class defining the expected data shape
            strict: if True, invalid items are dropped entirely
                    if False (default), invalid items are flagged but passed through
        """
        self.schema = schema
        self.strict = strict
        log.debug(
            "DataValidator initialized (schema={}, strict={})",
            schema.__name__, strict
        )

    def validate_item(self, item: dict) -> ValidationResult:
        """
        Validates a single item against the schema.

        Pydantic's model_validate() attempts to parse the dict into the schema.
        It applies type coercions (e.g. "9.99" → 9.99 for a float field),
        checks required fields are present, and validates any constraints.

        Args:
            item: transformed dict to validate

        Returns:
            ValidationResult with valid=True or valid=False + error messages
        """
        try:
            # model_validate() parses the dict and applies type coercions
            validated = self.schema.model_validate(item)

            # model_dump() converts the Pydantic model back to a plain dict
            # This ensures the output is always a regular dict, not a Pydantic object
            return ValidationResult(
                valid=True,
                item=validated.model_dump(),
                original=item,
            )

        except ValidationError as e:
            # ValidationError contains detailed info about every field that failed
            # e.errors() returns a list of dicts with field, type, msg
            errors = [
                f"{err['loc'][0]}: {err['msg']}"
                for err in e.errors()
                if err.get("loc")
            ]

            log.debug(
                "DataValidator: item failed validation — {}",
                ", ".join(errors[:3])
            )

            return ValidationResult(
                valid=False,
                item=item,          # return original in lenient mode
                errors=errors,
                original=item,
            )

    def validate_batch(self, items: list[dict]) -> BatchValidationResult:
        """
        Validates a list of items and separates valid from invalid.

        In strict mode:  only valid items returned, invalid ones dropped
        In lenient mode: both valid and invalid tracked, caller decides what to do

        Args:
            items: list of transformed dicts

        Returns:
            BatchValidationResult with valid_items, invalid_items, pass_rate
        """
        if not items:
            return BatchValidationResult()

        result = BatchValidationResult()

        for item in items:
            validation = self.validate_item(item)

            if validation.valid:
                result.valid_items.append(validation.item)
            else:
                if not self.strict:
                    # Lenient mode — track the failure but include in valid_items
                    # with original data so nothing is silently lost
                    result.invalid_items.append(validation)
                else:
                    # Strict mode — drop invalid items entirely
                    result.invalid_items.append(validation)
                    log.warning(
                        "DataValidator [strict]: dropped item — {}",
                        validation.errors[:1]
                    )

        log.info(
            "DataValidator: {}/{} items valid ({:.1%} pass rate)",
            len(result.valid_items),
            result.total,
            result.pass_rate,
        )

        return result

    def get_schema_fields(self) -> dict:
        """
        Returns the schema's field definitions as a dict.
        Useful for debugging — shows what fields are expected and their types.
        """
        return {
            name: str(field_info.annotation)
            for name, field_info in self.schema.model_fields.items()
        }


# ── Built-in reusable schemas ─────────────────────────────────────────────────
# Ready-to-use Pydantic schemas for common scraping patterns.
# Import and use directly, or use as templates for your own schemas.

class BaseScrapedItem(BaseModel):
    """
    Minimal base schema — every scraped item should at least have a URL.
    Inherit from this to build your own schemas.
    """
    url: str
    scraped_at: Optional[str] = None

    class Config:
        # extra="ignore" means fields not in the schema are silently dropped
        # rather than causing a validation error
        model_config = ConfigDict(extra="ignore")


class BookSchema(BaseScrapedItem):
    """
    Schema for books.toscrape.com — used in Day 8 example.
    Shows how to define required vs optional fields and type constraints.
    """
    title: str
    price: Optional[float] = None       # float — Pydantic will coerce "9.99" → 9.99
    rating: Optional[str] = None        # "One", "Two", "Three", "Four", "Five"
    availability: Optional[str] = None  # "In stock", "Out of stock"
    scraped_at: Optional[str] = None

    class Config:
        model_config = ConfigDict(extra="ignore")


class QuoteSchema(BaseScrapedItem):
    """
    Schema for quotes.toscrape.com — used in Day 8 example.
    """
    text: str
    author: str
    tags: Optional[list[str]] = None
    scraped_at: Optional[str] = None

    class Config:
        model_config = ConfigDict(extra="ignore")


class ProductSchema(BaseScrapedItem):
    """
    Generic e-commerce product schema.
    A starting point for product scraping jobs.
    """
    name: str
    price: Optional[float] = None
    currency: Optional[str] = None
    sku: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    in_stock: Optional[bool] = None
    scraped_at: Optional[str] = None

    class Config:
        model_config = ConfigDict(extra="ignore")


class LeadSchema(BaseScrapedItem):
    """
    Business lead schema for lead generation scraping.
    """
    company_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    category: Optional[str] = None
    scraped_at: Optional[str] = None

    class Config:
        model_config = ConfigDict(extra="ignore")
