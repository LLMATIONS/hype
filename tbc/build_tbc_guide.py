# -*- coding: utf-8 -*-
"""Generate a polished, self-contained HTML guide from the TBC rep-leveling spreadsheet."""
import html, re, json, unicodedata
import urllib.parse

def esc(s):
    return html.escape(str(s))

# ---------------------------------------------------------------------------
# WOWHEAD LINKING  (Goal 2)
# ---------------------------------------------------------------------------
# WoW database ids are global; the /tbc/ path selects TBC-era tooltip data.
# Every in-game reference is routed through a small helper so it stays
# maintainable. Anything not in this verified table falls back to a Wowhead
# search URL (always resolves; just no hover tooltip) — so a public page can
# never carry a broken link. IDs below were each resolved + verified against
# live Wowhead /tbc/ pages (2026-06-03; additions 2026-06-10).
WH_BASE = "https://www.wowhead.com/tbc"

WOWHEAD = {
    # --- quests ---
    "Weaken the Ramparts": ("quest", 9575),
    "Oh, It's On!": ("quest", 9717),
    "Stalk the Stalker": ("quest", 9719),
    "I Must Have Them!": ("quest", 10109),
    "Bring Me The Egg!": ("quest", 10111),
    "Entry Into Karazhan": ("quest", 9831),
    "How to Break Into the Arcatraz": ("quest", 10704),
    "Harbinger of Doom": ("quest", 10882),
    "The Cudgel of Kar'desh": ("quest", 10901),
    "The Hand of Gul'dan": ("quest", 10680),
    "The Vials of Eternity": ("quest", 10445),
    "An Artifact From the Past": ("quest", 10947),
    "Ruse of the Ashtongue": ("quest", 10946),
    # --- items ---
    "Mark of Conquest": ("item", 27921),
    "Mark of Defiance": ("item", 27922),
    "Mark of Vindication": ("item", 27927),
    "Unidentified Plant Parts": ("item", 24401),
    "Mark of Kil'jaeden": ("item", 29425),
    "Firewing Signet": ("item", 29426),
    "Mark of Sargeras": ("item", 30809),
    "Sunfury Signet": ("item", 30810),
    "Fel Armament": ("item", 29740),
    "Arcane Tome": ("item", 29739),
    "Arakkoa Feather": ("item", 25719),
    "Fel Iron Bar": ("item", 23445),
    "Mote of Fire": ("item", 22574),
    "Arcane Dust": ("item", 22445),
    "Coilfang Armaments": ("item", 24368),
    "Zaxxis Insignia": ("item", 29209),
    "Obsidian Warbeads": ("item", 25433),
    "Medivh's Journal": ("item", 23933),
    "Medallion of Karabor": ("item", 32649),
    "Key of Time": ("item", 30635),
    # --- npcs ---
    "Fahssn": ("npc", 17923),
    "Gurgthock": ("npc", 18471),
    "Wazat": ("npc", 19035),
    "Archmage Alturus": ("npc", 17613),
    "Smith Gorlunk": ("npc", 22037),
    "Nether-Stalker Khay'ji": ("npc", 19880),
    "Warp-Raider Nesaad": ("npc", 19641),
    "Nether-Stalker Mah'duun": ("npc", 24370),
    "Wind Trader Zhareem": ("npc", 24369),
    "Skar'this the Heretic": ("npc", 22421),
    "Earthmender Sophurus": ("npc", 21937),
    "Earthmender Splinthoof": ("npc", 21938),
    "Haggard War Veteran": ("npc", 19684),
    "A'dal": ("npc", 18481),
    "Nightbane": ("npc", 17225),
    "Soridormi": ("npc", 19935),
    "Lady Vashj": ("npc", 21212),
    "Kael'thas Sunstrider": ("npc", 19622),
    "Rage Winterchill": ("npc", 17767),
    "Al'ar": ("npc", 19514),
    "Talon King Ikiss": ("npc", 18473),
    # --- zones / dungeons ---
    "Hellfire Ramparts": ("zone", 3562),
    "The Blood Furnace": ("zone", 3713),
    "The Shattered Halls": ("zone", 3714),
    "The Slave Pens": ("zone", 3717),
    "The Underbog": ("zone", 3716),
    "The Steam Vaults": ("zone", 3715),
    "Mana-Tombs": ("zone", 3792),
    "Auchenai Crypts": ("zone", 3790),
    "Sethekk Halls": ("zone", 3791),
    "Shadow Labyrinth": ("zone", 3789),
    "Old Hillsbrad Foothills": ("zone", 2367),
    "The Black Morass": ("zone", 2366),
    "The Botanica": ("zone", 3847),
    "The Mechanar": ("zone", 3849),
    "The Arcatraz": ("zone", 3848),
    "Magisters' Terrace": ("zone", 4131),
    "Karazhan": ("zone", 3457),
    "Hellfire Peninsula": ("zone", 3483),
    "Zangarmarsh": ("zone", 3521),
    "Terokkar Forest": ("zone", 3519),
    "Nagrand": ("zone", 3518),
    "Blade's Edge Mountains": ("zone", 3522),
    "Netherstorm": ("zone", 3523),
    "Shadowmoon Valley": ("zone", 3520),
    "Shattrath City": ("zone", 3703),
    "Deadwind Pass": ("zone", 41),
    # --- factions ---
    "Honor Hold": ("faction", 946),
    "Thrallmar": ("faction", 947),
    "Cenarion Expedition": ("faction", 942),
    "The Consortium": ("faction", 933),
    "Lower City": ("faction", 1011),
    "Keepers of Time": ("faction", 989),
    "The Sha'tar": ("faction", 935),
    "The Aldor": ("faction", 932),
    "The Scryers": ("faction", 934),
    "Sha'tari Skyguard": ("faction", 1031),
    "Kurenai": ("faction", 978),
    "The Mag'har": ("faction", 941),
    "Netherwing": ("faction", 1015),
    "Ogri'la": ("faction", 1038),
    "Sporeggar": ("faction", 970),
    "The Violet Eye": ("faction", 967),
    "Ashtongue Deathsworn": ("faction", 1012),
    "The Scale of the Sands": ("faction", 990),
    "Shattered Sun Offensive": ("faction", 1077),
    # --- faction aliases (the guide writes these without a leading "The") ---
    "Consortium": ("faction", 933),
    "Sha'tar": ("faction", 935),
    "Aldor": ("faction", 932),
    "Scryers": ("faction", 934),
    "Mag'har": ("faction", 941),
    "Violet Eye": ("faction", 967),
    "Scale of the Sands": ("faction", 990),
}

def _wh_key(raw):
    """Normalize a display string (tags, HTML entities, curly quotes) to a
    plain lookup key matching the WOWHEAD table."""
    s = re.sub(r"<[^>]+>", "", str(raw))          # strip any HTML tags
    s = html.unescape(s)                          # &rsquo; -> ’  etc.
    s = (s.replace("’", "'").replace("‘", "'")
           .replace("–", "-").replace("—", "-"))
    return re.sub(r"\s+", " ", s).strip()

def wh_url(name):
    ent = WOWHEAD.get(_wh_key(name))
    if ent:
        return f"{WH_BASE}/{ent[0]}={ent[1]}"
    return f"{WH_BASE}/search?q={urllib.parse.quote(_wh_key(name))}"

def wh_link(name, label=None):
    """Anchor for one reference. Resolved ids get class 'wh' (tooltip-capable);
    search fallbacks get 'wh wh-q'. Display label keeps the original wording."""
    ent = WOWHEAD.get(_wh_key(name))
    label = name if label is None else label
    if ent:
        return (f'<a class="wh" href="{WH_BASE}/{ent[0]}={ent[1]}" '
                f'target="_blank" rel="noopener">{label}</a>')
    q = urllib.parse.quote(_wh_key(name))
    return (f'<a class="wh wh-q" href="{WH_BASE}/search?q={q}" '
            f'target="_blank" rel="noopener">{label}</a>')

def maybe_link_entity(text):
    """Link each ' / '-separated part ONLY if it's a known entity; unknown
    parts (generic phrases like 'Mobs, quests') stay plain — no search noise
    in dense structured cells."""
    parts = str(text).split(" / ")
    out = []
    for p in parts:
        out.append(wh_link(p, label=p) if _wh_key(p) in WOWHEAD else esc(p))
    return " / ".join(out)

def link_faction(name):
    """Faction label that may carry a trailing phase badge span and/or a
    ' / ' pairing. Link the faction name(s), preserve the badge."""
    m = re.search(r"(\s*<span class=['\"]ph['\"]>.*?</span>\s*)$", name)
    suffix, base = ("", name)
    if m:
        suffix, base = m.group(1), name[:m.start()]
    return maybe_link_entity(base) + suffix

def linkify_brackets(text):
    """Wrap every [bracketed reference]'s inner name in a Wowhead link,
    keeping the literal brackets as plain text around it."""
    return re.sub(r"\[([^\[\]]+)\]",
                  lambda m: "[" + wh_link(m.group(1), label=m.group(1)) + "]",
                  text)

def linkify_bold(text):
    """Link a <b>…</b> run when its whole contents are a known entity
    (dungeon, NPC, faction, item). Skips runs already containing a link or a
    bracket (handled by linkify_brackets)."""
    def repl(m):
        inner = m.group(1)
        if "<a" in inner or "[" in inner:
            return m.group(0)
        key = _wh_key(inner)
        ent = WOWHEAD.get(key)
        tail = ""
        disp = inner
        if not ent and key.endswith(":") and key[:-1] in WOWHEAD:
            ent, disp, tail = WOWHEAD[key[:-1]], inner[:-1], ":"
        if not ent:
            return m.group(0)
        return (f'<b><a class="wh" href="{WH_BASE}/{ent[0]}={ent[1]}" '
                f'target="_blank" rel="noopener">{disp}</a>{tail}</b>')
    return re.sub(r"<b>(.*?)</b>", repl, text, flags=re.S)

def linkify(text):
    """Full prose pass: bracketed refs first, then bold known-entities."""
    return linkify_bold(linkify_brackets(text))

