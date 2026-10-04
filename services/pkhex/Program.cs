using System.Reflection;
using System.Text.Json.Nodes;
using PKHeX.Core;
using static PKHeX.Core.GameVersion;

var strings = GameInfo.GetStrings("en");
var games = new Dictionary<string, Game>
{
    ["frlg"] = new([FR, LG, E, R, S], PersonalTable.FR, EntityContext.Gen3, () => new PK3(), DecryptedParty),
    ["lgpe"] = new([GP, GE], PersonalTable.GG, EntityContext.Gen7b, () => new PB7(), EncryptedParty),
    ["bdsp"] = new([BD, SP], PersonalTable.BDSP, EntityContext.Gen8b, () => new PB8(), EncryptedStored),
    ["swsh"] = new([SW, SH], PersonalTable.SWSH, EntityContext.Gen8, () => new PK8(), EncryptedParty),
    ["pla"] = new([PLA], PersonalTable.LA, EntityContext.Gen8a, () => new PA8(), EncryptedParty),
    ["sv"] = new([SL, VL], PersonalTable.SV, EntityContext.Gen9, () => new PK9(), EncryptedParty),
    // The app frames the decrypted record into Z-A's offer message (pokeldn.za.pokemon.build_offer).
    ["za"] = new([ZA], PersonalTable.ZA, EntityContext.Gen9a, () => new PA9(), DecryptedParty),
};

while (Console.ReadLine() is { } line)
{
    JsonObject reply;
    try
    {
        var request = JsonNode.Parse(line)!.AsObject();
        var game = games[(string)request["game"]!];
        reply = (string)request["cmd"]! switch
        {
            "species" => Species(game),
            "names" => Names(game, (string)request["list"]!),
            "options" => Options(game, request),
            "gender_ratio" => GenderRatio(game, request),
            "make" => Make(game, request),
            "paste" => Paste(game, request),
            "check" => Check(game, Convert.FromBase64String((string)request["data"]!), request),
            "gift" => Gift(Convert.FromBase64String((string)request["data"]!)),
            "events" => Events(),
            "event" => Event(game, request),
            var other => throw new ArgumentException($"unknown command {other}"),
        };
        reply["ok"] = true;
    }
    catch (Exception e)
    {
        reply = new JsonObject { ["ok"] = false, ["error"] = e.Message };
    }
    Console.WriteLine(reply.ToJsonString());
}

JsonObject Species(Game game)
{
    var list = new JsonArray();
    for (ushort s = 1; s <= game.Table.MaxSpeciesID; s++)
        if (game.Table.IsPresentInGame(s, 0))
            list.Add(new JsonObject { ["id"] = s, ["name"] = strings.specieslist[s] });
    return new JsonObject { ["species"] = list };
}

JsonObject GenderRatio(Game game, JsonObject request)
{
    var species = checked((ushort)(int)request["species"]!);
    var form = checked((byte)((int?)request["form"] ?? 0));
    if (!game.Table.IsPresentInGame(species, form))
        form = 0;
    return new JsonObject { ["ratio"] = (int)game.Table.GetFormEntry(species, form).Gender };
}

JsonObject Names(Game game, string list)
{
    if (list == "species")
        return new JsonObject { ["names"] = Species(game)["species"]!.DeepClone() };
    var blank = game.Blank();
    var names = new JsonArray();
    void Add(int id, string name)
    {
        if (!string.IsNullOrWhiteSpace(name))
            names.Add(new JsonObject { ["id"] = id, ["name"] = name });
    }
    switch (list)
    {
        case "moves":
            var dummied = MoveInfo.GetDummiedMovesHashSet(game.Context);
            for (ushort m = 1; m <= blank.MaxMoveID; m++)
                if (!MoveInfo.IsDummiedMove(dummied, m))
                    Add(m, strings.movelist[m]);
            break;
        case "items":
            for (var i = 1; i <= blank.MaxItemID; i++)
                Add(i, strings.itemlist[i]);
            break;
        case "held":
            var items = strings.GetItemStrings(game.Context, game.Versions[0]);
            for (var i = 1; i < items.Length; i++)
                if (ItemRestrictions.IsHeldItemAllowed(i, game.Context))
                    Add(i, items[i]);
            break;
        case "balls":
            for (var b = 1; b <= blank.MaxBallID; b++)
                Add(b, strings.balllist[b]);
            break;
        default:
            throw new ArgumentException($"unknown list {list}");
    }
    return new JsonObject { ["names"] = names };
}

