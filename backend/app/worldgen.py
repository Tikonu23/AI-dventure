"""World generation: one structured-output Claude call produces a complete
world (locations, exits, NPCs, pre-authored secret facts), validated in code
before it ever reaches the database.

The validator is the load-bearing part: a generated map with an unreachable
room is wasted tokens, but a room the party can enter and never leave is a
soft-locked game. Exit connectivity is checked in both directions from the
starting location. Validation failure retries once with the errors fed back;
a second failure raises and the caller degrades (pool: log and retry next
tick; on-demand create: fall back to the hand-authored FALLBACK_WORLD).

Counts are parameters with server defaults — the plan calls for players
requesting custom sizes later, within server-set limits.
"""

import base64
import json
import logging
import os
import random
import re
import xml.etree.ElementTree as ET

import anthropic
import httpx

from app import db

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"

# Server defaults; hard validation bounds are deliberately looser than the
# prompt's ask so a 5-location gem isn't rejected for missing a quota.
DEFAULT_LOCATIONS = (6, 9)
DEFAULT_NPCS = (3, 6)
HARD_LOCATION_BOUNDS = (4, 12)
HARD_NPC_BOUNDS = (2, 8)

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")

# Two random motifs seed each generation — without them, back-to-back calls
# converge on near-identical crypt delves. Same register, different worlds.
_MOTIFS = [
    "a drowned monastery",
    "a plague-quarantined port town",
    "a buried temple to a forgotten star",
    "an abandoned dwarven foundry",
    "a mire where an army sank and did not die",
    "a lighthouse that calls ships to wreck",
    "a manor whose family never stopped dining",
    "an ossuary city beneath a cathedral",
    "a glacier calving open an older world",
    "a mine that broke into something's burrow",
    "a witch-tribunal fortress turned prison for its judges",
    "a caravanserai on a road no map admits to",
    "a theater rehearsing a play that must not finish",
    "an orchard grafted onto gallows-wood",
]

WORLD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "concept": {"type": "string"},
        "starting_location": {"type": "string"},
        "locations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "exits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "direction": {"type": "string"},
                                "to": {"type": "string"},
                            },
                            "required": ["direction", "to"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "name", "description", "exits"],
                "additionalProperties": False,
            },
        },
        "npcs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "location": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["id", "location", "name", "description"],
                "additionalProperties": False,
            },
        },
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["entity", "key", "value"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "concept", "starting_location", "locations", "npcs", "facts"],
    "additionalProperties": False,
}

GEN_SYSTEM = """\
You are the world-builder for a Darkest Dungeon-style text adventure: \
grimdark, punishing, atmospheric dread, gothic horror. Never cheerful, \
never cute.

Author a complete, self-contained world for a party to explore. Rules:

- `id` fields are lowercase_snake_case slugs, unique across locations AND \
npcs.
- `concept` is a 2-3 sentence premise a game master will run the whole \
campaign from: what this place is, what is wrong with it, what presses on \
the party.
- Location descriptions are 2-4 sentences, written to be read aloud. \
Sensory, specific, dread-forward.
- Exits use simple lowercase directions (north, south, east, west, up, \
down). Every passage must work in BOTH directions — if the crypt is north \
of the gate, the gate is south of the crypt. Every location must be \
reachable from the starting location. No dead ends a party cannot walk \
back out of.
- The starting location is the world's threshold — the party arrives here.
- NPCs are strange, morally ambiguous, and placed in specific locations. \
Their descriptions say what they want and what is off about them.
- `facts` are SECRET pre-authored truths the game master will enforce but \
players must discover: a monster's weak spot, a hidden door and how it \
opens, what an NPC is concealing, a ritual's true cost. Write 4-8 of them. \
`entity` is the slug of the location or npc the fact belongs to, or \
"world" for campaign-level truths. Make them concrete and adjudicable — \
"the Collector's hood hides a second face that must be addressed by name" \
beats "the Collector has a secret".
"""

GEN_USER_TEMPLATE = """\
Author a world of {n_locations} locations and {n_npcs} NPCs.

Setting inspiration (bend it however serves the horror): {motif_a}; \
with an undercurrent of {motif_b}.
{feedback}"""


