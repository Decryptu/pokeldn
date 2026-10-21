"""The 444-byte struct WonderNews [decomp:include/global.h:646] and the news the host can serve.
ValidateWonderNews checks only id != 0; any changed byte makes old news new [docs/frlg_gift.md].
"""
from pokeldn.app.i18n import message_ref as _message

from dataclasses import dataclass

from pokeldn.frlg.text import charmap
from pokeldn.frlg.gift.mystery_gift import (
    NUM_WONDER_BGS, SEND_TYPE_ALLOWED, SEND_TYPE_ALLOWED_ALWAYS, SEND_TYPE_DISALLOWED,
)

# [decomp:include/constants/global.h:70]
WONDER_NEWS_TEXT_LENGTH = 40
WONDER_NEWS_BODY_TEXT_LINES = 10
WONDER_NEWS_SIZE = 444              # u16 id + u8 sendType + u8 bgType + 40 + 10*40

# A non-empty line past index 7 arms the scroll indicator [decomp:src/mystery_gift_show_news.c:346].
WONDER_NEWS_VISIBLE_LINES = 8

# newsType [decomp:src/wonder_news.c]
WONDER_NEWS_NONE = 0
WONDER_NEWS_RECV_FRIEND = 1
WONDER_NEWS_RECV_WIRELESS = 2
WONDER_NEWS_SENT = 3


def _news_text(text):
    return charmap.encode(text or "", width=WONDER_NEWS_TEXT_LENGTH, pad=0xFF)


def build_wonder_news(*, news_id, title="", body=(), send_type=SEND_TYPE_ALLOWED_ALWAYS,
                      bg_type=0):
    """id must be non-zero or ValidateWonderNews rejects the news and the console keeps nothing."""
    if not 0 < news_id <= 0xFFFF:
        raise ValueError(_message('core.pokeldn.frlg.gift.wonder_news.news_id_must_be_1_65535_0_fails_validatewonderne_1198ee11'))
    if send_type not in (SEND_TYPE_DISALLOWED, SEND_TYPE_ALLOWED, SEND_TYPE_ALLOWED_ALWAYS):
        raise ValueError(_message('core.pokeldn.frlg.gift.wonder_news.sendtype_must_be_0_1_or_2_2af371a7'))
    if not 0 <= bg_type < NUM_WONDER_BGS:
        raise ValueError(_message('core.pokeldn.frlg.gift.wonder_news.bgtype_must_be_0_value0_969ebb6d', value0=NUM_WONDER_BGS - 1))
    body = list(body)
    if len(body) > WONDER_NEWS_BODY_TEXT_LINES:
        raise ValueError(
            _message('core.pokeldn.frlg.gift.wonder_news.wonder_news_carries_value0_body_lines_got_value1_5c4e818a', value0=WONDER_NEWS_BODY_TEXT_LINES, value1=len(body)))
    out = bytearray()
    out += (news_id & 0xFFFF).to_bytes(2, "little")     # +0
    out += bytes([send_type & 0xFF, bg_type & 0xFF])    # +2, +3
    out += _news_text(title)                            # +4
    for index in range(WONDER_NEWS_BODY_TEXT_LINES):    # +44 .. +444
        out += _news_text(body[index] if index < len(body) else "")
    assert len(out) == WONDER_NEWS_SIZE, len(out)
    return bytes(out)


JAPANESE_WONDER_NEWS_SIZE = 224


def for_build(news, build=None):
    """Roman news text in the Japanese twenty-byte fields [BPRJ Server_Run, 0x081494EE]."""
    from pokeldn.frlg.rom import builds
    if builds.resolve(build).language != "japanese" or len(news) == JAPANESE_WONDER_NEWS_SIZE:
        return news
    out = bytearray(news[:4])
    for offset in range(4, WONDER_NEWS_SIZE, WONDER_NEWS_TEXT_LENGTH):
        text = charmap.latin_text_for_japanese(charmap.decode(news[offset:offset + WONDER_NEWS_TEXT_LENGTH]))
        out += charmap.encode(text, width=20, pad=0xFF)
    return bytes(out)