def slug(s):
    """Stable, url-safe id from a display string — used for checkbox /
    localStorage keys. Stays stable as long as the step title is unchanged."""
    s = _wh_key(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

# ---------------------------------------------------------------------------
# DATA  (transcribed from "TBC dungeon rep leveling (Stamaka).xlsx", then
# cross-checked against Wowhead TBC Classic / warcraft.wiki.gg / Icy Veins and
# the 2026 anniversary-realm phase schedule — corrections landed 2026-06-10)
# ---------------------------------------------------------------------------

# --- The leveling route (the flowchart) ---
ROUTE = [
    {"lvl": "58 / 60", "title": "Hellfire Ramparts",
     "do": ["Run Hellfire Ramparts.", "Complete the quests outside until you get <b>[Weaken the Ramparts]</b>."],
     "leave": "Honored with Honor Hold / Thrallmar",
     "tips": []},
    {"lvl": "~61", "title": "The Blood Furnace",
     "do": ["Run The Blood Furnace once for the quests.", "Do quests out in Hellfire Peninsula."],
     "leave": "Honored with Honor Hold / Thrallmar &nbsp;·&nbsp; if not yet 62, stay till 62",
     "tips": ["Normal Ramparts and Blood Furnace runs cap at Honored. Revered and Exalted come later, from level-70 heroics and <b>The Shattered Halls</b>.",
              "Consider grabbing <b>[Mark of Conquest]</b>, <b>[Mark of Defiance]</b> or <b>[Mark of Vindication]</b> for easier farming.",
              "Learn your new skills."]},
    {"lvl": "62", "title": "The Slave Pens",
     "do": ["Kill each pack&rsquo;s enslaved Wastewalkers <i>before</i> their Coilfang masters — freed slaves turn friendly and stop giving rep.",
            "Turn in 10 <b>[Unidentified Plant Parts]</b> once — sell the rest.",
            "Go to <b>Fahssn</b> and run repeatable quests until <b>friendly with Sporeggar</b>.",
            "Grab <b>[Oh, It&rsquo;s On!]</b> and <b>[Stalk the Stalker]</b> (good farming trinkets)."],
     "leave": "Honored with Cenarion Expedition",
     "tips": []},
    {"lvl": "63", "title": "The Underbog",
     "do": ["Run it once for the quests.", "Do quests out in Zangarmarsh."],
     "leave": "Honored with Cenarion Expedition &nbsp;·&nbsp; if not yet 64, stay till 64",
     "tips": ["The Slave Pens and Underbog cap at Honored. Revered and Exalted come from Uncatalogued Species turn-ins (the rare find in <b>[Unidentified Plant Parts]</b> packages), <b>[Coilfang Armaments]</b>, <b>The Steam Vaults</b>, and heroics.",
              "Learn your new skills."]},
    {"lvl": "64", "title": "Mana-Tombs",
     "do": ["If not yet 65: farm Mark of Kil&rsquo;jaeden / Firewing Signet (up to 220), or quest in Terokkar / Nagrand till 65.",
            "Go to <b>[Haggard War Veteran]</b> in Shattrath and run the <b>[A&rsquo;dal]</b> chain to pick <b>Aldor or Scryers</b>.",
            "Turn in your <b>[Mark of Kil&rsquo;jaeden] / [Firewing Signet]</b> until honored."],
     "leave": "Honored with Consortium",
     "tips": []},
    {"lvl": "65", "title": "Nagrand Arena — Ring of Blood",
     "do": ["See <b>Gurgthock</b> for the Ring of Blood chain.", "Grab <b>[I Must Have Them!]</b> and <b>[Bring Me The Egg!]</b>.",
            "Visit <b>Wazat</b> for a cape in 2 quests."],
     "leave": "",
     "tips": []},
    {"lvl": "65", "title": "Auchenai Crypts",
     "do": ["Run it.", "Learn your new skills."],
     "leave": "Ding 66",
     "tips": []},
    {"lvl": "66", "title": "Old Hillsbrad Foothills",
     "do": ["Run once to unlock access to <b>The Black Morass</b>."],
     "leave": "",
     "tips": []},
    {"lvl": "66", "title": "Sethekk Halls",
     "do": ["The <b>Shadow Labyrinth key</b> is in the chest beside <b>Talon King Ikiss</b> — everyone in the group can loot it.",
            "Sell all your <b>[Arakkoa Feather]</b>.", "Learn your new skills."],
     "leave": "Ding 68",
     "tips": []},
    {"lvl": "68", "title": "Start Karazhan Attunement",
     "do": ["Go to Deadwind Pass &rarr; <b>Archmage Alturus</b>.",
            "Run the Karazhan attunement chain until you get <b>[Entry Into Karazhan]</b>."],
     "leave": "",
     "tips": []},
    {"lvl": "68", "title": "Shadow Labyrinth",
     "do": ["Run at least once for the attune."],
     "leave": "Revered with Lower City",
     "tips": []},
    {"lvl": "69", "title": "Shattered Halls Key",
     "do": ["Go to Shadowmoon Valley and kill <b>Smith Gorlunk</b>.",
            "Bring 4&times;[Fel Iron Bar], 4&times;[Mote of Fire], 2&times;[Arcane Dust].",
            "Complete the chain to get the <b>[Shattered Halls Key]</b>."],
     "leave": "",
     "tips": []},
    {"lvl": "69", "title": "Arcatraz Key (start)",
     "do": ["Go to Netherstorm &rarr; <b>Nether-Stalker Khay&rsquo;ji</b>.",
            "Run the chain from <b>[Warp-Raider Nesaad]</b> until <b>[How to Break Into the Arcatraz]</b>."],
     "leave": "",
     "tips": []},
    {"lvl": "69", "title": "The Steam Vaults",
     "do": ["Run at least once for the attune.",
            "<i>Alternatively</i> run The Shattered Halls if you aren&rsquo;t revered with either.",
            "Sell all your <b>[Coilfang Armaments]</b>.", "Learn your new skills."],
     "leave": "Ding 70",
     "tips": []},
    {"lvl": "70", "title": "Hit Max Level",
     "do": ["GZ! Train <b>Expert Riding</b> in <b>Shadowmoon Valley</b> and grab your flying mount.",
            "Visit quartermasters — <b>Honor Hold/Thrallmar, Cenarion Expedition, Lower City</b> — for revered gear.",
            "Aldor / Scryers: turn in items now till revered if you need to.",
            "See <b>Nether-Stalker Mah&rsquo;duun</b> &amp; <b>Wind Trader Zhareem</b> in Shattrath for dailies."],
     "leave": "",
     "tips": []},
    {"lvl": "70", "title": "Heroic & Attune Farm",
     "do": ["The Botanica, The Mechanar (take <b>[Harbinger of Doom]</b>), The Arcatraz, The Black Morass.",
            "Farm <b>The Botanica</b> till revered with Sha&rsquo;tar.",
            "Farm <b>The Black Morass</b> till revered with <b>Keepers of Time</b> for the heroic <b>[Key of Time]</b>. That Revered pays twice — the heroic key now, and the Hyjal attune (<b>[The Vials of Eternity]</b>) in P3. The Kara attune itself just needs one normal clear."],
     "leave": "Fully attuned to T4 raids &amp; every heroic dungeon",
     "tips": []},
    {"lvl": "Raids", "title": "Raid Attunements",
     "do": ["<b>Nightbane:</b> at honored with Violet Eye, return to Archmage Alturus; take <b>[Medivh&rsquo;s Journal]</b> and finish the chain.",
            "<b>SSC:</b> find <b>[Skar&rsquo;this the Heretic]</b> in heroic Slave Pens &rarr; <b>[The Cudgel of Kar&rsquo;desh]</b> — it wants the signets off <b>Gruul</b> and <b>Nightbane</b>.",
            "<b>TK:</b> Shadowmoon Valley &rarr; <b>[Earthmender Sophurus]</b> / <b>[Earthmender Splinthoof]</b>; take <b>[The Hand of Gul&rsquo;dan]</b>, finish the long chain, then visit A&rsquo;dal for the 4 trials — heroic Shattered Halls, Steamvault &amp; Shadow Labyrinth, Arcatraz, and finally <b>Magtheridon</b>.",
            "<b>Hyjal:</b> at revered with <b>Keepers of Time</b>, grab <b>[The Vials of Eternity]</b> from <b>Soridormi</b> at the Caverns of Time. It only wants the vials off <b>Lady Vashj</b> (SSC) and <b>Kael&rsquo;thas Sunstrider</b> (TK), so it&rsquo;s done in P2 the moment both are down.",
            "<b>BT:</b> the <b>[Medallion of Karabor]</b> chain starts at your Aldor/Scryers base, finds <b>Seer Udalo</b> inside the Arcatraz, then needs <b>[Al&rsquo;ar]</b> dead in TK (<b>[Ruse of the Ashtongue]</b>) — run it alongside the P2 raids. Only its final step, <b>[An Artifact From the Past]</b>, needs Mount Hyjal&rsquo;s first boss <b>Rage Winterchill</b>, so that part waits for P3."],
     "leave": "",
     "tips": []},
]

GOLDEN_RULES = [
    "Don&rsquo;t turn in <b>any</b> quests with a faction until you&rsquo;re <b>honored</b> (5999/6000 friendly) — most normal-dungeon rep dries up at Honored, quest rep never does.",
    "When you reach honored, visit that faction&rsquo;s quartermaster — there are good low-level options.",
]

# --- Faction ↔ dungeon associations ---
FACTIONS = [
    ("Honor Hold / Thrallmar", "Hellfire Peninsula", [("Hellfire Ramparts","honored"),("The Blood Furnace","honored"),("The Shattered Halls","exalted")]),
    ("Cenarion Expedition", "Zangarmarsh", [("The Slave Pens","honored"),("The Underbog","honored"),("Unidentified Plant Parts","honored"),("The Steam Vaults","exalted"),("Uncatalogued Species","exalted"),("Coilfang Armaments","exalted")]),
    ("Consortium", "Netherstorm / Nagrand", [("Mana-Tombs","honored"),("Zaxxis Insignia / Obsidian Warbeads","exalted"),("Ethereum Prison Keys","exalted")]),
    ("Lower City", "Shattrath City", [("Auchenai Crypts","honored"),("Sethekk Halls","honored"),("Arakkoa Feather","honored"),("Shadow Labyrinth","revered")]),
    ("Keepers of Time", "Caverns of Time (Tanaris)", [("Old Hillsbrad Foothills","exalted"),("The Black Morass","exalted")]),
    ("Sha&rsquo;tar", "Shattrath City", [("Shared rep with Aldor / Scryers","friendly"),("The Botanica","exalted"),("The Mechanar","exalted"),("The Arcatraz","exalted")]),
    ("Aldor / Scryers", "Shattrath City", [("Mark of Kil&rsquo;jaeden / Firewing Signet","honored"),("Mark of Sargeras / Sunfury Signet","exalted"),("Fel Armament / Arcane Tome","exalted")]),
    ("Sha&rsquo;tari Skyguard <span class='ph'>p2</span>", "Terokkar Forest", [("Mobs, dailies, quests, turn-ins","")]),
    ("Kurenai / Mag&rsquo;har", "Nagrand", [("Mobs, quests, turn-ins","")]),
    ("Netherwing <span class='ph'>p3</span>", "Shadowmoon Valley", [("Dailies, quests, turn-ins","")]),
    ("Ogri&rsquo;la <span class='ph'>p2</span>", "Blade&rsquo;s Edge Mountains", [("Dailies, quests","")]),
    ("Sporeggar", "Zangarmarsh", [("The Underbog","exalted"),("Mobs, quests, repeatables, turn-ins","")]),
    ("Violet Eye", "Deadwind Pass", [("Karazhan","")]),
    ("Ashtongue Deathsworn <span class='ph'>p3</span>", "Shadowmoon Valley", [("Black Temple","")]),
    ("Scale of the Sands <span class='ph'>p3</span>", "Caverns of Time", [("The Battle for Mount Hyjal","")]),
    ("Shattered Sun Offensive <span class='ph'>p4</span>", "Isle of Quel&rsquo;Danas", [("Magisters&rsquo; Terrace","")]),
]

# --- Dungeon & zone viability (level ranges) ---
DUNGEON_LVL = [
    ("Hellfire Ramparts","58-63","59-62"),("The Blood Furnace","61-64","61-63"),
    ("The Slave Pens","62-65","62-64"),("The Underbog","63-65","62-65"),
    ("Mana-Tombs","64-66","63-66"),("Auchenai Crypts","65-67","65-67"),
    ("Old Hillsbrad Foothills","66-68","66-68"),("Sethekk Halls","66-69","66-69"),
    ("Shadow Labyrinth","68-70","69-72"),("The Steam Vaults","69-70","70-72"),
    ("The Shattered Halls","69-70","69-72"),("The Black Morass","69-70","70-72"),
    ("The Botanica","70","70-72"),("The Mechanar","70","69-72"),("The Arcatraz","70","70-72"),
]
ZONE_LVL = [
    ("Hellfire Peninsula","58-63","57-63"),("Zangarmarsh","61-65","60-64 (65)"),
    ("Terokkar Forest","62-66","62-66"),("Nagrand","64-68","64-68 (71)"),
    ("Blade&rsquo;s Edge Mountains","65-69","65-68 (72)"),("Netherstorm","67-70","66-70 (72)"),
    ("Shadowmoon Valley","68-70","67-71 (73)"),
]

# --- Difficulty tiers ---
NORMAL_DIFF = [
    ("easy", ["The Botanica","Shadow Labyrinth"]),
    ("medium", ["The Mechanar","The Steam Vaults","The Shattered Halls","The Black Morass"]),
    ("hard", ["The Arcatraz"]),
]
HEROIC_DIFF = [
    ("easy", ["Hellfire Ramparts","The Slave Pens","The Steam Vaults","Auchenai Crypts","The Botanica"]),
    ("medium", ["The Underbog","Sethekk Halls","Shadow Labyrinth","The Mechanar"]),
    ("hard", ["Mana-Tombs","Old Hillsbrad Foothills","The Black Morass"]),
    ("very hard", ["The Shattered Halls","The Blood Furnace","The Arcatraz"]),
]

# --- Dungeon keys ---
KEY_GROUPS = [
    ("Hellfire Citadel", [
        ("Hellfire Ramparts","60","–","Flamewrought Key"),
        ("The Blood Furnace","61","–","Flamewrought Key"),
        ("The Shattered Halls","69","Shattered Halls Key","Flamewrought Key"),
    ]),
    ("Coilfang Reservoir", [
        ("The Slave Pens","62","–","Reservoir Key"),
        ("The Underbog","63","–","Reservoir Key"),
        ("The Steam Vaults","69","–","Reservoir Key"),
    ]),
    ("Auchindoun", [
        ("Mana-Tombs","64","–","Auchenai Key"),
        ("Auchenai Crypts","65","–","Auchenai Key"),
        ("Sethekk Halls","66","–","Auchenai Key"),
        ("Shadow Labyrinth","68","Shadow Labyrinth Key","Auchenai Key"),
    ]),
    ("Caverns of Time", [
        ("Old Hillsbrad Foothills","66","The Caverns of Time","Key of Time"),
        ("The Black Morass","69","Return to Andormu","Key of Time"),
    ]),
    ("Tempest Keep", [
        ("The Botanica","70","fly mount","Warpforged Key"),
        ("The Mechanar","70","fly mount","Warpforged Key"),
        ("The Arcatraz","70","Key to the Arcatraz","Warpforged Key"),
    ]),
    ("Magisters&rsquo; Terrace <span class='ph'>p4</span>", [
        ("Magisters&rsquo; Terrace","70","–","Hard to Kill"),
    ]),
]

# --- Raids & attunement ---
RAIDS = [
    ("Magtheridon&rsquo;s Lair","","–"),
    ("Gruul&rsquo;s Lair","","–"),
    ("Karazhan","","The Master&rsquo;s Key"),
    ("Serpentshrine Cavern","p2","The Cudgel of Kar&rsquo;desh"),
    ("Tempest Keep","p2","Trial of the Naaru: Magtheridon"),
    ("Black Temple","p3","Medallion of Karabor"),
    ("The Battle for Mount Hyjal","p3","The Vials of Eternity"),
    ("Zul&rsquo;Aman","p3.5","–"),
    ("Sunwell Plateau","p4","–"),
]

# --- Phase 1 quartermaster rewards (both factions share rewards under different names) ---
QM_ROLES = ["Agi DPS","Str DPS","Caster","Healer","Tank"]
QM = {
 "honored": [
    ["Grunt&rsquo;s Waraxe","Explorer&rsquo;s Walking Stick","Farseer&rsquo;s Band","Preserver&rsquo;s Cudgel","Petrified Lichen Guard"],
    ["Footman&rsquo;s Longsword","","Sage&rsquo;s Band","",""],
    ["Explorer&rsquo;s Walking Stick","","Nethershard","",""],
    ["Gift of the Ethereal","","","",""],
 ],
 "revered": [
    ["Glyph of Ferocity","Glyph of Ferocity","Glyph of Power","Glyph of Renewal","Glyph of the Defender"],
    ["Blackened Spear","Glyph of the Outcast","Xi&rsquo;ri&rsquo;s Gift","Ancestral Band","Timewarden&rsquo;s Leggings"],
    ["Hellforged Halberd","Consortium Blaster","Stormspire Vest","Ring of Convalescence","Vindicator&rsquo;s Hauberk"],
    ["Consortium Blaster","Salvager&rsquo;s Hauberk","Leggings of the Skettis Exile","Lower City Prayerbook","Gauntlets of the Chosen"],
    ["Nomad&rsquo;s Leggings","Retainer&rsquo;s Leggings","Continuum Blade","Seer&rsquo;s Cane",""],
    ["Salvager&rsquo;s Hauberk","","Sporeling&rsquo;s Firestick","",""],
    ["Blessed Scale Girdle","","Anchorite&rsquo;s Robes","",""],
    ["Hardened Stone Shard","","Auchenai Staff","",""],
    ["Lightwarden&rsquo;s Band","","Scryer&rsquo;s Bloodgem","",""],
    ["Retainer&rsquo;s Leggings","","","",""],
 ],
 "exalted": [
    ["Marksman&rsquo;s Bow","Earthwarden","Stormcaller","Windcaller&rsquo;s Orb","Warbringer"],
    ["Veteran&rsquo;s Musket","Haramad&rsquo;s Bargain","Blade of the Archmage","Nether Runner&rsquo;s Cowl","Honor&rsquo;s Call"],
    ["Guile of Khoraazi","Shapeshifter&rsquo;s Signet","Ashyen&rsquo;s Gift","Bindings of the Timewalker","Earthwarden"],
    ["Haramad&rsquo;s Bargain","Trident of the Outcast Tribe","Nether Runner&rsquo;s Cowl","Gavel of Pure Light","Timelapse Shard"],
    ["Shapeshifter&rsquo;s Signet","A&rsquo;dal&rsquo;s Command","Gavel of Unearthed Secrets","Medallion of the Lightbearer","Crest of the Sha&rsquo;tar"],
    ["Riftmaker","","Seer&rsquo;s Signet","",""],
    ["A&rsquo;dal&rsquo;s Command","","","",""],
    ["Vindicator&rsquo;s Brand","","","",""],
    ["Retainer&rsquo;s Blade","","","",""],
 ],
}

# --- Rep from quests (per-faction sources) ---
REP_SOURCES = [
    ("Honor Hold", [("dungeons","2800"),("Hellfire Peninsula","11620")]),
    ("Thrallmar", [("dungeons","2300"),("Hellfire Peninsula","12940")]),
    ("Cenarion Expedition", [("dungeons","2335"),("Hellfire Peninsula","1805"),("Zangarmarsh","6525"),("Terokkar Forest","2425"),("Blade&rsquo;s Edge Mountains","4820"),("Netherstorm","850")]),
    ("Sporeggar", [("dungeons","1450"),("Zangarmarsh","2000 + repeatables")]),
    ("Lower City", [("dungeons","1950"),("Terokkar Forest","6700")]),
    ("Consortium", [("dungeons","1850"),("Nagrand","1510 + repeatables"),("Blade&rsquo;s Edge Mountains","1500"),("Netherstorm","11915 + repeatables"),("daily dungeons &amp; HC","")]),
    ("Keepers of Time", [("dungeons","14270")]),
    ("Sha&rsquo;tar", [("dungeons","3645"),("Terokkar Forest","1610"),("Nagrand","1175"),("Shadowmoon Valley","1900")]),
    ("Aldor / Scryers", [("Terokkar Forest","75"),("Nagrand","75"),("Shattrath City","6860"),("Netherstorm","4425"),("Shadowmoon Valley","2900")]),
    ("Sha&rsquo;tari Skyguard <span class='ph'>p2</span>", [("Shattrath City","325"),("Blade&rsquo;s Edge Mountains","3820"),("Skettis","3485"),("and dailies","")]),
    ("Ogri&rsquo;la <span class='ph'>p2</span>", [("Blade&rsquo;s Edge Mountains","3755"),("and dailies","")]),
    ("Kurenai", [("Zangarmarsh","2250"),("Nagrand","6035 + repeatables")]),
    ("Mag&rsquo;har", [("Hellfire Peninsula","1100"),("Terokkar Forest","760"),("Nagrand","9015 + repeatables")]),
    ("Netherwing <span class='ph'>p3</span>", [("intro","42000"),("Shadowmoon Valley","9575"),("and dailies","")]),
    ("Violet Eye", [("kara attune","2100"),("Nightbane attune","4345"),("ring chain","1300")]),
    ("Ashtongue Deathsworn <span class='ph'>p3</span>", [("Shadowmoon Valley","3250"),("raids","2600")]),
    ("Scale of the Sands <span class='ph'>p3</span>", [("raid","3000"),("ring chain","1300")]),
    ("Shattered Sun Offensive <span class='ph'>p5</span>", [("Isle of Quel&rsquo;Danas","620"),("dungeons","750"),("and a myriad of dailies","")]),
]

# --- Notable open-world pre-70 quests ---
QUESTS = [
    ("Overlord","chain","trinket","Hellfire Peninsula","Honor Hold"),
    ("Cruel&rsquo;s Intentions","chain","trinket","Hellfire Peninsula","Thrallmar"),
    ("The Foot of the Citadel","chain","chest","Hellfire Peninsula","Thrallmar"),
    ("Drill the Drillmaster","chain","chest","Hellfire Peninsula","Honor Hold"),
    ("Grillok &ldquo;Darkeye&rdquo;","chain","chest","Hellfire Peninsula","Thrallmar"),
    ("Zeth&rsquo;Gor Must Burn!","chain","chest","Hellfire Peninsula","Honor Hold"),
    ("Natural Remedies","chain","varies","Hellfire Peninsula","Cenarion Expedition"),
    ("The Skettis Offensive","prequest","neck","Shattrath City","Lower City"),
    ("Fhwoor Smash!","exalted rep","weapons","Zangarmarsh","Sporeggar"),
    ("The Big Bone Worm","chain","weapons","Terokkar Forest","Lower City"),
    ("The Ultimate Bloodsport","chain","ranged weapons","Nagrand","–"),
    ("Levixus the Soul Caller","dungeon chain","varies","Terokkar Forest","Sha&rsquo;tar"),
    ("Gurok the Usurper","chain","neck","Nagrand","–"),
    ("Bring Me The Egg!","prequest","cloak","Nagrand","–"),
    ("Message to Telaar","chain","varies","Nagrand","Kurenai"),
    ("Message to Garadar","chain","varies","Nagrand","Mag&rsquo;har"),
    ("The Ring of Blood: The Final Challenge","small chain","weapons","Nagrand","–"),
    ("The Hound-Master","chain","neck","Blade&rsquo;s Edge Mountains","Cenarion Expedition"),
    ("Showdown","chain","varies","Blade&rsquo;s Edge Mountains","–"),
    ("Cho&rsquo;war the Pillager","chain","varies","Nagrand","Kurenai / Mag&rsquo;har"),
    ("Hero of the Mag&rsquo;har","long chain","varies","Nagrand","Mag&rsquo;har"),
    ("Forge Camp: Annihilated","chain","varies","Nagrand","–"),
    ("Wanted: Durn the Hungerer","chain","weapons","Nagrand","Kurenai / Mag&rsquo;har"),
    ("Special Delivery to Shattrath City","part of Arcatraz chain","varies","Netherstorm","Sha&rsquo;tar"),
    ("Teron Gorefiend, I am...","chain","head","Shadowmoon Valley","–"),
    ("Deathblow to the Legion","chain","varies","Netherstorm","Aldor"),
    ("Turning Point","chain","varies","Netherstorm","Scryers"),
    ("Shutting Down Manaforge Ara","chain","varies","Netherstorm","Aldor / Scryers"),
    ("Hitting the Motherlode","chain","varies","Netherstorm","Consortium"),
    ("Quenching the Blade","dungeon chain","weapons","Terokkar Forest","–"),
    ("News of Victory","chain","varies","Shadowmoon Valley","–"),
    ("Destroy Naberius!","chain","varies","Netherstorm","–"),
    ("Back to the Chief!","chain","varies","Netherstorm","–"),
    ("The Cipher of Damnation &ndash; The Third Fragment Recovered","chain","varies","Shadowmoon Valley","–"),
    ("Dimensius the All-Devouring","chain","varies (BiS tank trinket)","Netherstorm","Consortium"),
    ("Nexus-King Salhadaar","chain","weapons","Netherstorm","Consortium"),
    ("Dissension Amongst the Ranks...","chain","ring","Netherstorm","–"),
    ("Battle of the Crimson Watch","prequest","ring","Shadowmoon Valley","Sha&rsquo;tar"),
    ("Varedis Must Be Stopped","dungeon chain","varies","Shadowmoon Valley","Aldor / Scryers"),
    ("The Cipher of Damnation","chain","weapons","Shadowmoon Valley","–"),
    ("Akama&rsquo;s Promise","chain","varies","Shadowmoon Valley","Sha&rsquo;tar / Ashtongue Deathsworn"),
]

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def rep_badge(rep):
    if not rep:
        return ""
    return f'<span class="rep rep-{rep}">{rep}</span>'

def diff_block(tiers):
    out = []
    for name, items in tiers:
        chips = "".join(f'<span class="chip">{esc(i) if "&" not in i else i}</span>' for i in items)
        out.append(f'<div class="diffrow"><span class="diff diff-{name.replace(" ","")}">{name}</span><div class="chips">{chips}</div></div>')
    return "".join(out)

# ---- Build route nodes ----
# Each node carries a real, keyboard-accessible checkbox. The big level badge
# is a <label for> bound to that checkbox, so clicking the circle toggles it
# too. data-step-id is a stable, title-derived key used for localStorage.
route_nodes = []
route_steps_js = []  # [{id, lvl}] embedded into the page for the progress bar
for i, s in enumerate(ROUTE):
    sid = "route-" + slug(s["title"])
    do_items = "".join(f"<li>{linkify(d)}</li>" for d in s["do"])
    tips = ""
    if s["tips"]:
        tips = '<ul class="tips">' + "".join(f"<li>{linkify(t)}</li>" for t in s["tips"]) + "</ul>"
    leave = (f'<div class="leave"><span class="leave-label">leave when</span> '
             f'{linkify(s["leave"])}</div>') if s["leave"] else ""
    title_html = maybe_link_entity(s["title"])
    aria = esc("Mark step complete: " + _wh_key(s["title"]))
    route_nodes.append(f"""
      <div class="node" id="node-{sid}" data-step-id="{sid}">
        <label class="lvlbadge" for="cb-{sid}" title="Toggle this step complete">
          <span class="lvl">{esc(s['lvl'])}</span><span class="check" aria-hidden="true">&#10003;</span>
        </label>
        <div class="card">
          <div class="cardtop">
            <h3>{title_html}</h3>
            <label class="stepcheck">
              <input type="checkbox" id="cb-{sid}" data-step="{sid}" data-route="1" aria-label="{aria}">
              <span class="cbx" aria-hidden="true"></span><span class="lbl">Done</span>
            </label>
          </div>
          <ul class="do">{do_items}</ul>
          {tips}
          {leave}
        </div>
      </div>""")
    route_steps_js.append({"id": sid, "lvl": _wh_key(s["lvl"])})
route_html = '<div class="flow">' + "".join(route_nodes) + '</div>'
ROUTE_STEPS_JSON = json.dumps(route_steps_js, ensure_ascii=False)

# ---- Faction cards ----
# Optional bonus: each faction header carries a checkbox so people can tick off
# a reputation goal as obtained — same localStorage pattern, separate from the
# route progress count.
fac_cards = []
for name, hq, dgs in FACTIONS:
    base = re.sub(r"\s*<span class='ph'>.*?</span>\s*", "", name)
    fid = "fac-" + slug(base)
    rows = ""
    for d, rep in dgs:
        rows += f'<li><span class="dg">{maybe_link_entity(d)}</span>{rep_badge(rep)}</li>'
    aria = esc("Reputation goal obtained: " + _wh_key(base))
    fac_cards.append(f"""
      <div class="faccard" data-step-id="{fid}">
        <div class="fachead">
          <div class="factext"><span class="facname">{link_faction(name)}</span><span class="hq">{hq}</span></div>
          <label class="goalcheck" title="Mark this reputation goal obtained">
            <input type="checkbox" id="cb-{fid}" data-step="{fid}" data-goal="1" aria-label="{aria}">
            <span class="cbx" aria-hidden="true"></span>
          </label>
        </div>
        <ul class="faclist">{rows}</ul>
      </div>""")
fac_html = '<div class="facgrid">' + "".join(fac_cards) + '</div>'

# ---- Level-range tables ----
def lvl_table(rows, head):
    body = "".join(f'<tr><td class="name">{maybe_link_entity(n)}</td><td class="num">{esc(a)}</td><td class="num">{esc(b)}</td></tr>' for n,a,b in rows)
    return f'<table class="lvl"><thead><tr><th scope="col">{head}</th><th scope="col">Lvl range</th><th scope="col">NPC lvl</th></tr></thead><tbody>{body}</tbody></table>'

# ---- Keys table ----
# Optional bonus: each dungeon row is checkable ("key / attune obtained"),
# same localStorage pattern as the route (separate from the route count).
key_rows = ""
for grp, rows in KEY_GROUPS:
    key_rows += f'<tr class="grouprow"><td colspan="5">{link_faction(grp)}</td></tr>'
    for d, lvl, norm, hero in rows:
        kid = "key-" + slug(d)
        nv = "&ndash;" if norm == "–" else f'<span class="keyitem">{norm}</span>'
        aria = esc("Key or attune obtained: " + _wh_key(d))
        key_rows += (f'<tr data-step-id="{kid}">'
                     f'<td class="ck"><label class="rowcheck"><input type="checkbox" id="cb-{kid}" '
                     f'data-step="{kid}" data-goal="1" aria-label="{aria}">'
                     f'<span class="cbx" aria-hidden="true"></span></label></td>'
                     f'<td class="name">{maybe_link_entity(d)}</td><td class="num">{esc(lvl)}</td>'
                     f'<td>{nv}</td><td><span class="keyitem hero">{hero}</span></td></tr>')
keys_html = (f'<div class="tbl-scroll"><table class="keys keys-check"><thead><tr><th class="ck" title="obtained" scope="col">&#10003;</th>'
             f'<th scope="col">Dungeon</th><th scope="col">Lvl</th><th scope="col">Normal key</th><th scope="col">Heroic key</th></tr></thead>'
             f'<tbody>{key_rows}</tbody></table></div>')

# ---- Raids table ----
raid_rows = ""
for name, ph, req in RAIDS:
    phb = f' <span class="ph">{ph}</span>' if ph else ""
    rv = "&ndash;" if req == "–" else f'<span class="keyitem">{wh_link(req, label=req)}</span>'
    raid_rows += f'<tr><td class="name">{wh_link(name, label=name)}{phb}</td><td>{rv}</td></tr>'
raids_html = f'<table class="keys"><thead><tr><th scope="col">Raid</th><th scope="col">Attunement / requirement</th></tr></thead><tbody>{raid_rows}</tbody></table>'

# ---- QM tables ----
def qm_table(tier):
    head = "".join(f'<th scope="col">{r}</th>' for r in QM_ROLES)
    body = ""
    for row in QM[tier]:
        cells = ""
        for c in row:
            cells += f'<td>{wh_link(c, label=c)}</td>' if c else '<td class="empty">&middot;</td>'
        body += f"<tr>{cells}</tr>"
    return f'<div class="qmblock"><div class="qmtier qm-{tier}">{tier}</div><table class="qm"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

qm_html = "".join(qm_table(t) for t in ["honored","revered","exalted"])

# ---- Rep source cards ----
rep_cards = []
for name, srcs in REP_SOURCES:
    rows = ""
    total = 0
    for src, amt in srcs:
        amt_disp = amt
        try:
            total += int(amt)
        except (ValueError, TypeError):
            if amt and amt[0].isdigit():
                total += int(amt.split()[0])
        rows += f'<li><span class="src">{maybe_link_entity(src)}</span><span class="amt">{esc(amt_disp)}</span></li>'
    rep_cards.append(f"""
      <div class="repcard">
        <div class="rephead">{link_faction(name)}</div>
        <ul class="replist">{rows}</ul>
      </div>""")
rep_html = '<div class="repgrid">' + "".join(rep_cards) + '</div>'

# ---- Quests table ----
zone_class = {
 "Hellfire Peninsula":"z-hfp","Shattrath City":"z-shat","Zangarmarsh":"z-zang",
 "Terokkar Forest":"z-tero","Nagrand":"z-nag","Blade&rsquo;s Edge Mountains":"z-bem",
 "Netherstorm":"z-neth","Shadowmoon Valley":"z-smv",
}
quest_rows = ""
for q, req, rew, zone, fac in QUESTS:
    zc = zone_class.get(zone, "")
    facd = maybe_link_entity(fac) if fac != "–" else '<span class="empty">&middot;</span>'
    quest_rows += (f'<tr><td class="name">{wh_link(q, label=q)}</td><td>{esc(req)}</td>'
                   f'<td class="rew">{rew}</td><td><span class="zone {zc}">{maybe_link_entity(zone)}</span></td>'
                   f'<td>{facd}</td></tr>')
quests_html = (f'<div class="tbl-scroll"><table class="quests"><thead><tr><th scope="col">Quest</th><th scope="col">Requires</th><th scope="col">Reward</th>'
               f'<th scope="col">Zone</th><th scope="col">Faction</th></tr></thead><tbody>{quest_rows}</tbody></table></div>')

golden_html = "".join(f"<li>{g}</li>" for g in GOLDEN_RULES)

# ---------------------------------------------------------------------------
# CSS  +  page assembly
# ---------------------------------------------------------------------------
CSS = """
:root{
  --fel:#9bd62f; --fel-bright:#c2ff5e; --fel-dim:#6f9c1f;
  --gold:#f3c969; --bg:#0c0f0a; --bg2:#11150e; --panel:#161b12;
  --panel2:#1c2317; --line:#2a3420; --ink:#e7eede; --muted:#9aa890;
  --blue:#4ea3ff; --epic:#c77bff; --honored:#5ec24a; --revered:#3b9bd6; --exalted:#c77bff;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:
   radial-gradient(1200px 600px at 80% -10%, #1a2b12 0%, transparent 60%),
   radial-gradient(900px 500px at 10% 0%, #241236 0%, transparent 55%),
   var(--bg);
  background-attachment:fixed;
  color:var(--ink);font-family:"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:15px;line-height:1.5;}
a{color:var(--fel-bright);text-decoration:none}
h1,h2,h3{font-family:"Cinzel","Trebuchet MS",Georgia,serif;letter-spacing:.5px;margin:0}
.wrap{max-width:1180px;margin:0 auto;padding:0 22px 90px}

/* hero */
/* No top-edge background here: the portal back-link sits in a bare strip above
   the hero, so any gradient anchored to the hero's top draws a hard seam that
   reads as a stray bar across the top of the page. The hero glow comes from the
   h1 text-shadow + the body's fixed radial wash instead. (#12 anchored the body
   wash with background-attachment:fixed; the seam was this overlay.) */
header.hero{padding:54px 22px 30px;text-align:center;border-bottom:1px solid var(--line);}
.hero h1{font-size:40px;color:var(--fel-bright);text-shadow:0 0 22px rgba(155,214,47,.45),0 2px 0 #000;}
.hero .sub{color:var(--gold);margin-top:8px;font-size:17px;letter-spacing:2px;text-transform:uppercase}
.hero .src{color:var(--muted);font-size:13px;margin-top:12px}

/* sticky nav */
nav{position:sticky;top:0;z-index:30;background:rgba(10,12,8,.92);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--line);padding:9px 0}
nav .navin{max-width:1180px;margin:0 auto;padding:0 18px;display:flex;flex-wrap:wrap;gap:6px;justify-content:center}
nav a{font-size:12.5px;color:var(--muted);padding:5px 11px;border-radius:20px;border:1px solid transparent;
  text-transform:uppercase;letter-spacing:.6px}
nav a:hover{color:var(--fel-bright);border-color:var(--fel-dim);background:rgba(155,214,47,.07)}
nav a:focus-visible{color:var(--fel-bright);border-color:var(--fel-dim);background:rgba(155,214,47,.07);outline:2px solid var(--fel-bright);outline-offset:2px}

section{padding-top:46px}
h2.sec{font-size:25px;color:var(--fel);margin-bottom:4px;
  display:flex;align-items:center;gap:12px}
h2.sec::before{content:"";width:8px;height:26px;background:linear-gradient(var(--fel),var(--fel-dim));
  border-radius:2px;box-shadow:0 0 10px var(--fel-dim)}
.lead{color:var(--muted);margin:0 0 20px;max-width:760px}

/* golden rules */
.rules{background:linear-gradient(135deg,rgba(243,201,105,.1),rgba(243,201,105,.03));
  border:1px solid #4a3f1e;border-left:4px solid var(--gold);border-radius:10px;padding:14px 20px;margin:22px 0}
.rules ul{margin:0;padding-left:20px}
.rules li{margin:5px 0;color:#f0e7cf}

/* ---- flowchart ---- */
.flow{position:relative;margin-top:26px;padding-left:8px}
.flow::before{content:"";position:absolute;left:46px;top:14px;bottom:14px;width:3px;
  background:linear-gradient(var(--fel),var(--fel-dim) 60%,transparent);border-radius:2px;
  box-shadow:0 0 14px rgba(155,214,47,.4)}
.node{position:relative;display:flex;gap:22px;margin-bottom:18px;align-items:flex-start}
.lvlbadge{flex:0 0 auto;width:78px;min-height:78px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;text-align:center;
  font-family:"Cinzel",serif;font-weight:700;font-size:15px;line-height:1.05;padding:6px;
  color:#0c0f0a;background:radial-gradient(circle at 35% 30%,var(--fel-bright),var(--fel-dim));
  border:3px solid #0c0f0a;box-shadow:0 0 0 3px var(--fel-dim),0 0 18px rgba(155,214,47,.5);
  position:relative;z-index:2}
.card{flex:1;background:linear-gradient(180deg,var(--panel2),var(--panel));
  border:1px solid var(--line);border-radius:12px;padding:15px 20px;
  box-shadow:0 8px 26px rgba(0,0,0,.4)}
.card h3{font-size:19px;color:var(--gold);margin-bottom:9px}
.card ul.do{margin:0;padding-left:19px}
.card ul.do li{margin:4px 0}
ul.tips{margin:10px 0 0;padding:9px 14px 9px 30px;list-style:none;position:relative;
  background:rgba(78,163,255,.07);border:1px solid #1f3a52;border-radius:8px}
ul.tips li{margin:3px 0;color:#bcd6ee;position:relative}
ul.tips li::before{content:"\\1F4A1";position:absolute;left:-22px}
.leave{margin-top:11px;padding-top:10px;border-top:1px dashed var(--line);color:var(--fel-bright);font-weight:600}
.leave-label{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:1px;
  color:#0c0f0a;background:var(--fel);padding:1px 8px;border-radius:4px;margin-right:8px;font-weight:700;vertical-align:middle}

/* rep badges */
.rep{font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;font-weight:700;
  padding:2px 9px;border-radius:11px;margin-left:auto;white-space:nowrap}
.rep-honored{background:rgba(94,194,74,.18);color:var(--honored);border:1px solid #2f6a25}
.rep-revered{background:rgba(59,155,214,.16);color:var(--revered);border:1px solid #265d80}
.rep-exalted{background:rgba(199,123,255,.16);color:var(--exalted);border:1px solid #5a3a7a}
.rep-friendly{background:rgba(154,168,144,.14);color:#b7c4ad;border:1px solid #45523c}

/* faction grid */
.facgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.faccard{background:var(--panel);border:1px solid var(--line);border-radius:11px;overflow:hidden;
  display:flex;flex-direction:column}
.fachead{padding:11px 15px;background:linear-gradient(180deg,var(--panel2),var(--panel));
  border-bottom:1px solid var(--line)}
.facname{display:block;font-weight:700;color:var(--gold);font-size:15.5px}
.facname .ph,.ph{font-size:10px;background:var(--epic);color:#1a0a26;padding:1px 6px;border-radius:9px;
  vertical-align:middle;font-weight:700;letter-spacing:.4px}
.phnote{color:var(--muted);font-size:12.5px;margin:-10px 0 18px;max-width:860px}
.phnote .ph{margin:0 2px}
.hq{display:block;color:var(--muted);font-size:12px;margin-top:2px}
.faclist{list-style:none;margin:0;padding:8px 15px 12px}
.faclist li{display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px dotted #232c1b}
.faclist li:last-child{border-bottom:none}
.dg{flex:1}

/* generic tables */
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);
  border-radius:10px;overflow:hidden;font-size:13.5px}
thead th{background:var(--panel2);color:var(--fel);text-align:left;padding:9px 13px;font-size:11.5px;
  text-transform:uppercase;letter-spacing:.7px;border-bottom:1px solid var(--line)}
tbody td{padding:8px 13px;border-bottom:1px solid #1d2416}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:rgba(155,214,47,.045)}
td.name{font-weight:600;color:var(--ink)}
td.num{color:var(--gold);font-variant-numeric:tabular-nums;text-align:center;width:90px}
td.empty,.empty{color:#3c4633;text-align:center}
.twocol{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.tblcap{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin:0 0 7px}
.tbl-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* difficulty */
.diffwrap{display:grid;grid-template-columns:1fr 1fr;gap:26px}
.diffrow{display:flex;gap:12px;align-items:flex-start;margin:11px 0}
.diff{flex:0 0 78px;text-align:center;font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.6px;padding:5px 0;border-radius:7px;margin-top:2px}
.diff-easy{background:rgba(94,194,74,.16);color:#7ed463;border:1px solid #2f6a25}
.diff-medium{background:rgba(243,201,105,.14);color:var(--gold);border:1px solid #5a4d20}
.diff-hard{background:rgba(255,140,60,.14);color:#ff9b4d;border:1px solid #6b4321}
.diff-veryhard{background:rgba(255,80,80,.14);color:#ff6b6b;border:1px solid #6b2424}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:3px 11px;font-size:12.5px}

/* keys */
.keys td .keyitem{background:rgba(78,163,255,.12);color:var(--blue);border:1px solid #1f3a52;
  padding:2px 8px;border-radius:6px;font-size:12.5px;font-weight:600}
.keys td .keyitem.hero{background:rgba(199,123,255,.12);color:var(--epic);border-color:#4a3060}
/* Keep key names whole — a pill like "Shadow Labyrinth Key" should never break
   mid-name when the column narrows. Scoped to the dungeon-keys table, which is
   wrapped in .tbl-scroll (so extreme narrow widths scroll, not clip); the raids
   table is left free to wrap its longer attunement phrases. */
.keys-check td .keyitem{white-space:nowrap}
tr.grouprow td{background:linear-gradient(90deg,rgba(155,214,47,.1),transparent);
  color:var(--fel);font-family:"Cinzel",serif;font-weight:700;font-size:13px;letter-spacing:.5px;
  text-transform:uppercase}

/* QM */
.qmblock{margin-bottom:20px;overflow-x:auto;-webkit-overflow-scrolling:touch}
.qmtier{display:inline-block;font-family:"Cinzel",serif;font-size:14px;font-weight:700;text-transform:capitalize;
  padding:4px 16px;border-radius:8px 8px 0 0;color:#0c0f0a}
.qm-honored{background:var(--honored)} .qm-revered{background:var(--revered)} .qm-exalted{background:var(--exalted)}
table.qm{border-top-left-radius:0}
table.qm td{font-size:12.5px}
table.qm thead th{width:20%}

/* rep grid */
.repgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:13px}
.repcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.rephead{padding:9px 14px;background:var(--panel2);border-bottom:1px solid var(--line);
  font-weight:700;color:var(--gold);font-size:14px}
.replist{list-style:none;margin:0;padding:7px 14px 11px}
.replist li{display:flex;justify-content:space-between;gap:10px;padding:3px 0;border-bottom:1px dotted #232c1b}
.replist li:last-child{border-bottom:none}
.src{color:var(--muted)}
.amt{color:var(--gold);font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap}

/* quests */
.quests td.rew{color:var(--fel-bright);font-style:italic}
.zone{font-size:11.5px;padding:2px 9px;border-radius:11px;white-space:nowrap;border:1px solid}
.z-hfp{background:rgba(196,84,52,.15);color:#ff8a66;border-color:#5c2f20}
.z-shat{background:rgba(243,201,105,.13);color:var(--gold);border-color:#5a4d20}
.z-zang{background:rgba(78,200,160,.13);color:#56d6a8;border-color:#205045}
.z-tero{background:rgba(120,160,90,.16);color:#a7d06a;border-color:#3c4d23}
.z-nag{background:rgba(120,200,230,.13);color:#7fd0ec;border-color:#234a55}
.z-bem{background:rgba(200,150,90,.14);color:#e0a35c;border-color:#5a4324}
.z-neth{background:rgba(160,120,230,.14);color:#b594f0;border-color:#3f3060}
.z-smv{background:rgba(220,80,90,.14);color:#f06b78;border-color:#5c242a}

footer{margin-top:60px;padding-top:24px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12.5px;text-align:center}

/* portal chrome (part of the hype site) */
.portal-back{display:inline-block;margin:14px 0 -8px 18px;font-size:12px;letter-spacing:.4px;
  color:var(--muted);text-decoration:none;border:1px solid var(--line);border-radius:20px;
  padding:5px 13px;transition:color .14s,border-color .14s,background .14s}
.portal-back:hover{color:var(--fel-bright);border-color:var(--fel-dim);background:rgba(155,214,47,.08)}
.portal-back:focus-visible{color:var(--fel-bright);border-color:var(--fel-dim);background:rgba(155,214,47,.08);outline:2px solid var(--fel-bright);outline-offset:2px}
.foot-links{margin-bottom:9px;font-size:13px}
.foot-links a{color:var(--muted);min-height:44px;display:inline-flex;align-items:center;vertical-align:middle;padding:0 .5rem}
.foot-links a:hover{color:var(--fel-bright)}
.foot-links a:focus-visible{color:var(--fel-bright);outline:2px solid var(--fel-bright);outline-offset:2px}
.foot-note{color:var(--muted);font-size:11.5px;max-width:640px;margin:0 auto;line-height:1.5}
.foot-note a{color:var(--muted);text-decoration:underline;text-underline-offset:2px}
.foot-note a:hover{color:var(--fel-bright)}

/* ============ Wowhead links (Goal 2) ============ */
a.wh{color:var(--fel-bright);border-bottom:1px dotted transparent;transition:border-color .12s,color .12s}
a.wh:hover{border-bottom-color:currentColor}
/* In dense tables, headings and chips, links inherit local colour so the
   layout the guide hand-tuned isn't disrupted. Wowhead's colorLinks still
   rarity-tints resolved item/quest links via inline styles. */
.card h3 a.wh, table a.wh, .chip a.wh, .zone a.wh, .keyitem a.wh,
.faclist a.wh, .replist a.wh{color:inherit;border-bottom-color:transparent}
.card h3 a.wh:hover, table a.wh:hover, .chip a.wh:hover,
.faclist a.wh:hover, .replist a.wh:hover{color:var(--fel-bright)}
/* search-fallback links (no id, no tooltip) stay quiet */
a.wh-q{color:inherit;border-bottom:1px dotted rgba(155,214,47,.26)}
a.wh-q:hover{color:var(--fel-bright);border-bottom-color:currentColor}

/* ============ Interactive route (Goal 1) ============ */
/* sticky progress bar */
.progress{position:sticky;top:44px;z-index:40;margin:0 0 20px;
  background:linear-gradient(180deg,rgba(12,15,10,.975),rgba(12,15,10,.93));
  backdrop-filter:blur(8px);border:1px solid var(--line);border-radius:12px;
  padding:12px 16px;box-shadow:0 8px 22px rgba(0,0,0,.5)}
.progress .ptop{display:flex;align-items:center;justify-content:space-between;
  gap:12px 16px;margin-bottom:9px;flex-wrap:wrap}
.progress .plabel{font-family:"Cinzel",serif;font-weight:700;font-size:15.5px;color:var(--gold)}
.progress .plabel b{color:var(--fel-bright)}
.progress .pright{display:flex;align-items:center;gap:12px}
.progress .pcount{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.pbar{height:12px;border-radius:7px;background:rgba(0,0,0,.4);border:1px solid var(--line);overflow:hidden}
.pfill{height:100%;width:0;border-radius:7px;
  background:linear-gradient(90deg,var(--fel-dim),var(--fel-bright));
  box-shadow:0 0 12px rgba(155,214,47,.6);transition:width .35s ease}
.progress.complete .pfill{background:linear-gradient(90deg,var(--gold),#ffe39a);
  box-shadow:0 0 14px rgba(243,201,105,.7)}
.progress.complete .plabel{color:var(--gold)}
.resetbtn{font:inherit;font-size:11px;text-transform:uppercase;letter-spacing:.7px;font-weight:700;
  color:var(--muted);background:rgba(255,255,255,.03);border:1px solid var(--line);
  border-radius:8px;padding:5px 11px;cursor:pointer;transition:all .15s}
.resetbtn:hover{color:#ff8a66;border-color:#5c2f20;background:rgba(196,84,52,.1)}
.resetbtn:focus-visible{outline:2px solid var(--fel-bright);outline-offset:2px}
.jumpbtn{font:inherit;font-size:11px;text-transform:uppercase;letter-spacing:.7px;font-weight:700;
  color:var(--muted);background:rgba(255,255,255,.03);border:1px solid var(--line);
  border-radius:8px;padding:5px 11px;cursor:pointer;transition:all .15s}
.jumpbtn:hover{color:var(--fel-bright);border-color:#2f5c20;background:rgba(105,196,52,.1)}
.jumpbtn:focus-visible{outline:2px solid var(--fel-bright);outline-offset:2px}
.progress.complete .jumpbtn{display:none}

/* card header that holds the checkbox */
.cardtop{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.cardtop h3{margin-bottom:0}
.stepcheck{display:inline-flex;align-items:center;gap:7px;cursor:pointer;flex:0 0 auto;
  user-select:none;padding:3px 5px;border-radius:8px}
.stepcheck .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-weight:700}
.stepcheck:hover .lbl{color:var(--ink)}
.node.done .stepcheck .lbl{color:var(--gold)}

/* the visually-hidden native checkbox stays keyboard-focusable; the .cbx span
   is the painted box */
.stepcheck input,.goalcheck input,.rowcheck input{
  position:absolute;width:1px;height:1px;opacity:0;margin:0;pointer-events:none}
.cbx{display:inline-block;width:20px;height:20px;flex:0 0 auto;border-radius:6px;
  border:2px solid var(--fel-dim);background:rgba(0,0,0,.3);position:relative;transition:all .15s}
.cbx::after{content:"";position:absolute;left:5px;top:1px;width:6px;height:11px;
  border:solid #0c0f0a;border-width:0 3px 3px 0;transform:rotate(45deg) scale(0);
  transform-origin:center;transition:transform .15s}
input:checked + .cbx{background:radial-gradient(circle at 35% 30%,var(--gold),#b8902f);border-color:var(--gold)}
input:checked + .cbx::after{transform:rotate(45deg) scale(1)}
.stepcheck input:focus-visible + .cbx,.goalcheck input:focus-visible + .cbx,
.rowcheck input:focus-visible + .cbx{outline:2px solid var(--fel-bright);outline-offset:2px}

/* level badge is now a clickable label */
.lvlbadge{cursor:pointer}
.lvlbadge .lvl{transition:opacity .15s}
.lvlbadge .check{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:36px;color:#0c0f0a;opacity:0;transform:scale(.4);transition:all .18s}

/* done step: gold/filled node, dimmed + struck card */
.node{transition:opacity .2s}
.node.done .card{opacity:.58}
.node.done .card h3{text-decoration:line-through;text-decoration-color:rgba(243,201,105,.6)}
.node.done .lvlbadge{background:radial-gradient(circle at 35% 30%,var(--gold),#b8902f);
  box-shadow:0 0 0 3px #8a6a1e,0 0 18px rgba(243,201,105,.55)}
.node.done .lvlbadge .lvl{opacity:.3}
.node.done .lvlbadge .check{opacity:1;transform:scale(1)}

/* current step: "you are here" */
.node.current::after{content:"you are here";position:absolute;left:2px;top:-13px;
  font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#0c0f0a;
  background:var(--fel-bright);padding:2px 9px;border-radius:8px;
  box-shadow:0 0 12px rgba(155,214,47,.6);z-index:3}
.node.current .lvlbadge{animation:youarehere 1.8s ease-in-out infinite}
@keyframes youarehere{
  0%,100%{box-shadow:0 0 0 3px var(--fel-bright),0 0 12px rgba(155,214,47,.5)}
  50%{box-shadow:0 0 0 4px var(--fel-bright),0 0 26px rgba(155,214,47,.95)}}
.node.current .card{border-color:var(--fel-dim);
  box-shadow:0 8px 26px rgba(0,0,0,.4),0 0 0 1px rgba(155,214,47,.35),inset 0 0 0 1px rgba(155,214,47,.1)}
@media(prefers-reduced-motion:reduce){.node.current .lvlbadge{animation:none}html{scroll-behavior:auto}}

/* faction rep-goal checkbox */
.fachead{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.factext{min-width:0}
.goalcheck{cursor:pointer;flex:0 0 auto;padding:2px;border-radius:6px;display:inline-flex}
.faccard.done{opacity:.62}
.faccard.done .facname{text-decoration:line-through;text-decoration-color:rgba(243,201,105,.5)}

/* keys table row checkbox */
.keys-check th.ck,.keys-check td.ck{width:36px;text-align:center;color:var(--fel-dim)}
.rowcheck{display:inline-flex;cursor:pointer;vertical-align:middle}
.keys-check tbody tr.done{opacity:.5}
.keys-check tbody tr.done td.name{text-decoration:line-through}

@media(max-width:760px){
  .twocol,.diffwrap{grid-template-columns:1fr}
  .lvlbadge{width:62px;min-height:62px;font-size:13px}
  .lvlbadge .check{font-size:30px}
  .flow::before{left:38px}
  .hero h1{font-size:30px}
  table{font-size:12.5px}
  .progress{top:72px;padding:10px 12px}
  .progress .plabel{font-size:14px}
  nav .navin{gap:3px;padding:0 8px}
  nav a{font-size:10px;padding:3px 6px;letter-spacing:.2px}
  .cardtop{gap:8px}
  .stepcheck .lbl{display:none}
}
"""

# Wowhead tooltip widget. renameLinks/iconizeLinks stay false so the guide's
# hand-written wording and dense tables aren't disrupted; colorLinks gives
# resolved item/quest links their rarity colour + hover tooltips. Kept as a
# plain string (not an f-string) so the JS object braces are literal.
WH_HEAD = (
    '<script>const whTooltips = {colorLinks:true, iconizeLinks:false, renameLinks:false};</script>\n'
    '<script async src="https://wow.zamimg.com/js/tooltips.js"></script>'
)

# Client-side progress: real checkboxes -> localStorage (one JSON object, keyed
# by stable per-step id) -> progress bar + "you are here" marker. No backend,
# no accounts, nothing leaves the browser. __ROUTE_STEPS__ is replaced with the
# embedded route metadata so the bar can show the current step's level.
PROGRESS_JS = """
<script>
(function () {
  "use strict";
  var KEY = "tbcGuide.progress.v1";
  var STEPS = __ROUTE_STEPS__;            // [{id, lvl}, ...] in route order
  var total = STEPS.length;

  function load() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  var state = load();

  var boxes = Array.prototype.slice.call(document.querySelectorAll("input[data-step]"));
  var elLabel = document.getElementById("plabel");
  var elCount = document.getElementById("pcount");
  var elFill  = document.getElementById("pfill");
  var elProg  = document.getElementById("progress");

  function applyState(cb) {
    var on = cb.checked;
    var node = cb.closest(".node");
    if (node) { node.classList.toggle("done", on); return; }
    var card = cb.closest(".faccard");
    if (card) { card.classList.toggle("done", on); return; }
    var row = cb.closest("tr");
    if (row) { row.classList.toggle("done", on); }
  }

  function recompute() {
    var doneCount = 0, currentIdx = -1;
    for (var i = 0; i < total; i++) {
      if (state[STEPS[i].id]) { doneCount++; }
      else if (currentIdx === -1) { currentIdx = i; }
    }
    Array.prototype.forEach.call(document.querySelectorAll(".node.current"),
      function (n) { n.classList.remove("current"); });
    if (elFill) { elFill.style.width = (total ? (doneCount / total * 100) : 0) + "%"; elFill.setAttribute("aria-valuenow", doneCount); }
    if (doneCount >= total) {
      if (elProg) { elProg.classList.add("complete"); }
      if (elLabel) { elLabel.innerHTML = "Complete &mdash; all " + total + " steps done"; }
      if (elCount) { elCount.textContent = total + " / " + total + " \\u00b7 level 70"; }
    } else {
      if (elProg) { elProg.classList.remove("complete"); }
      var step = STEPS[currentIdx];
      if (elLabel) { elLabel.innerHTML = "Step <b>" + (currentIdx + 1) + "</b> / " + total + " \\u2014 Level " + step.lvl; }
      if (elCount) { elCount.textContent = doneCount + " / " + total + " done"; }
      var cur = document.getElementById("node-" + step.id);
      if (cur) { cur.classList.add("current"); }
    }
  }

  var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion:reduce)").matches;

  function scrollToCurrent() {
    var node = document.querySelector(".node.current");
    if (!node) { return; }
    var navEl = document.querySelector("nav");
    var progEl = document.querySelector(".progress");
    var stickyOffset = (navEl ? navEl.offsetHeight : 0) + (progEl ? progEl.offsetHeight : 0) + 16;
    var y = node.getBoundingClientRect().top + window.pageYOffset - stickyOffset;
    window.scrollTo({ top: y, behavior: prefersReducedMotion ? "auto" : "smooth" });
  }

  // restore saved state on load
  boxes.forEach(function (cb) {
    cb.checked = !!state[cb.getAttribute("data-step")];
    applyState(cb);
  });
  recompute();

  boxes.forEach(function (cb) {
    cb.addEventListener("change", function () {
      var id = cb.getAttribute("data-step");
      var node = cb.closest(".node");
      var wasCurrent = node && node.classList.contains("current");
      if (cb.checked) { state[id] = 1; } else { delete state[id]; }
      save(state);
      applyState(cb);
      if (cb.hasAttribute("data-route")) {
        recompute();
        if (cb.checked && wasCurrent) { scrollToCurrent(); }  // advance to the next step
      }
    });
  });

  // The guide is ~1000 lines tall; once a dozen steps are done the current
  // node sits below a wall of completed cards. One click takes you there.
  var jump = document.getElementById("jumpbtn");
  if (jump) { jump.addEventListener("click", scrollToCurrent); }

  var reset = document.getElementById("resetbtn");
  if (reset) {
    reset.addEventListener("click", function () {
      if (!confirm("Reset your progress on this device? This unchecks every step, key, and rep goal.")) { return; }
      state = {}; save(state);
      boxes.forEach(function (cb) { cb.checked = false; applyState(cb); });
      recompute();
      window.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : "smooth" });
    });
  }
})();
</script>
""".replace("__ROUTE_STEPS__", ROUTE_STEPS_JSON)

HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TBC Dungeon Rep Leveling Guide &middot; hype</title>
<meta name="description" content="The Burning Crusade dungeon-reputation leveling route, 58 to 70 and into raids. Checkable steps, Wowhead tooltips, progress saved in your browser.">
<link rel="icon" href="/assets/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/assets/favicon-32.png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<meta name="theme-color" content="#0c0f0a">
<link rel="canonical" href="https://getajob.swagcounty.com/tbc/">
<meta property="og:title" content="TBC Dungeon Rep Leveling Guide">
<meta property="og:description" content="The dungeon-rep leveling route, 58 to 70 and into raids. Checkable, Wowhead-linked, saved in your browser.">
<meta property="og:url" content="https://getajob.swagcounty.com/tbc/">
<meta property="og:type" content="website">
<meta property="og:image" content="https://getajob.swagcounty.com/assets/og-card.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="TBC Dungeon Rep Leveling Guide — hype">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="TBC Dungeon Rep Leveling Guide">
<meta name="twitter:description" content="The dungeon-rep leveling route, 58 to 70 and into raids. Checkable, Wowhead-linked, saved in your browser.">
<meta name="twitter:image" content="https://getajob.swagcounty.com/assets/og-card.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&display=swap" media="print" onload="this.media='all'">
<noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&display=swap"></noscript>
<style>{CSS}</style>
{WH_HEAD}
</head>
<body>

<a class="portal-back" href="/">&larr; hype</a>

<header class="hero">
  <h1>The Burning Crusade</h1>
  <div class="sub">Dungeon Reputation Leveling Route</div>
  <div class="src">Reworked from &ldquo;TBC dungeon rep leveling (Stamaka).xlsx&rdquo; &middot; 58 &rarr; 70 &rarr; raids</div>
</header>

<nav aria-label="On this page"><div class="navin">
  <a href="#route">Leveling Route</a>
  <a href="#factions">Factions</a>
  <a href="#ranges">Level Ranges</a>
  <a href="#difficulty">Difficulty</a>
  <a href="#keys">Keys &amp; Attunes</a>
  <a href="#gear">Quartermaster Gear</a>
  <a href="#rep">Rep Sources</a>
  <a href="#quests">Notable Quests</a>
</div></nav>

<main class="wrap">

  <section id="route">
    <h2 class="sec">The Leveling Route</h2>
    <p class="lead">Follow the path top to bottom. Each node is a milestone: the big circle is your level, the card tells you what to do and when to move on. <b>Tick off each step</b> (click the circle or the checkbox) and your progress saves automatically in this browser.</p>
    <div class="progress" id="progress" role="group" aria-label="Leveling route progress">
      <div class="ptop">
        <span class="plabel" id="plabel" aria-live="polite" aria-atomic="true">Step 1 / {len(ROUTE)}</span>
        <div class="pright">
          <span class="pcount" id="pcount">0 / {len(ROUTE)} done</span>
          <button type="button" class="jumpbtn" id="jumpbtn">Jump to current step</button>
          <button type="button" class="resetbtn" id="resetbtn">Reset progress</button>
        </div>
      </div>
      <div class="pbar"><div class="pfill" id="pfill" role="progressbar" aria-valuemin="0" aria-valuemax="{len(ROUTE)}" aria-valuenow="0" aria-labelledby="plabel"></div></div>
    </div>
    <div class="rules"><ul>{golden_html}</ul></div>
    {route_html}
  </section>

  <section id="factions">
    <h2 class="sec">Factions &amp; Their Dungeons</h2>
    <p class="lead">Which dungeons and activities feed each reputation, where their home base is, and how far each source pays out (on normal mode, for dungeons). Heroic runs of any wing pay rep all the way to Exalted.</p>
    <p class="phnote">Phase badges follow the 2026 anniversary schedule — <span class="ph">p2</span> live since May 14, 2026 (SSC &amp; TK, Skyguard, Ogri&rsquo;la) &middot; <span class="ph">p3</span> Hyjal &amp; BT, Netherwing &middot; <span class="ph">p3.5</span> Zul&rsquo;Aman &middot; <span class="ph">p4</span> Sunwell, Magisters&rsquo; Terrace, Shattered Sun. Later-phase dates not yet announced.</p>
    {fac_html}
  </section>

  <section id="ranges">
    <h2 class="sec">Level Ranges</h2>
    <p class="lead">Where content is worth your time. &ldquo;Lvl range&rdquo; is the viable bracket; &ldquo;NPC lvl&rdquo; is the enemy level you&rsquo;ll face.</p>
    <div class="twocol">
      <div><p class="tblcap">Dungeon viability</p>{lvl_table(DUNGEON_LVL,"Dungeon")}</div>
      <div><p class="tblcap">Open-world zone viability</p>{lvl_table(ZONE_LVL,"Zone")}</div>
    </div>
  </section>

  <section id="difficulty">
    <h2 class="sec">Dungeon Difficulty</h2>
    <p class="lead">Relative difficulty by mob density, crowd-control demands, and gear check. Match the fight to your group.</p>
    <div class="diffwrap">
      <div><p class="tblcap">Normal &mdash; high-level dungeons</p>{diff_block(NORMAL_DIFF)}</div>
      <div><p class="tblcap">Heroic dungeons</p>{diff_block(HEROIC_DIFF)}</div>
    </div>
  </section>

  <section id="keys">
    <h2 class="sec">Keys &amp; Attunements</h2>
    <p class="lead">Normal-mode keys (where required) and the heroic key for each wing, plus raid entry requirements.</p>
    <div class="rules"><ul>
      <li>Heroic keys need <b>Revered</b> on your main (still true as of <span class="ph">p2</span> — the drop to Honored is expected in a later phase, as in 2021&rsquo;s P4).</li>
      <li>Attunements on the 2026 anniversary realms are <b>account-wide</b>: finish a chain once and your alts inherit it. A Revered main can also mail alts a <b>Communal Heroic Key</b>, usable at just Friendly.</li>
      <li>Raid attunements historically loosen as phases advance (2021: SSC/TK became optional in P3, Hyjal/BT in P4) — expect the same cadence here.</li>
    </ul></div>
    <div class="twocol">
      <div><p class="tblcap">Dungeon keys</p>{keys_html}</div>
      <div><p class="tblcap">Raids</p>{raids_html}</div>
    </div>
  </section>

  <section id="gear">
    <h2 class="sec">Phase&nbsp;1 Quartermaster Gear</h2>
    <p class="lead">Reputation rewards by role. Both factions of a pair (e.g. Aldor/Scryers, Honor Hold/Thrallmar) offer similar rewards under different names.</p>
    {qm_html}
  </section>

  <section id="rep">
    <h2 class="sec">Where the Rep Comes From</h2>
    <p class="lead">Approximate reputation available per source for each faction. Handy when you&rsquo;re short of a breakpoint.</p>
    {rep_html}
  </section>

  <section id="quests">
    <h2 class="sec">Notable Open-World Quests (pre-70)</h2>
    <p class="lead">Group quests and chains that reward blues. Most need a group, so grab guildies before you head out.</p>
    {quests_html}
  </section>

  <footer>
    <div class="foot-links">
      <a href="/">&larr; hype</a> &middot;
      <a href="https://swagcounty.com">Swag County</a> &middot;
      <a href="/privacy.html">Privacy</a> &middot;
      <a href="https://github.com/LLMATIONS/hype" target="_blank" rel="noopener">Source</a>
    </div>
    <div class="foot-note">A guild fan project &middot; not affiliated with Blizzard. Reworked from
    <a href="https://docs.google.com/spreadsheets/d/1RHHzSHiiNO9rMCYkYavtA2Rqx5huSLAS/edit?gid=797198729#gid=797198729" rel="noopener" target="_blank">Stamaka&rsquo;s &ldquo;TBC dungeon rep leveling&rdquo; spreadsheet</a>,
    cross-checked against Wowhead (TBC Classic), warcraft.wiki.gg &amp; Icy Veins, June 2026
    &middot; data links to Wowhead (TBC Classic).</div>
  </footer>
</main>
{PROGRESS_JS}
</body>
</html>"""

import io, os, sys
# Anchor the output to this script's directory so cwd doesn't matter — running
# `python3 tbc/build_tbc_guide.py` from the repo root must still land at
# tbc/index.html, never clobber the hub's root index.html. (Mirrors hub/build_hub.py.)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "index.html")
if "--check" in sys.argv[1:]:
    # CI guard (tbc-build.yml): fail if the committed index.html was hand-edited
    # or someone edited this generator and forgot to rebuild.
    current = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
    if current != HTML:
        sys.exit(
            "error: tbc/index.html is out of sync with build_tbc_guide.py.\n"
            "       run: python3 tbc/build_tbc_guide.py"
        )
    print("tbc/index.html is in sync with build_tbc_guide.py")
else:
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(HTML)
    print("Wrote %s  (%d chars)" % (OUT, len(HTML)))
