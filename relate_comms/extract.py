"""Extraction — propose entity spans. Decide nothing.

WHY THIS FILE EXISTS
--------------------
`canon` flattens a name it is handed; it cannot decide that a span *is* a name. Run
every capitalised word through `canonical(kind="place")` and `monday`, `hi dave` and
`ny` come back as clean keys — no error, no useful node. Something has to read the
body first, and that is this module.

The order it belongs to, and never breaks:

    extract per message  ->  fold within a platform  ->  match across platforms

    extract   this file   proposes spans, with offsets and the message they came from
    canon     `canon.canonical(kind=…)` converges spellings inside one platform
    link      `link.link()` merges across platforms

Extraction must not merge. It emits a list; a better extractor can be re-run over
older messages without touching the graph, because nothing here writes.

ENGLISH ONLY, ON PURPOSE
------------------------
v1 ships the English model. A body that is not English yields no spans, not wrong
ones: silence is cheaper than a node the user cannot trust. `language_guess()` is the
seam — a later language is a second model and a per-message guess here, not a rewrite
of the pipeline. A caller may surface the guess as a **warning**; it never raises.

NO MODEL FALLBACK
-----------------
spaCy is the declared extractor. If it is not installed, `available()` is False and
extraction returns nothing — it does not quietly degrade to a regex that would mint
`monday` again. The ingest reports the absence once, as a warning.

WHAT IS A PLACE HERE
--------------------
    GPE   geo-political: a city, region or country          `Austin`, `Texas`
    LOC   a non-political location                          `the Bay Area`
    FAC   a facility, building or road                      `12 Baker Street`

The label is kept on the mention, so a later question can tell a city from a street.

KNOWN FALSE POSITIVE, ACCEPTED
The small model labels a product or company `GPE` in some frames, and the samples show
it: `nothing new from Databricks` and `did you ever hear from Retool` both propose a
`Place`. The same words in a different frame (`We use Databricks daily`) propose
nothing, so the error is frame-sensitive rather than deterministic.

This is **not** filtered by a second guess. Suppressing a `GPE` because the token also
looks like a company would be extraction deciding, and it would silently drop the
`Hermes`-the-street case to protect the `Hermes`-the-company one. The mitigation is
the design's own: a Place node is derived and re-runnable, `mention_count` makes a
one-off obvious, and `link` never fuzzy-merges an entity — so a stray `place:retool`
costs a node, not a merge, and deleting it touches no message.
"""
from __future__ import annotations

import html
import re
from collections.abc import Iterable
from dataclasses import dataclass

from spacy.language import Language
from spacy.tokens import Span


# The spaCy labels that mean "a place". Anything else spaCy proposes is ignored —
# an `ORG` is not a `Place` even when the words look like one (`Kensington Market`
# comes back as an ORG, and guessing otherwise would be extraction deciding).
PLACE_LABELS: tuple[str, ...] = ("GPE", "LOC", "FAC")

# The spaCy label that means "an organisation" — deliberately BROAD, matching the
# CoNLL/OntoNotes scheme the model was trained on: companies, government bodies,
# councils, NGOs, unions, clubs, societies, universities, teams.
#
# **One label, one kind.** A span is a Place or an Organization, never both — the
# `_mentions_from_doc` loop assigns exactly one kind per entity, so the two kinds can
# never be minted from the same words. That is the same boundary the Place comments
# draw from the other side.
ORG_LABELS: tuple[str, ...] = ("ORG",)

# A span that ENDS on one of these was cut short by the model, not named. Measured on
# `en_core_web_sm`: `University of Sydney` came back as `University of`, which would
# have become its own node. Dropped rather than extended — extending means deciding
# where the name stops, which is extraction inventing.
TRUNCATION_TAILS = frozenset({"of", "the", "and", "de", "du", "des", "for"})

