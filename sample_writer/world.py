"""The cast, the topics, and the schedule — one seed, one world, one clock.

Everything the writers emit comes from here. That is what makes `Mary Olver` the same
person on WhatsApp and in email, and it is what makes two runs at the same seed
byte-identical.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config, fuzz

# --------------------------------------------------------------------------- topics

TOPIC_WORDS = {
    "dog": ["the dog", "Biscuit", "the vet", "walkies", "the lead", "kennel"],
    "baseball": ["the game", "the Sox", "the season", "tickets", "the bullpen", "Saturday's match"],
    "cola": ["the Coca-Cola thing", "the Coke account", "the campaign", "the vending machine"],
    "mary": ["Mary Jones", "Mary's birthday", "Mary Jones's place"],
    "abc": ["ABC Corp", "the ABC contract", "the ABC invoice", "their accounts team"],
    "invoice": ["the invoice", "the payment run", "the statement", "the remittance"],
    "weekend": ["the weekend", "Sunday", "the drive up", "the weather"],
    "work": ["the deck", "the review", "the deadline", "the client call"],
}

PEOPLE_ROLES = [
    ("colleague", "ABC Corp"),
    ("client", "ABC Corp"),
    ("supplier", "Northwind Supplies"),
    ("friend", None),
    ("family", None),
    ("recruiter", "Talent Partners"),
    ("landlord", None),
    ("contractor", None),
    # Roles that carry an organisation, so the expanded ORGS is actually used.
    ("engineer", "tech"),
    ("analyst", "tech"),
    ("vendor contact", "tech"),
    ("account manager", "tech"),
    ("contractor", "tech"),
    ("civil servant", "public"),
    ("consultant", "tech"),
]

FIRST_NAME = [
    "Mary", "Brandon", "Alexandra", "Lida", "Fred", "Sergio", "Kenny", "Morgan", "Anna",
    "Dimitri", "Priya", "Owen", "Ines", "Tomas", "Hannah", "Rahul", "Clare", "Nadia",
    "Ivo", "Beth", "Marco", "Sofia", "Jonas", "Amara", "Peter", "Yuki", "Fatima",
    "Callum", "Rosa", "Ahmed",
    "Ada", "Grace", "Alan", "Vint", "Niklaus", "Linus", "Barbara", "Margaret",
    "Katherine", "Radia", "Frances", "Anita", "Shafi", "Judea", "Ptolemy",
    # Given names with a nickname pair in `fuzz.NICKNAMES`.
    "Chris", "Christopher", "Bob", "Robert", "Dave", "David", "Jim", "James",
    "Bill", "William", "Liz", "Elizabeth", "Tom", "Thomas", "Dan", "Daniel",
    "Nick", "Nicholas", "Alexander",
    # --- expansion -----------------------------------------------------------
    # Breadth matters more than novelty: a wider cast means body Persons and
    # Correspondents collide less, and the name pool stops reading as one office.
    "Aisha", "Amir", "Anika", "Aoife", "Arjun", "Astrid", "Beatriz", "Bjorn",
    "Camila", "Chidi", "Ciara", "Dara", "Dmitri", "Elena", "Emeka", "Esme",
    "Esther", "Farah", "Fiona", "Gabriel", "Gemma", "Gustavo", "Halima", "Hugo",
    "Ibrahim", "Imogen", "Isabel", "Jakub", "Jamil", "Jasmine", "Joel", "Josef",
    "Kaito", "Karim", "Katya", "Keiran", "Lars", "Leila", "Leon", "Lucia",
    "Magnus", "Mairead", "Malik", "Marta", "Mateo", "Mei", "Miriam", "Nadia",
    "Naveen", "Niamh", "Olga", "Omar", "Orla", "Pablo", "Padma", "Quentin",
    "Rafael", "Ravi", "Rebecca", "Rhys", "Ruth", "Salma", "Sanjay", "Saskia",
    "Sean", "Sebastian", "Shreya", "Sian", "Simone", "Stefan", "Suki", "Tariq",
    "Tessa", "Thabo", "Theo", "Ulla", "Uma", "Valentina", "Vikram", "Wanda",
    "Xavier", "Yara", "Yusuf", "Zara", "Zoe",
    # ASCII only, deliberately: a non-ASCII name has to survive the whole write chain
    # (JSON, zip, SMS XML) and one mangled byte fails a test for a case the app does
    # not need. `canon` folds diacritics if they arrive; the generator no longer
    # manufactures them.
    "Rene",
    "Zoe",]
LAST_NAME = [
    "Olver", "Steinhart", "Lonon", "Geller", "Aaen", "Habegger", "Settens", "Davin",
    "Kowalski", "Petrov", "Nair", "Blythe", "Costa", "Novak", "Whitfield", "Iyer",
    "Mercer", "Haddad", "Ellis", "Ferreira", "Bauer", "Ricci", "Lindqvist", "Okafor",
    "Vance", "Tanaka", "Hassan", "Ross", "Marsh", "Zaman",
    "Lovelace", "Hopper", "Turing", "Cerf", "Wirth", "Torvalds", "Nakamoto",
    "Kernighan", "Ritchie", "Thompson", "Kay", "Perlman", "Lamarr", "Berners",
    "Fowley",
    # --- expansion -----------------------------------------------------------
    "Adeyemi", "Almeida", "Andersen", "Aritonang", "Bakshi", "Baranov", "Beaumont",
    "Bellini", "Bhattacharya", "Boateng", "Brennan", "Cardoso", "Castellano",
    "Chatterjee", "Chowdhury", "Dalgaard", "Deshmukh", "Diop", "Doyle", "Dubois",
    "Duarte", "Eriksen", "Esposito", "Fennell", "Fernandes", "Fitzgerald", "Fontaine",
    "Gallagher", "Ghosh", "Giordano", "Grimaldi",
    "Halloran", "Ibrahim", "Iversen", "Janssen", "Kaur", "Kelleher",
    "Kholodov", "Koval", "Krebs", "Kumar", "Lehtinen", "Lombardi",
    "MacLeod", "Mahmoud", "Mbatha", "McAllister", "Menon", "Montoya", "Morales",
    "Nakamura", "Ndlovu", "Nguyen", "Nilsson", "O'Connell", "Okonkwo",
    "Olsen", "Ortiz", "Pashkov", "Patel", "Pereira", "Pham", "Quinn", "Ramirez",
    "Reddy", "Reid", "Riordan", "Rose", "Roux", "Saito", "Salgado",
    "Schulz", "Sharma", "Sullivan", "Suzuki", "Takahashi", "Thibault",
    "Tokarev", "Tremblay", "Varga", "Vasquez", "Walsh", "Weber", "Wolff",
    "Yamamoto", "Yilmaz", "Zielinski", "Zimmermann",]

# Organisations quoted in bodies and subjects, and drawn by `PEOPLE_ROLES`.
# The first five are the original cast's employers and must stay: `ABC Corp` and
# `Northwind Supplies` are written into the fixed cast's `org` below.
#
# **An explicit list, not a slice.** These were `ORGS[5:24]` and `[24:]`, which
# silently broke whenever an entry was added or moved. An org belongs to a pool because
# it is listed there, not because of where it happens to sit in the array.
ORGS = [
    "ABC Corp", "Northwind Supplies", "Talent Partners", "Coca-Cola", "Sox Tickets",
    # --- data and infrastructure ---------------------------------------------
    "Databricks", "Snowflake", "Confluent", "HashiCorp", "Datadog", "Cloudflare",
    "Elastic", "MongoDB", "Neo4j", "Cloudera", "Teradata", "Informatica", "Fivetran",
    "dbt Labs", "Airbyte", "Denodo", "Starburst", "SingleStore", "CockroachDB",
    "Timescale", "InfluxData", "Redis", "Cassandra", "Postgres", "ClickHouse",
    "DuckDB", "Supabase", "PlanetScale", "Neon", "Crunchy Data", "Oracle", "SAP",
    "IBM", "Microsoft", "Amazon Web Services", "Google Cloud", "Alibaba Cloud",
    "DigitalOcean", "Hetzner", "OVH", "Akamai", "Fastly", "Vercel", "Netlify",
    "Render", "Railway", "Fly.io", "Heroku",
    # --- ai, ml and the current cast ------------------------------------------
    "Anthropic", "OpenAI", "Hugging Face", "Weights & Biases", "Scale AI", "Mistral",
    "Cohere", "DeepMind", "Stability AI", "Pinecone", "Weaviate", "Qdrant", "Chroma",
    "LangChain", "LlamaIndex", "Modal Labs", "Together AI", "Groq", "Cerebras",
    "SambaNova", "Graphcore", "Perplexity", "Midjourney", "Runway", "ElevenLabs",
    # --- robotics and hardware ------------------------------------------------
    "Boston Dynamics", "ABB", "KUKA", "Fanuc", "Universal Robots", "iRobot",
    "Agility Robotics", "Figure AI", "1X Technologies", "Unitree", "Clearpath Robotics",
    "NVIDIA", "AMD", "Intel", "Qualcomm", "Arm", "Broadcom", "TSMC", "ASML",
    "Mellanox", "Cisco", "Juniper", "Arista", "Dell", "HP", "Lenovo", "Supermicro",
    "Western Digital", "Seagate", "Toshiba Storage", "Micron", "Kingston", "NetApp",
    "Pure Storage", "Netgear", "Synology", "QNAP", "Ubiquiti",
    # --- software and services ------------------------------------------------
    "Celestica", "Retool", "n8n.io", "Hermes", "Zed", "Atlassian", "GitLab", "GitHub",
    "JetBrains", "Slack", "Zoom", "Notion", "Figma", "Asana", "Monday.com", "Airtable",
    "Salesforce", "HubSpot", "Zendesk", "Freshworks", "ServiceNow", "Workday",
    "Splunk", "Grafana Labs", "Sentry", "PagerDuty", "Twilio", "SendGrid", "Stripe",
    "Adyen", "PayPal", "Square", "Wise", "Plaid", "Okta", "Auth0", "1Password",
    "Cloudflare Workers", "Postman", "Insomnia",
    # --- banking, finance and insurance ---------------------------------------
    "HSBC", "Barclays", "Lloyds Bank", "NatWest", "Santander", "Deutsche Bank",
    "BNP Paribas", "ING", "Swedbank", "Danske Bank", "Nordea", "UBS", "Credit Suisse",
    "Citi", "Goldman Sachs", "Morgan Stanley", "JPMorgan", "BlackRock", "Vanguard",
    "Fidelity", "Aviva", "Prudential", "Allianz", "AXA", "Zurich Insurance",
    # --- government, public bodies, NGOs --------------------------------------
    "North Dakota DOT", "GSA", "National Archives", "NIST", "NSW Health",
    "Department of Transport", "Home Office", "HMRC", "Environment Agency",
    "Public Health England", "NHS Digital", "Government Digital Service",
    "UK Research and Innovation", "European Commission", "UNICEF", "Red Cross",
    "Oxfam", "Greenpeace", "Amnesty International",
    "Brotherhood of St Laurence", "Rotary Club", "Unite the Union", "City of Austin",
    "Illawarra City Council", "Parish Council", "Housing Association",
    # --- scholastic and research ---------------------------------------------
    "University of Sydney", "University of Cambridge", "University of Oxford",
    "MIT", "Stanford University", "ETH Zurich", "KAIST", "Tsinghua University",
    "Indian Institute of Science", "University of Cape Town", "Trinity College Dublin",
    "Max Planck Institute", "CERN", "Alan Turing Institute",
    # --- online and community groups -----------------------------------------
    "r/3d graphs", "r/dataisbeautiful", "Hacker News", "Lobsters", "Stack Overflow",
    "Kaggle", "Anthropic Developer Discord", "Neo4j Community Forum",
    "Bay Area Robotics Meetup", "North Dakota Dev Group", "Bismarck Chamber",]

# Org pools `PEOPLE_ROLES` draws an employer from. Membership is by LIST, not by slice.
# `public` is anything state-funded or non-profit; `tech` is the commercial remainder.
TECH_ORGS = [
    o for o in ORGS
    if o not in {
        "North Dakota DOT", "GSA", "National Archives", "NIST", "NSW Health",
        "Department of Transport", "Home Office", "HMRC", "Environment Agency",
        "Public Health England", "NHS Digital", "Government Digital Service",
        "UK Research and Innovation", "European Commission", "UNICEF", "Red Cross",
        "Oxfam", "Greenpeace", "Amnesty International", "Médecins Sans Frontières",
        "Brotherhood of St Laurence", "Rotary Club", "Unite the Union", "City of Austin",
        "Illawarra City Council", "Parish Council", "Housing Association",
        "University of Sydney", "University of Cambridge", "University of Oxford",
        "MIT", "Stanford University", "ETH Zurich", "KAIST", "Tsinghua University",
        "Indian Institute of Science", "University of Cape Town", "Trinity College Dublin",
        "Max Planck Institute", "CERN", "Alan Turing Institute",
        "r/3d graphs", "r/dataisbeautiful", "Hacker News", "Lobsters", "Stack Overflow",
        "Kaggle", "Anthropic Developer Discord", "Neo4j Community Forum",
        "Bay Area Robotics Meetup", "North Dakota Dev Group", "Bismarck Chamber",
    }
]
PUBLIC_ORGS = [o for o in ORGS if o not in TECH_ORGS]

ORG_POOLS = {"tech": TECH_ORGS, "public": PUBLIC_ORGS}

# Products. A body says `the Databricks account`, `Coca-Cola`, `Mazda CX-5` — things bought,
# used or complained about, never organisations.
#
# **Rebalanced 2026-11-24.** The pool had drifted to ~90% software: enterprise platforms,
# CLI tools, GPU part numbers. That is not what a real professional's phone looks like — it
# is what a vendor conference looks like. A person with a job also has a car, a mortgage,
# shoes and opinions about coffee, and those get mentioned more often than `gguf`.
#
# The section a name sits in decides two things downstream, and nothing else:
#
#     TECH        fuzz may hyphenate; frames are `still on X` / `the X renewal`
#     DURABLE     no hyphen fuzz; frames are owns-and-maintains: `the X needs new tyres`
#     FOOD        no hyphen fuzz; frames are consume-and-restock: `ran out of X`
#
# Hardware and software share frames deliberately — `we're still on Jira` and `we shipped
# the Jetson Orin config` are the same kind of statement: a thing we have and run. Only
# the consume/own distinction changes the sentence.

# --- tech: software, hardware, models -------------------------------------------
PRODUCTS_TECH = [
    "Databricks Lakehouse", "Snowflake Cortex", "Tableau", "Power BI", "Looker",
    "Excel", "Sheets", "Notion Calendar", "Slack Connect", "Teams", "Zoom Rooms",
    "Jira", "Confluence", "GitHub Copilot", "VS Code", "Cursor", "Vim", "Emacs",
    "Docker", "Kubernetes", "Terraform", "Ansible", "Prometheus", "Grafana",
    "Kafka", "Spark", "Airflow", "dbt Core", "Temporal", "Pulsar", "Flink",
    "Nginx", "Apache", "Redis Enterprise", "Elasticsearch", "OpenSearch",
    "MacBook Pro", "ThinkPad", "Surface Pro", "Pixel", "iPhone", "Galaxy",
    "Raspberry Pi", "Jetson Orin", "DGX Station", "Threadripper", "Xeon",
    "EPYC", "Apple Silicon", "Radeon", "GeForce", "RTX", "Ryzen",
    "NVMe", "SSD", "RAID", "Router", "Patch Panel", "PDU",
    "Claude", "GPT-4", "Llama", "Mistral Large", "Gemini", "Whisper",
    "Stable Diffusion", "Ollama", "vLLM", "LoRA",
    # Services bought rather than built. `Seat`, `Contract`, `SLA` and `Credits` are
    # deliberately absent: they are ordinary nouns, the app's index blocks them, and
    # carrying them here would generate product mentions the extractor refuses to read.
    "Support Plan", "Enterprise Licence", "Free Tier", "Training Day",
    "Onboarding Pack", "Migration Kit",
]

# --- durable goods: owned, maintained, replaced ----------------------------------
# Pricier things a person mentions more than once and across months: the car in for a
# service, the new sofa, the watch on a wishlist. Model names over bare brands, because
# `Toyota` alone is a company and would exercise the Organisation leg, not this one.
PRODUCTS_DURABLE = [
    # cars — model names, which are unambiguous
    "Toyota Highlander", "Honda Civic", "Ford Escape", "Mazda CX-5", "Tesla Model 3",
    "BMW 3 Series", "Volkswagen Golf", "Audi A4", "Subaru Outback", "Jeep Wrangler",
    "Range Rover Sport", "Volvo XC90", "Hyundai Tucson", "Kia Sportage",
    "Mercedes C-Class", "Porsche 911", "Mini Cooper", "Land Cruiser", "Ford Ranger",
    # bikes, boats, vehicles
    "Specialized Roubaix", "Trek Domane", "Brompton", "Vespa Primavera",
    "Yamaha MT-07", "Sea-Doo",
    # watches and jewellery
    "Rolex Submariner", "Omega Seamaster", "Tag Heuer Carrera", "Apple Watch Ultra",
    "Garmin Fenix", "Cartier Santos", "Tiffany necklace",
    # shoes and clothing
    "Nike Air Max", "Nike Jordans", "Adidas Samba", "New Balance 990",
    "Doc Martens", "Barbour jacket", "Patagonia fleece", "North Face jacket",
    "Levi 501", "Ray-Ban Wayfarer", "Hermes scarf", "Uniqlo down jacket",
    # furniture and home
    "Ikea Billy", "Ikea Kallax", "Herman Miller Aeron", "Vitra Eames chair",
    "Le Creuset pan", "Dyson vacuum", "Nespresso machine", "KitchenAid mixer",
    "Sub-Zero fridge", "Tempur mattress", "Benjamin Moore paint", "Farrow and Ball paint",
    "Persian rug", "Weber kettle", "Big Green Egg",
    # electronics and photography
    "Sony PlayStation", "Xbox Series X", "Nintendo Switch", "Sonos speaker",
    "Bose headphones", "LG OLED", "4k television", "Nikon D850", "Canon EOS R5",
    "Fujifilm X100", "GoPro Hero", "DJI Mavic", "Kindle Paperwhite", "iPad Pro",
    "Peloton bike", "Ring doorbell", "Philips Hue",
    # property and big-ticket
    "NYC condo", "Brooklyn brownstone", "colonial mansion", "beach house",
    "Honda generator", "DeWalt drill", "Makita saw",
    # other expensive interests
    "Glock 19", "Browning shotgun", "Gibson Les Paul", "Fender Stratocaster",
    "Yamaha piano", "Steinway grand",
]

# --- food and drink -------------------------------------------------------------
PRODUCTS_FOOD = [
    "Coca-Cola", "Diet Coke", "Sprite", "Fanta", "Powerade", "Monster Energy",
    "Weetabix", "Marmite", "Irn-Bru", "Yorkshire Tea", "Bovril", "Lucozade",
    "Cadbury Dairy Milk", "Walkers crisps", "Heinz beans", "Nando's sauce",
    "Toblerone", "Green and Black's", "Peroni", "Guinness",
]

PRODUCTS = [*PRODUCTS_TECH, *PRODUCTS_DURABLE, *PRODUCTS_FOOD]

# Which section a name belongs to. A `frozenset` rather than a prefix test because the
# distinction is a judgement about the real world: `Sprite` is a drink and `Spark` is a
# data engine, and only a human can say which.
PRODUCT_SECTION: dict[str, str] = {
    **{name: "tech" for name in PRODUCTS_TECH},
    **{name: "durable" for name in PRODUCTS_DURABLE},
    **{name: "food" for name in PRODUCTS_FOOD},
}


def product_section(name: str) -> str:
    """`tech` | `durable` | `food`. Unknown names get the tech frames, which are safest."""
    return PRODUCT_SECTION.get(name, "tech")

# Places. Bodies say `N Dakota` on one platform and `North Dakota` on another, and
# that is the point: the pool holds the abbreviated forms real people type.
PLACES = [
    "North Dakota", "N Dakota", "ND", "Fargo", "Bismarck",
    "Austin, TX", "Austin", "Denver", "Seattle", "Berlin", "Lisbon", "Toronto",
    "Cambridge, MA", "the Bay Area", "Chicago",
    # --- US --------------------------------------------------------------------
    "New York", "Brooklyn", "Queens", "Boston", "Philadelphia", "Pittsburgh",
    "Atlanta", "Miami", "Orlando", "Nashville", "Memphis", "New Orleans",
    "Houston", "Dallas", "San Antonio", "Phoenix", "Tucson", "Las Vegas",
    "Portland", "San Francisco", "San Jose", "Oakland", "Sacramento", "Los Angeles",
    "San Diego", "Salt Lake City", "Boise", "Minneapolis", "St Paul", "Milwaukee",
    "Detroit", "Cleveland", "Columbus", "Cincinnati", "St Louis", "Kansas City",
    "Oklahoma City", "Omaha", "Des Moines", "Anchorage", "Honolulu", "Baltimore",
    "Richmond", "Charlotte", "Raleigh", "Charleston", "Birmingham", "Louisville",
    "North Carolina", "South Carolina", "West Virginia", "New Mexico", "Montana",
    "Wyoming", "Vermont", "Maine", "Idaho", "Nebraska", "Iowa", "Arkansas",
    # --- UK and Ireland --------------------------------------------------------
    "London", "Manchester", "Birmingham UK", "Leeds", "Sheffield", "Bristol",
    "Liverpool", "Newcastle", "Nottingham", "Leicester", "Coventry", "Southampton",
    "Brighton", "Oxford", "Cambridge UK", "Norwich", "York", "Bath", "Cardiff",
    "Swansea", "Edinburgh", "Glasgow", "Aberdeen", "Dundee", "Inverness",
    "Belfast", "Derry", "Cork", "Dublin", "Galway", "Limerick",
    # --- Europe ------------------------------------------------------------------
    "Paris", "Lyon", "Marseille", "Bordeaux", "Madrid", "Barcelona", "Valencia",
    "Seville", "Porto", "Rome", "Milan", "Naples", "Turin",
    "Amsterdam", "Rotterdam", "Utrecht", "Brussels", "Antwerp", "Cologne",
    "Munich", "Hamburg", "Frankfurt", "Stuttgart", "Dresden", "Leipzig",
    "Vienna", "Zurich", "Geneva", "Basel", "Bern", "Copenhagen", "Aarhus",
    "Stockholm", "Gothenburg", "Oslo", "Bergen", "Helsinki", "Tampere",
    "Warsaw", "Krakow", "Wroclaw", "Prague", "Brno", "Bratislava", "Budapest",
    "Ljubljana", "Zagreb", "Belgrade", "Sofia", "Bucharest", "Athens",
    "Thessaloniki", "Istanbul", "Ankara", "Kyiv", "Lviv", "Tallinn", "Riga",
    "Vilnius", "Reykjavik", "Luxembourg", "Valletta",
    # --- rest of world ---------------------------------------------------------
    "Vancouver", "Montreal", "Ottawa", "Calgary", "Edmonton", "Winnipeg",
    "Halifax", "Mexico City", "Guadalajara", "Monterrey", "Bogota", "Medellin",
    "Lima", "Santiago", "Buenos Aires", "Sao Paulo", "Rio de Janeiro", "Brasilia",
    "Cairo", "Alexandria", "Lagos", "Abuja", "Accra", "Nairobi", "Kampala",
    "Dar es Salaam", "Johannesburg", "Cape Town", "Durban", "Pretoria", "Casablanca",
    "Tunis", "Algiers", "Addis Ababa", "Tel Aviv", "Amman", "Beirut", "Dubai",
    "Abu Dhabi", "Doha", "Riyadh", "Kuwait City", "Tehran", "Karachi", "Lahore",
    "Islamabad", "Delhi", "Mumbai", "Bangalore", "Hyderabad", "Chennai", "Pune",
    "Kolkata", "Dhaka", "Colombo", "Kathmandu", "Singapore", "Kuala Lumpur",
    "Jakarta", "Bangkok", "Hanoi", "Ho Chi Minh City", "Manila", "Taipei",
    "Hong Kong", "Shanghai", "Beijing", "Shenzhen", "Guangzhou", "Chengdu",
    "Seoul", "Busan", "Tokyo", "Osaka", "Kyoto", "Yokohama", "Sydney",
    "Melbourne", "Brisbane", "Perth", "Adelaide", "Canberra", "Hobart",
    "Auckland", "Wellington", "Christchurch",]

# How a body refers to an organisation: `Celestica`, `celestica`, `Celstica`, or
# `Celestica's`. The flattener has to survive all four; the writer picks per message.
ORG_FORMS = ("plain", "lower", "drop_letter", "possessive")


@dataclass
class Person:
    name: str
    email: str | None
    phone: str | None
    on: set[str]
    role: str
    org: str | None
    topics: list[str]
    is_fixed: bool = False
    # How this person's name is *printed* on a given platform. Empty means `name` is
    # used everywhere. Populated by the world at build time, never per message, so the
    # same person keeps one spelling per export — which is what a real download does.
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def handle(self) -> str:
        return "".join(ch for ch in self.name.lower() if ch.isalnum())

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "")

    def label(self, platform: str) -> str:
        """The name this person carries on `platform`.

        **Only the printed sender field uses this.** `name` stays the structural
        identity — it feeds `slug`, `handle` and therefore message keys and filenames,
        so a fuzzed spelling can never move a `Message.key`.
        """
        return self.labels.get(platform, self.name)

    def email_for(self, domain: str | None = None) -> str:
        if domain:
            return f"{self.name.split()[0].lower()}.{self.name.split()[-1].lower()}@{domain}"
        return self.email or f"{self.slug}@example.com"


# ------------------------------------------------------------------------ the world


def norm_person_name(name: str | None) -> str:
    """Compare two spellings of a person without case or accents mattering.

    The generator only needs this to answer "is this the Owner?", so it deliberately
    matches the app's own `resolution.norm_name` shape (casefold, strip marks, collapse
    spaces) without importing from the app.
    """
    import unicodedata

    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    without_marks = "".join(
        ch for ch in decomposed if not unicodedata.category(ch).startswith("M"))
    return " ".join(without_marks.casefold().split())


@dataclass
class EntityPlan:
    """What one body item (a Place, Organization or Product) will do.

    Three dice, rolled independently in `_assign_body_entities()`:

      platforms  1, or `randint(2, len(config.PLATFORMS))` — where it may be named
      mention    "single" | "multi", with `mention_n` times on ONE platform
      variant    the fuzzy spelling drawn by `fuzz.pick_variant()`, or None

    **Mentions are available, not promised.** `entity_line()` samples freely and may
    never name a given item at all; that is where the `mention_count: 1` tail comes
    from. Nothing here is an allocation the dialogue layer must honour.
    """

    platforms: tuple[str, ...]
    mention: str = "single"
    mention_n: int = 1
    variant: str | None = None
    variant_name: str | None = None

    @property
    def multi_platform(self) -> bool:
        return len(self.platforms) > 1

    @property
    def multi_mention(self) -> bool:
        return self.mention == "multi"


@dataclass
class World:
    seed: int
    owner: str
    start: datetime
    end: datetime
    people: list[Person] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    # Entity plans for message bodies, keyed `kind -> name -> EntityPlan`. One generic
    # table for every body kind: a Place, an Organization and a Product answer the same
    # three questions, so a fourth kind would need no second table.
    body_entities: dict[str, dict[str, EntityPlan]] = field(default_factory=dict)
    # Rows the world could not satisfy — a fuzzy item no variant would apply to. Printed
    # by `fuzz_lines()`, never raised: one stubborn name is not a build failure.
    fuzz_misses: list[str] = field(default_factory=list)

    # --- construction ------------------------------------------------------------

    @classmethod
    def build(cls, seed: int | None = None) -> World:
        seed = config.SEED if seed is None else seed
        rng = random.Random(seed)
        world = cls(
            seed=seed,
            owner=config.OWNER,
            start=datetime.fromisoformat(config.START),
            end=datetime.fromisoformat(config.END),
            rng=rng,
        )
        world._populate()
        world._assert_contract()
        return world

    def _populate(self) -> None:
        low, high = config.CORRESPONDENTS
        target = self.rng.randint(low, high)

        # The fixed cast, so the names the brief asks for are always present.
        fixed = [
            Person("Mary Jones", "mary.jones@example.com", "+447700900001",
                   {"whatsapp", "sms", "email"}, "family", None,
                   ["mary", "dog", "weekend"], is_fixed=True),
            Person("Mary Olver", "mary.olver@abccorp.example", "+447700900002",
                   {"whatsapp", "email"}, "colleague", "ABC Corp",
                   ["abc", "invoice", "work"], is_fixed=True),
            Person("Brandon Steinhart", "brandon@northwindsupplies.example", "+447700900003",
                   {"telegram", "linkedin"}, "supplier", "Northwind Supplies",
                   ["invoice", "work"], is_fixed=True),
            Person("ABC Corp", "accounts@abccorp.example", "+441134960000",
                   {"email", "linkedin"}, "client", "ABC Corp", ["abc", "invoice"],
                   is_fixed=True),
        ]
        self.people.extend(fixed)

        used = {p.name for p in self.people}
        while len(self.people) < target:
            name = f"{self.rng.choice(FIRST_NAME)} {self.rng.choice(LAST_NAME)}"
            if name in used:
                continue
            used.add(name)
            role, org = self.rng.choice(PEOPLE_ROLES)
            if org in ORG_POOLS:
                org = self.rng.choice(ORG_POOLS[org])
            topics = self.rng.sample(list(TOPIC_WORDS), k=self.rng.randint(1, 3))
            self.people.append(Person(
                name=name,
                email=f"{name.lower().replace(' ', '.')}@example.com",
                phone=f"+4477009{self.rng.randint(10000, 99999)}",
                on=set(),
                role=role,
                org=org,
                topics=topics,
            ))

        # Presence. Everyone gets at least one platform; `CORR_MULTI_PLATFORM` is the
        # share that gets more than one. Drawn over the random cast only — the fixed
        # cast is multi-platform by construction, so counting it would measure the
        # brief rather than the generator.
        #
        # The platform list comes from `config.PLATFORMS`, not a local copy: the local
        # list here and the one in `_assign_labels()` both omitted `outlook`, so a
        # platform could be added to config and silently never receive a person.
        platforms = self.cast_platforms()
        random_cast = [p for p in self.people if not p.is_fixed]
        multi_count = round(len(random_cast) * config.CORR_MULTI_PLATFORM)
        order = list(self.people)
        self.rng.shuffle(order)
        # Count *eligible* people, not loop indices: the fixed cast already has `on`
        # set and is skipped by the `continue`, so an index-based test spent the budget
        # on people it never multi-homed and undershot the band.
        multi_left = multi_count
        for person in order:
            if person.on:
                continue
            first = self.rng.choice(platforms)
            person.on.add(first)
            if multi_left > 0:
                extra = self.rng.choice([p for p in platforms if p != first])
                person.on.add(extra)
                multi_left -= 1

        self._assign_labels()

    def _assign_labels(self) -> None:
        """Decide once, per person, how their name is spelled on each platform.

        This is the whole of the sender-field fuzz: a `Person` keeps one structural
        `name`, and the downloads print a per-platform spelling from `labels`. Doing
        it here rather than inside a writer is what makes it deterministic, keeps one
        spelling per export (as a real download has), and leaves the writers dumb.

        Two shapes, both counted by their own knob:

          intra  two spellings *within one platform's export* — the platform lists a
                 thread title from the address book and a sender row the user typed
        cross  two spellings *across two platforms* — `Chris Fowley` on WhatsApp,
                 `Christopher Fowley` on Telegram, same phone, same email

        The Owner is never a candidate: `config.OWNER` is emitted verbatim by every
        writer, and a fuzzed owner would break the one invariant the app depends on.
        """
        owner = norm_person_name(self.owner)
        pool = [p for p in self.people
                if not p.is_fixed and norm_person_name(p.name) != owner]
        self.rng.shuffle(pool)
        # The platforms a person can be promoted onto come from `config.PLATFORMS` via
        # `cast_platforms()` inside the intra pass, so a new platform needs no second
        # list kept in step.

        # A person carries a fuzzy spelling on ONE of their platforms. Which people are
        # multi-platform is already settled by `CORR_MULTI_PLATFORM`; this pass decides
        # only *which spelling*, so it can never move the platform share. Jittered around
        # `CORR_FUZZY` rather than hitting it exactly, because the cast is small and a
        # rounded count would make every seed identical.
        candidates = [p for p in pool if len(p.on) >= 2]
        fuzzy_count = round(len(pool) * config.CORR_FUZZY)
        for person in candidates[:max(0, fuzzy_count)]:
            platforms_on = sorted(person.on)
            platform = platforms_on[self.rng.randrange(len(platforms_on))]
            if platform in person.labels:
                continue
            spelling, applied = fuzz.pick_variant(
                person.name, self.rng, config.FUZZ_VARIANTS["corr"])
            if applied is None:
                self.fuzz_misses.append(f"corr: no variant applied to {person.name!r}")
                continue
            person.labels[platform] = spelling

        # Keyed by name, not by object: `Person` is a mutable dataclass and therefore
        # unhashable. Names are unique in the cast (`_populate` dedupes on them).
        used: set[str] = set()
        intra_pool = list(pool)
        for platform in config.FUZZ_SENDERS_INTRA_PLATFORMS:
            quota = max(0, config.FUZZ_SENDERS_INTRA)
            if not quota:
                continue
            made = 0
            # If the platform's cast is too thin to meet the quota, promote a couple of
            # people onto it first. Measured on 300 seeds: 2 still fell short purely
            # because only 9 people were on WhatsApp. The cast is synthetic; being on
            # the platform is what the shape requires.
            candidates = [p for p in intra_pool if platform in p.on]
            if len(candidates) < quota:
                for person in [p for p in intra_pool if platform not in p.on]:
                    if len(candidates) >= quota:
                        break
                    person.on.add(platform)
                    candidates.append(person)
            # Walk the whole pool, not just the first `quota` candidates: the same
            # person can be skipped for a misspelling that `vary_sender` could not
            # produce, and stopping early would leave the knob unmet.
            for person in candidates:
                if made >= quota:
                    break
                # A person already carrying a label on this platform IS the intra
                # case — a cross-platform variant on the *other* platform does not
                # satisfy it, and vice versa. A person in a cross pair is left alone
                # entirely: giving them a third label made the summary report a cross
                # count the knob never asked for (cross=3 on a knob of 2).
                if platform in person.labels or person.name in used:
                    continue
                # Inside one export: the spelling the contact list holds, plus the
                # one a sender row carries. `SENDER_MODES` keeps this to mistypings —
                # an all-caps or possessive variant is not a sender name.
                variant = fuzz.vary_sender(person.name, self.rng)
                if variant != person.name:
                    person.labels[platform] = variant
                    used.add(person.name)
                    made += 1

        self._assign_body_entities()

    def cast_platforms(self) -> list[str]:
        """Platforms a *person* can be on, from `config.PLATFORMS`.

        `outlook` is excluded: a `.pst` is a byte copy of a committed fixture, so a
        person placed there is never written, and the same holds for a body variant.
        Derived from config so adding a platform needs no second list kept in step.
        """
        return [p for p in config.PLATFORMS if p != "outlook"]

    def _assign_body_entities(self) -> None:
        """Roll the three independent dice for every body item.

        One generic table, `body_entities[kind][name] -> EntityPlan`, because a Place, an
        Organization and a Product answer the same three questions. Per item:

          fuzzy          share `BODY_FUZZY`; one variant, uniform over `FUZZ_VARIANTS`
          multi-mention  share `BODY_MULTI_MENTION`; 2-4 mentions on ONE platform
          multi-platform share `BODY_MULTI_PLATFORM`; 2..len(PLATFORMS) platforms

        **Every dice is over the whole population of its kind**, never conditioned on an
        earlier roll — "fuzzy or otherwise", "multi-mention or not". That is what makes
        the four combinations independent and all of them reachable.

        `person` is deliberately absent: it competes with the Correspondent already on
        the thread.
        """
        platforms = self.cast_platforms()
        if not platforms:
            return
        kinds = set(config.FUZZ_BODY_KINDS)
        pools: dict[str, list[str]] = {}
        if "org" in kinds:
            pools["org"] = list(ORGS)
        if "place" in kinds:
            pools["place"] = list(PLACES)
        if "product" in kinds:
            pools["product"] = list(PRODUCTS)

        for kind, pool in pools.items():
            table: dict[str, EntityPlan] = {}
            for name in pool:
                # Axis B: how many platforms, and which. `randint(2, len(platforms))`
                # rather than a fixed (2, 7), so the dice cannot claim a platform the
                # world does not write.
                if self.rng.random() < config.BODY_MULTI_PLATFORM:
                    count = self.rng.randint(2, len(platforms))
                    where = tuple(sorted(self.rng.sample(platforms, k=count)))
                else:
                    where = (self.rng.choice(platforms),)

                # Axis C: mentions, independent of where it lands.
                low, high = config.MENTIONS_MULTI
                if self.rng.random() < config.BODY_MULTI_MENTION:
                    mention, mention_n = "multi", self.rng.randint(low, high)
                else:
                    mention, mention_n = "single", 1

                # Axis A: the spelling, uniform over the kind's list. Retried until one
                # applies, so a fuzzy item is genuinely fuzzy.
                #
                # A product draws from its **section's** list, not the kind's: physical
                # goods never hyphenate (see `config.FUZZ_VARIANTS`). The key falls back
                # to `product`, so a section added without a list still works.
                variant_key = kind
                if kind == "product":
                    section = product_section(name)
                    if f"product_{section}" in config.FUZZ_VARIANTS:
                        variant_key = f"product_{section}"
                variants = config.FUZZ_VARIANTS[variant_key]
                variant = variant_name = None
                if self.rng.random() < config.BODY_FUZZY:
                    variant, variant_name = fuzz.pick_variant(name, self.rng, variants)
                    if variant_name is None:
                        variant = None
                        self.fuzz_misses.append(
                            f"{kind}: no variant applied to {name!r}")

                table[name] = EntityPlan(platforms=where, mention=mention,
                                         mention_n=mention_n, variant=variant,
                                         variant_name=variant_name)
            self.body_entities[kind] = table

    def body_entity(self, canonical: str, platform: str, kind: str | None = None) -> str:
        """How a body on `platform` spells an org, place or product.

        Falls back to the canonical spelling when the item was not made fuzzy for this
        run. `kind` skips the scan; without it every kind is tried, which keeps the old
        call sites working.
        """
        tables = (self.body_entities[kind],) if kind in self.body_entities else \
            tuple(self.body_entities.values())
        for table in tables:
            plan = table.get(canonical)
            if plan and plan.variant:
                return plan.variant
        return canonical

    def plan_for(self, kind: str, name: str) -> EntityPlan | None:
        """The plan the dialogue layer reads: which platforms, how many mentions."""
        return self.body_entities.get(kind, {}).get(name)

    def fuzz_summary(self) -> dict[str, object]:
        """What the fuzz knobs actually produced, for the build log.

        Counts, not shares — `config.fuzz_lines()` prints each beside its knob so a
        share that produced nothing is visible rather than assumed.
        """
        owner = norm_person_name(self.owner)
        random_cast = [p for p in self.people
                       if not p.is_fixed and norm_person_name(p.name) != owner]
        summary: dict[str, object] = {
            "corr_total": len(random_cast),
            "corr_fuzzy": sum(1 for p in random_cast if p.labels),
            "corr_multi_platform": sum(1 for p in random_cast if len(p.on) > 1),
            "intra": sum(1 for p in random_cast if len(p.labels) == 1),
        }
        for kind, table in self.body_entities.items():
            plans = list(table.values())
            summary[kind] = {
                "items": len(plans),
                "fuzzy": sum(1 for plan in plans if plan.variant),
                "multi_mention": sum(1 for plan in plans if plan.multi_mention),
                "multi_platform": sum(1 for plan in plans if plan.multi_platform),
            }
        return summary

    def _assert_contract(self) -> None:
        share = self.multi_platform_share()
        if share > config.CORR_MULTI_PLATFORM + 0.05:
            raise AssertionError(
                f"cast multi-platform share {share:.3f} well above "
                f"CORR_MULTI_PLATFORM={config.CORR_MULTI_PLATFORM}"
            )

    # --- queries -----------------------------------------------------------------

    def multi_platform_share(self) -> float:
        """Share of the *random* cast on more than one platform.

        The fixed cast is excluded: it exists to be multi-platform, so counting it would
        measure the brief rather than the generator.
        """
        random_cast = [p for p in self.people if not p.is_fixed]
        if not random_cast:
            return 0.0
        return sum(1 for p in random_cast if len(p.on) > 1) / len(random_cast)

    def for_platform(self, platform: str) -> list[Person]:
        return [p for p in self.people if platform in p.on]

    def topic_words(self, topics: list[str]) -> list[str]:
        words: list[str] = []
        for topic in topics:
            words.extend(TOPIC_WORDS.get(topic, []))
        return words or ["it"]

    # --- time --------------------------------------------------------------------

    def export_date(self, fmt: str = "%Y-%m-%d") -> str:
        """The date this world's export is stamped with, from the world's clock.

        Real downloads carry the export date in their names (`DataExport_2026-11-14/`,
        `facebook-...-2026-11-14-....zip`). The seed is only a date by coincidence at
        the default; the date must come from the schedule, so a seed like `4` still
        names its files with a real date.
        """
        return self.end.strftime(fmt)

    def random_time(self, rng: random.Random | None = None) -> datetime:
        rng = rng or self.rng
        span = (self.end - self.start).total_seconds()
        moment = self.start + timedelta(seconds=rng.uniform(0, span))
        # Working-ish hours bias; some night owls, because real exports have them.
        if rng.random() < 0.85:
            moment = moment.replace(
                hour=rng.randint(7, 22), minute=rng.randint(0, 59), second=rng.randint(0, 59)
            )
        return moment

    def message_count(self, rng: random.Random) -> int:
        counts = list(config.MESSAGE_WEIGHTS)
        weights = [config.MESSAGE_WEIGHTS[c] for c in counts]
        return rng.choices(counts, weights=weights, k=1)[0]

    def message_times(self, start: datetime, count: int, rng: random.Random) -> list[datetime]:
        """When each message in a thread was sent — deliberately irregular.

        Real threads are not evenly spread. They arrive in **bursts**: three messages
        on one evening, silence for eight months, two more, then nothing for a year.
        A thread of fifteen messages can therefore span two calendar years, while a
        thread of three may span one day. Spreading them uniformly (the old model)
        made every thread look machine-generated and left the app's month histogram
        flat.

        The shape, all from `config.TIMING_*`:

          1. draw a burst count for this thread (`min..max`)
          2. give each burst a random weight, so one burst dominates and the rest are
             one or two messages
          3. choose the burst days across a span up to `TIMING_SPAN_DAYS`
          4. jitter the time of day inside each burst, sometimes seconds apart

        Returns `count` datetimes in ascending order, the first equal to `start`.
        """
        from datetime import timedelta

        if count <= 0:
            return []
        if count == 1:
            return [start]

        low, high = config.TIMING_BURSTS
        bursts = max(1, min(count, rng.randint(low, high)))

        # Weighted split: one big burst, the rest small. Drawing every burst from the
        # same distribution gave an even spread and lost the "sudden burst" feel.
        weights = [rng.uniform(0.5, 1.0) ** 2 for _ in range(bursts)]
        weights[rng.randrange(bursts)] *= rng.uniform(2.0, 4.0)
        total = sum(weights)
        sizes = [max(1, round(count * w / total)) for w in weights]

        # Correct rounding drift so the sizes always sum to `count`.
        while sum(sizes) > count:
            biggest = sizes.index(max(sizes))
            if sizes[biggest] == 1:
                sizes.pop()
                break
            sizes[biggest] -= 1
        while sum(sizes) < count:
            sizes[sizes.index(min(sizes))] += 1

        span_days = max(1.0, float(config.TIMING_SPAN_DAYS))
        # Never run past the world's end: 730 days from a 2025 start reached 2027, which
        # put messages outside the export window the app is told about.
        room = max(0.0, (self.end - start).total_seconds() / 86400)
        span_days = min(span_days, room) or 0.0
        # Burst starts, sorted, each somewhere in the window after `start`.
        offsets = sorted(rng.uniform(0, span_days) for _ in range(len(sizes))) if span_days else [0.0] * len(sizes)
        # A thread's first burst IS its start time, so the earliest is pinned to day 0.
        offsets[0] = 0.0

        moments: list[datetime] = []
        for burst_index, (size, offset) in enumerate(zip(sizes, offsets)):
            burst_start = start + timedelta(days=offset)
            # Inside a burst messages are minutes apart, occasionally seconds. The
            # first burst keeps `start`'s time of day so the thread really begins at
            # `start`; later bursts pick their own hour.
            if burst_index or not size:
                burst_start = burst_start.replace(
                    hour=rng.randint(7, 22), minute=rng.randint(0, 59),
                    second=rng.randint(0, 59))
            cursor = burst_start
            for index in range(size):
                if index:
                    gap = (timedelta(seconds=rng.randint(20, 600))
                           if rng.random() < 0.55
                           else timedelta(minutes=rng.randint(10, 240)))
                    cursor = cursor + gap
                moments.append(min(cursor, self.end))
        # No re-stamping of `moments[0]` here: the first burst already begins at
        # `start`, and forcing it afterwards put a late hour in front of an earlier
        # one, which made some threads end before they began (span -1).
        moments.sort()
        return moments[:count]


def build(seed: int | None = None) -> World:
    return World.build(seed)
