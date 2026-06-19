"""Static reference data for Uzbekistan regions (viloyat) and districts (tuman).

Each region carries an approximate WGS84 (EPSG:4326) bounding box
``(min_lon, min_lat, max_lon, max_lat)`` used to seed the grid generator when a
live WFS extent cannot be determined.  District lists are the practical
selectable values; the actual feature filtering happens server-side through a
CQL filter on the ``region`` / ``district`` attributes.

These values are a fallback. ``wfs_client.get_distinct_values`` can refresh the
district list dynamically from the live service when a session is available.
"""
from __future__ import annotations

from typing import Dict, List, TypedDict


class Region(TypedDict):
    name: str
    bbox_4326: List[float]  # [min_lon, min_lat, max_lon, max_lat]
    districts: List[str]


# Approximate bounding boxes are intentionally generous so the grid fully
# covers each region; empty cells simply return zero features.
REGIONS: Dict[str, Region] = {
    "Toshkent shahri": {
        "name": "Toshkent shahri",
        "bbox_4326": [69.10, 41.20, 69.45, 41.40],
        "districts": [
            "Bektemir", "Chilonzor", "Mirobod", "Mirzo Ulug'bek", "Olmazor",
            "Sergeli", "Shayxontohur", "Uchtepa", "Yakkasaroy", "Yashnobod",
            "Yunusobod", "Yangihayot",
        ],
    },
    "Toshkent viloyati": {
        "name": "Toshkent viloyati",
        "bbox_4326": [68.80, 40.45, 70.20, 41.75],
        "districts": [
            "Bekobod", "Bo'ka", "Bo'stonliq", "Chinoz", "Qibray", "Ohangaron",
            "Oqqo'rg'on", "Parkent", "Piskent", "Quyichirchiq", "O'rtachirchiq",
            "Yangiyo'l", "Yuqorichirchiq", "Zangiota", "Toshkent tumani",
        ],
    },
    "Andijon": {
        "name": "Andijon",
        "bbox_4326": [71.70, 40.40, 72.95, 41.05],
        "districts": [
            "Andijon shahri", "Andijon tumani", "Asaka", "Baliqchi", "Bo'z",
            "Buloqboshi", "Izboskan", "Jalaquduq", "Marhamat", "Oltinko'l",
            "Paxtaobod", "Qo'rg'ontepa", "Shahrixon", "Ulug'nor", "Xo'jaobod",
        ],
    },
    "Buxoro": {
        "name": "Buxoro",
        "bbox_4326": [62.00, 39.10, 65.50, 41.20],
        "districts": [
            "Buxoro shahri", "Buxoro tumani", "G'ijduvon", "Jondor", "Kogon",
            "Olot", "Peshku", "Qorako'l", "Qorovulbozor", "Romitan",
            "Shofirkon", "Vobkent",
        ],
    },
    "Farg'ona": {
        "name": "Farg'ona",
        "bbox_4326": [70.50, 39.90, 72.20, 41.05],
        "districts": [
            "Farg'ona shahri", "Farg'ona tumani", "Beshariq", "Bog'dod",
            "Buvayda", "Dang'ara", "Furqat", "Marg'ilon", "Oltiariq",
            "Qo'qon", "Qo'shtepa", "Quva", "Rishton", "So'x", "Toshloq",
            "Uchko'prik", "O'zbekiston tumani", "Yozyovon",
        ],
    },
    "Jizzax": {
        "name": "Jizzax",
        "bbox_4326": [66.60, 39.60, 68.80, 41.20],
        "districts": [
            "Jizzax shahri", "Arnasoy", "Baxmal", "Do'stlik", "Forish",
            "G'allaorol", "Mirzacho'l", "Paxtakor", "Yangiobod", "Zarbdor",
            "Zafarobod", "Zomin", "Sharof Rashidov",
        ],
    },
    "Xorazm": {
        "name": "Xorazm",
        "bbox_4326": [60.00, 40.90, 61.90, 42.10],
        "districts": [
            "Urganch shahri", "Urganch tumani", "Bog'ot", "Gurlan", "Xiva",
            "Xonqa", "Hazorasp", "Qo'shko'pir", "Shovot", "Yangiariq",
            "Yangibozor", "Tuproqqal'a",
        ],
    },
    "Namangan": {
        "name": "Namangan",
        "bbox_4326": [70.60, 40.55, 71.95, 41.55],
        "districts": [
            "Namangan shahri", "Namangan tumani", "Chortoq", "Chust",
            "Kosonsoy", "Mingbuloq", "Norin", "Pop", "To'raqo'rg'on",
            "Uchqo'rg'on", "Uychi", "Yangiqo'rg'on", "Davlatobod",
        ],
    },
    "Navoiy": {
        "name": "Navoiy",
        "bbox_4326": [62.50, 39.30, 66.50, 42.30],
        "districts": [
            "Navoiy shahri", "Zarafshon shahri", "Karmana", "Konimex",
            "Navbahor", "Nurota", "Qiziltepa", "Tomdi", "Uchquduq", "Xatirchi",
        ],
    },
    "Qashqadaryo": {
        "name": "Qashqadaryo",
        "bbox_4326": [63.80, 37.70, 67.20, 39.70],
        "districts": [
            "Qarshi shahri", "Qarshi tumani", "Chiroqchi", "Dehqonobod",
            "G'uzor", "Kasbi", "Kitob", "Koson", "Mirishkor", "Muborak",
            "Nishon", "Qamashi", "Shahrisabz shahri", "Shahrisabz tumani",
            "Yakkabog'", "Ko'kdala",
        ],
    },
    "Qoraqalpog'iston": {
        "name": "Qoraqalpog'iston",
        "bbox_4326": [55.90, 41.00, 61.50, 45.60],
        "districts": [
            "Nukus shahri", "Nukus tumani", "Amudaryo", "Beruniy", "Bo'zatov",
            "Chimboy", "Ellikqal'a", "Kegeyli", "Mo'ynoq", "Qanliko'l",
            "Qo'ng'irot", "Qorao'zak", "Shumanay", "Taxtako'pir", "To'rtko'l",
            "Xo'jayli",
        ],
    },
    "Samarqand": {
        "name": "Samarqand",
        "bbox_4326": [65.80, 39.10, 68.00, 40.40],
        "districts": [
            "Samarqand shahri", "Samarqand tumani", "Bulung'ur", "Ishtixon",
            "Jomboy", "Kattaqo'rg'on shahri", "Kattaqo'rg'on tumani", "Narpay",
            "Nurobod", "Oqdaryo", "Past darg'om", "Paxtachi", "Payariq",
            "Qo'shrabot", "Toyloq", "Urgut", "Tayloq",
        ],
    },
    "Sirdaryo": {
        "name": "Sirdaryo",
        "bbox_4326": [68.00, 40.00, 69.40, 40.90],
        "districts": [
            "Guliston shahri", "Guliston tumani", "Boyovut", "Mirzaobod",
            "Oqoltin", "Sardoba", "Sayxunobod", "Sirdaryo tumani",
            "Xovos", "Yangiyer", "Shirin",
        ],
    },
    "Surxondaryo": {
        "name": "Surxondaryo",
        "bbox_4326": [66.50, 37.10, 68.50, 38.80],
        "districts": [
            "Termiz shahri", "Termiz tumani", "Angor", "Bandixon", "Boysun",
            "Denov", "Jarqo'rg'on", "Qiziriq", "Qumqo'rg'on", "Muzrabot",
            "Oltinsoy", "Sariosiyo", "Sherobod", "Sho'rchi", "Uzun",
        ],
    },
}


def list_regions() -> List[str]:
    """Return region names sorted alphabetically (Uzbek-friendly)."""
    return sorted(REGIONS.keys())


def get_region(name: str) -> Region | None:
    return REGIONS.get(name)


def list_districts(region_name: str) -> List[str]:
    region = REGIONS.get(region_name)
    return list(region["districts"]) if region else []
