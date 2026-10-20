"""Game form indices -> PokeAPI sprite filenames; unmapped forms have no image.
PKHeX.Core/PKM/Util/Conversion/FormConverter.cs defines the indices; docs/gui.md, Pokemon sprites.
"""

# PokeAPI's ids for the Gigantamax shapes, by (species, form).
GIGANTAMAX_SPRITES = {
    (3, 0): 10195,       # Venusaur
    (6, 0): 10196,       # Charizard
    (9, 0): 10197,       # Blastoise
    (12, 0): 10198,      # Butterfree
    (25, 0): 10199,      # Pikachu
    (52, 0): 10200,      # Meowth
    (68, 0): 10201,      # Machamp
    (94, 0): 10202,      # Gengar
    (99, 0): 10203,      # Kingler
    (131, 0): 10204,     # Lapras
    (133, 0): 10205,     # Eevee
    (143, 0): 10206,     # Snorlax
    (569, 0): 10207,     # Garbodor
    (809, 0): 10208,     # Melmetal
    (812, 0): 10209,     # Rillaboom
    (815, 0): 10210,     # Cinderace
    (818, 0): 10211,     # Inteleon
    (823, 0): 10212,     # Corviknight
    (826, 0): 10213,     # Orbeetle
    (834, 0): 10214,     # Drednaw
    (839, 0): 10215,     # Coalossal
    (841, 0): 10216,     # Flapple
    (842, 0): 10217,     # Appletun
    (844, 0): 10218,     # Sandaconda
    (849, 0): 10219,     # Toxtricity Amped
    (851, 0): 10220,     # Centiskorch
    (858, 0): 10221,     # Hatterene
    (861, 0): 10222,     # Grimmsnarl
    (869, 0): 10223,     # Alcremie
    (879, 0): 10224,     # Copperajah
    (884, 0): 10225,     # Duraludon
    (892, 0): 10226,     # Urshifu Single Strike
    (892, 1): 10227,     # Urshifu Rapid Strike
    (849, 1): 10228,     # Toxtricity Low Key
}


FORM_SPRITES = {
    # Cosmetic forms use filenames, battle forms use pokemon.csv's alternate IDs.
    **{(201, n): f"201-{name}" for n, name in enumerate(
        (*"bcdefghijklmnopqrstuvwxyz", "exclamation", "question"), start=1)},
    (351, 1): 10013, (351, 2): 10014, (351, 3): 10015,
    (386, 1): 10001, (386, 2): 10002, (386, 3): 10003,
    (412, 1): "412-sandy", (412, 2): "412-trash", (413, 1): 10004, (413, 2): 10005,
    (483, 1): 10245, (484, 1): 10246, (492, 1): 10006,
    # Pikachu's game index 8 is the Let's Go partner, not the World Cap (9).
    (25, 1): 10094, (25, 2): 10095, (25, 3): 10096, (25, 4): 10097,
    (25, 5): 10098, (25, 6): 10099, (25, 7): 10148, (25, 9): 10160,
    # Alolan forms.
    (19, 1): 10091, (20, 1): 10092, (26, 1): 10100, (27, 1): 10101,
    (28, 1): 10102, (37, 1): 10103, (38, 1): 10104, (50, 1): 10105,
    (51, 1): 10106, (52, 1): 10107, (53, 1): 10108, (74, 1): 10109,
    (75, 1): 10110, (76, 1): 10111, (88, 1): 10112, (89, 1): 10113,
    (103, 1): 10114, (105, 1): 10115,
    # Galarian forms; Meowth and Slowbro already have another form at index 1.
    (52, 2): 10161, (77, 1): 10162, (78, 1): 10163, (79, 1): 10164,
    (80, 2): 10165, (83, 1): 10166, (110, 1): 10167, (122, 1): 10168,
    (144, 1): 10169, (145, 1): 10170, (146, 1): 10171, (199, 1): 10172,
    (222, 1): 10173, (263, 1): 10174, (264, 1): 10175, (554, 1): 10176,
    (555, 2): 10177, (555, 3): 10178, (562, 1): 10179, (618, 1): 10180,
    # Hisuian and Paldean forms shared by the native-title trade pickers.
    (58, 1): 10229, (59, 1): 10230, (100, 1): 10231, (101, 1): 10232,
    (157, 1): 10233, (211, 1): 10234, (215, 1): 10235, (503, 1): 10236,
    (549, 1): 10237, (550, 2): 10247, (570, 1): 10238, (571, 1): 10239,
    (628, 1): 10240, (705, 1): 10241, (706, 1): 10242, (713, 1): 10243,
    (724, 1): 10244, (902, 1): 10248, (905, 1): 10249,
    (128, 1): 10250, (128, 2): 10251, (128, 3): 10252, (194, 1): 10253,
    # Other alternate forms in the bundled Sword/Shield event cards.
    (423, 1): "423-east", (801, 1): 10147, (854, 1): "854-antique", (893, 1): 10192,
    # Remaining Sword/Shield form choices from the app's PKHeX Options response.
    (421, 1): "421-sunshine", (422, 1): "422-east", (487, 1): 10007,
    (479, 1): 10008, (479, 2): 10009, (479, 3): 10010, (479, 4): 10011, (479, 5): 10012,
    (550, 1): 10016, (555, 1): 10017, (641, 1): 10019, (642, 1): 10020, (645, 1): 10021,
    (646, 1): 10023, (646, 2): 10022, (647, 1): 10024,
    (649, 1): "649-douse", (649, 2): "649-shock", (649, 3): "649-burn", (649, 4): "649-chill",
    (678, 1): 10025, (681, 1): 10026,
    (710, 1): 10027, (710, 2): 10028, (710, 3): 10029,
    (711, 1): 10030, (711, 2): 10031, (711, 3): 10032,
    (716, 0): "716-neutral", (716, 1): "716-active",
    (718, 1): 10181, (718, 2): 10118, (718, 3): 10119, (718, 4): 10120,
    (744, 1): 10151, (745, 1): 10126, (745, 2): 10152, (746, 1): 10127,
    (778, 1): 10143, (800, 1): 10155, (800, 2): 10156,
    (845, 1): 10182, (845, 2): 10183, (849, 1): 10184, (855, 1): "855-antique",
    (875, 1): 10185, (876, 1): 10186, (877, 1): 10187,
    (888, 1): 10188, (889, 1): 10189, (890, 1): 10190, (892, 1): 10191,
    (898, 1): 10193, (898, 2): 10194,
    **{(s, n): f"{s}-{name}" for s in (493, 773) for n, name in enumerate((
        "fighting", "flying", "poison", "ground", "rock", "bug", "ghost", "steel", "fire",
        "water", "grass", "electric", "psychic", "ice", "dragon", "dark", "fairy"), start=1)},
    **{(s, n): f"{s}-{name}" for s in (585, 586)
       for n, name in enumerate(("summer", "autumn", "winter"), start=1)},
    # The gift builder leaves Alcremie's decoration at its default Strawberry Sweet.
    **{(869, n): f"869-{name}-strawberry-sweet" for n, name in enumerate((
        "ruby-cream", "matcha-cream", "mint-cream", "lemon-cream", "salted-cream",
        "ruby-swirl", "caramel-swirl", "rainbow-swirl"), start=1)},
}


def sprite_key(species: int, form: int = 0, gigantamax: bool = False) -> int | str | None:
    # Every cream of Alcremie Gigantamaxes into the one shape.
    if gigantamax and (key := GIGANTAMAX_SPRITES.get((species, 0 if species == 869 else form))):
        return key
    return FORM_SPRITES.get((species, form), None if form else species)
