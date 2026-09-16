"""Controlled tenancy-inventory ontology used to stabilise item identity.

The ontology intentionally separates machine identity (`item_type`) from
human report prose (`name`/`description`). Split concepts only where confusing
them would materially change an inventory or comparison. Keep material,
colour, mounting and stylistic detail outside identity.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Optional

ONTOLOGY_VERSION = "tenancy-items-v1"

@dataclass(frozen=True)
class ItemType:
    key: str
    category: str
    label: str
    aliases: tuple[str, ...] = ()

# ~100 tenancy-relevant concepts. `other` is the explicit open-world escape.
_RAW = {
"structure": {
"ceiling":("Ceiling",()), "wall":("Wall",("walls",)), "flooring":("Flooring",("floor","floors","carpet flooring","laminate flooring","vinyl flooring")),
"skirting_board":("Skirting board",("skirting","skirting boards")), "cornice":("Cornice / coving",("cornice","coving")),
"door":("Door",("doors","patio door","balcony door")), "door_frame":("Door frame",("doorframe","door frames")),
"threshold":("Threshold strip",("threshold","threshold strip")), "window":("Window",("windows",)), "window_sill":("Window sill",("windowsill","window sills")),
"staircase":("Staircase",("stairs","stairway","stairwell")), "tile":("Tile / tiling",("tiles","tiling")), "splashback":("Splashback",("backsplash",)),
},
"fixture": {
"door_handle":("Door handle",("door handles","door furniture")), "door_lock":("Door lock",("lockset",)), "doorstop":("Doorstop",("door stop",)),
"banister":("Banister / balustrade",("balustrade",)), "handrail":("Handrail",("hand rail",)), "newel_post":("Newel post",("newel",)),
"worktop":("Worktop",("countertop","counter top","work surface")), "radiator":("Radiator",("radiators",)), "towel_rail":("Towel rail",("heated towel rail","towel radiator")),
"light":("Light fitting",("lamp","light fitting","ceiling light","spotlight","spotlights","pendant light")), "light_switch":("Light switch",("light switches",)),
"power_socket":("Power socket",("socket","sockets","power sockets","electrical socket")), "thermostat":("Thermostat",()), "intercom":("Entryphone / intercom",("entryphone","entry phone","intercom")),
"air_vent":("Air vent",("vent","extract vent")), "blind":("Blind",("blinds","roller blind","roller blinds")), "curtain_rail":("Curtain rail / pole",("curtain pole","curtain track")),
"built_in_cabinet":("Built-in cabinet",("kitchen unit","kitchen units","wall unit","base unit","fitted cupboard")), "shelf":("Shelf / shelving",("shelves","shelving")),
"basin":("Basin",("wash basin","washbasin","pedestal basin","bathroom sink")), "sink":("Sink",("kitchen sink","utility sink")), "tap":("Tap",("faucet","mixer tap","taps")),
"toilet":("Toilet / WC",("wc","lavatory")), "bathtub":("Bath",("bath","bathtub")), "bath_panel":("Bath panel",("bath side panel",)),
"shower":("Shower",("shower fitting","shower unit")), "shower_screen":("Shower screen / door",("shower door","shower screen")), "shower_tray":("Shower tray",()),
"toilet_roll_holder":("Toilet roll holder",("toilet paper holder",)),
},
"safety": {
"smoke_alarm":("Smoke alarm",("smoke detector","smoke heat alarm")), "heat_alarm":("Heat alarm",("heat detector",)), "co_alarm":("Carbon monoxide alarm",("co alarm","carbon monoxide detector")), "fire_extinguisher":("Fire extinguisher",()),
},
"meter": {
"fuse_box":("Fuse box / consumer unit",("consumer unit","fusebox")), "electricity_meter":("Electricity meter",("electric meter",)), "gas_meter":("Gas meter",()), "water_meter":("Water meter",()),
},
"appliance": {
"refrigerator":("Refrigerator",("fridge","fridge freezer","fridge-freezer")), "freezer":("Freezer",()), "oven":("Oven",("built in oven","built-in oven")),
"hob":("Hob",("stove","cooktop","induction hob","gas hob","ceramic hob")), "extractor_hood":("Extractor hood",("cooker hood","extractor fan","range hood")),
"microwave":("Microwave",()), "dishwasher":("Dishwasher",()), "washing_machine":("Washing machine",("washer",)), "tumble_dryer":("Tumble dryer",("dryer","clothes dryer")),
"washer_dryer":("Washer-dryer",("washer dryer",)), "kettle":("Kettle",()), "toaster":("Toaster",()), "coffee_machine":("Coffee machine",("coffee maker",)),
"vacuum_cleaner":("Vacuum cleaner",("vacuum","hoover")), "boiler":("Boiler",()),
},
"furniture": {
"sofa":("Sofa",("settee","couch")), "armchair":("Armchair",("easy chair",)), "chair":("Chair",("dining chair","dining chairs","office chair")),
"stool":("Stool",("bar stool","bar stools","bar chair","bar chairs")), "table":("Table",("dining table","coffee table","side table","console table")), "desk":("Desk",()),
"bed":("Bed / bed frame",("bed frame","bed base","divan")), "mattress":("Mattress",()), "bedside_table":("Bedside table",("bedside cabinet","nightstand","night stand")),
"wardrobe":("Wardrobe",()), "chest_of_drawers":("Chest of drawers",("drawer chest","drawers")), "bookcase":("Bookcase",("bookshelf","book shelf")),
"freestanding_cabinet":("Freestanding cabinet",("cabinet","cupboard","storage cabinet")), "tv_unit":("TV unit / media unit",("tv stand","media unit")), "shoe_rack":("Shoe rack / cabinet",("shoe cabinet",)),
},
"soft furnishing": {
"curtain":("Curtain",("curtains","drape","drapes")), "rug":("Rug",("floor rug",)), "cushion":("Cushion",("cushions","throw pillow")), "throw":("Throw / blanket",("blanket",)), "bedding":("Bedding / linen",("bed linen","linen")),
},
"decor": {
"mirror":("Mirror",()), "picture":("Picture / wall art",("painting","picture frame","wall art","canvas","canvas picture")), "clock":("Clock",()), "plant":("Plant / planter",("plant pot","potted plant")), "ornament":("Ornament / decorative object",("decorative object",)),
},
"electronics": {
"television":("Television",("tv",)), "monitor":("Monitor",("computer monitor",)), "computer":("Computer",("desktop computer","pc")), "laptop":("Laptop",()), "speaker":("Speaker",("speakers",)), "router":("Router / hub",("wifi router","wi-fi router","broadband hub")),
},
"kitchenware": {
"bin":("Waste bin",("waste bin","trash bin","rubbish bin")), "bread_bin":("Bread bin",("bread box",)), "draining_rack":("Draining rack",("dish rack",)), "cookware":("Cookware",("pots and pans","pans")), "crockery":("Crockery",("plates","bowls")), "cutlery":("Cutlery",()),
},
"other": {"bicycle":("Bicycle",("bike",)), "other":("Other inventory item",())},
}

ITEM_TYPES = tuple(ItemType(key, cat, label, tuple(aliases)) for cat, entries in _RAW.items() for key,(label,aliases) in entries.items())
ITEM_TYPE_BY_KEY = {x.key:x for x in ITEM_TYPES}
ITEM_TYPE_KEYS = tuple(ITEM_TYPE_BY_KEY)

def _norm(text:str)->str:
    text=text.lower().replace("&"," and ").replace("-"," ").replace("/"," ")
    text=re.sub(r"\bx\s*\d+\b"," ",text); text=re.sub(r"\([^)]*\)"," ",text)
    return " ".join(re.sub(r"[^a-z0-9 ]"," ",text).split())

_ALIAS_TO_KEY={}
for item in ITEM_TYPES:
    for form in (item.key.replace("_"," "),item.label,*item.aliases):
        n=_norm(form)
        if n and n not in _ALIAS_TO_KEY: _ALIAS_TO_KEY[n]=item.key

def canonicalize_name(name:str)->Optional[str]:
    """Conservative legacy-name mapper; abstains on ambiguous/unknown names."""
    n=_norm(name)
    if not n:return None
    if n in _ALIAS_TO_KEY:return _ALIAS_TO_KEY[n]
    padded=f" {n} "; candidates=[]
    for alias,key in _ALIAS_TO_KEY.items():
        if f" {alias} " in padded:candidates.append((len(alias.split()),key))
    if not candidates:return None
    longest=max(n for n,_ in candidates); keys={k for n,k in candidates if n==longest}
    return next(iter(keys)) if len(keys)==1 else None

def category_for(item_type:str)->str:
    return ITEM_TYPE_BY_KEY.get(item_type,ITEM_TYPE_BY_KEY["other"]).category

def label_for(item_type:str)->str:
    return ITEM_TYPE_BY_KEY.get(item_type,ITEM_TYPE_BY_KEY["other"]).label