// What the offer options can ask of this species in this game; the GUI shows only what is listed.
JsonObject Options(Game game, JsonObject request)
{
    var species = checked((ushort)(int)request["species"]!);
    if (!game.Table.IsPresentInGame(species, 0))
        throw new ArgumentException("This species is absent from the selected game.");
    var form = checked((byte)((int?)request["form"] ?? 0));
    if (!game.Table.IsPresentInGame(species, form))
        form = 0;
    var detail = game.Table.GetFormEntry(species, form);
    var (versions, trainer) = Trainer(game, request);
    // A ball is listed when PKHeX permits it for at least one encounter of the species.
    var blank = game.Blank();
    blank.Species = species;
    blank.Form = form;
    var permitted = new HashSet<Ball>();
    Span<Ball> found = stackalloc Ball[BallApplicator.MaxBallSpanAlloc];
    foreach (var encounter in EncounterMovesetGenerator.GenerateEncounters(blank, trainer, ReadOnlyMemory<ushort>.Empty, versions).Take(80))
    {
        if (encounter is not IEncounterConvertible convertible)
            continue;
        var pk = convertible.ConvertToPKM(trainer);
        foreach (var ball in found[..BallApplicator.GetLegalBalls(found, pk, encounter)])
            permitted.Add(ball);
    }
    var balls = new JsonArray();
    foreach (var ball in permitted.Order())
        balls.Add(new JsonObject { ["id"] = (int)ball, ["name"] = strings.balllist[(int)ball] });
    // An ability is listed when a legal Pokemon of the species can carry it (Let's Go has no hidden ability to give).
    var abilities = new JsonArray();
    // Legends Z-A has no abilities in battle.
    if (game.Context != EntityContext.Gen9a)
        foreach (var id in Enumerable.Range(0, detail.AbilityCount).Select(detail.GetAbilityAtIndex).Distinct())
        {
            var probe = request.DeepClone().AsObject();
            probe["options"] = new JsonObject { ["ability"] = id, ["form"] = (int)form };
            try
            {
                Make(game, probe);
            }
            catch (InvalidOperationException)
            {
                continue;
            }
            abilities.Add(new JsonObject { ["id"] = id, ["name"] = strings.abilitylist[id] });
        }
    var natures = new JsonArray();
    for (var n = 0; n < 25; n++)
        natures.Add(new JsonObject { ["id"] = n, ["name"] = strings.natures[n] });
    var effort = game.Blank() switch
    {
        IAwakened => new JsonObject { ["kind"] = "avs", ["max"] = AwakeningUtil.AwakeningMax },
        IGanbaru => new JsonObject { ["kind"] = "gvs", ["max"] = GanbaruExtensions.TrueMax },
        _ => new JsonObject { ["kind"] = "evs", ["max"] = EffortValues.Max252, ["total"] = EffortValues.Max510 },
    };
    var forms = new JsonArray();
    var formNames = FormConverter.GetFormList(species, strings.types, strings.forms, game.Context);
    for (byte f = 0; f < game.Table[species].FormCount; f++)
        if (game.Table.IsPresentInGame(species, f))
            forms.Add(new JsonObject { ["id"] = f, ["name"] = f < formNames.Length && formNames[f].Length > 0 ? formNames[f] : $"Form {f}" });
    return new JsonObject
    {
        ["forms"] = forms,
        ["natures"] = natures,
        ["abilities"] = abilities,
        ["gendered"] = !detail.Genderless && !detail.OnlyFemale && !detail.OnlyMale,
        ["effort"] = effort,
        ["held"] = Names(game, "held")["names"]!.DeepClone(),
        ["balls"] = balls,
    };
}

(GameVersion[], SimpleTrainerInfo) Trainer(Game game, JsonObject request)
{
    var t = request["trainer"]!.AsObject();
    var versions = game.Versions;
    if ((string?)request["version"] is { Length: > 0 } v)
    {
        if (!Enum.TryParse<GameVersion>(v, out var chosen) || !versions.Contains(chosen))
            throw new ArgumentException("This version is incompatible with the selected game.");
        versions = [chosen, .. versions.Where(x => x != chosen)];
    }
    return (versions, new SimpleTrainerInfo(versions[0])
    {
        OT = (string)t["ot"]!, TID16 = checked((ushort)(int)t["tid"]!), SID16 = checked((ushort)(int)t["sid"]!),
        Language = (int)t["language"]!, Gender = (byte)(int)t["gender"]!,
    });
}

