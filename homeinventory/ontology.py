"""Canonical tenancy-inventory item ontology.

Machine identity is deliberately smaller and more stable than report prose.
`item_type` answers "what inventory concept is this?"; subtype and attributes
carry distinctions that should not create additions/removals by themselves.
Free-text `name`/`description` remain presentation and evidence detail.

This module is the single source of truth for canonical item labels and their
common aliases. Detector mappings can consume the same concepts without making
detector vocabulary the product ontology.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Optional

ONTOLOGY_VERSION = "tenancy-items-v1"


@dataclass(frozen=True)
class ItemType:
    key: str
    category: str
    label: str
    aliases: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()


# Granularity rule: split concepts when confusing them would materially change
# a tenancy inventory/comparison; otherwise retain the distinction as subtype
# or descriptive detail. `other` is an explicit open-world escape hatch.
ITEM_TYPES: tuple[ItemType, ...] = (
    # Structure / finishes
    ItemType("ceiling", "structure", "Ceiling"),
    ItemType("wall", "structure", "Wall", ("walls",)),
    ItemType("flooring", "structure", "Flooring", ("floor", "floors"), ("carpet", "laminate", "vinyl", "tile", "wood", "stone")),
    ItemType("skirting_board", "structure", "Skirting board", ("skirting", "skirting boards")),
    ItemType("cornice", "structure", "Cornice / coving", ("coving", "cornice")),
    ItemType("door", "structure", "Door", ("doors", "patio door", "balcony door"), ("internal", "external", "patio", "sliding")),
    ItemType("door_frame", "structure", "Door frame", ("doorframe", "door frames")),
    ItemType("door_handle", "fixture", "Door handle", ("door handles", "handle", "door furniture")),
    ItemType("door_lock", "fixture", "Door lock", ("lock", "lockset")),
    ItemType("doorstop", "fixture", "Doorstop", ("door stop",)),
    ItemType("threshold", "structure", "Threshold strip", ("threshold", "threshold strip")),
    ItemType("window", "structure", "Window", ("windows",)),
    ItemType("window_sill", "structure", "Window sill", ("windowsill", "window sills")),
    ItemType("staircase", "structure", "Staircase", ("stairs", "stairway", "stairwell")),
    ItemType("banister", "fixture", "Banister / balustrade", ("balustrade", "banister")),
    ItemType("handrail", "fixture", "Handrail", ("hand rail",)),
    ItemType("newel_post", "fixture", "Newel post", ("newel",)),
    ItemType("tile", "structure", "Tile / tiling", ("tiles", "tiling"), ("wall", "floor", "splashback")),
    ItemType("splashback", "structure", "Splashback", ("backsplash",)),
    ItemType("worktop", "fixture", "Worktop", ("countertop", "counter top", "work surface")),
    # Fixed fixtures / services
    ItemType("radiator", "fixture", "Radiator", ("radiators",)),
    ItemType("towel_rail", "fixture", "Towel rail", ("heated towel rail", "towel radiator"), ("heated", "unheated")),
    ItemType("light", "fixture", "Light fitting", ("lamp", "light fitting", "ceiling light", "spotlight", "spotlights", "pendant light"), ("ceiling", "pendant", "recessed", "wall", "floor", "table", "bedside")),
    ItemType("light_switch", "fixture", "Light switch", ("light switches", "switch")),
    ItemType("power_socket", "fixture", "Power socket", ("socket", "sockets", "power sockets", "electrical socket")),
    ItemType("thermostat", "fixture", "Thermostat"),
    ItemType("intercom", "fixture", "Entryphone / intercom", ("entryphone", "entry phone", "intercom")),
    ItemType("air_vent", "fixture", "Air vent", ("vent", "air vent", "extract vent")),
    ItemType("blind", "fixture", "Blind", ("blinds", "roller blind", "roller blinds"), ("roller", "venetian", "roman", "vertical")),
    ItemType("curtain_rail", "fixture", "Curtain rail / pole", ("curtain pole", "curtain rail", "curtain track")),
    ItemType("built_in_cabinet", "fixture", "Built-in cabinet", ("kitchen unit", "kitchen units", "wall unit", "base unit", "fitted cupboard")),
    ItemType("shelf", "fixture", "Shelf / shelving", ("shelves", "shelving")),
    # Safety / meters
    ItemType("smoke_alarm", "safety", "Smoke alarm", ("smoke detector", "smoke heat alarm")),
    ItemType("heat_alarm", "safety", "Heat alarm", ("heat detector",)),
    ItemType("co_alarm", "safety", "Carbon monoxide alarm", ("co alarm", "carbon monoxide detector")),
    ItemType("fire_extinguisher", "safety", "Fire extinguisher"),
    ItemType("fuse_box", "meter", "Fuse box / consumer unit", ("consumer unit", "fusebox")),
    ItemType("electricity_meter", "meter", "Electricity meter", ("electric meter",)),
    ItemType("gas_meter", "meter", "Gas meter"),
    ItemType("water_meter", "meter", "Water meter"),
    # Sanitary ware
    ItemType("basin", "fixture", "Basin", ("wash basin", "washbasin", "pedestal basin", "bathroom sink"), ("pedestal", "wall_hung", "countertop")),
    ItemType("sink", "fixture", "Sink", ("kitchen sink", "utility sink"), ("single_bowl", "one_and_half_bowl", "double_bowl")),
    ItemType("tap", "fixture", "Tap", ("faucet", "mixer tap", "taps"), ("mixer", "pillar", "shower")),
    ItemType("toilet", "fixture", "Toilet / WC", ("wc", "lavatory")),
    ItemType("bathtub", "fixture", "Bath", ("bath", "bathtub")),
    ItemType("bath_panel", "fixture", "Bath panel", ("bath side panel",)),
    ItemType("shower", "fixture", "Shower", ("shower fitting", "shower unit"), ("over_bath", "enclosure", "walk_in")),
    ItemType("shower_screen", "fixture", "Shower screen / door", ("shower door", "shower screen")),
    ItemType("shower_tray", "fixture", "Shower tray"),
    ItemType("toilet_roll_holder", "fixture", "Toilet roll holder", ("toilet paper holder",)),
    # Appliances
    ItemType("refrigerator", "appliance", "Refrigerator", ("fridge", "fridge freezer", "fridge-freezer"), ("fridge", "fridge_freezer", "american_style")),
    ItemType("freezer", "appliance", "Freezer"),
    ItemType("oven", "appliance", "Oven", ("built in oven", "built-in oven")),
    ItemType("hob", "appliance", "Hob", ("stove", "cooktop", "induction hob", "gas hob", "ceramic hob"), ("induction", "gas", "ceramic", "electric")),
    ItemType("extractor_hood", "appliance", "Extractor hood", ("cooker hood", "extractor fan", "range hood")),
    ItemType("microwave", "appliance", "Microwave"),
    ItemType("dishwasher", "appliance", "Dishwasher"),
    ItemType("washing_machine", "appliance", "Washing machine", ("washer",)),
    ItemType("tumble_dryer", "appliance", "Tumble dryer", ("dryer", "clothes dryer")),
    ItemType("washer_dryer", "appliance", "Washer-dryer", ("washer dryer",)),
    ItemType("kettle", "appliance", "Kettle"),
    ItemType("toaster", "appliance", "Toaster"),
    ItemType("coffee_machine", "appliance", "Coffee machine", ("coffee maker",)),
    ItemType("vacuum_cleaner", "appliance", "Vacuum cleaner", ("vacuum", "hoover")),
    ItemType("boiler", "appliance", "Boiler"),
    # Furniture
    ItemType("sofa", "furniture", "Sofa", ("settee", "couch"), ("two_seat", "three_seat", "corner", "sofa_bed")),
    ItemType("armchair", "furniture", "Armchair", ("easy chair",)),
    ItemType("chair", "furniture", "Chair", ("dining chair", "dining chairs", "office chair"), ("dining", "office", "accent")),
    ItemType("stool", "furniture", "Stool", ("bar stool", "bar stools", "bar chair", "bar chairs"), ("bar", "foot")),
    ItemType("table", "furniture", "Table", ("dining table", "coffee table", "side table", "console table"), ("dining", "coffee", "side", "console")),
    ItemType("desk", "furniture", "Desk"),
    ItemType("bed", "furniture", "Bed / bed frame", ("bed frame", "bed base", "divan"), ("single", "double", "king", "bunk")),
    ItemType("mattress", "furniture", "Mattress"),
    ItemType("bedside_table", "furniture", "Bedside table", ("bedside cabinet", "nightstand", "night stand")),
    ItemType("wardrobe", "furniture", "Wardrobe"),
    ItemType("chest_of_drawers", "furniture", "Chest of drawers", ("drawer chest", "drawers")),
    ItemType("bookcase", "furniture", "Bookcase", ("bookshelf", "book shelf")),
    ItemType("freestanding_cabinet", "furniture", "Freestanding cabinet", ("cabinet", "cupboard", "storage cabinet")),
    ItemType("tv_unit", "furniture", "TV unit / media unit", ("tv stand", "media unit")),
    ItemType("shoe_rack", "furniture", "Shoe rack / cabinet", ("shoe cabinet",)),
    # Soft furnishings / decor
    ItemType("curtain", "soft furnishing", "Curtain", ("curtains", "drape", "drapes")),
    ItemType("rug", "soft furnishing", "Rug", ("floor rug",)),
    ItemType("cushion", "soft furnishing", "Cushion", ("cushions", "throw pillow")),
    ItemType("throw", "soft furnishing", "Throw / blanket", ("blanket",)),
    ItemType("bedding", "soft furnishing", "Bedding / linen", ("bed linen", "linen")),
    ItemType("mirror", "decor", "Mirror"),
    ItemType("picture", "decor", "Picture / wall art", ("painting", "picture frame", "wall art", "canvas", "canvas picture")),
    ItemType("clock", "decor", "Clock"),
    ItemType("plant", "decor", "Plant / planter", ("plant pot", "potted plant")),
    ItemType("ornament", "decor", "Ornament / decorative object", ("ornament", "decorative object")),
    # Electronics
    ItemType("television", "electronics", "Television", ("tv",)),
    ItemType("monitor", "electronics", "Monitor", ("computer monitor",)),
    ItemType("computer", "electronics", "Computer", ("desktop computer", "pc")),
    ItemType("laptop", "electronics", "Laptop"),
    ItemType("speaker", "electronics", "Speaker", ("speakers",)),
    ItemType("router", "electronics", "Router / hub", ("wifi router", "wi-fi router", "broadband hub")),
    # Kitchenware / notable contents
    ItemType("bin", "kitchenware", "Waste bin", ("waste bin", "trash bin", "rubbish bin")),
    ItemType("bread_bin", "kitchenware", "Bread bin", ("bread box",)),
    ItemType("draining_rack", "kitchenware", "Draining rack", ("dish rack",)),
    ItemType("cookware", "kitchenware", "Cookware", ("pots and pans", "pans")),
    ItemType("crockery", "kitchenware", "Crockery", ("plates", "bowls")),
    ItemType("cutlery", "kitchenware", "Cutlery"),
    ItemType("bicycle", "other", "Bicycle", ("bike",)),
    ItemType("other", "other", "Other inventory item"),
)

ITEM_TYPE_BY_KEY = {item.key: item for item in ITEM_TYPES}
ITEM_TYPE_KEYS = tuple(ITEM_TYPE_BY_KEY)


def _norm(text: str) -> str:
    text = text.lower().replace("&", " and ").replace("-", " ").replace("/", " ")
    text = re.sub(r"\bx\s*\d+\b", " ", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())


def _forms(item: ItemType) -> tuple[str, ...]:
    return (item.key.replace("_", " "), item.label, *item.aliases)

# Exact aliases are intentionally one-to-one. Ambiguous generic words should
# be resolved by the structured model, not silently guessed here.
_ALIAS_TO_KEY: dict[str, str] = {}
for _item in ITEM_TYPES:
    for _form in _forms(_item):
        _n = _norm(_form)
        if _n and _n not in _ALIAS_TO_KEY:
            _ALIAS_TO_KEY[_n] = _item.key


def canonicalize_name(name: str) -> Optional[str]:
    """Return a safe canonical key for a known surface name.

    Exact aliases are preferred. Then accept a canonical phrase embedded in a
    more descriptive noun phrase (e.g. "white ceramic pedestal basin"). If
    multiple different keys tie for the longest phrase, abstain rather than
    manufacture correspondence. Unknowns remain unknown.
    """
    n = _norm(name)
    if not n:
        return None
    if n in _ALIAS_TO_KEY:
        return _ALIAS_TO_KEY[n]
    candidates: list[tuple[int, str]] = []
    padded = f" {n} "
    for alias, key in _ALIAS_TO_KEY.items():
        if f" {alias} " in padded:
            candidates.append((len(alias.split()), key))
    if not candidates:
        return None
    best_len = max(length for length, _ in candidates)
    keys = {key for length, key in candidates if length == best_len}
    return next(iter(keys)) if len(keys) == 1 else None


def category_for(item_type: str) -> str:
    return ITEM_TYPE_BY_KEY.get(item_type, ITEM_TYPE_BY_KEY["other"]).category


def label_for(item_type: str) -> str:
    return ITEM_TYPE_BY_KEY.get(item_type, ITEM_TYPE_BY_KEY["other"]).