# A shipped ORG dictionary, applied by the same `EntityRuler` as the place list.
#
# **Why it is needed, measured not assumed.** Over 18 clearly-named organisations,
# `en_core_web_sm` found 13. It missed exactly the names it was never trained to treat as
# institutions: product-style company names (`Snowflake`, `Databricks`, `BlackRock`),
# and an NGO whose name is not English (`Medecins Sans Frontieres`). It also split
# `Unite the Union` down to `Union`.
#
# This is not a substitute for the model — it is the same audit table `PLACE_DICTIONARY`
# is, for the names the model silently drops. Keep it boring: every entry is a claim
# that the words name an organisation. The Owner's own graph is the useful seed.
ORG_DICTIONARY: tuple[str, ...] = (
    # Product-style company names the model reads as brands, not institutions.
    "Snowflake", "Databricks", "BlackRock", "Scale AI", "Weights & Biases",
    "OpenAI", "Anthropic", "Retool", "Celestica", "Palantir", "Stripe",
    "Shopify", "Twilio", "Cloudflare", "MongoDB", "Hugging Face",
    # NGOs and bodies whose names are not English, which the English model skips.
    "Medecins Sans Frontieres", "Médecins Sans Frontières", "Amnesty International",
    "Oxfam", "Greenpeace", "Red Cross", "Brotherhood of St Laurence",
    # Long forms the model truncates or partial-matches.
    "Unite the Union", "University of Sydney", "NSW Health",
    # --- Curated list (2026-11-24) ---
    # Merged, not replaced: the nine names above are the ones the model was measured to
    # miss, and they stay. A name listed in both PRODUCTS and here resolves to ORG —
    # `_arbitrate` never demotes an ORG span, and the ruler's GPE beats ORG on a tie.
    # --- Tech & data platforms ---
    "Datadog", "Grafana Labs", "Confluent", "HashiCorp", "Elastic", "GitHub",
    "GitLab", "Atlassian", "Mistral AI", "DeepMind", "Red Hat", "Canonical",
    "VMware", "Microsoft", "Google", "Alphabet", "Amazon Web Services",
    "Netflix", "Spotify", "Nvidia", "Intel", "Advanced Micro Devices",
    "Qualcomm", "Broadcom", "Cisco", "Dell Technologies", "Lenovo", "Samsung",
    "Sony", "Siemens", "SAP", "Adobe", "Salesforce", "ServiceNow", "Workday",
    "Zendesk", "HubSpot", "Okta", "CrowdStrike", "Uber", "Lyft", "Airbnb",
    "DoorDash", "Deliveroo", "Just Eat Takeaway", "Booking Holdings", "Expedia",
    "Tripadvisor", "Skyscanner", "Canva", "Figma", "Notion Labs", "Dropbox",
    "Zoom Video Communications", "PayPal", "Klarna", "Revolut", "Monzo",
    "Wise Payments", "Adyen", "Coinbase", "Binance", "Block Inc", "Tesla",
    "SpaceX", "Rivian", "ByteDance", "Tencent", "Alibaba", "Baidu", "Huawei",
    "Xiaomi", "Infosys", "Tata Consultancy Services", "Wipro", "Cognizant",
    "Accenture", "Capgemini", "Naspers", "Prosus", "Flutterwave", "Paystack",
    "Takealot", "Gojek", "Grab Holdings", "Sea Limited", "Rakuten",
    "Mercado Libre", "Nubank", "Zalando", "Spotify Technology",
    "Wikimedia Foundation", "Mozilla", "Linux Foundation",
    "Apache Software Foundation",
    # --- Telecoms ---
    "Vodafone", "Vodacom", "MTN", "Safaricom", "Airtel", "Telkom", "Telstra",
    "Verizon", "AT&T", "T-Mobile", "Deutsche Telekom", "Telefónica", "Singtel",
    "Jio Platforms",
    # --- Banks, insurers, asset managers, exchanges ---
    "JPMorgan Chase", "Goldman Sachs", "Morgan Stanley", "Citigroup",
    "Bank of America", "Wells Fargo", "HSBC", "Barclays", "Lloyds Banking Group",
    "NatWest", "Standard Chartered", "Santander", "BBVA", "UBS", "Credit Suisse",
    "Deutsche Bank", "BNP Paribas", "Société Générale", "Crédit Agricole", "ING",
    "ABN Amro", "Rabobank", "Nordea", "Danske Bank", "Commerzbank", "UniCredit",
    "Intesa Sanpaolo", "Mizuho", "Mitsubishi UFJ Financial Group",
    "Sumitomo Mitsui", "DBS", "OCBC", "United Overseas Bank", "ICICI Bank",
    "HDFC Bank", "State Bank of India", "Royal Bank of Canada", "TD Bank",
    "Scotiabank", "Commonwealth Bank", "Westpac", "ANZ",
    "National Australia Bank", "Standard Bank", "Absa", "Nedbank", "FirstRand",
    "Capitec", "Access Bank", "Zenith Bank", "Guaranty Trust Bank", "Ecobank",
    "Equity Bank", "Itaú", "Bradesco", "Vanguard", "Fidelity Investments",
    "State Street", "Blackstone", "KKR", "Carlyle", "Apollo Global Management",
    "Bridgewater Associates", "Citadel", "Mastercard", "American Express",
    "Berkshire Hathaway", "Allianz", "AXA", "Zurich Insurance", "Aviva",
    "Legal & General", "Munich Re", "Swiss Re", "Old Mutual", "Sanlam",
    "Moody's", "S&P Global", "London Stock Exchange", "Nasdaq", "Bloomberg",
    # --- Consultancies, audit, law ---
    "McKinsey & Company", "Boston Consulting Group", "Bain & Company",
    "Deloitte", "PwC", "KPMG", "Ernst & Young", "Oliver Wyman", "Roland Berger",
    "Booz Allen Hamilton", "Clifford Chance", "Linklaters", "Freshfields",
    "Baker McKenzie", "Latham & Watkins",
    # --- Retail & consumer ---
    "Walmart", "Costco", "Tesco", "Sainsbury's", "Asda", "Aldi", "Lidl",
    "Carrefour", "IKEA", "H&M", "Inditex", "Marks & Spencer", "John Lewis",
    "Woolworths", "Pick n Pay", "Shoprite", "Checkers", "Home Depot", "Best Buy",
    "Currys", "MediaMarkt", "Walgreens", "Nike", "Adidas", "Puma", "Lululemon",
    "Uniqlo", "Patagonia", "Starbucks", "McDonald's", "Nando's", "Domino's",
    "Pret A Manger", "Costa Coffee", "Unilever", "Procter & Gamble", "Nestlé",
    "Coca-Cola", "PepsiCo", "Diageo", "Heineken", "AB InBev", "Danone",
    "Mondelez", "L'Oréal", "LVMH", "Hermès", "Kering", "Richemont", "Burberry",
    "Rolex", "Ferrari", "Porsche", "Toyota", "Volkswagen", "BMW",
    "Mercedes-Benz", "Ford", "General Motors", "Honda", "Nissan", "Hyundai",
    "Kia", "Volvo", "Renault", "Stellantis", "Tata Motors", "BYD",
    # --- Airlines ---
    "British Airways", "Lufthansa", "Air France", "KLM", "Emirates",
    "Qatar Airways", "Etihad", "Turkish Airlines", "Singapore Airlines",
    "Cathay Pacific", "Qantas", "Delta Air Lines", "United Airlines",
    "American Airlines", "Southwest Airlines", "Ryanair", "easyJet", "Wizz Air",
    "Air Canada", "Ethiopian Airlines", "Kenya Airways", "South African Airways",
    "FlySafair", "Virgin Atlantic", "Air New Zealand", "LATAM", "Avianca",
    "Japan Airlines", "All Nippon Airways", "Korean Air", "Air India", "IndiGo",
    "Garuda Indonesia", "Thai Airways", "Vietnam Airlines",
    "Philippine Airlines", "Jet2", "Iberia", "Finnair", "Aer Lingus",
    "Swiss International Air Lines", "JetBlue", "Alaska Airlines",
    # --- Energy, industrials, mining, logistics ---
    "BP", "ExxonMobil", "Chevron", "TotalEnergies", "Equinor", "Saudi Aramco",
    "Eni", "Repsol", "Sasol", "Eskom", "Orsted", "Vestas", "National Grid",
    "Electricité de France", "Enel", "Iberdrola", "Octopus Energy", "Boeing",
    "Airbus", "Rolls-Royce", "BAE Systems", "Lockheed Martin",
    "General Electric", "Caterpillar", "Honeywell", "ABB", "Schneider Electric",
    "Maersk", "DHL", "FedEx", "Rio Tinto", "BHP", "Glencore", "Vale",
    "ArcelorMittal", "Anglo American", "Gold Fields", "Sibanye-Stillwater",
    "Impala Platinum", "De Beers", "Dangote Group",
    # --- Healthcare & pharma ---
    "Pfizer", "Moderna", "Novartis", "Roche", "Johnson & Johnson", "AstraZeneca",
    "GlaxoSmithKline", "Sanofi", "Novo Nordisk", "Bayer", "Eli Lilly",
    "Medtronic", "Mayo Clinic", "Cleveland Clinic", "Kaiser Permanente", "Bupa",
    "Discovery Health", "Mediclinic", "Netcare", "UnitedHealth Group", "Cigna",
    "Aetna",
    # --- Media & entertainment ---
    "BBC", "CNN", "Reuters", "Associated Press", "Financial Times",
    "The Guardian", "The New York Times", "The Wall Street Journal",
    "The Economist", "Al Jazeera", "Walt Disney Company",
    "Warner Bros. Discovery", "Comcast", "Channel 4", "ITV", "News Corp",
    "Condé Nast", "Penguin Random House", "Universal Music Group", "Sony Music",
    "Multichoice",
    # --- Government, regulators, international bodies ---
    "European Commission", "European Central Bank", "European Union",
    "International Monetary Fund", "World Bank", "World Health Organization",
    "World Trade Organization", "United Nations", "NATO", "OECD",
    "Federal Reserve", "Bank of England", "Reserve Bank of India",
    "South African Reserve Bank", "Securities and Exchange Commission",
    "Federal Trade Commission", "Food and Drug Administration",
    "Centers for Disease Control and Prevention",
    "Environmental Protection Agency", "Department of Homeland Security",
    "Federal Bureau of Investigation", "NASA", "Internal Revenue Service",
    "HM Revenue and Customs", "National Health Service", "Home Office",
    "Foreign Office", "Financial Conduct Authority",
    "Competition and Markets Authority", "Ofcom",
    "South African Revenue Service", "Department of Home Affairs",
    "Australian Taxation Office", "Canada Revenue Agency",
    "European Space Agency", "CERN", "UNHCR", "UNICEF", "World Food Programme",
    "World Economic Forum",
    # --- Universities & business schools ---
    "Harvard University", "Stanford University",
    "Massachusetts Institute of Technology", "Yale University",
    "Princeton University", "Columbia University", "University of Chicago",
    "Cornell University", "Duke University", "Northwestern University",
    "Johns Hopkins University", "Carnegie Mellon University",
    "California Institute of Technology", "New York University",
    "University of California", "University of Oxford",
    "University of Cambridge", "Imperial College London",
    "London School of Economics", "University College London",
    "King's College London", "University of Edinburgh",
    "University of Manchester", "University of Warwick", "Durham University",
    "ETH Zurich", "EPFL", "Sorbonne University",
    "Technical University of Munich", "Humboldt University",
    "Heidelberg University", "Leiden University", "University of Amsterdam",
    "KU Leuven", "Karolinska Institute", "University of Copenhagen",
    "Bocconi University", "INSEAD", "IESE Business School",
    "London Business School", "HEC Paris", "University of Toronto",
    "McGill University", "University of British Columbia",
    "University of Waterloo", "University of Melbourne",
    "Australian National University", "University of Auckland",
    "National University of Singapore", "Nanyang Technological University",
    "University of Hong Kong", "Tsinghua University", "Peking University",
    "Fudan University", "University of Tokyo", "Kyoto University",
    "Seoul National University", "KAIST", "Indian Institute of Technology",
    "Indian Institute of Management", "University of Cape Town",
    "University of the Witwatersrand", "Stellenbosch University",
    "University of Pretoria", "University of Nairobi", "University of Lagos",
    "American University in Cairo", "University of São Paulo",
    "Universidad Nacional Autónoma de México",
    # --- NGOs, charities, foundations ---
    "Doctors Without Borders", "Médecins du Monde",
    "International Committee of the Red Cross", "World Wildlife Fund",
    "Save the Children", "Habitat for Humanity",
    "Bill & Melinda Gates Foundation", "Wellcome Trust", "Rotary International",
    "Salvation Army", "Cancer Research UK", "Comic Relief", "Human Rights Watch",
    "Transparency International", "Electronic Frontier Foundation",
    "Islamic Relief", "Mercy Corps", "Caritas",
    # --- Sports clubs ---
    "Manchester United", "Manchester City", "Liverpool FC", "Arsenal",
    "Tottenham Hotspur", "Real Madrid", "FC Barcelona", "Atlético Madrid",
    "Bayern Munich", "Borussia Dortmund", "Juventus", "AC Milan", "Inter Milan",
    "Paris Saint-Germain", "Ajax", "Celtic", "Kaizer Chiefs", "Orlando Pirates",
    "Mamelodi Sundowns", "Al Ahly", "Los Angeles Lakers",
    "Golden State Warriors", "Boston Celtics", "Chicago Bulls",
    "New York Yankees", "Dallas Cowboys", "New England Patriots",
    "Green Bay Packers", "Mumbai Indians", "Chennai Super Kings",
    "Red Bull Racing", "McLaren Racing",
)

