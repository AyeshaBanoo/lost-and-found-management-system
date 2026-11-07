import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY= os.environ["SECRET_KEY"]
    DATABASE = os.path.join(BASE_DIR, "instance", "lostfound.sqlite")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB max upload

    # ---- AI Matching configuration (weights are configurable, not "scientific") ----
    MATCH_WEIGHTS = {
        "text": 0.35,
        "image": 0.40,
        "category": 0.10,
        "location": 0.10,
        "date": 0.05,
    }
    # Minimum overall score for a match to be stored/shown at all
    MATCH_STORE_THRESHOLD = 0.30
    # Minimum overall score that triggers a "potential match" notification
    MATCH_NOTIFY_THRESHOLD = 0.65

    CONFIDENCE_HIGH = 0.80
    CONFIDENCE_MEDIUM = 0.60

    # Categories where the app should redirect users to an official channel
    RESTRICTED_CATEGORIES = {
        "Mobile Phone": (
            "For lost or stolen mobile phones, please also report the loss to the "
            "police and use the Government of India's Sanchar Saathi / CEIR service "
            "(https://www.ceir.gov.in) to block the device using its IMEI number. "
            "This platform cannot block, track, or recover a phone by itself."
        ),
    }

    ITEM_CATEGORIES = [
        "Mobile Phone", "Laptop/Tablet", "Wallet/Purse", "Bag/Backpack",
        "Documents/ID Cards", "Jewellery", "Electronics/Earphones", "Keys",
        "Clothing", "Spectacles", "Watch", "Sports Equipment", "Pet",
        "Vehicle Accessory", "Other",
    ]
        # Categories where handover should go through an authority rather than
    # a casual public meetup, once a claim is approved.
    HIGH_VALUE_CATEGORIES = {
        "Mobile Phone", "Laptop/Tablet", "gold Jewellery", "Documents/ID Cards", "branded Watch",
    }