JsonObject Make(Game game, JsonObject request)
{
    var species = checked((ushort)(int)request["species"]!);
    if (!game.Table.IsPresentInGame(species, 0))
        throw new ArgumentException("This species is absent from the selected game.");
    var level = (int?)request["level"] ?? 0;
    if (level < 0 || level > 100)
        throw new ArgumentException("Level must be between 0 and 100.");
    var shiny = (bool?)request["shiny"] ?? false;
    var nickname = (string?)request["nickname"] ?? "";
    var wish = Wish.From(request["options"] as JsonObject);
    var form = wish.Form ?? 0;
    if (!game.Table.IsPresentInGame(species, form))
        throw new ArgumentException("This form is absent from the selected game.");
    // SetNickname cuts a longer name without saying so; the record would not carry what was asked.
    if (nickname.Length > game.Blank().MaxStringLengthNickname)
        throw new ArgumentException($"A nickname is at most {game.Blank().MaxStringLengthNickname} characters in this game.");
    var (versions, trainer) = Trainer(game, request);
    var blank = game.Blank();
    blank.Species = species;
    blank.Form = form;
    // Encounters are matched on the blank's gender: a female-only Vespiquen comes only from a female Combee.
    var detail = game.Table.GetFormEntry(species, form);
    var gender = detail.OnlyFemale ? Gender.Female : detail.OnlyMale ? Gender.Male
        : detail.Genderless ? Gender.Random : wish.Gender ?? Gender.Random;
    if (gender != Gender.Random)
        blank.Gender = (byte)gender;
    string? firstProblem = null, firstUnmet = null;
    var lowest = int.MaxValue;
    var shinyLocked = false;
    // The first encounter that stays legal with the requested level, shininess and nickname wins.
    // The first pass takes encounters as they come; the second lets an evolved Pokemon climb to its evolution level.
    // Mystery Gifts come last: an event's fixed PID makes the launchers' new-PID offer illegal.
    foreach (var climb in new[] { false, true })
    {
        foreach (var encounter in EncounterMovesetGenerator.GenerateEncounters(blank, trainer, wish.Moves, versions)
                     .Take(80).OrderBy(e => e is MysteryGift))
        {
            if (encounter is not IEncounterConvertible convertible)
                continue;
            if (level > 0 && encounter.LevelMin > level)
            {
                lowest = Math.Min(lowest, encounter.LevelMin);
                continue;
            }
            if (shiny && encounter.Shiny == Shiny.Never)
            {
                shinyLocked = true;
                continue;
            }
            // Shininess is chosen while the encounter builds its PID: a Gen 3 to 5 PID rewritten afterwards
            // no longer matches the RNG frame the legality check expects.
            var criteria = wish.Criteria(detail) with { Gender = gender };
            if (shiny)
                criteria = criteria with { Shiny = Shiny.Always };
            // The PID, IVs and, for a wild slot, the level are rolled at random; a roll can be refused or land
            // above the level asked for, so an encounter gets several.
            PKM? built = null, mendable = null;
            for (var roll = 0; roll < 8 && built is null; roll++)
            {
                var rolled = convertible.ConvertToPKM(trainer, criteria);
                if (rolled.GetType() != blank.GetType() || (level != 0 && rolled.CurrentLevel > level))
                    continue;
                if (new LegalityAnalysis(rolled).Valid)
                    built = rolled;
                // A gift of the species asked for can be invalid as generated (a missing handler or HOME tracker).
                else if (rolled.Species == species)
                    mendable ??= rolled;
            }
            built ??= mendable;
            if (built is null)
                continue;
            // An egg or a pre-evolution encounter is evolved into the species asked for.
            var evolved = built.Species != species;
            if (evolved)
            {
                built.Species = species;
                built.ClearNickname();
                if (detail.Genderless)
                    built.Gender = EntityGender.Genderless;
                // A Galarian Farfetch'd (form 1) becomes Sirfetch'd, which has only form 0.
                built.Form = form < detail.FormCount ? form : (byte)0;
            }
            if (level > 0 && level < built.CurrentLevel)
                continue;
            // An evolved Pokemon left at the level it was caught at can be below its evolution level: walk up.
            var last = climb && evolved && level == 0 ? 100 : Math.Max(level, built.CurrentLevel);
            for (var lv = Math.Max(level, built.CurrentLevel); lv <= last; lv++)
            {
                var pk = built.Clone();
                if (lv > pk.CurrentLevel)
                    pk.CurrentLevel = (byte)lv;
                // A form the player changes (Rotom's appliances) is caught as another.
                if (pk.Form != form && FormInfo.IsFormChangeable(species, pk.Form, form, game.Context, pk.Context))
                    pk.Form = form;
                if (shiny && !pk.IsShiny)
                    pk.SetIsShiny(true);
                if (nickname.Length > 0)
                    pk.SetNickname(nickname);
                wish.Apply(pk);
                var la = Mend(pk, evolved, encounter, trainer, wish);
                var unmet = wish.Unmet(pk, strings);
                if (la.Valid && unmet is null)
                    return Describe(game, pk, la);
                if (unmet is null)
                    firstProblem ??= la.Report();
                else
                    firstUnmet ??= unmet;
            }
        }
    }
    var name = strings.specieslist[species];
    throw new InvalidOperationException(firstProblem is not null
        ? $"No legal {name} with these choices. {firstProblem}"
        : firstUnmet is not null
            ? $"No legal {name} in this game has {firstUnmet}."
        : lowest != int.MaxValue
            ? $"{name} cannot be lower than level {lowest} in this game."
            : shinyLocked
                ? $"{name} cannot be shiny in this game."
                : wish.Moves.Length > 1
                    ? $"No legal {name} in this game can know these moves together."
                    : $"PKHeX has no legal {name} for this game.");
}