# Below this many characters a span is noise (`NY` survives, `N` does not). Applied
# after trimming, never to the canonical form: `canon` owns that decision.
MIN_SPAN_CHARS = 2

# A body above this many characters is not a chat message, and running chat-oriented
# NER over it is a category error.
# **Measured, not guessed.** On the live store of 2,085 messages the length
# distribution is: median 28 chars, p95 77, p99 122, max 11,719. Every junk
# Organization we saw (`pdf`, `swf`, `pptm`, `wordprocessing ml 2003`,
# `end user license agreement`, `jasper reports`) came from exactly ONE message — a
# 11,719-character marketing newsletter — which is 96x the p99.
#
# So the noise was never a long tail of uncertain mentions. It was one document being
# read as if it were a conversation. A frequency threshold (`count >= 2`) would have
# kept every one of those junk nodes, because the real signal (`sox`, 15 mentions
# across two platforms) and the junk differ by LENGTH, not by count.
#
# The number is derived, not chosen: 4x the p99 of this corpus (122 chars) rounded up to
# a clean boundary, i.e. ~400 chars. A genuine long message — a forwarded brief, a
# pasted transcript, a long email — sits in the hundreds and still extracts. The guard
# only catches a body that is orders of magnitude out of family with the corpus, which
# is what the 11,719-char newsletter was.
#
# **Getting this wrong once already:** the first version used 12,000, one round number
# picked by eye, which sat just ABOVE the 11,719-char message it was written to catch and
# therefore did nothing. A threshold next to the case it targets is a coincidence, not a
# rule; derive it from the distribution and the mistake cannot recur.
DOCUMENT_CHARS = 2_000

# Is the `Product` kind live? **Off until its dictionary exists.**
#
# The arbitration below is real and tested with the flag on, but a `Product` leg with no
# product vocabulary would be a guess: `en_core_web_sm` has no `PRODUCT` label at all, so
# the only thing that can claim a span is a dictionary entry, and there is no index yet
# (`TECHREADME.md` §5). Off means the seam exists, is exercised by tests,
# and writes nothing — the live store and every existing count are unchanged.
#
# Deliberately a module constant and not an env var: a switch that can differ between two
# machines running the same code makes a store impossible to explain.
PRODUCT_ENABLED = True