BACKDROP_SYSTEM = """\
You are a scenic artist painting theatrical backdrops for a Darkest \
Dungeon-style text adventure: grimdark, gothic horror, atmospheric dread.

Draw a single SVG backdrop for the world described by the user. Hard rules:

- Output ONLY the SVG markup. No prose, no code fences, no explanation.
- Root element: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" \
preserveAspectRatio="xMidYMid slice">.
- Near-black base in the #0b0b0f family; the whole scene stays dark and desaturated.
- Compose 3-5 depth layers of flat silhouette (horizon shapes, architecture, \
terrain) getting darker toward the foreground.
- Fog or mist as soft translucent bands or radial gradients between layers.
- Exactly ONE light source (a moon, lantern, flame, or glow) — small, focused, \
the emotional center of the image.
- Flat poster-art style: broad shapes, gradients, silhouettes. No fine detail, \
no texture noise.
- No text, no people or creatures, no animation, no <script>, no event \
attributes, no external references or images. Local url(#id) gradient refs \
are fine.
- Keep it under 200 SVG elements.
"""

_SVG_EXTRACT_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL)
_EVENT_ATTR_RE = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
_HREF_RE = re.compile(r"""(?:xlink:)?href\s*=\s*["']([^"']*)""", re.IGNORECASE)
MAX_BACKDROP_BYTES = 64_000


def sanitize_svg(svg: str) -> str | None:
    """Backdrops render via CSS background-image, which never executes SVG
    scripts — this is belt-and-braces so nothing active is ever stored.
    Returns the SVG unchanged, or None to reject (no partial stripping:
    a backdrop that trips any check is model misbehavior, not salvage)."""
    if len(svg.encode()) > MAX_BACKDROP_BYTES:
        return None
    lowered = svg.lower()
    if "<script" in lowered or "<foreignobject" in lowered or "javascript:" in lowered:
        return None
    if _EVENT_ATTR_RE.search(svg):
        return None
    # Only local fragment refs (#gradient-id) — no fetches of any kind.
    for match in _HREF_RE.finditer(svg):
        if not match.group(1).startswith("#"):
            return None
    try:
        ET.fromstring(svg)
    except ET.ParseError:
        return None
    return svg


# A1111 / SD-WebUI instance for backdrop_mode='local'.
SD_WEBUI_URL = os.environ.get("SD_WEBUI_URL", "http://127.0.0.1:7860")
# SD generation on modest local hardware is slow — be patient, not fragile.
SD_TIMEOUT_SECONDS = 180
MAX_RASTER_BYTES = 3_000_000

# xAI image generation for backdrop_mode='grok' (GROK_KEY in .env).
XAI_IMAGE_URL = "https://api.x.ai/v1/images/generations"
XAI_IMAGE_MODEL = os.environ.get("XAI_IMAGE_MODEL", "grok-imagine-image-quality")
XAI_TIMEOUT_SECONDS = 120

# Sniffed, not trusted: the mime we store must match the bytes we got.
_RASTER_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg"}


def _raster_data_uri(raw: bytes) -> str | None:
    for magic, mime in _RASTER_MAGIC.items():
        if raw.startswith(magic) and len(raw) <= MAX_RASTER_BYTES:
            return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    return None

# The concept is already Claude-authored evocative prose — it IS the image
# prompt. ponytail: templated, no prompt-writing model call; add one only if
# raster quality disappoints.
SD_PROMPT_SUFFIX = (
    ", dark gothic horror matte painting, flat atmospheric backdrop, muted "
    "desaturated palette, near-black tones, fog, single light source, "
    "no text, masterpiece"
)
SD_NEGATIVE_PROMPT = "text, watermark, people, faces, bright colors, cartoon, frame, border"