// Repairs a built record one step at a time, each step on top of the last, and stops at the first that is legal.
LegalityAnalysis Mend(PKM pk, bool evolved, IEncounterTemplate encounter, ITrainerInfo trainer, Wish wish)
{
    var la = Refresh(pk, wish);
    if (la.Valid)
        return la;
    var repairs = new List<Action>();
    // Event Pokemon that Sword/Shield received only through HOME (Zeraora, Melmetal) carry a HOME tracker.
    // This comes first: a refit would replace the event's fixed moves.
    if (encounter is MysteryGift && pk is IHomeTrack { HasTracker: false } home)
        repairs.Add(() => home.Tracker = (ulong)Random.Shared.NextInt64(1, long.MaxValue));
    // Moves, relearn moves and move flags depend on the species and level just set.
    repairs.Add(() => Refit(pk, wish));
    if (evolved)
        // The ability keeps its slot but names the species it was caught as.
        repairs.Add(() => { pk.RefreshAbility(pk.AbilityNumber >> 1 & 3); Refit(pk, wish); });
    if (pk.HandlingTrainerName.Length == 0)
        repairs.Add(() =>
        {
            // A trade evolution has been through a trade, and some gifts (Z-A's Magearna) arrive already handled.
            pk.CurrentHandler = 1;
            pk.HandlingTrainerName = "POKELDN";
            pk.HandlingTrainerGender = (byte)(1 - trainer.Gender);
            if (pk is IHandlerLanguage language)
                language.HandlingTrainerLanguage = (byte)trainer.Language;
            Refit(pk, wish);
        });
    if (evolved)
    {
        // Evolutions that count something (critical hits, damage taken, Rage Fist uses, coins) start from that count.
        if (FormArgumentUtil.GetFormArgumentMinEvolution(pk.Species, encounter.Species) is var counted and not 0)
            repairs.Add(() => { FormArgumentUtil.ChangeFormArgument(pk, counted); Refit(pk, wish); });
        // BDSP's Milotic evolves at Beauty 170; poffins that raise Beauty also raise Sheen.
        if (pk is PB8 pb8 && HowEvolved(pk) is { Method: EvolutionType.LevelUpBeauty } beauty)
            repairs.Add(() =>
            {
                pb8.ContestBeauty = (byte)beauty.Argument;
                pb8.ContestSheen = ContestStatInfo.CalculateMinimumSheen8b(pb8, pb8.Nature, ContestStatInfo.GetReferenceTemplate(encounter));
            });
    }
    foreach (var repair in repairs)
    {
        try
        {
            repair();
        }
        catch (IndexOutOfRangeException)
        {
            // PKHeX's move suggester indexes past a learnset some forms lack; this candidate stays as it was.
            continue;
        }
        la = Refresh(pk, wish);
        if (la.Valid)
            break;
    }
    return la;
}

// The method that turned the species before this one into the record's species, if PKHeX has one.
static EvolutionMethod? HowEvolved(PKM pk)
{
    var tree = EvolutionTree.GetEvolutionTree(pk.Context);
    foreach (var (species, form) in tree.Reverse.GetPreEvolutions(pk.Species, pk.Form))
        foreach (var method in tree.Forward.GetForward(species, form).Span)
            if (method.Species == pk.Species)
                return method;
    return null;
}

LegalityAnalysis Refresh(PKM pk, Wish? wish = null)
{
    if (pk is PB7 pb7)
    {
        AwakeningUtil.SetSuggestedAwakenedValues(pb7, pb7);
        wish?.ApplyEffort(pk);
        pb7.ResetCalculatedValues();
    }
    pk.ResetPartyStats();
    pk.RefreshChecksum();
    return new LegalityAnalysis(pk);
}

void Refit(PKM pk, Wish wish)
{
    // Moves the request names stay; PKHeX suggests the rest.
    if (wish.Moves.Length > 0)
        pk.SetMoves(wish.Moveset());
    else
        pk.SetMoveset();
    pk.SetRelearnMoves(new LegalityAnalysis(pk));
    // A TM or TR move the suggested moveset holds is legal only with its record flag (Sword/Shield's TRs).
    if (pk is ITechRecord record)
        record.SetRecordFlags(pk, TechnicalRecordApplicatorOption.LegalCurrent);
    if (pk is IPlusRecord plus && pk.PersonalInfo is IPermitPlus permit)
        PlusRecordApplicator.SetPlusFlags(plus, pk, permit, PlusRecordApplicatorOption.LegalCurrent);
    if (pk is IMoveShop8Mastery shop)
        shop.SetMoveShopFlags(pk);
    if (pk is PA8 pa8)
    {
        pa8.ResetHeight();
        pa8.ResetWeight();
    }
}

JsonObject Check(Game game, byte[] data, JsonObject request)
{
    if (game.Context == EntityContext.Gen7b && data.Length == 0xE8)
        data = [.. data, .. new byte[0x104 - data.Length]];
    var pk = EntityFormat.GetFromBytes(data, game.Context)
             ?? throw new InvalidDataException($"{data.Length} bytes are not a Pokemon of this game.");
    if (pk.GetType() != game.Blank().GetType())
        throw new InvalidDataException($"Expected {game.Blank().GetType().Name}, received {pk.GetType().Name}.");
    if (!game.Table.IsPresentInGame(pk.Species, pk.Form))
        throw new InvalidDataException("This species or form is absent from the selected game.");
    if (!pk.ChecksumValid)
        throw new InvalidDataException("The Pokemon checksum is invalid.");
    if (request["fields"] is JsonObject fields)
        foreach (var (name, value) in fields)
        {
            switch (name)
            {
                case "nickname": pk.SetNickname((string)value!); break;
                case "ot_name": pk.OriginalTrainerName = (string)value!; break;
                case "trainer_id": pk.TID16 = checked((ushort)(int)value!); break;
                case "secret_id": pk.SID16 = checked((ushort)(int)value!); break;
                default: throw new ArgumentException($"Unsupported edit {name}.");
            }
        }
    string? note = null;
    if ((bool?)request["fresh"] == true)
    {
        var (pid, ec) = (pk.PID, pk.EncryptionConstant);
        var legal = new LegalityAnalysis(pk).Valid;
        var xor = (pk.PID >> 16) ^ (pk.PID & 0xFFFF);
        var high = (uint)Random.Shared.Next(0x10000);
        pk.PID = (high << 16) | (high ^ xor);
        pk.EncryptionConstant = (uint)Random.Shared.NextInt64(1, 1L << 32);
        // An event Pokemon's PID is part of the event: a new one makes it illegal.
        if (legal && !new LegalityAnalysis(pk).Valid)
        {
            (pk.PID, pk.EncryptionConstant) = (pid, ec);
            note = "kept its own PID: this event Pokemon is legal only with it";
        }
    }
    pk.ResetPartyStats();
    pk.RefreshChecksum();
    // A box record carries no party stats; the receiving console computes them, so do the same.
    if (pk is PB7 pb7)
    {
        pb7.ResetPartyStats();
        pb7.ResetCalculatedValues();
    }
    var reply = Describe(game, pk, new LegalityAnalysis(pk));
    if (note is not null)
        reply["note"] = note;
    return reply;
}