# A shipped place dictionary, applied by spaCy's `EntityRuler` **before** the learned
# NER. This is not a nicety: `en_core_web_sm` labels a bare city `PERSON` when the
# sentence gives no locative cue (`Then Austin on Friday` -> PERSON, `I am in Austin` ->
# GPE). Relying on the model alone would silently drop a real place for a reason the
# user cannot see or act on, which is precisely the failure the extraction design
# calls unacceptable. The ruler is a deliberate, auditable counterweight.
#
# Keep this list boring and English: every entry is a claim that a token is a place.
PLACE_DICTIONARY: tuple[str, ...] = (
    "Amsterdam", "Athens", "Atlanta", "Auckland", "Austin", "Baghdad",
    "Bangkok", "Barcelona", "Beijing", "Belfast", "Berlin", "Birmingham",
    "Bogota", "Bombay", "Boston", "Brisbane", "Brussels", "Budapest",
    "Buenos Aires", "Cairo", "Calgary", "Cape Town", "Cardiff", "Chicago",
    "Copenhagen", "Dallas", "Delhi", "Denver", "Detroit", "Dubai",
    "Dublin", "Durban", "Edinburgh", "Frankfurt", "Geneva", "Glasgow",
    "Hamburg", "Helsinki", "Hong Kong", "Houston", "Istanbul", "Jakarta",
    "Johannesburg", "Kansas City", "Kuala Lumpur", "Lagos", "Las Vegas",
    "Leeds", "Lisbon", "Liverpool", "London", "Los Angeles", "Madrid",
    "Manchester", "Manila", "Melbourne", "Mexico City", "Miami", "Milan",
    "Montreal", "Moscow", "Mumbai", "Nairobi", "New York", "Newcastle",
    "Oslo", "Ottawa", "Paris", "Perth", "Philadelphia", "Phoenix", "Prague",
    "Pretoria", "Rio de Janeiro", "Rome", "San Francisco", "Santiago",
    "Sao Paulo", "Seattle", "Seoul", "Shanghai", "Singapore", "Stockholm",
    "Sydney", "Taipei", "Tokyo", "Toronto", "Vancouver", "Vienna",
    "Warsaw", "Washington", "Wellington", "Zurich",
    # The generated samples' own pool, so a public clone exercises the pipeline.
    "North Dakota", "Fargo", "Bismarck", "Bay Area",
    # --- Curated gazetteer (2026-11-24) ---
    # Merged from `temp-lists`, not pasted over the list above: the entries already here
    # are the ones the pipeline was tested against, and several of them (the sample pool
    # above) exist so a public clone has something to find.
    # --- Africa: cities ---
    "Abuja", "Kano", "Ibadan", "Port Harcourt", "Accra", "Kumasi", "Mombasa",
    "Kisumu", "Addis Ababa", "Dar es Salaam", "Dodoma", "Arusha", "Zanzibar",
    "Kampala", "Entebbe", "Kigali", "Lusaka", "Harare", "Bulawayo", "Maputo",
    "Luanda", "Windhoek", "Gaborone", "Lilongwe", "Soweto", "Sandton",
    "Stellenbosch", "Gqeberha", "Bloemfontein", "Polokwane", "Alexandria",
    "Giza", "Luxor", "Casablanca", "Marrakech", "Rabat", "Tangier", "Tunis",
    "Algiers", "Tripoli", "Dakar", "Abidjan", "Bamako", "Ouagadougou", "Conakry",
    "Freetown", "Monrovia", "Lomé", "Cotonou", "Kinshasa", "Lubumbashi",
    "Brazzaville", "Douala", "Yaoundé", "Libreville", "Khartoum", "Mogadishu",
    "Antananarivo", "Port Louis", "Maseru",
    # --- Africa: countries / regions ---
    "Nigeria", "Ghana", "Kenya", "Ethiopia", "Tanzania", "Uganda", "Rwanda",
    "Zambia", "Zimbabwe", "Mozambique", "Angola", "Namibia", "Botswana",
    "Malawi", "South Africa", "Egypt", "Morocco", "Tunisia", "Algeria", "Libya",
    "Senegal", "Ivory Coast", "Mali", "Cameroon", "Sudan", "Somalia",
    "Mauritius", "Madagascar", "Lesotho", "Eswatini",
    "Democratic Republic of the Congo", "Western Cape", "Gauteng",
    "KwaZulu-Natal",
    # --- Middle East & Central Asia ---
    "Abu Dhabi", "Sharjah", "Doha", "Riyadh", "Jeddah", "Mecca", "Medina",
    "Kuwait City", "Manama", "Muscat", "Amman", "Beirut", "Damascus", "Tehran",
    "Isfahan", "Tel Aviv", "Jerusalem", "Haifa", "Ankara", "Izmir", "Baku",
    "Tbilisi", "Yerevan", "Almaty", "Astana", "Tashkent", "Bishkek", "Kabul",
    "United Arab Emirates", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman",
    "Lebanon", "Iraq", "Iran", "Israel", "Turkey", "Azerbaijan", "Armenia",
    "Kazakhstan", "Uzbekistan", "Afghanistan",
    # --- South Asia ---
    "New Delhi", "Bangalore", "Bengaluru", "Hyderabad", "Chennai", "Kolkata",
    "Pune", "Ahmedabad", "Jaipur", "Surat", "Lucknow", "Kochi", "Goa",
    "Chandigarh", "Gurgaon", "Gurugram", "Noida", "Indore", "Nagpur",
    "Coimbatore", "Thiruvananthapuram", "Karachi", "Lahore", "Islamabad",
    "Rawalpindi", "Peshawar", "Dhaka", "Chittagong", "Colombo", "Kandy",
    "Kathmandu", "Thimphu", "India", "Pakistan", "Bangladesh", "Sri Lanka",
    "Nepal", "Bhutan", "Maldives", "Kerala", "Rajasthan", "Maharashtra",
    "Tamil Nadu", "Karnataka",
    # --- Southeast Asia ---
    "Surabaya", "Bandung", "Bali", "Denpasar", "Yogyakarta", "Medan", "Penang",
    "Johor Bahru", "Chiang Mai", "Phuket", "Pattaya", "Hanoi",
    "Ho Chi Minh City", "Saigon", "Da Nang", "Cebu", "Davao", "Quezon City",
    "Makati", "Phnom Penh", "Siem Reap", "Vientiane", "Yangon", "Indonesia",
    "Malaysia", "Thailand", "Vietnam", "Philippines", "Cambodia", "Laos",
    "Myanmar", "Brunei",
    # --- East Asia ---
    "Osaka", "Kyoto", "Yokohama", "Nagoya", "Sapporo", "Fukuoka", "Kobe",
    "Hiroshima", "Busan", "Incheon", "Shenzhen", "Guangzhou", "Chengdu",
    "Hangzhou", "Wuhan", "Xi'an", "Nanjing", "Chongqing", "Tianjin", "Suzhou",
    "Kowloon", "Macau", "Kaohsiung", "Ulaanbaatar", "Japan", "China",
    "South Korea", "North Korea", "Taiwan", "Mongolia",
    # --- Oceania ---
    "Adelaide", "Canberra", "Gold Coast", "Hobart", "Darwin", "Cairns",
    "Wollongong", "Bondi", "Christchurch", "Queenstown", "Dunedin", "Suva",
    "Port Moresby", "Apia", "Nouméa", "Papeete", "Tahiti", "Tasmania",
    "Queensland", "New South Wales", "Western Australia", "Australia",
    "New Zealand", "Fiji", "Samoa", "Tonga", "Vanuatu", "Papua New Guinea",
    # --- South America ---
    "São Paulo", "Brasília", "Salvador", "Belo Horizonte", "Fortaleza", "Recife",
    "Porto Alegre", "Curitiba", "Florianópolis", "Manaus", "Rosario", "Mendoza",
    "Valparaíso", "Lima", "Cusco", "Arequipa", "Bogotá", "Medellín", "Cali",
    "Cartagena", "Quito", "Guayaquil", "Caracas", "Montevideo", "Asunción",
    "La Paz", "Patagonia", "Brazil", "Argentina", "Chile", "Peru", "Colombia",
    "Ecuador", "Venezuela", "Uruguay", "Paraguay", "Bolivia",
    # --- Central America & Caribbean ---
    "Guadalajara", "Monterrey", "Cancún", "Tijuana", "Puebla", "Oaxaca",
    "Guatemala City", "San Salvador", "Tegucigalpa", "Managua", "Panama City",
    "Havana", "Kingston", "Nassau", "Santo Domingo", "Port-au-Prince",
    "San Juan", "Bridgetown", "Port of Spain", "Punta Cana", "Mexico",
    "Guatemala", "Costa Rica", "Panama", "Cuba", "Jamaica", "Bahamas",
    "Barbados", "Trinidad and Tobago", "Dominican Republic", "Haiti",
    "Puerto Rico", "Honduras", "El Salvador", "Nicaragua",
    # --- United States ---
    "San Antonio", "San Diego", "San Jose", "Jacksonville", "Fort Worth",
    "Columbus", "Charlotte", "Indianapolis", "Nashville", "Portland", "Memphis",
    "Louisville", "Baltimore", "Milwaukee", "Albuquerque", "Tucson", "Fresno",
    "Sacramento", "Raleigh", "Omaha", "Minneapolis", "Tampa", "Orlando",
    "New Orleans", "Cleveland", "Pittsburgh", "Cincinnati", "St. Louis",
    "Salt Lake City", "Oakland", "Honolulu", "Anchorage", "Boise", "Richmond",
    "Charleston", "Savannah", "Palo Alto", "Silicon Valley", "Berkeley",
    "Brooklyn", "Manhattan", "Queens", "Harlem", "Hollywood", "Santa Monica",
    "Napa Valley", "the Bay Area", "New England", "the Midwest", "California",
    "Texas", "Florida", "United States",
    # --- Canada ---
    "Edmonton", "Winnipeg", "Quebec City", "Halifax", "Saskatoon", "Mississauga",
    "Ontario", "British Columbia", "Alberta", "Quebec", "Canada",
    # --- UK & Ireland ---
    "Bristol", "Sheffield", "Nottingham", "Leicester", "Oxford", "Cambridge",
    "Brighton", "York", "Southampton", "Aberdeen", "Dundee", "Milton Keynes",
    "Shoreditch", "Hackney", "Camden", "Soho", "Kensington", "Chelsea",
    "Islington", "Canary Wharf", "Notting Hill", "Brixton", "Peckham", "Cork",
    "Galway", "Limerick", "England", "Scotland", "Wales", "Northern Ireland",
    "Ireland", "United Kingdom", "Cornwall", "Yorkshire", "the Cotswolds",
    "the Lake District",
    # --- France ---
    "Lyon", "Marseille", "Toulouse", "Nantes", "Strasbourg", "Bordeaux", "Lille",
    "Montpellier", "Cannes", "Montmartre", "Provence", "Normandy", "Brittany",
    "Alsace", "Burgundy", "France",
    # --- Germany ---
    "Munich", "Cologne", "Stuttgart", "Düsseldorf", "Dortmund", "Leipzig",
    "Dresden", "Hanover", "Nuremberg", "Bremen", "Bonn", "Heidelberg",
    "Kreuzberg", "Neukölln", "Prenzlauer Berg", "Bavaria", "Saxony", "Germany",
    # --- Spain & Portugal ---
    "Valencia", "Seville", "Bilbao", "Málaga", "Zaragoza", "Palma", "Granada",
    "San Sebastián", "Ibiza", "Mallorca", "Tenerife", "Catalonia", "Andalusia",
    "Canary Islands", "Spain", "Porto", "Faro", "Algarve", "Madeira", "Portugal",
    # --- Italy ---
    "Naples", "Turin", "Florence", "Venice", "Bologna", "Genoa", "Verona",
    "Palermo", "Catania", "Bari", "Pisa", "Tuscany", "Sicily", "Sardinia",
    "Lombardy", "Puglia", "Amalfi", "Italy",
    # --- Benelux, Alpine, Nordics ---
    "Rotterdam", "The Hague", "Utrecht", "Eindhoven", "Netherlands", "Antwerp",
    "Ghent", "Bruges", "Belgium", "Luxembourg", "Basel", "Bern", "Lausanne",
    "Zug", "Switzerland", "Salzburg", "Graz", "Innsbruck", "Austria", "Aarhus",
    "Denmark", "Gothenburg", "Malmö", "Sweden", "Bergen", "Norway", "Finland",
    "Reykjavik", "Iceland",
    # --- Central & Eastern Europe, Balkans, Baltics ---
    "Kraków", "Gdańsk", "Wrocław", "Poland", "Brno", "Czechia", "Bratislava",
    "Slovakia", "Hungary", "Bucharest", "Cluj-Napoca", "Romania", "Sofia",
    "Bulgaria", "Thessaloniki", "Crete", "Santorini", "Greece", "Zagreb",
    "Dubrovnik", "Croatia", "Belgrade", "Serbia", "Ljubljana", "Slovenia",
    "Sarajevo", "Tallinn", "Riga", "Vilnius", "Estonia", "Latvia", "Lithuania",
    "Kyiv", "Lviv", "Odesa", "Ukraine", "Saint Petersburg", "Russia", "Minsk",
    "Belarus", "Malta", "Valletta", "Cyprus", "Monaco", "Tirana", "Albania",
    "Montenegro", "North Macedonia", "Skopje",
)


@dataclass(frozen=True)
class Mention:
    """One proposed place, with where it came from. Not yet a node, not yet a key.

    `message_key` and the offsets are the provenance the design insists on: a mention
    can be re-derived, re-scored or thrown away without asking the graph anything.

    `platform` rides along because folding is per platform, and asking the store for it
    later would be a second query for a fact the caller already has.
    """

    text: str
    label: str
    start: int
    end: int
    message_key: str
    platform: str
    # Which canonicalisation kind and store label this mention belongs to:
    # `"place"`, `"organization"` or `"product"`. Set here, because something has to
    # resolve the competing labels, and resolving it in the writer would mean re-deciding
    # per row what was already decided per span.
    kind: str = "place"
    # Every kind this span could plausibly be, strongest first — **provenance, not a
    # decision**. `kind` is what gets written; this is the record of what lost and why a
    # later reviewer might disagree. It exists because the arbitration is the newest and
    # least proven part of the pipeline (`TECHREADME.md` §5), and a wrong
    # choice should be visible without re-running the extractor.
    #
    # Empty on a mention from a path that never arbitrates (the old single-kind helpers),
    # so a caller can tell "considered and rejected" from "never considered".
    candidates: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "message_key": self.message_key,
            "platform": self.platform,
            "kind": self.kind,
            "candidates": list(self.candidates),
        }