async def _generate_backdrop_local(title: str, concept: str) -> str | None:
    """txt2img against a locally running SD-WebUI. Returns a data: URI, or
    None on any failure (server down, bad payload) — caller falls back."""
    async with httpx.AsyncClient(timeout=SD_TIMEOUT_SECONDS) as http:
        response = await http.post(
            f"{SD_WEBUI_URL}/sdapi/v1/txt2img",
            json={
                "prompt": f"{title}: {concept}{SD_PROMPT_SUFFIX}",
                "negative_prompt": SD_NEGATIVE_PROMPT,
                "width": 1024,
                "height": 576,
                "steps": 25,
            },
        )
        response.raise_for_status()
        images = response.json().get("images") or []
    if not images:
        logger.warning("local backdrop for %r: SD returned no images", title)
        return None
    raw = base64.b64decode(images[0])
    # Magic + size cap — don't store whatever a misconfigured server sent.
    uri = _raster_data_uri(raw)
    if uri is None:
        logger.warning("local backdrop for %r: rejected payload (%d bytes)", title, len(raw))
    return uri


async def _generate_backdrop_grok(title: str, concept: str) -> str | None:
    """txt2img via the xAI image API. Returns a data: URI, or None on any
    failure (no key, API error, bad payload) — caller falls back."""
    key = os.environ.get("GROK_KEY")
    if not key:
        logger.warning("grok backdrop for %r: GROK_KEY not set", title)
        return None
    async with httpx.AsyncClient(timeout=XAI_TIMEOUT_SECONDS) as http:
        response = await http.post(
            XAI_IMAGE_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": XAI_IMAGE_MODEL,
                "prompt": f"{title}: {concept}{SD_PROMPT_SUFFIX}",
                "n": 1,
                "aspect_ratio": "16:9",
                "resolution": "1k",
                "response_format": "b64_json",
            },
        )
        response.raise_for_status()
        data = response.json().get("data") or []
    if not data or not data[0].get("b64_json"):
        logger.warning("grok backdrop for %r: no image in response", title)
        return None
    raw = base64.b64decode(data[0]["b64_json"])
    uri = _raster_data_uri(raw)
    if uri is None:
        logger.warning("grok backdrop for %r: rejected payload (%d bytes)", title, len(raw))
    return uri


