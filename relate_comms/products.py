"""The product index — the vocabulary that lets a span be claimed as a Product.

WHY A DICTIONARY AT ALL
-----------------------
Recall for this kind is a dictionary problem, and the dictionary is the feature.

**Corrected 2026-11-23:** `en_core_web_sm` *does* have a `PRODUCT` label — the earlier note
in this repo said it did not, and that was wrong. What it has is a deeply unreliable one.
Measured on the sample corpus: of 77 known product names present in message bodies it
proposes no span at all for **23** — every lowercase spelling (`the excel renewal`,
`iphone`, `rtx`, `gguf`) and most capitalised but contextless names (`Temporal`,
`Grafana`, `Surface Pro`, `Pixel`, `Raspberry Pi`).

Its `PRODUCT` label is also **frame-sensitive**, exactly like the `GPE` false positives
already documented in `extract.py`: `"I've moved everything onto Ansible."` is labelled
`PRODUCT`, while `"Ansible keeps falling over."` proposes nothing. A label that fires on
one preposition and not another is not a taxonomy, it is a coincidence.

So the index is not compensating for an absent label — it is compensating for an
**unreliable** one, which is the same argument `PLACE_DICTIONARY` and `ORG_DICTIONARY`
rest on. There is no rule that reads `the excel renewal is due` and decides `Excel` is a
name without already knowing it.

But a dictionary alone is precision-hostile, which is the other half of the design:

WHAT THE INDEX IS NOT
---------------------
`canon.canonical(kind="product")` folds `Seat` and `seat` to the same key `seat`. That is
correct — it is a spelling function. It cannot know that one of those is a licence concept
and the other is furniture. **The generic block therefore lives here, not in `canon`.**

A case-insensitive dictionary match on `seat`, `contract`, `credits`, `rack`, `switch` would
manufacture a junk node for every ordinary sentence. Measured on the live store: ten of the
sample generator's 100 product names are common nouns, and they already exist as
`organization:sla`, `organization:seat`-shaped noise.

THE THREE TIERS
---------------
Each tier exists because a rule in `arbitrate()` consumes it. A field nothing reads would
be a field to maintain for no reason.

    Tier 1  blocked generics    never a standalone product   `seat`, `sla`, `credits`
    Tier 2  context-gated       a product only with a cue     `support plan`, `free tier`
    Tier 3  plain names         a product on sight            `grafana`, `raspberry pi`

**A vendor is not a product.** `Grafana Labs` was removed from the index on 2026-11-23:
the company ships `Grafana`, and listing both made `I'm at Grafana Labs all week` mint a
Product node for a premises. `Snowflake` and `Databricks` stay because the words *are* the
product — there is no separate product name — which is the same ambiguity §5 open decision 2
records.

WHERE ENTRIES COME FROM
-----------------------
Hand-typed, for now, deliberately. The fuzz generator's `PRODUCT_LISTS` is the seed because
it is the only labelled product vocabulary this repo has, and the tier assignment is a human
judgement a generator cannot make: nothing in a package registry says `Seat` is a bad node
and `Slack Connect` is a good one.

`TECHREADME.md` §5 records the intended generation sources (the live graph's
own mislabelled nodes, package registries, vendor catalogues) and why each was deferred:
registries bias hard toward a developer's vocabulary, and the live graph cannot seed a
correction until the corrections exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from .canon import canonical

# --------------------------------------------------------------------------- entries


@dataclass(frozen=True)
class ProductEntry:
    """One known product name, and how confident the index is about it.

    Deliberately small. `vendor`, `kind`, `source[]` and `version` all appeared in the
    design notes and all were dropped: nothing in the rule ladder reads them, and a field
    with no reader is a field that rots.
    """

    display: str
    key: str
    # A product only when the sentence is about procurement, deployment or licensing.
    requires_context: bool = False


def _entry(display: str, **kwargs) -> ProductEntry:
    """Build an entry whose key is `canon`'s, so the index and the store cannot disagree."""
    return ProductEntry(display=display, key=canonical(display, kind="product").key, **kwargs)