# The loaded pipeline. Loading is ~1s and allocates tens of MB, so it happens once,
# on first use, and a failure is remembered rather than retried per message.
_NLP = None
_LOAD_ERROR: str | None = None


def available() -> bool:
    """Is the English extractor installed and loadable?

    Checked by the ingest so a missing model is one warning on the report rather than
    a stack trace per batch, and so the rest of the run is unaffected.
    """
    _ensure_model()
    return _NLP is not None


def unavailable_reason() -> str:
    """Why `available()` said no, as a sentence a report can print. Empty when loaded."""
    _ensure_model()
    return _LOAD_ERROR or ""


def _ensure_model() -> None:
    global _NLP, _LOAD_ERROR
    if _NLP is not None or _LOAD_ERROR is not None:
        return
    try:
        import spacy
    except ImportError:
        _LOAD_ERROR = (
            "entity extraction skipped: spacy is not installed "
            "(python -m pip install spacy && python -m spacy download en_core_web_sm)"
        )
        return
    try:
        _NLP = spacy.load("en_core_web_sm", exclude=["lemmatizer", "attribute_ruler"])
    except OSError:
        _LOAD_ERROR = (
            "entity extraction skipped: the English model is not installed "
            "(python -m spacy download en_core_web_sm)"
        )
        return
    _install_ruler()


# `casefolded entry -> spaCy label` for the promotion pass. Built once from the two
# dictionaries; a name in both resolves to `GPE`, matching the ruler's own precedence.
_DICTIONARY_LABELS: dict[str, str] = {
    **{name.casefold(): "ORG" for name in ORG_DICTIONARY},
    **{name.casefold(): "GPE" for name in PLACE_DICTIONARY},
}

# Labels the dictionary may overrule. A `DATE` or `CARDINAL` that spells a city is a
# different reading of the same word, and the model is the better judge of that.
#
# **`FAC` is here because of `Paris Saint-Germain`.** The model reads a football club as
# a facility, and `FAC` means Place, so a curated organization was landing as
# `place:paris saint-germain`. A `FAC` span that is exactly a dictionary entry is the
# dictionary's to decide; one that is not (`12 Baker Street`) is untouched.
_PROMOTABLE_LABELS: frozenset[str] = frozenset({"PERSON", "ORG", "NORP", "FAC"})


def _pattern_form(display: str) -> str:
    """The string the ruler should match for an index entry.

    A leading `The ` is dropped: `canon` already ignores it for the key, and a pattern
    that requires the article cannot match the way people write (`North Face Nuptse`).
    """
    text = display.strip()
    if text.lower().startswith("the ") and len(text) > 4:
        return text[4:]
    return text


@Language.component("model_span_snapshot")
def _model_span_snapshot(doc):
    """Remember what the learned pass found, before the ruler is allowed to overwrite it.

    The ruler needs `overwrite_ents=True` or a multi-word product never wins: `Toyota
    Hilux` arrives as `Toyota` (ORG) + `Hilux` (PRODUCT), and a non-overwriting ruler
    skips the phrase because its tokens are already claimed. But overwriting is also what
    truncated `Kensington Market` to `place:kensington`.

    So the model's spans are recorded here and restored afterwards, and the two rules
    stop fighting: the ruler wins where it has a **phrase**, the model keeps a span it
    found that is **longer** than the ruler's.
    """
    doc.user_data["model_ents"] = [(e.start, e.end, e.label_) for e in doc.ents]
    return doc


@Language.component("dictionary_promote")
def _dictionary_promote(doc):
    """Make an **exact, whole-span** dictionary hit authoritative over the model's label.

    This is the second half of the dictionary's authority, and it exists because the
    first half (`overwrite_ents` on a ruler placed *before* `ner`) had a cost that only
    showed up once the gazetteer got large.

    **What went wrong.** `overwrite_ents` lets a dictionary hit replace whatever the
    learned pass produced. That is what makes `Then Austin on Friday` a `GPE` instead of
    the `PERSON` the model guesses. But it also lets a one-word entry *truncate* a longer
    name: `Kensington Market` is an `ORG` to the model, and a gazetteer holding
    `Kensington` cut it to `place:kensington`. Measured on the 2026-11-24 list: 32
    organizations and 8 products begin with a place name (`London Stock Exchange`,
    `Canada Goose Expedition Parka`), and `Kensington Market` is the case a test pins.

    **The fix, and why it is shaped this way.** The ruler now runs *after* `ner` with
    `overwrite_ents=False`, so it can only add spans the model missed and never shortens
    one it found. That alone would lose the `PERSON` rescue, so this pass restores it:
    when the model's span is **exactly** a dictionary entry, the dictionary's label wins.
    Exactness is the whole safety argument — `Kensington Market` is not an entry, so it is
    left as the `ORG` the model found; `Austin` is, so it is promoted from `PERSON`.

    Only `PERSON`/`ORG`/`NORP` are promoted. A `DATE` or `CARDINAL` that happens to spell
    a city is a different reading of the same word, and the model is the better judge.
    """
    if not doc.ents:
        return doc

    # 1. Restore a model span the ruler truncated. Only when it starts at the same token
    #    and is strictly longer — that is the `Kensington Market` shape, and nothing else.
    #    A ruler phrase that *contains* the model's spans (`Toyota Hilux`) is untouched,
    #    because no model span starts where it starts and is longer.
    keep = list(doc.ents)
    for start, end, label in doc.user_data.get("model_ents", ()):
        for current in list(keep):
            if current.start == start and end > current.end:
                keep.remove(current)
                keep.append(Span(doc, start, end, label=label))
                break

    # 2. An exact whole-span dictionary hit is the dictionary's to label. This is what
    #    keeps `Then Austin on Friday` a Place rather than the `PERSON` the model guessed.
    out = []
    for ent in keep:
        label = _DICTIONARY_LABELS.get(ent.text.casefold())
        if label and ent.label_ in _PROMOTABLE_LABELS:
            out.append(Span(doc, ent.start, ent.end, label=label))
        else:
            out.append(ent)
    doc.ents = sorted(out, key=lambda span: span.start)
    return doc


def _install_ruler() -> None:
    """Put a place dictionary in front of the learned NER.

    `before="ner"` and `overwrite_ents=True` together are what make the dictionary
    authoritative: the ruler's span wins over the learned pass, so `Then Austin on
    Friday` is a GPE rather than the PERSON the model would have produced. A `FAC` the
    model finds and the dictionary does not (`12 Baker Street`) is untouched — the
    ruler only speaks about the names it was given.
    """
    if _NLP is None or "place_ruler" in _NLP.pipe_names:
        return
    # Renamed in spirit, kept as `place_ruler` so an existing pipeline is not rebuilt.
    # One pipe holds both dictionaries: `overwrite_ents` gives the ruler precedence over
    # the learned pass, and two pipes would only make that precedence harder to reason
    # about (the second would silently win on an overlapping span).
    # **After `ner`, overwriting, with the model's spans snapshotted first.** The three
    # pieces are one mechanism and none of them works alone:
    #
    #   snapshot   records what the learned pass found
    #   ruler      overwrites, so a multi-word phrase wins (`Toyota Hilux`)
    #   promote    restores a longer model span the ruler truncated (`Kensington Market`)
    #              and re-labels an exact dictionary hit (`Then Austin on Friday`)
    #
    # Measured on the 2026-11-24 lists: 32 organizations and 8 products begin with a place
    # name, and 724 product entries were absent from the ruler entirely.
    _NLP.add_pipe("model_span_snapshot", after="ner")
    ruler = _NLP.add_pipe("entity_ruler", name="place_ruler", after="model_span_snapshot",
                         config={"overwrite_ents": True})
    ruler.add_patterns([
        {"label": "GPE", "pattern": name, "id": name.casefold()}
        for name in PLACE_DICTIONARY
    ])
    ruler.add_patterns([
        {"label": "ORG", "pattern": name, "id": name.casefold()}
        for name in ORG_DICTIONARY
    ])
    # **Products too, and this was a real gap.** Until 2026-11-24 the ruler held only
    # places and organizations, so a multi-word product never matched as a phrase and the
    # model split it: `Toyota Hilux` became `Toyota` (ORG) + `Hilux` (PRODUCT), and the
    # index could only rescue the single token it was handed. Measured on the curated
    # list, 7 of 724 entries reached the ruler by accident (they are also org names).
    #
    # `PRODUCT` is a label `_arbitrate` already understands, so a phrase landing here is
    # decided by the same ladder as any other span — the ruler only stops the split.
    if PRODUCT_ENABLED:
        from . import products  # local: `products` imports `canon`, not `extract`

        # **A leading `The ` is stripped from the pattern.** `canon` already drops it for
        # the key, so the entry is `north face nuptse` either way — but the ruler matches
        # the *display* string, and a pattern of `The North Face Nuptse` requires the
        # article. A body writing `North Face Nuptse` then never matched, and the model's
        # own `LOC`/`FAC` label won. Measured: 2 of 724 entries were affected, and both
        # were real products.
        ruler.add_patterns([
            {"label": "PRODUCT", "pattern": _pattern_form(entry.display), "id": entry.key}
            for entry in products.INDEX.values()
        ])
    _NLP.add_pipe("dictionary_promote", after="place_ruler")