async def generate_backdrop(
    client: anthropic.AsyncAnthropic, title: str, concept: str
) -> str | None:
    """One scene from the world's own concept, in whichever mode the server
    setting selects. Failure-tolerant by contract: any error returns None
    and the world ships without art — a backdrop must never cost us a world.
    Local mode degrades to SVG rather than to nothing (user-chosen)."""
    try:
        mode = db.get_setting("backdrop_mode", "svg")
    except Exception:
        # Settings unreadable — honor the never-cost-a-world contract.
        mode = "svg"
    if mode in ("local", "grok"):
        raster_gen = _generate_backdrop_local if mode == "local" else _generate_backdrop_grok
        try:
            raster = await raster_gen(title, concept)
            if raster is not None:
                return raster
        except Exception as e:
            logger.warning("%s backdrop for %r failed (%s) — falling back to SVG", mode, title, e)
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=BACKDROP_SYSTEM,
            messages=[{"role": "user", "content": f"World: {title}\n\n{concept}"}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        match = _SVG_EXTRACT_RE.search(text)
        if match is None:
            logger.warning("backdrop for %r: no <svg> in response", title)
            return None
        svg = sanitize_svg(match.group(0))
        if svg is None:
            logger.warning("backdrop for %r rejected by sanitizer", title)
        return svg
    except Exception:
        logger.exception("backdrop generation failed for %r", title)
        return None


class WorldValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_world(world: dict) -> None:
    """Raises WorldValidationError listing every structural problem."""
    errors: list[str] = []
    locations = world.get("locations", [])
    npcs = world.get("npcs", [])

    lo, hi = HARD_LOCATION_BOUNDS
    if not (lo <= len(locations) <= hi):
        errors.append(f"{len(locations)} locations, need {lo}-{hi}")
    lo, hi = HARD_NPC_BOUNDS
    if not (lo <= len(npcs) <= hi):
        errors.append(f"{len(npcs)} npcs, need {lo}-{hi}")

    slugs: set[str] = set()
    for entity in [*locations, *npcs]:
        slug = entity.get("id", "")
        if not _SLUG_RE.match(slug):
            errors.append(f"bad slug {slug!r}")
        if slug in slugs:
            errors.append(f"duplicate slug {slug!r}")
        slugs.add(slug)
    if "world" in slugs:
        errors.append("'world' is a reserved entity id")

    location_ids = {loc["id"] for loc in locations}
    start = world.get("starting_location")
    if start not in location_ids:
        errors.append(f"starting_location {start!r} is not a location")

    forward: dict[str, set[str]] = {loc_id: set() for loc_id in location_ids}
    reverse: dict[str, set[str]] = {loc_id: set() for loc_id in location_ids}
    for loc in locations:
        seen_directions: set[str] = set()
        for ex in loc["exits"]:
            if ex["direction"] in seen_directions:
                errors.append(f"{loc['id']} has two '{ex['direction']}' exits")
            seen_directions.add(ex["direction"])
            if ex["to"] not in location_ids:
                errors.append(f"{loc['id']} exits to unknown location {ex['to']!r}")
            else:
                forward[loc["id"]].add(ex["to"])
                reverse[ex["to"]].add(loc["id"])

    # Soft-lock check: from the start you must be able to reach every room,
    # and from every room you must be able to get back.
    if start in location_ids and not errors:
        def bfs(edges: dict[str, set[str]]) -> set[str]:
            seen, frontier = {start}, [start]
            while frontier:
                seen_next = [n for node in frontier for n in edges[node] if n not in seen]
                seen.update(seen_next)
                frontier = seen_next
            return seen

        unreachable = location_ids - bfs(forward)
        if unreachable:
            errors.append(f"unreachable from start: {sorted(unreachable)}")
        stranded = location_ids - bfs(reverse)
        if stranded:
            errors.append(f"cannot return to start from: {sorted(stranded)}")

    for npc in npcs:
        if npc.get("location") not in location_ids:
            errors.append(f"npc {npc['id']} placed in unknown location {npc.get('location')!r}")

    valid_entities = slugs | {"world"}
    for fact in world.get("facts", []):
        if fact.get("entity") not in valid_entities:
            errors.append(f"fact against unknown entity {fact.get('entity')!r}")

    if errors:
        raise WorldValidationError(errors)


async def generate_world(
    client: anthropic.AsyncAnthropic,
    n_locations: tuple[int, int] = DEFAULT_LOCATIONS,
    n_npcs: tuple[int, int] = DEFAULT_NPCS,
) -> dict:
    """Generate and validate one world. One retry with the validator's
    errors fed back; a second failure raises WorldValidationError."""
    motif_a, motif_b = random.sample(_MOTIFS, 2)
    feedback = ""
    last_error: WorldValidationError | None = None

    for attempt in range(2):
        response = await client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=GEN_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": WORLD_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": GEN_USER_TEMPLATE.format(
                        n_locations=f"{n_locations[0]}-{n_locations[1]}",
                        n_npcs=f"{n_npcs[0]}-{n_npcs[1]}",
                        motif_a=motif_a,
                        motif_b=motif_b,
                        feedback=feedback,
                    ),
                }
            ],
        )
        world = json.loads(next(b.text for b in response.content if b.type == "text"))
        try:
            validate_world(world)
            # Attached here so both the pool loop and on-demand creates get
            # art for free; None (generation/sanitize failure) is fine.
            world["backdrop_svg"] = await generate_backdrop(
                client, world["title"], world["concept"]
            )
            return world
        except WorldValidationError as e:
            last_error = e
            logger.warning("world generation attempt %d invalid: %s", attempt + 1, e)
            feedback = (
                "\nYour previous attempt failed validation with these errors — "
                f"fix all of them: {'; '.join(e.errors)}"
            )
    raise last_error