// A Showdown or Smogon set, read by PKHeX's own parser in any language it knows, as the values `make` takes.
// A line it cannot read or a choice this game lacks is an error; a value the builder does not set is a note.
JsonObject Paste(Game game, JsonObject request)
{
    var (_, trainer) = Trainer(game, request);
    // The parser reads item names and forms in the context of the most recent trainer.
    RecentTrainerCache.SetRecentTrainer(trainer);
    var lines = ((string)request["text"]!).Replace("\r", "").Split('\n');
    var sets = new JsonArray();
    var blank = game.Blank();
    var dummied = MoveInfo.GetDummiedMovesHashSet(game.Context);
    var errorText = BattleTemplateParseErrorLocalization.Get();
    foreach (var set in ShowdownParsing.GetShowdownSets(lines))
    {
        var errors = new JsonArray();
        var notes = new JsonArray();
        foreach (var invalid in set.InvalidLines)
            errors.Add(invalid.Humanize(errorText));
        var species = set.Species;
        var name = species < strings.specieslist.Length ? strings.specieslist[species] : "";
        // A team export opens with a "=== [gen9] Team ===" line, read as a set with nothing in it.
        if (species == 0 && set.InvalidLines.Count == 0)
            continue;
        if (species == 0)
        {
            errors.Add("The first line names no Pokemon.");
            sets.Add(new JsonObject { ["errors"] = errors });
            continue;
        }
        if (!game.Table.IsPresentInGame(species, set.Form))
        {
            errors.Add(game.Table.IsPresentInGame(species, 0)
                ? $"{name} has no {set.FormName} form in this game."
                : $"{name} is not in this game.");
            sets.Add(new JsonObject { ["species"] = name, ["errors"] = errors });
            continue;
        }
        var detail = game.Table.GetFormEntry(species, set.Form);
        var options = new JsonObject();
        if (set.Form != 0)
            options["form"] = set.Form;
        if (set.Nature != Nature.Random)
            options["nature"] = (int)set.Nature;
        if (set.Ability >= 0)
        {
            if (game.Context == EntityContext.Gen9a)
                notes.Add("Legends Z-A has no abilities; the ability was left out.");
            else if (Enumerable.Range(0, detail.AbilityCount).All(i => detail.GetAbilityAtIndex(i) != set.Ability))
                errors.Add($"{name} cannot have {strings.abilitylist[set.Ability]}.");
            else
                options["ability"] = set.Ability;
        }
        if (set.Gender is { } gender && !detail.Genderless && !detail.OnlyFemale && !detail.OnlyMale)
            options["gender"] = (int)gender;
        if (set.HeldItem != 0)
        {
            if (!ItemRestrictions.IsHeldItemAllowed(set.HeldItem, game.Context))
                errors.Add($"{strings.GetItemStrings(game.Context, game.Versions[0])[set.HeldItem]} cannot be held in this game.");
            else
                options["held_item"] = set.HeldItem;
        }
        var moves = new JsonArray();
        var moveNames = new JsonArray();
        foreach (var move in set.Moves)
        {
            if (move == 0)
                continue;
            if (move > blank.MaxMoveID || MoveInfo.IsDummiedMove(dummied, move))
                errors.Add($"{strings.movelist[move]} is not in this game.");
            else
            {
                moves.Add(move);
                moveNames.Add(strings.movelist[move]);
            }
        }
        if (moves.Count > 0)
            options["moves"] = moves;
        // The parser keeps stats in PKHeX's order, Speed fourth (H/A/B/S/C/D).
        string[] stats = ["hp", "atk", "def", "spe", "spa", "spd"];
        options["ivs"] = new JsonObject(stats.Select((s, i) => KeyValuePair.Create(s, (JsonNode?)set.IVs[i])));
        if (set.EVs.Any(v => v != 0))
        {
            if (blank is IAwakened or IGanbaru)
                notes.Add("This game has no EVs; the EVs were left out.");
            else if (set.EVs.Sum() > EffortValues.Max510)
                errors.Add($"EVs add up to {set.EVs.Sum()}; at most {EffortValues.Max510}.");
            else
                options["effort"] = new JsonObject(stats.Select((s, i) => KeyValuePair.Create(s, (JsonNode?)Math.Min(set.EVs[i], EffortValues.Max252))));
        }
        if (set.TeraType != MoveType.Any)
            notes.Add("The Tera Type is not set; the Pokemon keeps its own.");
        if (set.CanGigantamax || set.DynamaxLevel != 10)
            notes.Add("Gigantamax and Dynamax level are not set.");
        if (set.HiddenPowerType >= 0 && blank.Format < 8)
            notes.Add("Hidden Power follows the IVs; its type is not set.");
        if (set.Friendship != 255)
            notes.Add("Friendship is not set.");
        sets.Add(new JsonObject
        {
            ["species"] = name,
            ["species_id"] = species,
            ["form"] = set.Form == 0 ? "" : ShowdownParsing.GetStringFromForm(set.Form, strings, species, game.Context),
            ["nickname"] = set.Nickname,
            ["level"] = set.Level,
            ["shiny"] = set.Shiny,
            ["options"] = options,
            ["moves"] = moveNames,
            ["errors"] = errors,
            ["notes"] = notes,
        });
    }
    if (sets.Count == 0)
        throw new ArgumentException("The text holds no Pokemon set.");
    return new JsonObject { ["sets"] = sets };
}