# ------------------------------------------------------------------ language seam


# Words that are overwhelmingly English-commercial rather than merely shared with
# another Latin-script language. Deliberately tiny and boring: this is a *warning*
# signal, so a false negative costs nothing and a false positive costs a line of text.
_ENGLISH_MARKERS = frozenset({
    "the", "and", "you", "your", "for", "with", "that", "this", "have", "will",
    "from", "are", "was", "were", "not", "but", "can", "what", "when", "there",
    "about", "would", "should", "thanks", "please", "hello", "today", "tomorrow",
})

# Enough words before the guess means anything. Below this a body is too short to
# tell `ok` (English) from `ok` (Dutch), so it is not accused of anything.
_MIN_WORDS_FOR_GUESS = 12
_MARKER_SHARE = 0.12


def looks_like_document(body: str) -> bool:
    """Is this body too long to be a chat message? See `DOCUMENT_CHARS`.

    A warning signal like `language_guess`, not a silent gate: the ingest counts these
    and says so, because "N message(s) look like documents and contributed no entities"
    is actionable, whereas an unexplained empty result is not.
    """
    return len(body or "") > DOCUMENT_CHARS


def language_guess(body: str) -> str:
    """`"en"`, `"non-en"` or `"unknown"` — a warning signal, never a gate.

    Script decides first: Latin letters are required for the English model to have any
    chance, so a Cyrillic, CJK or Arabic body is `non-en` without counting words. For a
    Latin body, a short one is `unknown` rather than accused, and a long one is judged
    on the share of common English function words.

    Nothing downstream branches on this. It exists so the ingest can say "3 messages
    look non-English, so they contribute no Places" instead of leaving the user to
    wonder why a French export drew nothing.
    """
    text = (body or "").strip()
    if not text:
        return "unknown"
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "unknown"
    latin = sum(1 for ch in letters if ch.isascii())
    if latin / len(letters) < 0.6:
        return "non-en"

    words = [word.strip(".,!?;:'\"()[]-").casefold() for word in text.split()]
    words = [word for word in words if word]
    if len(words) < _MIN_WORDS_FOR_GUESS:
        return "unknown"
    hits = sum(1 for word in words if word in _ENGLISH_MARKERS)
    return "en" if hits / len(words) >= _MARKER_SHARE else "non-en"


# -------------------------------------------------------------------- extraction


def places(body: str, *, message_key: str = "", platform: str = "") -> list[Mention]:
    """Every place span in one body, in order. No key, no node, no dedupe.

    The caller folds; this only reads. A message with no places returns `[]`, which is
    the ordinary answer and not a failure.

    **Fragmented, like `extract()`.** A single-body helper that read an HTML export
    whole would disagree with the batch path about the same message, and the difference
    would only show up on the platform that concatenates turns.
    """
    _ensure_model()
    if _NLP is None or not (body or "").strip():
        return []
    return [
        mention for fragment in fragments(body)
        for mention in _mentions_from_doc(
            _NLP(fragment.text), message_key, platform, body, offset=fragment.offset)
        if mention.kind == "place"
    ]


def organizations(
    body: str, *, message_key: str = "", platform: str = "",
) -> list[Mention]:
    """Every organization span in one body. Same contract as `places()`."""
    _ensure_model()
    if _NLP is None or not (body or "").strip():
        return []
    return [
        mention for fragment in fragments(body)
        for mention in _mentions_from_doc(
            _NLP(fragment.text), message_key, platform, body, offset=fragment.offset)
        if mention.kind == "organization"
    ]


def extract(
    messages: Iterable[tuple[str, str, str]],
) -> list[Mention]:
    """Every entity span — Places AND Organizations — from `(key, platform, body)`.

    One `nlp.pipe` call rather than one per message: the parser pays a fixed cost per
    call, and an ingest hands over thousands of bodies at once. Each `Mention` carries
    its own `kind`, so the caller splits rather than asking the model twice.
    """
    _ensure_model()
    rows = [(key, platform, body or "") for key, platform, body in messages]
    if _NLP is None or not rows:
        return []

    out: list[Mention] = []
    for mentions in _pipe_with_context(rows):
        out.extend(mentions)
    return out


# An exported HTML body is several chat turns concatenated by the exporter, not one turn.
#
# **Measured, not assumed.** 149 messages in the live store contain `<br>`, every one of
# them more than once, and the bodies read like this:
#
#     "I'll look at the Coke account tonight.<br>OpenSearch keeps falling over. just sent
#      it over.<br>shall we sort the campaign out?"
#
# Two unrelated procurement contexts and a social line, read by the model as one span
# context. Splitting them was measured on that corpus: +4 mentions found, and **six
# contaminated spans removed** — including `organization:abc corp?<br>`, which existed
# only because a dictionary name abutted a tag and the ruler matched across it.
#
# The tag itself is never part of a span once a body is split, which is the real prize.
# The split is here rather than in the adapters because it is an extraction concern: the
# stored body must stay as the export wrote it (`canon`'s display path and the Viewer both
# show it), and only the reading of it changes.
HTML_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)

# **Both kinds of line break.** `HTML_BREAK` alone was right for Messenger, which stores
# `<br>`, and wrong for every leg that stores a real newline — Email, Telegram, WhatsApp.
# An email body is `"Hello Notable Health,\n\nI built …"` and stayed ONE fragment, so the
# greeting was parsed as part of the first sentence and the span came out
# `Hello Notable Health`. Measured on the live mailbox: 157 of 224 bodies were affected.
_BREAK = re.compile(r"<br\s*/?>|\r?\n", re.IGNORECASE)

# A URL is not a name. Seen in the live store: `href="https://help.figma.com` became an
# Organization because the opening quote was treated as a word boundary.
#
# The optional `[\w-]+=[\"']?` prefix is what catches a dangling attribute that survived
# tag stripping — `href="https://help.figma.com` with no closing quote and no `>`. It is
# bounded to a plausible attribute name so it cannot eat prose before a link.
_URL = re.compile(r"(?:\b[\w-]{1,20}=[\"']?)?(?:https?://|www\.)\S+", re.IGNORECASE)

# An angle-bracket tag. Runs after `html.unescape`, so `&lt;EMAIL-9&gt` is caught here.
# The attribute class allows `>` inside a quoted value, which a bare `[^>]*` does not —
# `<a href="x>y">` is one tag, not two.
_TAG = re.compile(r"</?[A-Za-z][^<>]*(?:\"[^\"]*\"[^<>]*)*>", re.DOTALL)

# Zero-width and other invisible characters. One body was a CSS reset whose entities
# decoded to punctuation only, and produced three Organizations out of nothing.
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")

# A salutation at the start of ANY line: `Hi X,` / `Hello X,` / `Dear X,` / `Hi Team,`.
# `MULTILINE` is what makes a quoted reply's greeting visible (see `_drop_greeting`).
#
# **`wrote:` is a boundary, not decoration.** A reply header ends `… David <EMAIL-1> wrote:`
# and the quoted body follows; when the client flattened the newlines and filled the gaps
# with `&nbsp;` and a bullet, the greeting ended up mid-line and a `^`-anchored rule could
# not see it. Measured: 5 of 224 bodies on the real mailbox, each producing
# `organization:hello memgraph` beside the real `organization:memgraph`.
_GREETING = re.compile(
    r"(?:^\s*|(?<=\bwrote:)\s*)"
    r"(?:hello|hi|hey|dear|greetings|good\s+(?:morning|afternoon|evening))"
    r"(?:[ \t]+[^,\n]{0,60})?\s*[,:\n]?",
    re.IGNORECASE | re.MULTILINE,
)