# Hand-authored backdrop for the fallback world — the degrade path keeps its
# art, and the test fixture world exercises the backdrop column end to end.
FALLBACK_BACKDROP = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">
  <defs>
    <radialGradient id="fb_sky" cx="50%" cy="35%" r="85%">
      <stop offset="0%" stop-color="#16131c"/>
      <stop offset="100%" stop-color="#0b0b0f"/>
    </radialGradient>
    <radialGradient id="fb_glow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#3d6b5c" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="#3d6b5c" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1920" height="1080" fill="url(#fb_sky)"/>
  <path d="M0 620 L340 560 L620 610 L980 540 L1320 600 L1660 550 L1920 600 L1920 1080 L0 1080 Z" fill="#100f15"/>
  <path d="M760 1080 L760 520 Q960 380 1160 520 L1160 1080 Z" fill="#0d0c11"/>
  <ellipse cx="960" cy="660" rx="260" ry="220" fill="url(#fb_glow)"/>
  <path d="M820 1080 L820 560 Q960 450 1100 560 L1100 1080 Z" fill="#08080b"/>
  <rect x="700" y="440" width="60" height="640" fill="#0d0c11"/>
  <rect x="1160" y="440" width="60" height="640" fill="#0d0c11"/>
  <path d="M0 1080 L0 980 L480 1010 L960 985 L1440 1010 L1920 980 L1920 1080 Z" fill="#060608"/>
</svg>"""

# The Phase 1 hand-authored world, kept as the degrade path when generation
# fails during an on-demand create, and as the test-suite fixture world.
FALLBACK_WORLD = {
    "title": "The Ruined Gate",
    "backdrop_svg": FALLBACK_BACKDROP,
    "concept": (
        "A broken dungeon mouth beneath a dead keep, where something in the "
        "ossuary has been arranging the bones of the interred into patterns "
        "that should not hum. The deeper halls remember being a place of "
        "burial; lately they have begun to behave like a place of worship."
    ),
    "starting_location": "dungeon_entrance",
    "locations": [
        {
            "id": "dungeon_entrance",
            "name": "The Ruined Gate",
            "description": (
                "A broken portcullis hangs from rusted chains. Cold air "
                "breathes up from the dark beyond, carrying the smell of "
                "wet stone and something long dead."
            ),
            "exits": [{"direction": "north", "to": "crypt_hall"}],
        },
        {
            "id": "crypt_hall",
            "name": "Crypt Hall",
            "description": (
                "Rows of shattered sarcophagi line a hall lit by a single "
                "guttering torch. Something has been dragging itself "
                "across the dust here, recently."
            ),
            "exits": [
                {"direction": "south", "to": "dungeon_entrance"},
                {"direction": "east", "to": "ossuary"},
            ],
        },
        {
            "id": "ossuary",
            "name": "The Ossuary",
            "description": (
                "Bones are stacked floor to ceiling in deliberate, "
                "unsettling patterns. A low hum, felt more than heard, "
                "comes from somewhere beneath the floor."
            ),
            "exits": [
                {"direction": "west", "to": "crypt_hall"},
                {"direction": "down", "to": "sunken_chapel"},
            ],
        },
        {
            "id": "sunken_chapel",
            "name": "The Sunken Chapel",
            "description": (
                "Stairs descend into black water that laps at a drowned "
                "altar. Candle stubs float upright, burning, though no one "
                "has lit a candle here in a hundred years."
            ),
            "exits": [{"direction": "up", "to": "ossuary"}],
        },
    ],
    "npcs": [
        {
            "id": "aldric",
            "location": "crypt_hall",
            "name": "Brother Aldric",
            "description": (
                "A monk driven mad by what he found down here. He mutters "
                "scripture that isn't quite scripture anymore."
            ),
        },
        {
            "id": "collector",
            "location": "ossuary",
            "name": "The Collector",
            "description": (
                "A hooded figure arranging bones with obsessive care. "
                "It does not look up when you enter."
            ),
        },
    ],
    "facts": [
        {
            "entity": "collector",
            "key": "weakness",
            "value": (
                "The Collector cannot abide a disordered pattern — scattering "
                "its arranged bones forces it to stop and rebuild, leaving it "
                "defenseless for the duration."
            ),
        },
        {
            "entity": "ossuary",
            "key": "hidden_door",
            "value": (
                "Behind the northern bone stack is a sealed descent; it opens "
                "only when the humming beneath the floor is answered by "
                "striking the same three-note rhythm on the femur chimes."
            ),
        },
        {
            "entity": "aldric",
            "key": "secret",
            "value": (
                "Aldric's mangled scripture is a real warding litany read "
                "backwards — recited correctly, it quiets the hum for a short "
                "while. He remembers the true order only when calmed."
            ),
        },
    ],
}