// PKHeX's Gen 3 event table (internal, read by name: pin the package before renaming it). Japanese
// distributions are left out: their names do not render on a European cartridge.
IEnumerable<EncounterGift3> Gen3Events() =>
    ((EncounterGift3[])typeof(PK3).Assembly.GetType("PKHeX.Core.EncountersWC3")!
        .GetField("Encounter_WC3", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)!
        .GetValue(null)!).Where(e => !e.IsEgg && e.Language != (byte)LanguageID.Japanese);

string EventName(EncounterGift3 e) => $"{e.OriginalTrainerName} {strings.specieslist[e.Species]}";

JsonObject Events()
{
    var list = new JsonArray();
    foreach (var e in Gen3Events())
        list.Add(new JsonObject
        {
            ["name"] = EventName(e), ["species"] = e.Species, ["level"] = e.Level,
            ["language"] = e.Language, ["trainer_id"] = e.TID16,
        });
    return new JsonObject { ["events"] = list };
}

// A fresh copy of one event, made by PKHeX's own PID/IV method for it. `language` picks among the
// event's language releases (0 takes any); an event released in every language takes it too.
JsonObject Event(Game game, JsonObject request)
{
    var name = (string)request["name"]!;
    var language = (int?)request["language"] ?? 0;
    var matches = Gen3Events().Where(e => EventName(e) == name).ToList();
    if (matches.Count == 0)
        throw new ArgumentException($"No Gen 3 event is named {name}.");
    var encounter = matches.FirstOrDefault(e => e.Language == language)
                    ?? matches.FirstOrDefault(e => e.Language == (byte)LanguageID.English) ?? matches[0];
    var trainer = new SimpleTrainerInfo(GameVersion.FR)
    {
        Language = language is > 0 and <= 7 ? language : (int)LanguageID.English,
    };
    // A random roll can land on a PID its own check rejects (seen on 10 ANIV Entei): roll again.
    PKM pk = null!;
    LegalityAnalysis la = null!;
    for (var attempt = 0; attempt < 32; attempt++)
    {
        pk = encounter.ConvertToPKM(trainer, EncounterCriteria.Unrestricted);
        pk.ResetPartyStats();
        la = new LegalityAnalysis(pk);
        if (la.Valid)
            break;
    }
    if (!la.Valid)
        throw new InvalidDataException($"PKHeX made an illegal {name}: {la.Report()}");
    return new JsonObject
    {
        ["data"] = Convert.ToBase64String(game.Write(pk)),
        ["name"] = name, ["language"] = pk.Language,
        ["summary"] = $"{strings.specieslist[pk.Species]} Lv{pk.CurrentLevel} {strings.natures[(int)pk.Nature]}, "
                      + $"OT {pk.OriginalTrainerName} {pk.TID16:00000}, PID {pk.PID:X8}",
    };
}

JsonObject Gift(byte[] data)
{
    if (data.Length != WC8.Size)
        throw new InvalidDataException("A WC8 record must contain 720 bytes.");
    var card = new WC8(data);
    var held = ItemStorage8SWSH.GetAllHeld();
    bool ValidItem(int item) => item == 0 || held.Contains((ushort)item);
    if (card.IsEntity)
    {
        if (!PersonalTable.SWSH.IsPresentInGame(card.Species, card.Form))
            throw new InvalidDataException("This species or form is absent from Sword/Shield.");
        var blank = new PK8();
        var dummied = MoveInfo.GetDummiedMovesHashSet(EntityContext.Gen8);
        ushort[] moves = [card.Move1, card.Move2, card.Move3, card.Move4,
                          card.RelearnMove1, card.RelearnMove2, card.RelearnMove3, card.RelearnMove4];
        foreach (var move in moves)
            if (move > blank.MaxMoveID || MoveInfo.IsDummiedMove(dummied, move))
                throw new InvalidDataException("This move is unavailable in Sword/Shield.");
        if (card.Level > 100 || card.Ball > blank.MaxBallID || !ValidItem(card.HeldItem))
            throw new InvalidDataException("Invalid gift level, ball or held item.");
        if (data[0x243] > 3 || (data[0x246] > 24 && data[0x246] != 255) ||
            data[0x247] > 4 || data[0x248] > 4 || data[0x24A] > 10)
            throw new InvalidDataException("Invalid gift gender, nature, ability, shininess or Dynamax level.");
        if (data[0x24B] > 1 || (data[0x24B] == 1 && !Gigantamax.CanToggle(card.Species, card.Form)))
            throw new InvalidDataException("This species has no Gigantamax form.");
    }
    else if (card.IsItem)
    {
        for (var i = 0; i < 6; i++)
            if (!ValidItem(card.GetItem(i)) || (card.GetItem(i) != 0 && card.GetQuantity(i) is < 1 or > 999))
                throw new InvalidDataException("Invalid gift item or quantity; bag items only, up to 999.");
    }
    else if (card.CardType == WC8.GiftType.Clothing)
    {
        // Twelve u32 (category, index) pairs from +0x20; the setter 0x0143a450 takes categories 0..14
        // and indices 0..1023, and the redemption skips index 0xFFFFFFFF (docs/swsh_gift.md).
        for (var i = 0; i < 12; i++)
        {
            var category = BitConverter.ToUInt32(data, 0x20 + 8 * i);
            var index = BitConverter.ToUInt32(data, 0x24 + 8 * i);
            if (index != uint.MaxValue && (category > 14 || index > 1023))
                throw new InvalidDataException("Invalid clothing category or index.");
        }
    }
    else if (data[0x11] == 5)
    {
        if (BitConverter.ToUInt32(data, 0x20) is < 1 or > 9_999_999)
            throw new InvalidDataException("Money is 1 to 9,999,999.");
    }
    else if (card.CardType != WC8.GiftType.BP)
        throw new InvalidDataException("Supported WC8 gifts are Pokemon, bag items, BP, clothing and money.");
    return new JsonObject { ["valid"] = true };
}

