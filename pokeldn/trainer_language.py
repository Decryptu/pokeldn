"""The language a Switch title's trainer record should carry for a player name: the game draws a name
in its language's font, and a Japanese name under an English record comes out in narrow half-width
glyphs (docs/switch_re.md, Trainer names). Ids are the games' LanguageID, as PKHeX numbers them.
"""

JAPANESE, ENGLISH, FRENCH, ITALIAN, GERMAN, SPANISH, KOREAN, CHINESE_S, CHINESE_T = 1, 2, 3, 4, 5, 7, 8, 9, 10
_CJK = (JAPANESE, CHINESE_S, CHINESE_T)


def _script(name):
    kana = hangul = han = False
    for c in name:
        o = ord(c)
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F:
            kana = True
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            hangul = True
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            han = True
    return kana, hangul, han


def for_name(name, language):
    """-> `language` unless `name` needs another font: kana Japanese, hangul Korean, Chinese characters
    Japanese unless `language` is already Japanese or Chinese. A Latin name keeps `language`."""
    kana, hangul, han = _script(name or "")
    if kana:
        return JAPANESE
    if hangul:
        return KOREAN
    if han and language not in _CJK:
        return JAPANESE
    return language
