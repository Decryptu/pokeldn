using System.Diagnostics.CodeAnalysis;
using System.Reflection;
using System.Text.Json.Nodes;
using PKHeX.Core;

// Scarlet and Violet's wild encounters as PKHeX knows them, for the Union Circle's crafted spawns
// (docs/sv_union_circle.md, Crafted encounters): every wild slot by the location a catch there names,
// and PKHeX's verdict on a crafted spawn caught at one of them.
static class Wild
{
    const int AnyForm = -1;                 // a slot that draws its form, as Scatterbug's pattern

    // PKHeX's Scarlet / Violet wild areas (internal, read by name: pin the package before renaming it; the
    // attribute keeps it through trimming).
    [DynamicDependency(DynamicallyAccessedMemberTypes.PublicFields | DynamicallyAccessedMemberTypes.NonPublicFields,
        "PKHeX.Core.Encounters9", "PKHeX.Core")]
    static EncounterArea9[] Areas() =>
        (EncounterArea9[])typeof(PK9).Assembly.GetType("PKHeX.Core.Encounters9")!
            .GetField("Slots", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)!.GetValue(null)!;

    static string LocationName(GameStrings strings, ushort location) =>
        strings.GetLocationName(false, location, 9, 9, GameVersion.SL);

    // -> {"areas": [{"location", "name", "slots": [[species, form or -1, lowest level, highest]]}], "types": the Tera
    // Types' names}, each location once, its slots merged; names in `strings`' language.
    public static JsonObject AreasReply(GameStrings strings)
    {
        var byLocation = new SortedDictionary<ushort, HashSet<(int, int, int, int)>>();
        foreach (var area in Areas())
        {
            if (!byLocation.TryGetValue(area.Location, out var slots))
                byLocation[area.Location] = slots = [];
            foreach (var slot in area.Slots)
            {
                var forms = PersonalTable.SV[slot.Species].FormCount;
                slots.Add((slot.Species, slot.Form < forms ? slot.Form : AnyForm, slot.LevelMin, slot.LevelMax));
            }
        }
        var areas = new JsonArray();
        foreach (var (location, slots) in byLocation)
        {
            var list = new JsonArray();
            foreach (var (s, f, lo, hi) in slots.OrderBy(x => x))
                list.Add(new JsonArray(s, f, lo, hi));
            areas.Add(new JsonObject { ["location"] = location, ["name"] = LocationName(strings, location), ["slots"] = list });
        }
        var types = new JsonArray();
        for (var t = 0; t < TeraTypes; t++)
            types.Add(strings.types[t]);
        return new JsonObject { ["areas"] = areas, ["types"] = types };
    }

    // -> what a crafted spawn of "species" (National) in "form" can hold: {"forms": [{"id", "name"}], "types",
    // "abilities": [{"slot", "name"}] (slot 2 the hidden one), "gender" ratio (0 male only, 254 female only,
    // 255 genderless), "natures": [{"id", "name"}]}, names in `strings`' language.
    public static JsonObject SpeciesReply(JsonObject request, GameStrings strings)
    {
        var species = checked((ushort)(int)request["species"]!);
        var form = checked((byte)((int?)request["form"] ?? 0));
        var table = PersonalTable.SV;
        if (!table.IsPresentInGame(species, form))
            form = 0;
        var info = table.GetFormEntry(species, form);
        var forms = new JsonArray();
        var formNames = FormConverter.GetFormList(species, strings.types, strings.forms, EntityContext.Gen9);
        for (byte f = 0; f < table[species].FormCount; f++)
            if (table.IsPresentInGame(species, f))
                forms.Add(new JsonObject { ["id"] = f, ["name"] = f < formNames.Length && formNames[f].Length > 0 ? formNames[f] : $"Form {f}" });
        var abilities = new JsonArray();
        for (var slot = 0; slot < 3; slot++)
            abilities.Add(new JsonObject { ["slot"] = slot, ["name"] = strings.abilitylist[info.GetAbilityAtIndex(slot)] });
        var natures = new JsonArray();
        for (var n = 0; n < 25; n++)
            natures.Add(new JsonObject { ["id"] = n, ["name"] = strings.natures[n] });
        return new JsonObject
        {
            ["forms"] = forms,
            ["types"] = new JsonArray((int)info.Type1, (int)info.Type2),
            ["abilities"] = abilities,
            ["gender"] = (int)info.Gender,
            ["natures"] = natures,
        };
    }