JsonObject Describe(Game game, PKM pk, LegalityAnalysis la)
{
    var moves = new JsonArray();
    foreach (var move in pk.Moves)
        if (move != 0)
            moves.Add(strings.movelist[move]);
    return new JsonObject
    {
        ["data"] = Convert.ToBase64String(game.Write(pk)),
        ["format"] = pk.GetType().Name,
        ["species"] = strings.specieslist[pk.Species],
        ["species_id"] = pk.Species,
        ["form"] = pk.Form == 0 ? "" : ShowdownParsing.GetStringFromForm(pk.Form, strings, pk.Species, pk.Context),
        ["form_id"] = pk.Form,
        ["level"] = pk.CurrentLevel,
        ["shiny"] = pk.IsShiny,
        ["nickname"] = pk.Nickname,
        ["ot"] = pk.OriginalTrainerName,
        ["trainer_id"] = pk.DisplayTID,
        ["secret_id"] = pk.DisplaySID,
        ["nature"] = strings.natures[(int)pk.StatAlignment],
        ["ball"] = strings.balllist[pk.Ball],
        ["ability"] = game.Context == EntityContext.Gen9a ? "" : strings.abilitylist[pk.Ability],
        ["held_item"] = pk.HeldItem == 0 ? "" : strings.GetItemStrings(game.Context, game.Versions[0])[pk.HeldItem],
        ["moves"] = moves,
        ["encounter"] = la.EncounterOriginal.LongName,
        ["legal"] = la.Valid,
        ["report"] = la.Report(),
    };
}

static byte[] EncryptedStored(PKM pk)
{
    var data = new byte[pk.SIZE_STORED];
    pk.WriteEncryptedDataStored(data);
    return data;
}

static byte[] EncryptedParty(PKM pk)
{
    var data = new byte[pk.SIZE_PARTY];
    pk.WriteEncryptedDataParty(data);
    return data;
}

static byte[] DecryptedParty(PKM pk)
{
    var data = new byte[pk.SIZE_PARTY];
    pk.WriteDecryptedDataParty(data);
    return data;
}