# What the scrub gate leaves behind when it redacts: `EMAIL-1`, `PHONE-12`, `CARD-3`.
# Extraction must skip these — there is no entity behind a redaction.
_SCRUB_ALIAS = re.compile(r"(?:EMAIL|PHONE|CARD|IBAN|ADDRESS|SECRET)[-_]?\d+", re.IGNORECASE)

# A quoted-reply marker: one or more `>` at the start of a line, optional space.
#
# **A reply quotes the original, including its greeting.** The body that produced
# `organization:hello memgraph` was a reply whose quoted block began
# `> Hello Memgraph team,` — the greeting was not at the start of the fragment, so
# `_GREETING` could not see it. It also left the `>` glued to spans.
_QUOTE = re.compile(r"^\s*(?:>\s*)+", re.MULTILINE)

# Below this many characters a fragment is not worth a spaCy parse.
#
# **Measured on the 374 fragments in the live store:** 8 are 2 characters (`ok`, `hi`),
# 25 are under 8. Those are real turns and they never name an entity, so paying a parse
# for them is waste. The floor is deliberately a single character, not a word — an empty
# piece between adjacent tags is the only thing being dropped.
MIN_FRAGMENT_CHARS = 1


@dataclass(frozen=True)
class Fragment:
    """One readable piece of a body, with where it sits in the concatenated original.

    `offset` is the fragment's start within the **original** body, so a span found here
    maps back to the stored text without the caller knowing a split happened. Nothing
    downstream needs a fragment id: the `MENTIONS` edge hangs off the message, and a
    message naming the same entity in two turns is one edge.
    """

    text: str
    offset: int


def _readable(text: str) -> str:
    """Text a human would have read: entities decoded, tags and URLs gone.

    **Measured on the live mailbox (224 messages): 8 bodies carried HTML entities and 11
    carried tags, and each one produced a junk node** — `Account &amp`,
    `href="https://help.figma.com`, `Marko Srsan &lt;EMAIL-9&gt`, `Apple\nIntelligence'`.
    These are not model errors: the span is exactly what the string said. No recogniser,
    GLiNER included, can classify `&lt;EMAIL-9&gt` correctly, so the fix is to stop
    handing it over.

    `html.unescape` before stripping matters in this order, not the reverse — `&lt;b&gt;`
    becomes `<b>` and would otherwise survive as a tag-shaped word.
    """
    if not text:
        return ""
    # Entities first, so an escaped tag becomes a tag and is stripped below.
    text = html.unescape(text)
    # **Tags before URLs, and the tag pattern must cross a quoted attribute.**
    # `<a href="https://help.figma.com/x">` contains `>` only at the end, but a naive
    # `[^>]*` stops at the first `>` — fine — while the failure here was stripping the
    # URL first, which left `<a href="  ">` and then a tag regex that could no longer see
    # a closing bracket. Removing the whole element first is the order that works.
    text = _TAG.sub(" ", text)
    # Any URL left over, whether bare or inside prose.
    text = _URL.sub(" ", text)
    # Zero-width and other invisible characters: one body was a CSS reset full of
    # `&#8199;` / `&#65279;` and produced three Organizations out of punctuation.
    text = _INVISIBLE.sub(" ", text)
    # `>` quote markers last: they are punctuation at line starts, and leaving them turns
    # a quoted greeting into an unquoted one for `_drop_greeting` below.
    text = _QUOTE.sub("", text)
    return text


def _drop_greeting(text: str) -> str:
    """Remove salutations wherever a greeting can sit, including inside a quoted reply.

    **This is the single largest source of junk on the real mailbox: 157 of 224 bodies
    open with `Hi X,` / `Hello X,` / `Dear X,`** — one outbound campaign of theirs. The
    recogniser reads `Hello Onix Networking` and correctly reports an Organization; the
    span is not wrong, the *string* is. Fourteen Organizations in the live store were
    their own greeting (`Hello Memgraph`, `Hello Y Combinator`, `Hello SS&C
    Technologies`, …), each a distinct node for a company that already had one.

    Three positions, all of which occur in this corpus:

    * the start of the text — the campaign itself;
    * the start of any line — a plain-text reply;
    * immediately after `wrote:` — a reply whose newlines were flattened and padded with
      `&nbsp;` and a bullet, so the greeting arrived mid-line.

    Only a salutation, and only at one of those boundaries, so `I said hello to Marko`
    is untouched. `Hello,` alone (a support ticket) goes too — it names nobody.
    """
    return _GREETING.sub("", text)


def fragments(body: str) -> list[Fragment]:
    """Split an exported body into readable pieces, with where each sits in the original.

    Two jobs, both required for the offsets to be useful:

    1. **Split on line breaks** — HTML `<br>` and a literal newline, because Email,
       Telegram and WhatsApp store real newlines while Messenger stores `<br>`.
    2. **Make each piece readable** (`_readable`) and drop a leading salutation
       (`_drop_greeting`). *The original is never modified* — only the text handed to
       the model — so every `Mention` offset still points at the stored body.

    A body with no break is one fragment starting at 0, so the caller has one code path.
    Empty pieces between adjacent breaks are dropped rather than parsed — `<br><br>` is a
    paragraph gap, not an empty message.
    """
    if not body:
        return []
    out: list[Fragment] = []
    position = 0
    for match in _BREAK.finditer(body):
        piece = body[position:match.start()]
        lead = len(piece) - len(piece.lstrip())
        # **Every piece, not only the first.** A quoted reply puts the greeting on its own
        # line (`> Hello Memgraph team,`), which becomes its own fragment — applying the
        # strip to fragment 0 only meant every quoted greeting survived.
        text = _drop_greeting(_readable(piece.strip()))
        if len(text.strip()) >= MIN_FRAGMENT_CHARS:
            out.append(Fragment(text=text.strip(), offset=position + lead))
        position = match.end()
    piece = body[position:]
    lead = len(piece) - len(piece.lstrip())
    text = _drop_greeting(_readable(piece.strip()))
    if len(text.strip()) >= MIN_FRAGMENT_CHARS:
        out.append(Fragment(text=text.strip(), offset=position + lead))
    return out


def _pipe_with_context(rows: list[tuple[str, str, str]]) -> Iterable[list[Mention]]:
    """Every mention for each body, skipping empty bodies.

    spaCy's `pipe` skips nothing, so empty bodies would still cost a parse; they are
    filtered here.

    **One doc per fragment, not per body.** `fragments()` is applied first, so an HTML
    export's concatenated turns are parsed separately (see `HTML_BREAK`). Each fragment
    carries its offset into the original body, and `_mentions_from_doc` adds it back, so
    every `Mention` keeps an offset that points at the stored text.

    **Yields mentions only, not `(doc, mentions)`.** The doc was never read by the
    caller, and with fragmentation there is no longer one doc per row to hand back — a
    tuple would invite a caller to assume there is.
    """
    live = [
        (index, body) for index, (_k, _p, body) in enumerate(rows)
        # `looks_like_document` skips a newsletter or pasted article: chat-oriented NER
        # over marketing copy mints file extensions as Organizations. Skipped here, so
        # the cost is not even paid, and reported by the caller rather than silently.
        if body.strip() and not looks_like_document(body)
    ]
    if not live or _NLP is None:
        return

    # Flatten to (row index, fragment) so `nlp.pipe` sees every fragment as its own text.
    units: list[tuple[int, Fragment]] = [
        (index, fragment) for index, body in live for fragment in fragments(body)
    ]
    if not units:
        return

    docs = _NLP.pipe([fragment.text for _i, fragment in units], batch_size=64)
    found: dict[int, list[Mention]] = {}
    for (index, fragment), doc in zip(units, docs):
        key, platform, body = rows[index]
        found.setdefault(index, []).extend(
            _mentions_from_doc(doc, key, platform, body, offset=fragment.offset)
        )
    for index in (i for i, _b in live):
        yield found.get(index, [])


