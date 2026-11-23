"""The cast, the topics, and the schedule — one seed, one world, one clock.

Everything the writers emit comes from here. That is what makes `Mary Olver` the same
person on WhatsApp and in email, and it is what makes two runs at the same seed
byte-identical.
"""
from __future__ import annotations

import math
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

# Products. A body says `the Databricks account`, `Coca-Cola`, `MongoDB` — things bought,
# used or complained about, never organisations. This pool exists because no body could
# name a product before it, so `Product` had no data to be tested with.
PRODUCTS = [
    # software and platforms
    "Databricks Lakehouse", "Snowflake Cortex", "Tableau", "Power BI", "Looker",
    "Excel", "Sheets", "Notion Calendar", "Slack Connect", "Teams", "Zoom Rooms",
    "Jira", "Confluence", "GitHub Copilot", "VS Code", "Cursor", "Vim", "Emacs",
    "Docker", "Kubernetes", "Terraform", "Ansible", "Prometheus", "Grafana",
    "Kafka", "Spark", "Airflow", "dbt Core", "Temporal", "Pulsar", "Flink",
    "Nginx", "Apache", "Redis Enterprise", "Elasticsearch", "OpenSearch",
    # hardware and storage
    "MacBook Pro", "ThinkPad", "Surface Pro", "Pixel", "iPhone", "Galaxy",
    "Raspberry Pi", "Jetson Orin", "DGX Station", "Threadripper", "Xeon",
    "EPYC", "Apple Silicon", "Radeon", "GeForce", "RTX", "Ryzen",
    "NVMe", "SSD", "RAID", "NAS", "SAN", "Tape Library", "Cold Storage",
    "Router", "Switch", "Patch Panel", "UPS", "PDU", "Rack",
    # ai models and services
    "Claude", "GPT-4", "Llama", "Mistral Large", "Gemini", "Whisper", "Stable Diffusion",
    "Ollama", "vLLM", "gguf", "LoRA", "RAG", "embeddings", "vector store",
    # consumer and retail
    "Coca-Cola", "Diet Coke", "Sprite", "Fanta", "Powerade", "Monster Energy",
    "Weetabix", "Marmite", "Irn-Bru", "Yorkshire Tea",
    # services bought rather than built
    "Support Plan", "Enterprise Licence", "Seat", "Credits", "Free Tier",
    "Contract", "SLA", "Training Day", "Onboarding Pack", "Migration Kit",]

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
class World:
    seed: int
    owner: str
    start: datetime
    end: datetime
    people: list[Person] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    # Entity fuzz for message bodies. Each entry is `canonical -> {platform: spelling}`,
    # so a body can say `Celestica` on one platform and `Celstica` on another. Decided
    # once at build time, like `Person.labels`.
    body_orgs: dict[str, dict[str, str]] = field(default_factory=dict)
    body_places: dict[str, dict[str, str]] = field(default_factory=dict)
    body_products: dict[str, dict[str, str]] = field(default_factory=dict)
    body_persons: dict[str, dict[str, str]] = field(default_factory=dict)

    # --- construction ------------------------------------------------------------

    @classmethod
    def build(cls, seed: int | None = None) -> "World":
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

        # Presence. Everyone gets at least one platform; only a small share get more
        # than one. The share is drawn over the random cast only — the fixed cast is
        # multi-platform by construction, so including it would push the ratio past the
        # band for reasons that are not a bug.
        platforms = ["whatsapp", "telegram", "messenger", "sms", "linkedin", "email"]
        share = self.rng.uniform(config.CROSS_PLATFORM_MIN, config.CROSS_PLATFORM_MAX)
        # The denominator must be the *random* cast only, because that is what
        # `multi_platform_share()` measures. This used `if not p.on`, but at this point
        # nobody has `on` set yet, so the fixed cast (already multi-platform) was counted
        # in the denominator and not in the numerator, dragging the ratio below the band.
        random_cast = [p for p in self.people if not p.is_fixed]
        # `round` can land a rounded share outside the band the contract asserts, which
        # made the build fail for reasons that depend on the cast size rather than on a
        # bug. Clamp to the band's own integer bounds instead, and round *up* at the
        # lower bound so a ratio that rounds down cannot under-shoot it.
        multi_count = int(round(len(random_cast) * share))
        low = math.ceil(config.CROSS_PLATFORM_MIN * len(random_cast))
        high = int(config.CROSS_PLATFORM_MAX * len(random_cast))
        multi_count = max(low, min(multi_count, high))
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
        # The platforms a person can be promoted onto. `_populate` has its own local
        # `platforms`; this method needs its own copy because the cross-promotion below
        # can add a second platform to a person who only has one.
        platforms = ["whatsapp", "telegram", "messenger", "sms", "linkedin", "email"]

        # A cross-platform pair needs two platforms. A nickname is the nicest case
        # (`Chris` / `Christopher`), but a mistyped given name across two platforms is
        # just as real a mismatch and is available for anybody — so a candidate without
        # a nickname falls back to that rather than leaving the knob unmet. Measured on
        # 60 seeds: nickname-only left 14 of them short.
        need = max(0, config.FUZZ_SENDERS_CROSS)
        # The cross shape needs two platforms *per candidate*, and only a small share of
        # the cast is multi-platform, so a fixed quota can exceed the multi-platform
        # pool. Two passes keep the cross-platform share band intact:
        #   1. use people already on two platforms — no promotion, so the share is
        #      untouched;
        #   2. only if the quota is still unmet, promote single-platform people onto a
        #      second platform, and only as many as the quota still needs.
        made = 0

        def _assign(person) -> bool:
            """Give `person` a cross pair of spellings; True if it took."""
            nonlocal made
            # Prefer two platforms that are NOT the intra ones, so a cross pair does not
            # spend the same platform slots the intra quota needs (seed 21 hit this).
            preferred = [x for x in sorted(person.on)
                         if x not in config.FUZZ_SENDERS_INTRA_PLATFORMS]
            if len(preferred) >= 2:
                first, second = preferred[:2]
            elif len(person.on) == 2 and set(person.on) <= set(
                    config.FUZZ_SENDERS_INTRA_PLATFORMS):
                # Both platforms are intra ones. The person is already multi-platform,
                # so using them for cross adds no platform and cannot inflate the share
                # band; the intra pass simply skips anyone already carrying a label.
                first, second = sorted(person.on)[:2]
            else:
                first, second = sorted(person.on)[:2]
            other = fuzz.nicknamed(person.name) or fuzz.vary_sender(person.name, self.rng)
            if not other or other == person.name:
                return False
            person.labels[first] = person.name
            person.labels[second] = other
            made += 1
            return True

        # Pass 1: already-multi-platform people only. No promotion, so the
        # cross-platform share band is untouched.
        for person in list(pool):
            if made >= need:
                break
            if len(person.on) >= 2:
                _assign(person)
        # Pass 2: promote singles only if the quota is still unmet. Promote one at a
        # time and **revert** if the person cannot be varied, so a failed promotion does
        # not inflate the cross-platform share band.
        if made < need:
            for person in list(pool):
                if made >= need:
                    break
                if len(person.on) >= 2:
                    continue
                extra = self.rng.choice([x for x in platforms if x not in person.on])
                person.on.add(extra)
                if not _assign(person):
                    person.on.discard(extra)

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

    def _assign_body_entities(self) -> None:
        """Decide how each fuzzed entity is spelled on each platform.

        Unlike a sender label, a body entity is not tied to a person: it is an
        organisation, a place or a named colleague mentioned in a message. Each gets a
        map `platform -> spelling`, and any platform without an entry uses the
        canonical spelling.

        Two shapes, both knob-counted:

          intra  several spellings inside one platform (`Celestica`, `celestica`)
          cross  a different spelling on two platforms (`N Dakota` / `North Dakota`)

        Kept to the drain-the-shortfall rule: if a pool runs out before the quota is
        met the build reports it rather than looping forever. `fuzz_lines` prints the
        counts, and `assert_contract` fails when a kind produced nothing at all.
        """
        # Outlook is excluded: `outlook_copy/Outlook.pst` is a byte copy of the
        # committed fixture, so a variant decided for it is never written. Including it
        # spent a quota slot on a platform that cannot carry the fuzz.
        platforms = [p for p in config.PLATFORMS
                     if p in config.VARIANTS and p != "outlook"]
        if not platforms:
            return
        # `FUZZ_BODIES_INTRA_PLATFORMS` is a count of platforms, not a list of names:
        # it says how many exports carry intra-platform variants. Pick that many, so
        # the shape is spread rather than piled onto one platform.
        count = max(1, min(int(config.FUZZ_BODIES_INTRA_PLATFORMS), len(platforms)))
        intra_platforms = sorted(self.rng.sample(platforms, k=count))

        kinds = set(config.FUZZ_BODY_KINDS)

        # (table, canonical pool, modes, cross-line transform)
        sources: list[tuple[dict, list[str], tuple[str, ...]]] = []
        if "org" in kinds:
            sources.append((self.body_orgs, list(ORG_POOLS["tech"] + ORG_POOLS["public"]),
                            ("lower", "drop_letter", "swap")))
        if "place" in kinds:
            # Places abbreviate by rule (`North Dakota` -> `N Dakota`), which is the
            # shape that matters here. Most place names have no qualifying first word
            # though (`Denver`, `Berlin`), so `abbrev` alone left the quota at 2 of 8.
            # Fall back to case/letter-drop, so every place can carry a variant.
            sources.append((self.body_places, list(PLACES),
                            ("abbrev", "lower", "drop_letter")))
        if "person" in kinds:
            # A person variant is a nickname, not a mechanical edit: `Bob` -> `Robert`.
            nicknamed = [p.name for p in self.people
                         if not p.is_fixed and fuzz.nicknamed(p.name)]
            sources.append((self.body_persons, nicknamed, ("nickname",)))
        if "product" in kinds:
            # Products had no body table at all before this, so `Product` could never be
            # mentioned in a message and the app's Product kind had no data to test with.
            # `hyphen` is product-only: `Coca Cola` / `Coca-Cola` is one product, and
            # `canon` flattens the hyphen for products and keeps it for people.
            sources.append((self.body_products, list(PRODUCTS),
                            ("lower", "drop_letter", "swap")))

        def variant(canonical: str, modes: tuple[str, ...]) -> str | None:
            if modes == ("nickname",):
                other = fuzz.nicknamed(canonical)
                return other if other and other != canonical else None
            # `abbrev` is tried first when the mode list contains it, so a place with a
            # qualifying word (`North Dakota`) abbreviates to `N Dakota` instead of
            # getting a letter dropped. A place without one falls through to the
            # mechanical modes, which is why the list carries both.
            for mode in modes:
                other = fuzz.vary(canonical, self.rng, (mode,))
                if other != canonical:
                    return other
            return None

        for table, pool, modes in sources:
            ordered = list(pool)
            self.rng.shuffle(ordered)

            # Cross: a different spelling on two platforms, drawn from the pool first
            # so an entity does not end up in both shapes.
            for canonical in ordered[:max(0, config.FUZZ_BODIES_CROSS)]:
                other = variant(canonical, modes)
                if other is None:
                    continue
                first, second = self.rng.sample(platforms, k=min(2, len(platforms)))
                table[canonical] = {first: canonical, second: other}

            # Intra: a variant inside one export, on the platforms the knob names.
            remaining = [c for c in ordered if c not in table]
            for canonical in remaining[:max(0, config.FUZZ_BODIES_INTRA)]:
                other = variant(canonical, modes)
                if other is None:
                    continue
                platform = self.rng.choice(intra_platforms)
                table.setdefault(canonical, {})[platform] = other

    def body_entity(self, canonical: str, platform: str) -> str:
        """How a body on `platform` spells an org, place or person.

        Falls back to the canonical spelling when the entity was not chosen for fuzz,
        or when this platform has no variant for it.
        """
        for table in (self.body_orgs, self.body_places, self.body_products,
                      self.body_persons):
            variants = table.get(canonical)
            if variants and platform in variants:
                return variants[platform]
        return canonical

    def fuzz_summary(self) -> dict[str, int]:
        """What the fuzz knobs actually produced, for the build log.

        `cross` counts people carrying two platform spellings; `intra` counts the
        single-platform spellings that are *not* part of a cross pair, so the two
        numbers answer different questions and can be checked against their knobs.
        """
        cross = sum(1 for p in self.people if len({v for v in p.labels.values()}) > 1
                    and len(p.labels) > 1)
        intra = sum(len(p.labels) for p in self.people
                    if len(p.labels) == 1)
        return {"labelled": len([p for p in self.people if p.labels]),
                "cross": cross, "intra": intra}

    def _assert_contract(self) -> None:
        share = self.multi_platform_share()
        if not (config.CROSS_PLATFORM_MIN <= share <= config.CROSS_PLATFORM_MAX):
            raise AssertionError(
                f"cross-platform share {share:.3f} outside "
                f"{config.CROSS_PLATFORM_MIN}-{config.CROSS_PLATFORM_MAX}"
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