    const int TeraTypes = 18;               // Normal to Fairy; a wild spawn is never Stellar

    // -> {"locations": [{"location", "name", "teras", "problems"}]}: each location with a wild slot for the spawn
    // `request` describes ("species" National, "form", "level", "tera", "shiny", "nature", "gender", "scale", "ivs"
    // HP Atk Def Spe SpA SpD, "ability" slot 0 1 or 2 hidden, "item"), the Tera Types PKHeX accepts it caught there
    // with, and PKHeX's problems with its own "tera" there as `plain` words them, none when it is legal.
    public static JsonObject LegalReply(JsonObject request, GameStrings strings, Func<LegalityAnalysis, string> plain)
    {
        var species = checked((ushort)(int)request["species"]!);
        var form = checked((byte)((int?)request["form"] ?? 0));
        var level = checked((byte)(int)request["level"]!);
        var tera = (int?)request["tera"] ?? 0;
        var forms = PersonalTable.SV[species].FormCount;
        var locations = new JsonArray();
        foreach (var area in Areas().GroupBy(a => a.Location).OrderBy(g => g.Key))
        {
            var slot = area.SelectMany(a => a.Slots).FirstOrDefault(s => s.Species == species
                && (s.Form == form || s.Form >= forms) && s.LevelMin <= level && level <= s.LevelMax);
            if (slot is null)
                continue;
            var teras = new JsonArray();
            var problems = new JsonArray();
            for (var t = 0; t < TeraTypes; t++)
            {
                var la = new LegalityAnalysis(Caught(slot, request, form, level, t));
                if (la.Valid)
                    teras.Add(t);
                else if (t == tera)
                    foreach (var line in plain(la).Split('\n', StringSplitOptions.RemoveEmptyEntries))
                        problems.Add(line);
            }
            locations.Add(new JsonObject
            {
                ["location"] = area.Key, ["name"] = LocationName(strings, area.Key), ["teras"] = teras, ["problems"] = problems,
            });
        }
        return new JsonObject { ["locations"] = locations };
    }

    // -> the spawn `request` describes as caught from `slot`, with Tera Type `tera`.
    static PK9 Caught(EncounterSlot9 slot, JsonObject request, byte form, byte level, int tera)
    {
        var trainer = new SimpleTrainerInfo(GameVersion.SL) { OT = "POKELDN", TID16 = 12345, SID16 = 54321, Language = 2 };
        var pk = (PK9)slot.ConvertToPKM(trainer, EncounterCriteria.Unrestricted);
        pk.Form = form;
        pk.MetLevel = pk.CurrentLevel = pk.ObedienceLevel = level;
        pk.TeraTypeOriginal = (MoveType)tera;
        if ((int?)request["nature"] is { } nature)
            pk.Nature = (Nature)nature;
        if ((int?)request["gender"] is { } gender && pk.PersonalInfo.IsDualGender)   // the record's sex bit
            pk.Gender = checked((byte)gender);
        if ((int?)request["scale"] is { } scale)
            pk.Scale = checked((byte)scale);
        if (request["ivs"] is JsonArray ivs)
            pk.IVs = ivs.Select(v => (int)v!).ToArray();
        if ((int?)request["ability"] is { } ability)
            pk.RefreshAbility(ability);
        pk.HeldItem = (int?)request["item"] ?? 0;
        pk.SetIsShiny((bool?)request["shiny"] ?? false);
        pk.ResetPartyStats();
        pk.RefreshChecksum();
        return pk;
    }
}