def _mentions_from_doc(doc, key: str, platform: str, body: str, *,
                       offset: int = 0) -> list[Mention]:
    """The span loop, over an already-parsed doc. Shared with `places()`.

    `offset` is where the parsed text starts within `body` — non-zero when the body was
    split on HTML breaks. It is added to every span's `start`, so offsets point at the
    original stored text and a fragment id never has to travel downstream.

    **The span is taken whole.** A leading `the` is *not* stripped here, and that is a
    deliberate reversal: slicing past the article of `the Coca-Cola` leaves `Coca-Cola`,
    a tail with no determiner, which is exactly the shape that reads as a place and was
    minting a false `place:coca-cola`. `canon` already drops a leading article for
    identity (`the Bay Area` -> `bay area`), so the key is unaffected and the span stays
    honest about what the model actually matched.
    """
    out: list[Mention] = []
    for ent in doc.ents:
        # **A scrub alias is not a name.** The gate replaces a phone or an address with
        # `PHONE-1` / `EMAIL-9` *before* the store is written, and extraction then sees
        # the alias. Measured: `EMAIL-1`, `EMAIL-9` and `Marko Srsan <EMAIL-9>` all
        # became Organizations, and `EMAIL-1` became a Place. The alias is the redaction,
        # so there is nothing behind it to classify.
        if _SCRUB_ALIAS.fullmatch(ent.text.strip()):
            continue
        # **The kind is arbitrated, not inherited.** Before this, `GPE` meant place and
        # `ORG` meant organization by the shape of an `if` statement, so whichever label
        # the model happened to fire owned the node. `_arbitrate` may return the same kind
        # — with the flag off it always does — but the decision now has one home.
        kind, candidates = _arbitrate(ent.text, ent.label_, body)
        if not kind:
            continue
        # **The flag gates the model's own `PRODUCT` label too.** `en_core_web_sm` does
        # emit it (rarely, and frame-sensitively), so without this a product mention would
        # reach the writer and be silently dropped by its `kinds=` filter — a mention that
        # passed arbitration and then evaporated. Dropped here, and counted, so the report
        # can say how much the leg would find.
        if kind == "product" and not PRODUCT_ENABLED:
            continue
        text = ent.text.strip()
        if len(text) < MIN_SPAN_CHARS:
            continue
        # A span the model cut short is a fragment, not a name — `University of` would
        # otherwise become an Organization node of its own. Dropped, never extended.
        if kind == "organization" and text.split()[-1].rstrip(".,").casefold() in TRUNCATION_TAILS:
            continue
        # A span must not contain markup. Before fragmentation this happened: a dictionary
        # name ending a turn abutted the tag and the ruler matched across it, minting
        # `organization:abc corp?<br>`. Fragmentation removes the cause; this keeps it
        # from returning by any other route. `_readable` has already stripped tags from
        # the parsed text, so this now catches only what survived (a stray `&`-entity
        # shape), and a URL that slipped through as one token.
        if HTML_BREAK.search(text) or _TAG.search(text) or _URL.match(text):
            continue
        # **Offsets are approximate for a fragment whose greeting was stripped.** Removing
        # `Hello X,` from the front shifts every character after it, and the shift is not
        # worth propagating: `start`/`end` exist so the Viewer can highlight the span in
        # the ORIGINAL body, and the clamp below keeps a wrong offset from corrupting
        # anything. They were already approximate across a fragment (`offset` is the
        # fragment start, not the text start after `.strip()`).
        start = offset + ent.start_char
        end = start + len(ent.text.rstrip())
        if end > len(body):
            start = max(0, min(start, len(body) - 1)) if body else 0
            end = min(len(body), max(end, start + len(text)))
        out.append(Mention(
            text=text, label=ent.label_, start=start, end=end,
            message_key=key, platform=platform, kind=kind, candidates=candidates,
        ))
    return out


# ------------------------------------------------------------------ arbitration

# Which kinds a spaCy label may propose, strongest first. The order is the tie-break:
# a span the model called `ORG` is an Organization before it is anything else.
#
# `PRODUCT` is included because `en_core_web_sm` DOES emit it — corrected 2026-11-23; an
# earlier note in this repo claimed it did not. It emits it rarely and frame-sensitively:
# `"I've moved everything onto Ansible."` is a `PRODUCT`, `"Ansible keeps falling over."`
# is nothing.
#
# **`PERSON` is deliberately ABSENT.** The model labels `Grafana`, `Tableau` and `Docker`
# as `PERSON` in most frames, and mapping `PERSON` to a kind would make every human name a
# candidate for something — `Dave said it was fine.` became a Product when this was tried.
# A `PERSON` span is therefore dropped by the model's opinion and can ONLY be rescued by
# the product index, which is `_PERSON_RESCUE_LABELS` below.
LABEL_KINDS: dict[str, tuple[str, ...]] = {
    **{label: ("place",) for label in PLACE_LABELS},
    **{label: ("organization",) for label in ORG_LABELS},
    "PRODUCT": ("product",),
}

# Labels the product index may overrule. `PERSON` is here because a bare product name with
# no cue reads as a person to the small model — the same failure `PLACE_DICTIONARY` exists
# to fix for bare cities (`Then Austin on Friday` -> PERSON). The index decides; an
# unrecognised `PERSON` is still dropped, so nothing is loosened but the names we claim.
# `NORP` is here for the same reason as `PERSON`: the model labels a brand as a
# nationality or group when the word is also one — `Vitra` and `Persian` both come back
# `NORP`, so `a Persian rug` and `a Vitra Eames chair` produced no node at all. Only the
# index promotes, so an unrecognised `NORP` (`British`, `Dutch`) is still dropped.
PRODUCT_RESCUE_LABELS: frozenset[str] = frozenset({"PERSON", "NORP"})


def _arbitrate(text: str, label: str, body: str = "") -> tuple[str, tuple[str, ...]]:
    """Decide what a proposed span **is**, returning `(winning kind, all candidates)`.

    This is the seam the rework exists for. Until 2026-11-23 the kind was simply
    "whichever spaCy label fired", which is how `place:tableau`, `place:gemini` and
    `organization:claude` got into the graph — 29 of 212 entity nodes were products
    wearing the wrong label.

    **With `PRODUCT_ENABLED` off this is the identity function.** It returns the same
    kind the label always implied, in the same order, so every existing count and node
    is byte-identical.

    **With it on, the index may overrule the model** — but only for these labels:

        GPE / LOC / FAC   the index may make it a Product
        PRODUCT           already a Product
        PERSON            the index may make it a Product, and ONLY the index
        ORG               the index may NOT

    `PERSON` is included because the small model labels `Grafana`, `Tableau` and `Docker`
    as people in most frames — and a dropped `PERSON` meant the index could never rescue
    the names it exists for. **Only the index promotes a `PERSON`**, never the label: an
    unrecognised human name is still dropped, which a test pins with `Dave said it was
    fine.`

    `ORG` is excluded on purpose. An `ORG` span is often a *longer* name than the product
    inside it — `Grafana Labs` the company contains `Grafana` the product — and demoting
    that would lose the organisation, which is a true fact the graph should keep. So
    `organization:snowflake` and `organization:claude` stay Organizations;
    `HANDOVER.md` Open decisions records that as deliberate.

    The arbitration is per span and needs the body, because a context-gated entry
    (`Support Plan`) is only a product in a procurement sentence.

    **`ORG` is promotable on a FULL-SPAN match only.** Until 2026-11-27 the
    organisation label was short-circuited before `products.decide()` was ever called,
    so an index entry could never rescue a product the small model called a company —
    `Snowflake`, `PhotoGenerator`, `Supabase` all stayed Organizations however
    catalogue-certain the name was. The worry that justified the blanket refusal is
    *containment* — `Grafana Labs` the company contains `Grafana` the product, and
    demoting the whole phrase would lose a true organisation.

    That worry is about the SPAN, not the label, so it is tested as one here: an index
    hit whose matched text is not the whole span leaves the organisation intact.
    `Grafana Labs` -> `organization`. `Snowflake` -> `product`.
    """
    possible = LABEL_KINDS.get(label, ())
    rescue = label in PRODUCT_RESCUE_LABELS
    if not possible and not rescue:
        return "", ()
    winning = possible[0] if possible else ""

    if PRODUCT_ENABLED and possible and winning == "organization":
        # Only a full-span hit. The matched text is compared after the same whitespace
        # flattening `canon` applies, so `Snowflake` and `snowflake ` agree.
        from . import products  # local: `products` imports `canon`, not `extract`

        verdict, _reason = products.decide(text, body)
        if verdict:
            entry = products.lookup(text)
            matched = (entry.display if entry is not None else text)
            if " ".join(matched.split()).casefold() == " ".join(text.split()).casefold():
                return "product", ("product", *possible)
        return winning, possible

    # Only titles the index can promote. A `PERSON`-without-a-hit falls through
    # to `winning`, which is `""` for a rescue label — a dropped span, as before.
    promotable = PRODUCT_ENABLED
    if promotable:
        from . import products  # local: `products` imports `canon`, not `extract`

        verdict, _reason = products.decide(text, body)
        if verdict:
            # The model's own label, when it gave one, stays as a candidate.
            return "product", ("product", *possible)

    return winning, possible