# Tier 1 — common nouns that are ALSO product names. Never a standalone Product node.
#
# Each of these appears in the sample generator's product list because a body says
# `can you get me a {product} seat?` — which is also exactly why `organization:seat` and
# `organization:sla` exist as junk in the live store. Blocking them here is the fix for
# that noise, and it must happen in the index because `canon` sees only a spelling.
GENERIC: frozenset[str] = frozenset({
    "seat", "contract", "credits", "credit", "sla", "rack", "switch", "san", "ups",
    "nas", "embeddings", "embedding", "support", "plan", "tier", "storage",
    # --- From `temp-lists` "CONSIDERED AND REJECTED" (2026-11-24) ---
    # Ordinary nouns that are also product names. `Teams`, `Cursor`, `Spark`, `Airflow`
    # and `Pixel` are deliberately absent: the drafted list rejects them, but the index
    # already carried them as tested plain entries, and a blocklist must not retroactively
    # delete a name the pipeline was validated on. Their multi-word forms still match.
    "beetle", "bike", "box", "brave", "contract", "copilot",
    "credit", "credits", "desk", "echo", "edge", "embedding",
    "embeddings", "escape", "explorer", "flight", "flights", "focus",
    "frame", "fusion", "golf", "grab", "hay", "home",
    "house", "hue", "linear", "medium", "nas", "nest",
    "numbers", "opera", "pages", "painting", "peacock", "pedigree",
    "plan", "polo", "rack", "ring", "san", "seat",
    "sentry", "shoes", "signal", "sketch", "sla", "speakers",
    "storage", "support", "switch", "tier", "ups", "watch",
})

# Tier 2 — a real product name that is also ordinary English. A Product only when the
# body is talking about buying, renewing, deploying or being licensed something.
_CONTEXT_GATED: tuple[str, ...] = (
    "Support Plan", "Enterprise Licence", "Free Tier", "Onboarding Pack",
    "Migration Kit", "Cold Storage", "Training Day", "Tape Library",
    # --- Curated list (2026-11-24) ---
    # The genuinely ambiguous middle: a real product name that is also ordinary English.
    # --- Software: productivity & everyday apps ---
    "Obsidian", "Notion", "Asana", "Confluence", "Slack", "Zoom", "Dropbox",
    "Telegram", "Hinge", "Bumble", "Calm", "Just Eat", "Blender", "Steam",
    "Safari", "Chrome",
    # --- Software: engineering & data ---
    "Savings Plan", "Reserved Instance", "Enterprise Agreement",
    "Premium Support",
)