// The offer options a request asks for; a stat array is HP, Atk, Def, SpA, SpD, Spe and -1 leaves a stat alone.
record Wish(Nature? Nature, int? Ability, Gender? Gender, int[] IVs, int[] Effort, int? Item, byte? Ball,
            byte? Form, ushort[] Moves)
{
    static readonly string[] Stats = ["hp", "atk", "def", "spa", "spd", "spe"];
    static readonly string[] StatNames = ["HP", "Attack", "Defense", "Sp. Atk", "Sp. Def", "Speed"];

    public static Wish From(JsonObject? o)
    {
        int[] Read(string key)
        {
            var group = o?[key] as JsonObject;
            return [.. Stats.Select(s => group?[s] is { } v ? (int)v : -1)];
        }
        int? Number(string key) => o?[key] is { } v ? (int)v : null;
        var ivs = Read("ivs");
        var effort = Read("effort");
        if (ivs.Any(v => v > 31) || effort.Any(v => v > 252))
            throw new ArgumentException("An IV is at most 31 and an effort value at most 252.");
        if (Number("nature") is < 0 or > 24)
            throw new ArgumentException("Unknown nature.");
        ushort[] moves = o?["moves"] is JsonArray list
            ? [.. list.Select(m => checked((ushort)(int)m!)).Where(m => m != 0).Distinct()] : [];
        if (moves.Length > 4)
            throw new ArgumentException("A Pokemon knows at most four moves.");
        return new Wish(Number("nature") is { } n ? (Nature)n : null, Number("ability"),
            Number("gender") is { } g ? (Gender)g : null, ivs, effort,
            Number("held_item"), Number("ball") is { } b ? checked((byte)b) : null,
            Number("form") is { } f ? checked((byte)f) : null, moves);
    }

    public ushort[] Moveset() => [.. Moves, .. new ushort[4 - Moves.Length]];

    public EncounterCriteria Criteria(IPersonalInfo detail) => EncounterCriteria.Unrestricted with
    {
        Nature = Nature ?? PKHeX.Core.Nature.Random,
        Ability = Ability is { } a ? Permission(detail, a) : AbilityPermission.Any12H,
        IV_HP = (sbyte)IVs[0], IV_ATK = (sbyte)IVs[1], IV_DEF = (sbyte)IVs[2],
        IV_SPA = (sbyte)IVs[3], IV_SPD = (sbyte)IVs[4], IV_SPE = (sbyte)IVs[5],
    };

    static AbilityPermission Permission(IPersonalInfo detail, int ability)
    {
        var first = detail.GetAbilityAtIndex(0) == ability;
        var second = detail.AbilityCount > 1 && detail.GetAbilityAtIndex(1) == ability;
        return first && second ? AbilityPermission.Any12 : first ? AbilityPermission.OnlyFirst
            : second ? AbilityPermission.OnlySecond : AbilityPermission.OnlyHidden;
    }

    // An encounter that rolled another nature, ability or a lower IV is moved there the way a player would:
    // a mint (Sword/Shield onward), an ability capsule or patch, hyper training. The legality check judges it.
    public void Apply(PKM pk)
    {
        if (Nature is { } nature && pk.StatAlignment != nature && pk.Format >= 8)
            pk.StatAlignment = nature;
        if (Ability is { } ability && pk.Ability != ability)
        {
            var pi = pk.PersonalInfo;
            for (var slot = 0; slot < pi.AbilityCount; slot++)
                if (pi.GetAbilityAtIndex(slot) == ability)
                {
                    pk.RefreshAbility(slot);
                    break;
                }
        }
        if (pk is IHyperTrain train && train.IsHyperTrainingAvailable() && pk.Context.IsHyperTrainingAvailable(pk.CurrentLevel))
            for (var i = 0; i < 6; i++)
                if (IVs[i] == 31 && IV(pk, i) != 31 && !train.IsHyperTrained(Battle(i)))
                    train.HyperTrainInvert(Battle(i));
        if (Moves.Length > 0)
            pk.SetMoves(Moveset());
        if (Item is { } item)
            pk.HeldItem = item;
        if (Ball is { } ball)
            pk.Ball = ball;
        ApplyEffort(pk);
        // Gen 3 and 4 raise an EV past 100 (the vitamin cap) only in battle, so the record must have gained
        // experience since it was met; one point stays below the next level.
        if (pk.Format < 5 && Effort.Any(v => v > EffortValues.MaxVitamins34) && pk.CurrentLevel < 100 &&
            pk.EXP + 1 < Experience.GetEXP((byte)(pk.CurrentLevel + 1), pk.PersonalInfo.EXPGrowth))
            pk.EXP += 1;
    }

    public void ApplyEffort(PKM pk)
    {
        for (var i = 0; i < 6; i++)
        {
            if (Effort[i] < 0)
                continue;
            var v = (byte)Effort[i];
            switch (pk)
            {
                case IAwakened av:
                    av.SetAV(Battle(i), v);
                    break;
                // The effort level Legends Arceus shows is the stored value plus a bias from the IV (3 at 31).
                case IGanbaru gv:
                    gv.SetGV(Battle(i), (byte)Math.Max(0, v - GanbaruExtensions.GetBias(IV(pk, i))));
                    break;
                default:
                    _ = i switch
                    {
                        0 => pk.EV_HP = v, 1 => pk.EV_ATK = v, 2 => pk.EV_DEF = v,
                        3 => pk.EV_SPA = v, 4 => pk.EV_SPD = v, _ => pk.EV_SPE = v,
                    };
                    break;
            }
        }
    }

    // The first choice the record does not carry, in words, or null when it carries all of them.
    public string? Unmet(PKM pk, GameStrings strings)
    {
        if (Nature is { } nature && pk.StatAlignment != nature)
            return $"a {strings.natures[(int)nature]} nature";
        if (Ability is { } ability && pk.Ability != ability)
            return $"the ability {strings.abilitylist[ability]}";
        if (Gender is { } gender && pk.Gender != (byte)gender)
            return gender == PKHeX.Core.Gender.Female ? "a female" : "a male";
        for (var i = 0; i < 6; i++)
            if (IVs[i] >= 0 && IV(pk, i) != IVs[i] && !(IVs[i] == 31 && pk is IHyperTrain t && t.IsHyperTrained(Battle(i))))
                return $"{StatNames[i]} IV {IVs[i]}";
        if (Ball is { } ball && pk.Ball != ball)
            return $"a {strings.balllist[ball]}";
        if (Form is { } form && pk.Form != form)
            return "this form";
        foreach (var move in Moves)
            if (!pk.HasMove(move))
                return $"the move {strings.movelist[move]}";
        return null;
    }

    // PKHeX's stat index order puts Speed fourth (H/A/B/S/C/D).
    static int Battle(int i) => i switch { 3 => 4, 4 => 5, 5 => 3, _ => i };

    static int IV(PKM pk, int i) => i switch
    {
        0 => pk.IV_HP, 1 => pk.IV_ATK, 2 => pk.IV_DEF, 3 => pk.IV_SPA, 4 => pk.IV_SPD, _ => pk.IV_SPE,
    };
}

record Game(GameVersion[] Versions, IPersonalTable Table, EntityContext Context, Func<PKM> Blank,
            Func<PKM, byte[]> Write);