def validate(news):
    """Port of ValidateWonderNews [decomp:src/mystery_gift.c:113]."""
    news = bytes(news)
    return len(news) in (WONDER_NEWS_SIZE, JAPANESE_WONDER_NEWS_SIZE) and int.from_bytes(news[0:2], "little") != 0


def parse(news):
    news = bytes(news)
    width = 20 if len(news) == JAPANESE_WONDER_NEWS_SIZE else WONDER_NEWS_TEXT_LENGTH
    if len(news) not in (WONDER_NEWS_SIZE, JAPANESE_WONDER_NEWS_SIZE):
        raise ValueError(_message('core.pokeldn.frlg.gift.wonder_news.wonder_news_is_value0_bytes_expected_444_or_224_e14979d7', value0=len(news)))
    language = 1 if width == 20 else None
    return {"id": int.from_bytes(news[:2], "little"), "send_type": news[2], "bg_type": news[3],
            "title": charmap.decode(news[4:4 + width], language=language),
            "body": tuple(charmap.decode(news[4 + (i + 1) * width:4 + (i + 2) * width],
                                         language=language) for i in range(10))}


def describe(news):
    parsed = parse(news)
    lines = tuple(line for line in parsed["body"] if line)
    return (_message('core.pokeldn.frlg.gift.wonder_news.news_id_value0_sendtype_value1_bg_value2_title_v_3815d5ea', value0=parsed['id'], value1=parsed['send_type'], value2=parsed['bg_type'], value3=parsed['title'], value4=len(lines)))


@dataclass(frozen=True)
class WonderNewsSpec:
    slug: str
    news_id: int
    title: str
    body: tuple = ()
    send_type: int = SEND_TYPE_ALLOWED_ALWAYS
    bg_type: int = 0
    description: str = ""

    def build(self, *, news_id=None):
        return build_wonder_news(
            news_id=self.news_id if news_id is None else news_id,
            title=self.title, body=self.body,
            send_type=self.send_type, bg_type=self.bg_type)


POKELDN_NEWS = WonderNewsSpec(
    slug="pokeldn",
    news_id=1,
    title="POKELDN NEWS",
    body=(
        "This news travelled to your",
        "GAME BOY ADVANCE over a",
        "SWITCH local wireless link.",
        "",
        "Ask the man in CERULEAN CITY",
        "about the news: he keeps a",
        "BERRY for every trainer who",
        "brings him something to read.",
    ),
    bg_type=1,
    description="the plain proof-of-link news, one berry from the man in CERULEAN CITY",
)

BERRY_NEWS = WonderNewsSpec(
    slug="berry",
    news_id=2,
    title="BERRY BULLETIN",
    body=(
        "BERRIES grow on soft soil all",
        "over KANTO and the SEVII",
        "ISLANDS.",
        "",
        "Plant one, water it, and come",
        "back in a day or two.",
        "",
        "Show this to the man in",
        "CERULEAN CITY for a BERRY of",
        "your own to start with.",
    ),
    bg_type=6,
    description="a ten-line news that exercises the console's scroll indicator",
)

NEWS_REGISTRY = {spec.slug: spec for spec in (POKELDN_NEWS, BERRY_NEWS)}
DEFAULT_NEWS = POKELDN_NEWS.slug


def news_choices():
    return tuple(NEWS_REGISTRY)


def build_news(slug, *, news_id=None):
    try:
        spec = NEWS_REGISTRY[slug]
    except KeyError as exc:
        choices = ", ".join(NEWS_REGISTRY)
        raise ValueError(_message('core.pokeldn.frlg.gift.wonder_news.unknown_wonder_news_value0_r_choose_from_value1_0c11373c', value0=slug, value1=choices)) from exc
    return spec.build(news_id=news_id)


def format_news_help():
    width = max(len(slug) for slug in NEWS_REGISTRY)
    lines = ["Wonder News payload to distribute (Mystery Gift -> Wonder News -> Friend).",
             "Available news:"]
    lines.extend(f"  {spec.slug:<{width}}  id {spec.news_id}: {spec.description}"
                 for spec in NEWS_REGISTRY.values())
    return "\n".join(lines)