# Tier 3 — names that are a product on sight. Multi-token entries are protected phrases
# by construction: `slack connect` cannot be confused with an ordinary sentence.
_PLAIN: tuple[str, ...] = (
    # SaaS and developer tooling
    "Databricks Lakehouse", "Snowflake Cortex", "Tableau", "Power BI", "Looker",
    "Excel", "Sheets", "Notion Calendar", "Slack Connect", "Teams", "Zoom Rooms",
    "Jira", "Confluence", "GitHub Copilot", "VS Code", "Cursor", "Vim", "Emacs",
    "Docker", "Kubernetes", "Terraform", "Ansible", "Prometheus", "Grafana",
    "Kafka", "Spark", "Airflow", "dbt Core", "Temporal", "Pulsar", "Flink", "Nginx",
    "Apache", "Redis Enterprise", "Elasticsearch", "OpenSearch", "Snowflake",
    "Databricks",
    # Hardware and SKUs
    "MacBook Pro", "ThinkPad", "Surface Pro", "Pixel", "iPhone", "Galaxy",
    "Raspberry Pi", "Jetson Orin", "DGX Station", "Threadripper", "Xeon", "EPYC",
    "Apple Silicon", "Radeon", "GeForce", "RTX", "Ryzen", "NVMe", "SSD", "RAID",
    "Router", "Patch Panel", "PDU",
    # AI models and runtimes
    "Claude", "GPT-4", "Llama", "Mistral Large", "Gemini", "Whisper",
    "Stable Diffusion", "Ollama", "vLLM", "gguf", "LoRA", "RAG",
    # Consumer brands — ordinary chat, and genuinely products
    "Coca-Cola", "Diet Coke", "Sprite", "Fanta", "Powerade", "Monster Energy",
    "Weetabix", "Marmite", "Irn-Bru", "Yorkshire Tea",
    # Commercial artefacts that name a specific SKU rather than a category
    "Migration Kit", "Enterprise Licence",
    # --- Curated list (2026-11-24) ---
    # Merged, not replaced: the entries above are the ones measured on the live store.
    # Multi-token entries are protected phrases by construction.
    #
    # --- Brand + generic noun (2026-11-24) ---
    # The sample generator names a product the way people actually write it — `North Face
    # jacket`, `Dyson vacuum`, `Levi 501` — while the index held only specific SKUs
    # (`The North Face Nuptse`, `Dyson V15`). 46 of its 184 products therefore had no
    # entry and produced no node. These are the branded forms; the bare generic nouns
    # (`beach house`, `Persian rug`, `4k television`) are deliberately NOT added, because
    # they name a category rather than a product and would mint a node per sentence.
    "Ford Escape", "Mercedes C-Class", "Land Cruiser", "Specialized Roubaix",
    "Sea-Doo", "Tiffany necklace", "Nike Jordans", "Doc Martens",
    "Barbour jacket", "Patagonia fleece", "North Face jacket", "Levi 501",
    "Hermes scarf", "Uniqlo down jacket", "Vitra Eames chair",
    "Le Creuset pan", "Dyson vacuum", "Nespresso machine",
    "KitchenAid mixer", "Sub-Zero fridge", "Tempur mattress",
    "Benjamin Moore paint", "Farrow and Ball paint", "Sony PlayStation",
    "Sonos speaker", "Bose headphones", "Nikon D850", "Fujifilm X100",
    "Honda generator", "Makita saw", "Glock 19", "Browning shotgun",
    "Yamaha piano", "Steinway grand", "Bovril", "Lucozade", "Walkers crisps",
    "Heinz beans", "Nando's sauce", "Green and Black's",
    # --- Cars (model names) ---
    "Toyota Highlander", "Toyota Corolla", "Toyota Hilux", "Toyota Land Cruiser",
    "Toyota Camry", "Toyota RAV4", "Toyota Prius", "Toyota Fortuner",
    "Honda Civic", "Honda Accord", "Honda CR-V", "Mazda CX-5", "Mazda MX-5",
    "Ford Mustang", "Ford Ranger", "Ford F-150", "Ford Transit",
    "Volkswagen Golf", "Volkswagen Polo", "Volkswagen Tiguan",
    "Volkswagen Passat", "BMW 3 Series", "BMW X5", "BMW M3",
    "Mercedes-Benz C-Class", "Mercedes E-Class", "Mercedes G-Wagon", "Audi A3",
    "Audi A4", "Audi Q5", "Tesla Model 3", "Tesla Model Y", "Tesla Model S",
    "Tesla Cybertruck", "Tesla Powerwall", "Tesla Supercharger", "Porsche 911",
    "Porsche Cayenne", "Porsche Macan", "Volvo XC60", "Volvo XC90",
    "Subaru Outback", "Subaru Forester", "Kia Sportage", "Hyundai Tucson",
    "Hyundai Kona", "Nissan Qashqai", "Nissan Leaf", "Nissan Navara",
    "Jeep Wrangler", "Jeep Grand Cherokee", "Land Rover Defender",
    "Range Rover Sport", "Range Rover Evoque", "Mini Cooper", "Fiat 500",
    "Renault Clio", "Peugeot 208", "Suzuki Swift", "Suzuki Jimny", "Isuzu D-Max",
    "Mitsubishi Pajero", "Mitsubishi Outlander", "Chevrolet Silverado",
    "Chevrolet Corvette", "Dodge Challenger", "Rivian R1T", "Polestar 2",
    "Lucid Air", "BYD Seal", "Alfa Romeo Giulia", "Lexus RX", "Jaguar F-Pace",
    "Maserati Ghibli", "Lamborghini Urus", "Ferrari Roma",
    # --- Bikes & motorbikes ---
    "Trek Domane", "Specialized Tarmac", "Cannondale Synapse", "Canyon Aeroad",
    "Pinarello Dogma", "Santa Cruz Hightower", "Brompton",
    "Harley-Davidson Sportster", "Ducati Monster", "Ducati Panigale",
    "Triumph Bonneville", "Royal Enfield Classic 350", "Vespa Primavera",
    "Yamaha MT-07", "Kawasaki Ninja", "BMW R 1250 GS", "Honda Africa Twin",
    "Wahoo Kickr", "Peloton Bike", "Zwift",
    # --- Watches & wearables ---
    "Rolex", "Rolex Submariner", "Rolex Datejust", "Rolex Daytona",
    "Omega Speedmaster", "Omega Seamaster", "Tudor Black Bay", "Seiko 5",
    "Casio G-Shock", "Casio F-91W", "Apple Watch", "Apple Watch Ultra",
    "Garmin Fenix", "Garmin Forerunner", "Garmin Edge", "Garmin inReach",
    "Patek Philippe Nautilus", "Audemars Piguet Royal Oak", "Cartier Santos",
    "Cartier Tank", "TAG Heuer Carrera", "Tissot PRX", "Breitling Navitimer",
    "Grand Seiko", "Longines Hydroconquest", "Timex Weekender", "Fitbit Charge",
    "Oura Ring", "Whoop",
    # --- Phones, computers, devices ---
    "iPhone 15 Pro", "iPhone 16 Pro", "iPhone 17 Pro", "Samsung Galaxy S24",
    "Samsung Galaxy S25", "Galaxy Z Fold", "Google Pixel 9", "Google Pixel 10",
    "OnePlus 12", "Nothing Phone", "MacBook Air", "iPad Pro", "iPad Air",
    "iPad Mini", "Mac Mini", "Mac Studio", "Apple Vision Pro", "AirPods Pro",
    "AirPods Max", "HomePod Mini", "Kindle Paperwhite", "Kindle Scribe",
    "Dell XPS 13", "ThinkPad X1 Carbon", "ThinkPad T14", "Surface Laptop",
    "Framework Laptop", "Razer Blade", "Asus ROG Zephyrus", "Sonos Arc",
    "Sonos Beam", "Sonos Era", "Bose QuietComfort", "Sony WH-1000XM5",
    "Sony WH-1000XM6", "Sennheiser Momentum", "Bang & Olufsen Beosound",
    "Marshall Stanmore", "JBL Flip", "Logitech MX Master", "Logitech MX Keys",
    "Keychron Q1", "Steam Deck", "Nintendo Switch", "Nintendo Switch 2",
    "PlayStation 5", "Xbox Series X", "Meta Quest 3", "Arduino Uno",
    "GoPro Hero", "DJI Mavic", "DJI Mini", "DJI Osmo", "Canon EOS R5",
    "Canon EOS R6", "Sony A7 IV", "Nikon Z6", "Fujifilm X100V", "Fujifilm X-T5",
    "Leica Q3", "Leica M11", "Ricoh GR III", "Samsung Frame TV", "LG OLED",
    "Philips Hue", "Ring Doorbell", "Google Nest", "Amazon Echo", "Echo Dot",
    "Chromecast", "Apple TV", "Roomba", "Dyson V15", "Dyson Airwrap",
    "Dyson Supersonic", "Theragun", "Eight Sleep Pod", "YubiKey",
    # --- Home, kitchen, furniture ---
    "Nespresso Vertuo", "Breville Barista Express", "De'Longhi Magnifica",
    "La Marzocco Linea Mini", "Rancilio Silvia", "Baratza Encore",
    "Fellow Stagg", "AeroPress", "Chemex", "Hario V60", "Moccamaster", "Vitamix",
    "KitchenAid Stand Mixer", "Le Creuset Dutch Oven", "Staub Cocotte",
    "Instant Pot", "Ninja Foodi", "Thermomix", "Weber Kettle", "Weber Genesis",
    "Traeger Pellet Grill", "Big Green Egg", "Kamado Joe", "Ooni Koda", "Smeg",
    "Miele", "Yeti Tumbler", "Stanley Quencher", "Hydro Flask", "Nalgene",
    "IKEA Billy", "IKEA Kallax", "IKEA Malm", "IKEA Poäng", "IKEA Ektorp",
    "IKEA Pax", "IKEA Hemnes", "IKEA Besta", "Herman Miller Aeron",
    "Herman Miller Embody", "Steelcase Gesture", "Eames Lounge Chair",
    "Flos Arco", "Anglepoise Type 75", "Artemide Tolomeo", "Casper Mattress",
    "Emma Mattress", "Sealy Posturepedic", "Victron MultiPlus", "Sunsynk",
    "Enphase",
    # --- Clothing, footwear, bags, eyewear ---
    "Nike Air Max", "Nike Air Force 1", "Nike Pegasus", "Nike Dunk",
    "Air Jordan 1", "Adidas Samba", "Adidas Ultraboost", "Adidas Stan Smith",
    "Adidas Gazelle", "New Balance 990", "New Balance 574",
    "New Balance Fresh Foam", "Asics Gel-Kayano", "Asics Gel-Nimbus",
    "Hoka Clifton", "Hoka Bondi", "On Cloudmonster", "Brooks Ghost",
    "Saucony Endorphin", "Salomon Speedcross", "Converse Chuck Taylor",
    "Vans Old Skool", "Dr. Martens 1460", "Birkenstock Arizona",
    "Birkenstock Boston", "Crocs Classic Clog", "Ugg Tasman",
    "Allbirds Wool Runners", "Common Projects Achilles", "Veja V-10",
    "Patagonia Better Sweater", "Patagonia Nano Puff", "The North Face Nuptse",
    "Arc'teryx Beta", "Canada Goose Expedition Parka", "Moncler Maya",
    "Barbour Wax Jacket", "Levi's 501", "Levi's 511", "Uniqlo Heattech",
    "Lululemon Align", "Ray-Ban Wayfarer", "Ray-Ban Aviator", "Oakley Holbrook",
    "Herschel Little America", "Longchamp Le Pliage", "Louis Vuitton Neverfull",
    "Hermès Birkin", "Chanel Classic Flap", "Gucci Marmont",
    "Goyard Saint Louis", "Fjällräven Kånken", "Osprey Atmos",
    "Peak Design Everyday Backpack", "Rimowa Essential", "Tumi Alpha",
    "Samsonite", "Carhartt Detroit Jacket", "Gymshark", "Rapha Classic Jersey",
    # --- Music & audio gear ---
    "Fender Stratocaster", "Fender Telecaster", "Gibson Les Paul", "Martin D-28",
    "Taylor 314ce", "Yamaha P-125", "Roland Juno", "Moog Minimoog",
    "Korg Minilogue", "Elektron Digitakt", "Shure SM58", "Rode NT1",
    "Focusrite Scarlett", "Audio-Technica ATH-M50x", "Technics SL-1200",
    "Rega Planar 3", "KEF LS50", "Ableton Live", "Logic Pro", "Pro Tools",
    "Final Cut Pro", "DaVinci Resolve",
    # --- Tools & sports gear ---
    "DeWalt Drill", "Makita Impact Driver", "Milwaukee M18",
    "Bosch Professional", "Leatherman Wave", "Wilson Pro Staff",
    "Babolat Pure Drive", "Titleist Pro V1", "Callaway Rogue",
    "TaylorMade Stealth",
    # --- Software: productivity & everyday apps ---
    "Microsoft Teams", "Microsoft Excel", "Microsoft Word", "Microsoft Outlook",
    "Microsoft Office", "Microsoft 365", "Google Workspace", "Google Docs",
    "Google Sheets", "Google Drive", "Google Maps", "Google Calendar",
    "Google Translate", "Google Flights", "Gmail", "iCloud", "Apple Music",
    "Apple Pay", "Google Pay", "Apple Maps", "Evernote", "Todoist", "Trello",
    "Figma", "Canva", "Miro", "WhatsApp", "Instagram", "TikTok", "Snapchat",
    "Pinterest", "LinkedIn", "Reddit", "Twitch", "Discord", "Substack", "Tinder",
    "Duolingo", "Grammarly", "DeepL", "Zotero", "Overleaf", "Strava",
    "MyFitnessPal", "Headspace", "Komoot", "AllTrails", "Citymapper", "Waze",
    "Trainline", "Skyscanner App", "Booking.com", "Uber Eats", "Deliveroo",
    "M-Pesa", "Cash App", "Venmo", "Zelle", "Revolut Metal", "Robinhood",
    "Trading 212", "Ledger Nano", "1Password", "Bitwarden", "LastPass",
    "Dashlane", "NordVPN", "ExpressVPN", "ProtonMail", "Proton VPN", "Tailscale",
    "WireGuard", "Adobe Photoshop", "Adobe Illustrator", "Adobe Premiere Pro",
    "Adobe Lightroom", "Adobe Acrobat", "AutoCAD", "SolidWorks", "Fusion 360",
    "Unreal Engine", "Firefox",
    # --- Software: engineering & data ---
    "Visual Studio Code", "IntelliJ IDEA", "PyCharm", "WebStorm", "Xcode",
    "Android Studio", "Jenkins", "ChatGPT", "Claude Code", "Midjourney", "Redis",
    "PostgreSQL", "Postgres", "MySQL", "dbt", "PagerDuty", "Splunk", "New Relic",
    "Vercel", "Netlify", "Heroku", "Supabase", "Firebase", "Cloudflare Workers",
    "AWS Lambda", "Amazon S3", "Amazon EC2", "Azure DevOps",
    "Google Cloud Platform", "BigQuery", "Homebrew", "Microsoft Dynamics 365",
    "SAP HANA", "Oracle Cloud",
    # --- Games & streaming ---
    "Roblox", "Minecraft", "Fortnite", "Call of Duty", "EA Sports FC",
    "Mario Kart", "Super Mario", "Animal Crossing", "The Legend of Zelda",
    "Pokémon Go", "Candy Crush", "Wordle", "Elden Ring", "Baldur's Gate 3",
    "Cyberpunk 2077", "Stardew Valley", "Civilization VI", "Football Manager",
    "Rocket League", "League of Legends", "World of Warcraft", "Counter-Strike",
    "Disney Plus", "Prime Video", "Amazon Prime", "HBO Max", "Apple TV Plus",
    "Paramount Plus", "Hulu", "Crunchyroll", "YouTube Premium",
    "Spotify Premium", "Audible", "Kindle Unlimited", "DStv Premium", "Showmax",
    "Sky Sports",
    # --- Food, drink, spirits ---
    "Johnnie Walker Blue Label", "Johnnie Walker Black Label", "Glenfiddich 12",
    "Glenlivet", "Macallan 18", "Lagavulin 16", "Laphroaig 10", "Ardbeg",
    "Talisker", "Jameson Irish Whiskey", "Jack Daniel's", "Jim Beam",
    "Maker's Mark", "Woodford Reserve", "Buffalo Trace", "Hennessy VS",
    "Hennessy XO", "Rémy Martin", "Grey Goose", "Belvedere Vodka",
    "Absolut Vodka", "Smirnoff", "Tanqueray", "Hendrick's Gin",
    "Bombay Sapphire", "Beefeater", "Aperol", "Campari", "Jägermeister",
    "Baileys", "Amarula", "Don Julio", "Patrón Silver", "Casamigos",
    "Havana Club", "Bacardi", "Captain Morgan", "Dom Pérignon", "Moët & Chandon",
    "Veuve Clicquot", "Guinness", "Corona Extra", "Stella Artois", "Peroni",
    "Castle Lager", "Windhoek Lager", "Tusker", "Red Bull", "Coca-Cola Zero",
    "Dr Pepper", "Nespresso", "Illy", "Lavazza", "Oatly", "Impossible Burger",
    "Beyond Meat", "Huel", "Pringles", "Doritos", "Oreo", "Kit Kat", "Nutella",
    "Vegemite", "Cadbury Dairy Milk", "Toblerone", "Haribo", "Ferrero Rocher",
    "Tim Tam",
    # --- Pets, kids, health, travel & loyalty ---
    "Royal Canin", "Hill's Science Diet", "Purina Pro Plan", "Whiskas", "Orijen",
    "Acana", "Kong Classic", "LEGO Technic", "LEGO Star Wars", "Playmobil",
    "Hot Wheels", "Bugaboo Fox", "Stokke Tripp Trapp", "Maxi-Cosi Pebble",
    "UPPAbaby Vista", "Cybex Sirona", "Ozempic", "Wegovy", "Mounjaro", "Panadol",
    "Nurofen", "Advil", "Tylenol", "Calpol", "Zyrtec", "Claritin", "Invisalign",
    "Withings Body", "Eurostar", "Eurail Pass", "Interrail Pass", "Gautrain",
    "Oyster Card", "Priority Pass", "TSA PreCheck", "Global Entry",
    "Amex Platinum", "Chase Sapphire Reserve", "Chase Sapphire Preferred",
    "Delta SkyMiles", "Marriott Bonvoy", "Hilton Honors", "World of Hyatt",
    "Club Med", "Center Parcs", "Contiki", "Intrepid Travel",
)

