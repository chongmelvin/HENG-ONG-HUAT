from enum import Enum


class Bucket(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class AssetGroup(str, Enum):
    FIXED = "fixed"
    VARIABLE = "variable"


class AccountType(str, Enum):
    CASH = "cash"
    BANK = "bank"
    EWALLET = "ewallet"
    CREDIT_CARD = "credit_card"
    BROKERAGE = "brokerage"
    VOUCHER = "voucher"


class Relationship(str, Enum):
    FRIEND = "friend"
    FAMILY = "family"


class ClaimStatus(str, Enum):
    UNCLAIMED = "unclaimed"
    SUBMITTED = "submitted"
    PAID = "paid"
    REJECTED = "rejected"


class HoldingType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"


class RewardType(str, Enum):
    MILES = "miles"
    CASHBACK = "cashback"
    POINTS = "points"


class Persona(str, Enum):
    OFF = "off"
    LIGHT = "light"
    SCOLD_OFF = "scold_off"


ACTIVE = "active"
ARCHIVED = "archived"