def _build(
    plain: tuple[str, ...], gated: tuple[str, ...],
) -> dict[str, ProductEntry]:
    """Assemble the index, dropping anything that a harder tier already owns.

    Precedence is **generic > context-gated > plain**, so a name cannot be listed twice
    and a plain entry can never shadow a gated one. Listing `Migration Kit` in both
    tuples is therefore harmless, which is why it is (it reads as a SKU and as a
    generic pack).
    """
    index: dict[str, ProductEntry] = {}
    for name in gated:
        entry = _entry(name, requires_context=True)
        if entry.key not in GENERIC:
            index[entry.key] = entry
    for name in plain:
        entry = _entry(name)
        if entry.key not in GENERIC and entry.key not in index:
            index[entry.key] = entry
    return index


INDEX: dict[str, ProductEntry] = _build(_PLAIN, _CONTEXT_GATED)

# Words that make a body about procurement, deployment or licensing rather than chat.
#
# **`seat` and `contract` are deliberately absent**, though both are obvious procurement
# words in a real conversation. They are also furniture and an agreement, so a body
# containing `a seat by the window` would otherwise satisfy the cue test and promote
# every context-gated entry in it. A cue has to be a word that is *only* commercial.
CONTEXT_CUES: frozenset[str] = frozenset({
    "renewal", "renew", "renewed", "licence", "license", "licensed", "quote",
    "pricing", "subscription", "subscribe", "deployment", "deployed", "deploy",
    "instance", "sku", "purchase", "purchased", "bought", "upgrade", "upgraded",
    "migration", "migrated", "trial", "invoice", "invoiced", "billing", "billed",
    "install", "installed", "provision", "provisioned", "vendor", "onboarding",
    "expiry", "expires", "expiring",
})


# ------------------------------------------------------------------------- the ladder


def lookup(text: str) -> ProductEntry | None:
    """The index entry for a span's canonical form, or None. Exact key, never fuzzy.

    A typo'd product name is not folded here on purpose: `Northwnd` and `Northwind` are
    different strings, and a fuzzy product match would let one mistyping mint a second
    node against a dictionary the user never chose. The sample writer's `drop_letter` and
    `swap` variants are documented as producing a second key for exactly this reason.
    """
    return INDEX.get(canonical(text, kind="product").key)


def has_context(body: str) -> bool:
    """Does this text read like procurement, deployment or licensing?

    Word-bounded, case-folded, and deliberately shallow: the cue set is small and boring
    because it is a tie-break, not a classifier. `A seat by the window` has no cue and
    stays furniture; `can you get me a Xeon seat?` does and does not.
    """
    words = set(canonical(body, kind="product").key.split())
    return bool(words & CONTEXT_CUES)


def is_generic(text: str) -> bool:
    return canonical(text, kind="product").key in GENERIC


def decide(text: str, body: str) -> tuple[bool, str]:
    """Is this span a Product in this body? Returns `(verdict, reason)`.

    **The rule ladder, in order, first match wins. No weights.** Most of these decisions
    are categorical, not smoothly tradeable: `seat` is furniture or it is a SKU, and there
    is no score that expresses "blocked unless protected" better than a rule saying so.

        1  not in the index and not generic -> no   (`Retool`, a stranger)
        2  generic, anywhere               -> no   (`seat`)
        3  plain name                      -> yes  (`grafana`, `docker`)
        4  context-gated                   -> yes iff the body is a product sentence
        5  otherwise                        -> no

    **Generics are checked BEFORE the index.** `seat` is in `GENERIC` and deliberately not
    in `INDEX`, so an index-first ladder reported the true verdict for a false reason
    ("not indexed" when the reason is "generic"). Checking the block first keeps the
    reason honest, and the reason is what lands in `Mention.candidates` provenance.

    `reason` is returned for the report and for provenance — a decision nobody can
    explain is worse than no decision.
    """
    if is_generic(text):
        return False, "generic noun"
    entry = lookup(text)
    if entry is None:
        return False, "not indexed"
    if not entry.requires_context:
        return True, "indexed name"
    if has_context(body):
        return True, "indexed + context"
    return False, "needs procurement context"
