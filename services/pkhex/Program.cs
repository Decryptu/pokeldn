using System.Diagnostics.CodeAnalysis;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Text.Json.Nodes;
using PKHeX.Core;
using static PKHeX.Core.GameVersion;


// A class rather than top-level statements: the iOS app loads the helper as a library (Library.cs).
static partial class Program
{
    static void Main() => Serve();

    // A language pack's BCP 47 tag -> PKHeX's text language; a TW, HK or MO region is Traditional Chinese.
    static string DisplayLanguage(string? tag)
    {
        var parts = (tag ?? "en").ToLowerInvariant().Split('-');
        return parts[0] switch
        {
            "zh" => parts.Skip(1).Any(p => p is "hant" or "tw" or "hk" or "mo") ? "zh-Hant" : "zh-Hans",
            "ja" or "fr" or "it" or "de" or "es" or "ko" => parts[0],
            _ => "en",
        };
    }

    internal static void Serve()
    {
        var strings = GameInfo.GetStrings("en");
        var displayLanguage = "en";
        // Cut, Fly, Surf, Strength, Waterfall, Flash, Rock Smash, Dive
        var hiddenMoves = new HashSet<ushort> { 15, 19, 57, 70, 127, 148, 249, 291 };
        // Diamond to SoulSilver: Cut, Fly, Surf, Strength, Waterfall, Rock Smash, Whirlpool, Rock Climb, Defog
        var hiddenMoves4 = new HashSet<ushort> { 15, 19, 57, 70, 127, 249, 250, 431, 432 };
        var games = new Dictionary<string, Game>
        {
            ["frlg"] = new([FR, LG, E, R, S], PersonalTable.FR, EntityContext.Gen3, () => new PK3(), DecryptedParty),
            // Ruby, Sapphire and Emerald, ahead of a Switch release (docs/rse.md).
            ["rse"] = new([E, R, S, FR, LG], PersonalTable.E, EntityContext.Gen3, () => new PK3(), DecryptedParty),
            ["lgpe"] = new([GP, GE], PersonalTable.GG, EntityContext.Gen7b, () => new PB7(), EncryptedParty),
            ["bdsp"] = new([BD, SP], PersonalTable.BDSP, EntityContext.Gen8b, () => new PB8(), EncryptedStored),
            ["swsh"] = new([SW, SH], PersonalTable.SWSH, EntityContext.Gen8, () => new PK8(), EncryptedParty),
            ["pla"] = new([PLA], PersonalTable.LA, EntityContext.Gen8a, () => new PA8(), EncryptedParty),
            ["sv"] = new([SL, VL], PersonalTable.SV, EntityContext.Gen9, () => new PK9(), EncryptedParty),
            // The app frames the decrypted record into Z-A's offer message (pokeldn.za.pokemon.build_offer).
            ["za"] = new([ZA], PersonalTable.ZA, EntityContext.Gen9a, () => new PA9(), DecryptedParty),
        };

        // The app's HOME tracker setting (docs/gui.md, The bank): "empty" leaves a tracker HOME would have issued unset
        // and accepts PKHeX's one complaint about it; "made" fills it. HOME 3.1.0 refuses a tracker it did not issue.
        var emptyTracker = true;
        var madeTrackers = new HashSet<ulong>();

        while (Console.ReadLine() is { } line)
        {
            JsonObject reply;
            try
            {
                var request = JsonNode.Parse(line)!.AsObject();
                // A reply's names; the record's own language and the Showdown parser stay as requested.
                displayLanguage = DisplayLanguage((string?)request["display_language"]);
                strings = GameInfo.GetStrings(displayLanguage);
                emptyTracker = (string?)request["home_tracker"] != "made";
                madeTrackers.Clear();
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
                    "owner" => Owner(game, Convert.FromBase64String((string)request["data"]!)),
                    "gift" => Gift(Convert.FromBase64String((string)request["data"]!)),
                    "events" => Events(),
                    "event" => Event(game, request),
                    "gift_events" => GiftEventList(game, request),
                    "gift_event" => GiftEvent(game, request),
                    "sav_read" => SaveRead(game, request),
                    "sav_box" => SaveBox(game, request),
                    "sav_edit" => SaveEdit(game, request),
                    "import" => Import(request),
                    "move" => Move(game, request),
                    "destinations" => Destinations(game, request),
                    "raid_scan" => RaidScan.Run(request),
                    "wild_areas" => Wild.AreasReply(strings),
                    "wild_legal" => Wild.LegalReply(request, strings, Plain),
                    "wild_species" => Wild.SpeciesReply(request, strings),
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
                if (FirstForm(game, s) is not null)
                    list.Add(new JsonObject { ["id"] = s, ["name"] = strings.specieslist[s] });
            return new JsonObject { ["species"] = list };
        }

        // Legends Arceus holds 16 species only in their Hisuian form (Growlithe, Zorua, Decidueye...): form 0 is absent.
        byte? FirstForm(Game game, ushort species)
        {
            for (byte f = 0; f < game.Table[species].FormCount; f++)
                if (game.Table.IsPresentInGame(species, f))
                    return f;
            return null;
        }

        // The encounters a build tries: per version wild slots, static encounters, trades, eggs; Mystery Gifts last, as an
        // event's fixed PID makes a new-PID offer illegal. PKHeX lists eggs first; each kind is cut at 80 on its own
        // (docs/architecture.md, Encounter order).
        List<IEncounterable> Encounters(PKM blank, ITrainerInfo trainer, ReadOnlyMemory<ushort> moves, GameVersion[] versions)
        {
            List<IEncounterable> found = [], gifts = [];
            try
            {
                foreach (var version in versions)
                    foreach (var group in (EncounterTypeGroup[])[EncounterTypeGroup.Slot, EncounterTypeGroup.Static,
                                 EncounterTypeGroup.Trade, EncounterTypeGroup.Egg, EncounterTypeGroup.Mystery])
                    {
                        EncounterMovesetGenerator.PriorityList = [group];
                        (group == EncounterTypeGroup.Mystery ? gifts : found)
                            .AddRange(EncounterMovesetGenerator.GenerateEncounters(blank, trainer, moves, version).Take(80));
                    }
            }
            finally
            {
                EncounterMovesetGenerator.ResetFilters();
            }
            return [.. found, .. gifts];
        }

        JsonObject GenderRatio(Game game, JsonObject request)
        {
            var species = checked((ushort)(int)request["species"]!);
            var form = checked((byte)((int?)request["form"] ?? 0));
            if (!game.Table.IsPresentInGame(species, form))
                form = FirstForm(game, species) ?? 0;
            return new JsonObject { ["ratio"] = (int)game.Table.GetFormEntry(species, form).Gender };
        }

        JsonObject Names(Game game, string list)
        {
            if (list == "species")
                return new JsonObject { ["names"] = Species(game)["species"]!.DeepClone() };
            if (list == "species3")
            {
                var species = new JsonArray();
                for (ushort id = 1; id <= 386; id++)
                    species.Add(new JsonObject { ["id"] = SpeciesConverter.GetInternal3(id), ["name"] = strings.specieslist[id] });
                return new JsonObject { ["names"] = species };
            }
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
                    // Gen 3 keeps its own item ids (Rare Candy 68, national 50); "???" marks the unused ones.
                    // FireRed's table ends at 374 [pokefirered include/constants/items.h]; 375-376 are Emerald's.
                    var names3 = strings.GetItemStrings(game.Context, game.Versions[0]);
                    var last = game.Context == EntityContext.Gen3 ? 374 : blank.MaxItemID;
                    for (var i = 1; i <= last && i < names3.Length; i++)
                        if (names3[i] != "???")
                            Add(i, names3[i]);
                    break;
                case "bag" when game.Context == EntityContext.Gen8:
                    foreach (var i in GiftItems().Order())
                        Add(i, strings.itemlist[i]);
                    break;
                case "bag" when game.Context == EntityContext.Gen9:
                    // What a Tera Raid reward may give: every pouch but the key items, unreleased items left out.
                    foreach (var i in RaidRewardItems().Order())
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
            var first = FirstForm(game, species) ?? throw new ArgumentException("This species is absent from the selected game.");
            var form = checked((byte)((int?)request["form"] ?? first));
            if (!game.Table.IsPresentInGame(species, form))
                form = first;
            var detail = game.Table.GetFormEntry(species, form);
            var (versions, trainer) = Trainer(game, request);
            // A ball is listed when PKHeX permits it for at least one encounter of the species.
            var blank = game.Blank();
            blank.Species = species;
            blank.Form = form;
            var permitted = new HashSet<Ball>();
            Span<Ball> found = stackalloc Ball[BallApplicator.MaxBallSpanAlloc];
            foreach (var encounter in Encounters(blank, trainer, ReadOnlyMemory<ushort>.Empty, versions))
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
                // "only_version": the trainer's own game alone, as a gift made for a receiving player (docs/gift_simulated.md).
                versions = (bool?)request["only_version"] ?? false ? [chosen] : [chosen, .. versions.Where(x => x != chosen)];
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
            var first = FirstForm(game, species) ?? throw new ArgumentException("This species is absent from the selected game.");
            var level = (int?)request["level"] ?? 0;
            if (level < 0 || level > 100)
                throw new ArgumentException("Level must be between 0 and 100.");
            var shiny = (bool?)request["shiny"] ?? false;
            var nickname = (string?)request["nickname"] ?? "";
            var wish = Wish.From(request["options"] as JsonObject);
            // A request that names no form takes the first that builds: Sword/Shield holds Zygarde only in its Power
            // Construct forms, Scarlet/Violet Ursaluna only as Bloodmoon.
            if (wish.Form is null)
            {
                InvalidOperationException? refused = null;
                for (var f = first; f < game.Table[species].FormCount; f++)
                {
                    if (!game.Table.IsPresentInGame(species, f))
                        continue;
                    var probe = request.DeepClone().AsObject();
                    if (probe["options"] is not JsonObject options)
                        probe["options"] = options = [];
                    options["form"] = (int)f;
                    try
                    {
                        return Make(game, probe);
                    }
                    catch (InvalidOperationException e)
                    {
                        refused ??= e;
                    }
                }
                throw refused!;
            }
            var form = wish.Form.Value;
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
            var encounters = Encounters(blank, trainer, wish.Moves, versions);
            foreach (var climb in new[] { false, true })
            {
                foreach (var encounter in encounters)
                {
                    if (encounter is not IEncounterConvertible convertible)
                        continue;
                    if (climb && (level > 0 || encounter.Species == species))
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
                    // above the level asked for, so an encounter gets several. A roll above the level costs no legality
                    // check and is not one of the eight: a slot straddling the level misses it often.
                    PKM? built = null, mendable = null;
                    for (int roll = 0, tries = 0; roll < 8 && tries < 64 && built is null; tries++)
                    {
                        var rolled = convertible.ConvertToPKM(trainer, criteria);
                        if (level != 0 && rolled.CurrentLevel > level && rolled.GetType() == blank.GetType())
                            continue;
                        roll++;
                        if (rolled.GetType() != blank.GetType())
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
                    var start = Math.Max(level, built.CurrentLevel);
                    if (!climb)
                    {
                        if (Try(start) is { } made)
                            return made;
                        continue;
                    }
                    // An evolved Pokemon left at the level it was caught at can be below its evolution level: climb to the
                    // lowest legal level. In 231 of 233 such climbs every level above it was legal too, so level 100 decides
                    // (docs/architecture.md, Encounter order).
                    if (Try(100) is not { } top)
                        continue;
                    var (low, high) = (start, 100);
                    while (low < high)
                    {
                        var mid = (low + high) / 2;
                        if (Try(mid) is { } made)
                            (top, high) = (made, mid);
                        else
                            low = mid + 1;
                    }
                    return top;

                    JsonObject? Try(int lv)
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
                        if (Accepted(pk, la) && unmet is null)
                            return Describe(game, pk, la);
                        if (unmet is null)
                            firstProblem ??= la.Report(displayLanguage);
                        else
                            firstUnmet ??= unmet;
                        return null;
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
            if (Accepted(pk, la))
                return la;
            var repairs = new List<Action>();
            // Event Pokemon that Sword/Shield received only through HOME (Zeraora, Melmetal) carry a HOME tracker.
            // This comes first: a refit would replace the event's fixed moves.
            if (!emptyTracker && encounter is MysteryGift && pk is IHomeTrack { HasTracker: false } home)
                repairs.Add(() => home.Tracker = MadeTracker((ulong)Random.Shared.NextInt64(1, long.MaxValue)));
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
                    pk.HandlingTrainerGender = 0;
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
                if (Accepted(pk, la))
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

        // Valid, or invalid only for the HOME tracker the "empty" setting leaves unset [HomeTrackerUtil.IsRequired].
        bool Accepted(PKM pk, LegalityAnalysis la) => la.Valid || emptyTracker && (OnlyTrackerMissing(la) || ValidWithTracker(pk, la));

        // A record judged with the tracker it lacks: PKHeX lets a Pokemon evolve in another HOME game, or keep the
        // ability HOME realigned in Legends Z-A, only with one [EvolutionGroupHOME.CheckAllAdjacent, AbilityVerifier].
        static bool ValidWithTracker(PKM pk, LegalityAnalysis la)
        {
            if (pk is not IHomeTrack { HasTracker: false }
                || !la.Results.Any(r => r.Result == LegalityCheckResultCode.TransferTrackerMissing))
                return false;
            var tracked = pk.Clone();
            ((IHomeTrack)tracked).Tracker = 1;
            HomeSeen(tracked);
            tracked.RefreshChecksum();
            return new LegalityAnalysis(tracked).Valid;
        }

        static bool OnlyTrackerMissing(LegalityAnalysis la)
            => la.Parsed && la.Results.Any(r => !r.Valid)
               && la.Results.All(r => r.Valid || r.Result == LegalityCheckResultCode.TransferTrackerMissing)
               && la.Info.Moves.All(m => m.Valid) && la.Info.Relearn.All(m => m.Valid);

        ulong MadeTracker(ulong tracker)
        {
            madeTrackers.Add(tracker);
            return tracker;
        }

        LegalityAnalysis Refresh(PKM pk, Wish? wish = null)
        {
            if (pk is PB7 pb7)
            {
                AwakeningUtil.SetSuggestedAwakenedValues(pb7, pb7);
                wish?.ApplyEffort(pk);
                ResetSizes(pb7);
            }
            pk.ResetPartyStats();
            pk.RefreshChecksum();
            return new LegalityAnalysis(pk);
        }

        // Let's Go computes a Pokemon's height and weight, except on HOME's Meltan (card 9028), which keeps the ones HOME
        // gave it [MiscVerifierPB7].
        static void ResetSizes(PB7 pb7)
        {
            pb7.ResetCalculatedValues();
            if (pb7.Species == (ushort)PKHeX.Core.Species.Meltan
                && new LegalityAnalysis(pb7).EncounterMatch is WB7 { IsHeightWeightFixed: true } card)
            {
                pb7.HeightAbsolute = card.GetHomeHeightAbsolute();
                pb7.WeightAbsolute = card.GetHomeWeightAbsolute();
            }
        }

        void Refit(PKM pk, Wish wish)
        {
            // Moves the request names stay; PKHeX suggests the rest.
            if (wish.Moves.Length > 0)
                pk.SetMoves(wish.Moveset());
            else
                pk.SetMoveset();
            pk.SetRelearnMoves(new LegalityAnalysis(pk));
            Permit(pk);
            if (pk is PA8 pa8)
            {
                pa8.ResetHeight();
                pa8.ResetWeight();
            }
        }

        void Permit(PKM pk)
        {
            // A TM or TR move the suggested moveset holds is legal only with its record flag (Sword/Shield's TRs).
            if (pk is ITechRecord record)
                record.SetRecordFlags(pk, TechnicalRecordApplicatorOption.LegalCurrent);
            if (pk is IPlusRecord plus && pk.PersonalInfo is IPermitPlus permit)
                PlusRecordApplicator.SetPlusFlags(plus, pk, permit, PlusRecordApplicatorOption.LegalCurrent);
            if (pk is IMoveShop8Mastery shop)
                shop.SetMoveShopFlags(pk);
        }

        // PKHeX's report as a player reads it: the per-move lines folded into one, each problem once.
        string Plain(LegalityAnalysis la)
        {
            var lines = new List<string>();
            var moves = la.Info.Moves.Count(m => !m.Valid);
            if (moves > 0)
                lines.Add(moves == 1 ? "One of its moves is not legal." : $"{moves} of its moves are not legal.");
            var original = la.Report().Split('\n');
            var translated = la.Report(displayLanguage).Split('\n');
            for (var i = 0; i < original.Length; i++)
            {
                var raw = original[i];
                var line = (i < translated.Length ? translated[i] : raw).Trim();
                if (line.Length == 0 || Regex.IsMatch(raw.Trim(), @"^Invalid (Relearn )?Move \d+:"))
                    continue;
                if (line.StartsWith("Invalid: "))
                    line = line["Invalid: ".Length..];
                if (!lines.Contains(line))
                    lines.Add(line);
            }
            return string.Join("\n", lines);
        }

        PKM Parse(Game game, byte[] data)
        {
            if (game.Context == EntityContext.Gen7b && data.Length == 0xE8)
                data = [.. data, .. new byte[0x104 - data.Length]];
            var pk = EntityFormat.GetFromBytes(data, game.Context)
                     ?? throw new InvalidDataException($"{data.Length} bytes are not a Pokemon of this game.");
            if (pk.GetType() != game.Blank().GetType())
                throw new InvalidDataException($"Expected {game.Blank().GetType().Name}, received {pk.GetType().Name}.");
            return pk;
        }

        // Whose a Pokemon is, read with no legality check, for a gift made for the save that offers it
        // (docs/gift_simulated.md, Made for the receiving player): its original trainer, its current handler (0 while
        // still with that trainer), the handler's name, gender and language, and the version it came from.
        JsonObject Owner(Game game, byte[] data)
        {
            var pk = Parse(game, data);
            if (!pk.ChecksumValid)
                throw new InvalidDataException("The Pokemon checksum is invalid.");
            return new JsonObject
            {
                ["species"] = pk.Species,
                ["shiny"] = pk.IsShiny,
                ["egg"] = pk.IsEgg,
                ["ot"] = pk.OriginalTrainerName,
                ["tid"] = pk.TID16,
                ["sid"] = pk.SID16,
                ["gender"] = pk.OriginalTrainerGender,
                ["language"] = pk.Language,
                ["handler"] = pk.CurrentHandler,
                ["ht_name"] = pk.HandlingTrainerName,
                ["ht_gender"] = pk.HandlingTrainerGender,
                ["ht_language"] = pk is IHandlerLanguage handler ? handler.HandlingTrainerLanguage : 0,
                ["version"] = (int)pk.Version,
            };
        }

        JsonObject Check(Game game, byte[] data, JsonObject request)
        {
            var pk = Parse(game, data);
            if (!game.Table.IsPresentInGame(pk.Species, pk.Form))
                throw new InvalidDataException("This species or form is absent from the selected game.");
            if (!pk.ChecksumValid)
                throw new InvalidDataException("The Pokemon checksum is invalid.");
            if (request["fields"] is JsonObject fields)
                foreach (var (name, value) in fields)
                {
                    switch (name)
                    {
                        case "nickname" when ((string)value!).Trim().Length == 0: pk.ClearNickname(); break;
                        case "nickname": pk.SetNickname((string)value!); break;
                        case "ot_name": pk.OriginalTrainerName = (string)value!; break;
                        case "trainer_id": pk.TID16 = checked((ushort)(int)value!); break;
                        case "secret_id": pk.SID16 = checked((ushort)(int)value!); break;
                        // The bank's editor (docs/gui.md, The bank): what a player can change in the game itself.
                        case "level":
                            var level = (int)value!;
                            if (level < pk.CurrentLevel || level > 100)
                                throw new ArgumentException($"The level goes from {pk.CurrentLevel} to 100: a Pokemon never loses levels.");
                            pk.CurrentLevel = (byte)level;
                            break;
                        case "moves":
                            var moves = ((JsonArray)value!).Select(m => (ushort)(int)m!).Where(m => m != 0).ToArray();
                            if (moves.Length == 0)
                                throw new ArgumentException("A Pokemon knows at least one move.");
                            pk.SetMoves(moves);
                            pk.HealPP();
                            Permit(pk);
                            break;
                        case "held_item": pk.HeldItem = (int)value!; break;
                        default: throw new ArgumentException($"Unsupported edit {name}.");
                    }
                }
            string? note = null;
            if ((bool?)request["fresh"] == true)
            {
                var (pid, ec) = (pk.PID, pk.EncryptionConstant);
                var legal = Accepted(pk, new LegalityAnalysis(pk));
                var xor = (pk.PID >> 16) ^ (pk.PID & 0xFFFF);
                var high = (uint)Random.Shared.Next(0x10000);
                pk.PID = (high << 16) | (high ^ xor);
                pk.EncryptionConstant = (uint)Random.Shared.NextInt64(1, 1L << 32);
                // An event Pokemon's PID is part of the event: a new one makes it illegal.
                if (legal && !Accepted(pk, new LegalityAnalysis(pk)))
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
                ResetSizes(pb7);
            }
            var reply = Describe(game, pk, new LegalityAnalysis(pk));
            if (note is not null)
                reply["note"] = note;
            return reply;
        }

        // A banked Pokemon taken to `game` through PKHeX's HOME conversion (docs/gui.md, The bank). A Pokemon from
        // another game carries the bank's HOME tracker under the "made" setting [HomeTrackerUtil].
        (PKM? Pokemon, LegalityAnalysis? Legality, string Refusal) Moved(Game from, Game to, byte[] data, ulong tracker,
                                                                           ITrainerInfo owner)
            // Between two Gen 3 games (FireRed and Emerald) a Pokemon moves by trade, not through HOME.
            => Converted(Parse(from, data), to, tracker, owner, from.Context != to.Context);

        (PKM? Pokemon, LegalityAnalysis? Legality, string Refusal) Converted(PKM source, Game to, ulong tracker,
                                                                               ITrainerInfo owner, bool transfer)
        {
            if (!source.ChecksumValid)
                return (null, null, "The Pokemon checksum is invalid.");
            PKM pk = source;
            if (transfer)
            {
                // Let's Go's format (7) is above FireRed's, so the converter alone would let a PK3 through.
                if (to.Context == EntityContext.Gen7b || !EntityConverter.IsConvertibleToFormat(source, to.Blank().Format))
                    return (null, null, "HOME cannot send Pokemon into this game.");
                if (source.IsEgg)
                    return (null, null, "An egg stays in its own game.");
                // HOME's screen for FireRed and LeafGreen: no held item, no hidden move (HM).
                if (source is PK3 && source.HeldItem != 0)
                    return (null, null, "HOME takes a FireRed or LeafGreen Pokemon only without a held item.");
                if (source is PK3 && source.Moves.Any(m => hiddenMoves.Contains(m)))
                    return (null, null, "HOME takes a FireRed or LeafGreen Pokemon only without an HM move.");
                if (!to.Table.IsPresentInGame(source.Species, source.Form))
                    return (null, null, source.Form == 0 ? $"{strings.specieslist[source.Species]} is not in that game."
                                                         : $"This form of {strings.specieslist[source.Species]} is not in that game.");
                pk = EntityConverter.ConvertToType(source, to.Blank().GetType(), out var result)
                     ?? throw new InvalidDataException($"PKHeX has no transfer route ({result}).");
                if (!emptyTracker && pk is IHomeTrack { HasTracker: false } home)
                    home.Tracker = MadeTracker(tracker);
                // The bank's owner receives it in the new game, as HOME hands it to the save it is moved into.
                if (pk is IHandlerUpdate handler)
                    handler.UpdateHandler(owner);
                else if (pk is PB8 pb8)
                    pb8.UpdateHandler(owner);
                pk.ResetPartyStats();
                pk.RefreshChecksum();
            }
            var la = new LegalityAnalysis(pk);
            // Sword/Shield's check wants a Pokemon from another game handled even by its own trainer.
            if (!Accepted(pk, la) && transfer && pk.CurrentHandler == 0)
            {
                pk.CurrentHandler = 1;
                pk.HandlingTrainerName = owner.OT;
                pk.HandlingTrainerGender = owner.Gender;
                if (pk is IHandlerLanguage language)
                    language.HandlingTrainerLanguage = (byte)owner.Language;
                pk.RefreshChecksum();
                var handled = new LegalityAnalysis(pk);
                if (Accepted(pk, handled))
                    la = handled;
                else
                    pk.CurrentHandler = 0;
            }
            // A move the new game lacks: HOME's games replace the moves, so the bank takes PKHeX's suggestion.
            if (!Accepted(pk, la) && transfer && la.Info.Moves.Any(m => !m.Valid))
            {
                Refit(pk, Wish.From(null));
                pk.RefreshChecksum();
                la = new LegalityAnalysis(pk);
            }
            return Accepted(pk, la) ? (pk, la, "") : (pk, la, Plain(la));
        }

        // A Pokemon file or a game save, each Pokemon in it as the bank would keep it (docs/gui.md, Importing). A
        // record of a game the bank holds stays as it is; any other goes through HOME's conversion.
        JsonObject Import(JsonObject request)
        {
            var data = Convert.FromBase64String((string)request["data"]!);
            var name = (string?)request["name"] ?? "";
            var found = new JsonArray();
            var reply = new JsonObject { ["pokemon"] = found };
            if (SaveUtil.TryGetSaveFile(data, out var sav, name))
            {
                // A GBA save does not say which of its pair it is; PKHeX guesses FireRed or Ruby.
                var version = sav switch
                {
                    SAV3FRLG => "FireRed/LeafGreen",
                    SAV3RS => "Ruby/Sapphire",
                    _ => GameInfo.GetVersionName(sav.Version),
                };
                reply["save"] = $"{version}, {sav.OT}";
                if (sav.HasParty)
                    for (var slot = 0; slot < sav.PartyCount; slot++)
                        if (sav.GetPartySlotAtIndex(slot) is { Species: not 0 } pk)
                            found.Add(Imported(request, pk, $"Party, slot {slot + 1}"));
                if (sav.HasBox)
                    for (var box = 0; box < sav.BoxCount; box++)
                    {
                        var title = sav is IBoxDetailNameRead named && named.GetBoxName(box) is { Length: > 0 } n
                            ? n : $"Box {box + 1}";
                        for (var slot = 0; slot < sav.BoxSlotCount; slot++)
                            if (sav.GetBoxSlotAtIndex(box, slot) is { Species: not 0 } pk)
                                found.Add(Imported(request, pk, $"{title}, slot {slot + 1}"));
                    }
            }
            else if (FileUtil.TryGetPKM(data, out var pk, Path.GetExtension(name)))
                found.Add(Imported(request, pk, ""));
            else
                throw new InvalidDataException("PKHeX reads neither a Pokemon nor a game save in this file.");
            return reply;
        }

        // `key` names the record as it sits in the file, so the app imports each one once.
        JsonObject Imported(JsonObject request, PKM source, string where)
        {
            var stored = new byte[source.SIZE_STORED];
            source.WriteDecryptedDataStored(stored);
            JsonObject reply;
            try
            {
                var (game, pk, la, notes) = Banked(request, source.Clone());
                reply = Describe(games[game], pk, la);
                reply["game"] = game;
                reply["notes"] = notes;
            }
            catch (InvalidDataException e)
            {
                reply = new JsonObject
                {
                    ["species"] = source.Species < strings.specieslist.Length ? strings.specieslist[source.Species] : "",
                    ["species_id"] = source.Species,
                    ["shiny"] = source.IsShiny,
                    ["refusal"] = e.Message,
                };
            }
            reply["key"] = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(stored));
            reply["where"] = where;
            reply["source"] = source.GetType().Name;
            return reply;
        }

        (string Game, PKM Pokemon, LegalityAnalysis Legality, JsonArray Notes) Banked(JsonObject request, PKM source)
        {
            if (!source.ChecksumValid)
                throw new InvalidDataException("The Pokemon checksum is invalid.");
            source.ResetPartyStats();
            source.RefreshChecksum();
            foreach (var (key, game) in games)
                if (source.GetType() == game.Blank().GetType())
                {
                    var la = new LegalityAnalysis(source);
                    return Accepted(source, la) ? (key, source, la, []) : throw new InvalidDataException(Plain(la));
                }
            // What HOME's way in takes off: the held item goes back to the bag, and Pal Park and Poke Transfer
            // refuse a Pokemon knowing an HM. The file is left as it is, so the item and moves stay in that game.
            var notes = new JsonArray();
            if (source.HeldItem != 0)
            {
                var items = strings.GetItemStrings(source.Context, source.Version);
                notes.Add($"Left its {(source.HeldItem < items.Length ? items[source.HeldItem] : $"item {source.HeldItem}")} behind");
                source.HeldItem = 0;
            }
            var hidden = source.Format switch { 3 => hiddenMoves, 4 => hiddenMoves4, _ => [] };
            if (source.Moves.Where(hidden.Contains).ToArray() is { Length: > 0 } forgotten)
            {
                source.SetMoves(source.Moves.Where(m => m != 0 && !hidden.Contains(m)).ToArray());
                source.FixMoves();
                notes.Add($"Forgot {string.Join(", ", forgotten.Select(m => strings.movelist[m]))}");
            }
            source.RefreshChecksum();
            // HOME's games replace moves a game lacks; a move its own game never allowed is no such move.
            if (new LegalityAnalysis(source) is { Valid: false } own)
                throw new InvalidDataException(Plain(own));
            var refusals = new List<string>();
            foreach (var key in new[] { "frlg", "sv", "swsh", "bdsp", "pla", "za" })
            {
                var tracker = (ulong)Random.Shared.NextInt64(1, long.MaxValue);
                var owner = Trainer(games[key], new JsonObject { ["trainer"] = request["trainers"]![key]!.DeepClone() }).Item2;
                var (pk, la, refusal) = Converted(source.Clone(), games[key], tracker, owner, true);
                if (pk is null || la is null || refusal.Length > 0)
                {
                    refusals.Add(refusal.Split('\n')[0]);
                    continue;
                }
                if (!pk.Moves.SequenceEqual(source.Moves))
                    notes.Add("New moves for its new game");
                return (key, pk, la, notes);
            }
            // A game HOME cannot reach or without the species says least; PKHeX's own reason says most.
            throw new InvalidDataException(
                refusals.FirstOrDefault(r => !r.StartsWith("HOME cannot send") && !r.EndsWith("not in that game."))
                ?? (refusals.Any(r => r.EndsWith("not in that game."))
                    ? $"{strings.specieslist[source.Species]} is in no game HOME can send it to."
                    : "HOME cannot send it into a game the bank holds."));
        }

        ulong Tracker(JsonObject request) => ulong.Parse((string?)request["tracker"] ?? "0");

        JsonObject Move(Game game, JsonObject request)
        {
            var from = games[(string)request["source"]!];
            var (pk, la, refusal) = Moved(from, game, Convert.FromBase64String((string)request["data"]!), Tracker(request),
                                          Trainer(game, request).Item2);
            if (pk is null || la is null || refusal.Length > 0)
                throw new InvalidDataException(refusal);
            return Describe(game, pk, la);
        }

        // Every game the banked Pokemon could go to, `game` being the one it is in now.
        JsonObject Destinations(Game game, JsonObject request)
        {
            var data = Convert.FromBase64String((string)request["data"]!);
            var tracker = Tracker(request);
            var reply = new JsonObject();
            foreach (var (key, to) in games)
            {
                string refusal, state = "";
                try
                {
                    var (pk, la, why) = Moved(game, to, data, tracker, Trainer(to, request).Item2);
                    refusal = why;
                    if (pk is not null && la is not null)
                        state = TrackerState(pk, la);
                }
                catch (Exception e)
                {
                    refusal = e.Message;
                }
                reply[key] = new JsonObject { ["ok"] = refusal.Length == 0, ["reason"] = refusal, ["home_tracker"] = state };
            }
            return new JsonObject { ["games"] = reply };
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
            var errorText = BattleTemplateParseErrorLocalization.Get(displayLanguage);
            // Whether a line holds the token in any language the parser reads (French writes "IVs : 0 Atq").
            static bool Names(string line, BattleTemplateToken token) => BattleTemplateLocalization.GetAll().Values
                .Any(l => l.Config.TryParse(line.Trim(), out _) == token);
            // A set is a run of lines between blank ones, as PKHeX's parser splits them.
            var blocks = new List<List<string>> { new() };
            foreach (var line in lines)
                if (!string.IsNullOrWhiteSpace(line))
                    blocks[^1].Add(line);
                else if (blocks[^1].Count > 0)
                    blocks.Add([]);
            foreach (var block in blocks.Where(b => b.Count > 0))
            {
                var set = ShowdownParsing.GetShowdownSets(block).Single();
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
                // A set that names no form takes the game's own: "Zorua" in Legends Arceus is the Hisuian one.
                var form = set.Form == 0 && set.FormName.Length == 0 ? FirstForm(game, species) ?? 0 : set.Form;
                if (!game.Table.IsPresentInGame(species, form))
                {
                    errors.Add(FirstForm(game, species) is not null
                        ? $"{name} has no {set.FormName} form in this game."
                        : $"{name} is not in this game.");
                    sets.Add(new JsonObject { ["species"] = name, ["errors"] = errors });
                    continue;
                }
                var detail = game.Table.GetFormEntry(species, form);
                var options = new JsonObject();
                if (form != 0)
                    options["form"] = form;
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
                // The parser fills an absent IVs line with 31s, which most wild catches cannot carry; a set names IVs to ask for them.
                if (block.Any(line => Names(line, BattleTemplateToken.IVs)))
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
                // Showdown leaves out a friendship of 255, its default; a set asks for one only by naming it, so an
                // event Pokemon whose friendship is fixed still builds from a set that does not.
                if (block.Any(line => Names(line, BattleTemplateToken.Friendship)))
                    options["friendship"] = set.Friendship;
                sets.Add(new JsonObject
                {
                    ["species"] = name,
                    ["species_id"] = species,
                    ["form"] = form == 0 ? "" : ShowdownParsing.GetStringFromForm(form, strings, species, game.Context),
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

        // PKHeX's Gen 3 event table (internal, read by name: pin the package before renaming it; the attribute keeps
        // it through trimming). Japanese distributions are left out: their names do not render on a European cartridge.
        [DynamicDependency(DynamicallyAccessedMemberTypes.PublicFields | DynamicallyAccessedMemberTypes.NonPublicFields,
            "PKHeX.Core.EncountersWC3", "PKHeX.Core")]
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
                throw new InvalidDataException($"PKHeX made an illegal {name}: {la.Report(displayLanguage)}");
            return new JsonObject
            {
                ["data"] = Convert.ToBase64String(game.Write(pk)),
                ["name"] = name, ["language"] = pk.Language,
                ["summary"] = $"{strings.specieslist[pk.Species]} Lv{pk.CurrentLevel} {strings.natures[(int)pk.Nature]}, "
                              + $"OT {pk.OriginalTrainerName} {pk.TID16:00000}, PID {pk.PID:X8}",
            };
        }

        // A game's Mystery Gift Pokemon in PKHeX's own event database, eggs left out, each under a key that names it
        // across PKHeX updates: its card, species, form and Tera type (one Mew card holds eighteen, one per type). Two
        // records under one key differ only in what the Pokemon does not carry, such as the card's revision.
        IEnumerable<(string Key, MysteryGift Gift)> GiftEvents(Game game)
        {
            MysteryGift[] table = game.Context switch
            {
                EntityContext.Gen7b => EncounterEvent.MGDB_G7GG,
                EntityContext.Gen8 => EncounterEvent.MGDB_G8,
                EntityContext.Gen8a => EncounterEvent.MGDB_G8A,
                EntityContext.Gen8b => EncounterEvent.MGDB_G8B,
                EntityContext.Gen9 => EncounterEvent.MGDB_G9,
                EntityContext.Gen9a => EncounterEvent.MGDB_G9A,
                _ => throw new ArgumentException("PKHeX has no Mystery Gift Pokemon for this game."),
            };
            var seen = new HashSet<string>();
            foreach (var gift in table.Where(g => g.IsEntity && !g.IsEgg))
            {
                var key = $"{gift.CardID:0000}-{gift.Species}-{gift.Form}"
                          + (gift is ITeraTypeReadOnly tera ? $"-{(int)tera.TeraType}" : "");
                if (seen.Add(key))
                    yield return (key, gift);
            }
        }

        // The day a card's distribution opened, where PKHeX holds it.
        static DateOnly? GiftDate(MysteryGift gift)
        {
            var window = default(DistributionWindow);
            var known = gift switch
            {
                WB7 g => EncounterServerDate.GetDistributionWindow(g, out window),
                WC8 g => EncounterServerDate.GetDistributionWindow(g, out window),
                WA8 g => EncounterServerDate.GetDistributionWindow(g, out window),
                WB8 g => EncounterServerDate.GetDistributionWindow(g, out window),
                WC9 g => EncounterServerDate.GetDistributionWindow(g, out window),
                WA9 g => EncounterServerDate.GetDistributionWindow(g, out window),
                _ => false,
            };
            return known && window.Start.Year > 1 ? window.Start : null;
        }

        // The game's Mystery Gift Pokemon, newest first, each made as the request's trainer would receive it: its OT and
        // language when the card fixes them, what it holds, knows and is caught in, whether the copy is legal, and its HOME
        // tracker under the app's setting (MendGift).
        JsonObject GiftEventList(Game game, JsonObject request)
        {
            var (versions, trainer) = Trainer(game, request);
            var items = strings.GetItemStrings(game.Context, versions[0]);
            var list = new List<(DateOnly? Date, JsonObject Entry)>();
            foreach (var (key, gift) in GiftEvents(game))
            {
                var (pk, la) = MakeGift(gift, versions, trainer);
                (pk, la, var refused) = InTrainerLanguage(gift, pk, la, trainer);
                var moves = new JsonArray();
                foreach (var move in pk.Moves)
                    if (move != 0)
                        moves.Add(strings.movelist[move]);
                var date = GiftDate(gift);
                list.Add((date, new JsonObject
                {
                    ["key"] = key, ["card_id"] = gift.CardID, ["title"] = gift.CardTitle.Trim(),
                    ["date"] = date?.ToString("yyyy-MM-dd") ?? "",
                    ["species"] = strings.specieslist[gift.Species], ["species_id"] = gift.Species,
                    ["form"] = gift.Form == 0 ? "" : ShowdownParsing.GetStringFromForm(gift.Form, strings, gift.Species, game.Context),
                    ["form_id"] = gift.Form,
                    ["level"] = pk.CurrentLevel,
                    // Never, may be (rolled like a wild one) or always.
                    ["shiny"] = gift.Shiny switch
                    {
                        Shiny.Never => "never", Shiny.Random => "random",
                        Shiny.FixedValue => pk.IsShiny ? "always" : "never", _ => "always",
                    },
                    ["tera"] = gift is ITeraTypeReadOnly tera ? strings.types[(int)tera.TeraType] : "",
                    ["ot"] = YourOT(pk, trainer) ? "" : pk.OriginalTrainerName,
                    ["language"] = pk.Language == trainer.Language ? 0 : pk.Language,
                    ["ball"] = strings.balllist[pk.Ball],
                    ["held_item"] = pk.HeldItem == 0 ? "" : items[pk.HeldItem],
                    ["moves"] = moves,
                    ["legal"] = Accepted(pk, la) && refused.Length == 0,
                    ["refused"] = refused,
                    ["home_tracker"] = TrackerState(pk, la),
                }));
            }
            return new JsonObject
            {
                ["events"] = new JsonArray(list.OrderByDescending(e => e.Date ?? DateOnly.MinValue)
                    .Select(e => (JsonNode?)e.Entry).ToArray()),
            };
        }

        // A fresh copy of one of the game's Mystery Gift Pokemon, as the request's trainer receives it, for a trade to pass
        // on (docs/gift_simulated.md), legal under the app's HOME tracker setting (MendGift). `refused` says why no save
        // like the trainer's received a card that gives the receiver's own trainer, "" when one did: the copy names that
        // save as its OT, so it must be one the card reached, on the save's version when made for it alone
        // ("only_version", ReachedVersion) and in its language (InTrainerLanguage). A card with its own trainer is never
        // refused: its copy is a traded Pokemon, which any save may hold.
        JsonObject GiftEvent(Game game, JsonObject request)
        {
            var key = (string)request["key"]!;
            var gift = GiftEvents(game).FirstOrDefault(e => e.Key == key).Gift
                       ?? throw new ArgumentException($"PKHeX has no Mystery Gift Pokemon {key} for this game.");
            var (versions, trainer) = Trainer(game, request);
            var (pk, la) = MakeGift(gift, versions, trainer);
            var refused = "";
            if (YourOT(pk, trainer))
            {
                if (versions.Length < game.Versions.Length && !ReachedVersion(gift, versions[0]))
                    refused = NeverTo(gift, game.Versions.Where(version => ReachedVersion(gift, version)), versions[0]);
                else if (Accepted(pk, la))
                    (pk, la, refused) = InTrainerLanguage(gift, pk, la, trainer);
                else if (game.Versions.Except(versions).Where(version => MakeGift(gift, [version], trainer) is var made && Accepted(made.Pokemon, made.Legality))
                             .ToArray() is { Length: > 0 } elsewhere)
                    refused = NeverTo(gift, elsewhere, versions[0]);
            }
            if (!Accepted(pk, la) && refused.Length == 0)
                throw new InvalidDataException($"PKHeX made an illegal {strings.specieslist[gift.Species]} from card "
                                               + $"{gift.CardID}: {Plain(la).Replace("\n", " ")}");
            var reply = Describe(game, pk, la);
            reply["key"] = key;
            reply["title"] = gift.CardTitle.Trim();
            // A copy legal only with a handler cannot go to its own trainer: that save clears the handler as it receives
            // it (docs/sv.md, What a trade rewrites), and PKHeX then refuses it (HOME's starters on Scarlet/Violet, Z-A).
            reply["handled"] = YourOT(pk, trainer) && pk.CurrentHandler == 1;
            reply["your_ot"] = YourOT(pk, trainer) && pk.CurrentHandler == 0;
            reply["refused"] = refused;
            return reply;
        }

        // A card that gives the receiver's own trainer, not one of its own: the copy carries the trainer it was made for.
        static bool YourOT(PKM pk, ITrainerInfo trainer) => pk.OriginalTrainerName == trainer.OT && pk.TID16 == trainer.TID16;

        // Whether saves of `version` received the card. HOME's (cards 9000 on) reached either version's saves, whatever
        // origin they fix. Any other card that fixes the Pokemon's origin reached that version's alone (Scarlet/Violet's
        // card 1540: Violet a Koraidon, Scarlet a Miraidon); otherwise its own restriction says (PKHeX's
        // CanBeReceivedByVersion): Scarlet/Violet's RestrictVersion (1 Scarlet, 2 Violet), Let's Go's IRestrictVersion.
        static bool ReachedVersion(MysteryGift gift, GameVersion version) => gift switch
        {
            { CardID: >= 9000 } => true,
            WC9 { OriginGame: not 0 } card => (GameVersion)card.OriginGame == version,
            WB8 { OriginGame: not 0 } card => (GameVersion)card.OriginGame == version,
            WC9 { RestrictVersion: 1 } => version == GameVersion.SL,
            WC9 { RestrictVersion: 2 } => version == GameVersion.VL,
            IRestrictVersion restricted => restricted.CanBeReceivedByVersion(version),
            _ => true,
        };

        static string NeverTo(MysteryGift gift, IEnumerable<GameVersion> reached, GameVersion version) =>
            $"card {gift.CardID} gave it to {string.Join(" and ", reached.Select(VersionName))} alone, never to "
            + VersionName(version);

        // A card that gives the receiver's own trainer reaches a save in that trainer's language, and the copy is in it.
        // Where the card fixes another (Let's Go's Chinese Meltan and Melmetal, cards 1501 and 1502), the copy in the
        // trainer's language is checked: legal, it is the copy; refused, no save in that language received the card, and
        // -> why, with the copy as the card makes it. A card with its own trainer keeps its language, whoever receives it.
        (PKM Pokemon, LegalityAnalysis Legality, string Refused) InTrainerLanguage(MysteryGift gift, PKM pk,
            LegalityAnalysis la, ITrainerInfo trainer)
        {
            if (!Accepted(pk, la) || !YourOT(pk, trainer) || pk.Language == trainer.Language)
                return (pk, la, "");
            var copy = pk.Clone();
            copy.Language = trainer.Language;
            if (!copy.IsNicknamed)
                copy.ClearNickname();
            var checkedCopy = Refresh(copy);
            return Accepted(copy, checkedCopy)
                ? (copy, checkedCopy, "")
                : (pk, la, $"card {gift.CardID} gave it in {LanguageName(pk.Language)} alone, never to a save in "
                           + LanguageName(trainer.Language));
        }

        static string LanguageName(int language) => language switch
        {
            1 => "Japanese", 2 => "English", 3 => "French", 4 => "Italian", 5 => "German", 7 => "Spanish", 8 => "Korean",
            9 => "Simplified Chinese", 10 => "Traditional Chinese", 11 => "Latin American Spanish",
            _ => $"language {language}",
        };

        static string VersionName(GameVersion version) => version switch
        {
            GameVersion.GP => "Let's Go Pikachu", GameVersion.GE => "Let's Go Eevee", GameVersion.BD => "Brilliant Diamond",
            GameVersion.SP => "Shining Pearl", GameVersion.PLA => "Legends Arceus", GameVersion.SL => "Scarlet",
            GameVersion.VL => "Violet", GameVersion.ZA => "Legends Z-A", _ => version.ToString(),
        };

        // A gift made on each of the game's versions in turn (some cards come to one version only), rolled again where its
        // own check refuses a PID. The first legal copy is kept.
        (PKM Pokemon, LegalityAnalysis Legality) MakeGift(MysteryGift gift, GameVersion[] versions, ITrainerInfo trainer)
        {
            PKM? pk = null;
            LegalityAnalysis? la = null;
            foreach (var version in versions)
            {
                var receiver = new SimpleTrainerInfo(version)
                {
                    OT = trainer.OT, TID16 = trainer.TID16, SID16 = trainer.SID16,
                    Language = trainer.Language, Gender = trainer.Gender,
                };
                for (var roll = 0; roll < 8; roll++)
                {
                    pk = gift.ConvertToPKM(receiver, EncounterCriteria.Unrestricted);
                    SetHomeIVs(gift, pk);
                    la = MendGift(pk, receiver);
                    if (Accepted(pk, la))
                        return (pk, la);
                }
            }
            return (pk!, la!);
        }

        // HOME's Legends Z-A starters (cards 9031-9033) have three perfect IVs and 20 in the rest, as PKHeX's check expects
        // [WA9.HomeBaseIV]; PKHeX 26.8.26 makes them with one perfect IV and the rest at 0.
        static void SetHomeIVs(MysteryGift gift, PKM pk)
        {
            if (gift is not WA9 { IsHOMEGift: true, HomeBaseIV: > 0, FlawlessIVCount: > 0 } card ||
                pk.FlawlessIVCount == card.FlawlessIVCount)
                return;
            var ivs = Enumerable.Repeat(card.HomeBaseIV, 6).ToArray();
            foreach (var i in Enumerable.Range(0, 6).OrderBy(_ => Random.Shared.Next()).Take(card.FlawlessIVCount))
                ivs[i] = 31;
            pk.SetIVs(ivs);
        }

        // What the save that received a gift sets on it: a handler for one that arrives already handled, and the HOME
        // tracker of a gift HOME gave, which the "empty" setting leaves unset and "made" fills (docs/gui.md, The bank).
        // Unlike Mend, the event's own moves stay.
        LegalityAnalysis MendGift(PKM pk, ITrainerInfo trainer)
        {
            var la = Refresh(pk);
            if (!Accepted(pk, la) && !OnlyTrackerMissing(la) && pk.HandlingTrainerName.Length == 0)
            {
                pk.CurrentHandler = 1;
                pk.HandlingTrainerName = "POKELDN";
                pk.HandlingTrainerGender = 0;
                if (pk is IHandlerLanguage language)
                    language.HandlingTrainerLanguage = (byte)trainer.Language;
                la = Refresh(pk);
            }
            if (!Accepted(pk, la) && OnlyTrackerMissing(la) && pk is IHomeTrack { HasTracker: false } home)
            {
                home.Tracker = MadeTracker((ulong)Random.Shared.NextInt64(1, long.MaxValue));
                HomeSeen(pk);
                la = Refresh(pk);
            }
            return la;
        }

        // What HOME changes on a Pokemon it has seen, which PKHeX's check expects of one with a tracker: a Gen 9 Pokemon's
        // height copied from its scale (Legends Z-A's weight too), a Legends Z-A Alpha marked [HomeQuirks,
        // MiscScaleVerifier, MiscVerifierPA9].
        static void HomeSeen(PKM pk)
        {
            switch (pk)
            {
                case PK9 sv:
                    sv.HeightScalar = sv.Scale;
                    break;
                case PA9 za:
                    za.HeightScalar = za.WeightScalar = za.Scale;
                    if (za.IsAlpha)
                        za.RibbonMarkAlpha = true;
                    break;
            }
        }

        // The items a Sword/Shield gift may give or a gifted Pokemon may hold; the GUI lists the same set.
        static IReadOnlySet<ushort> GiftItems() => ItemStorage8SWSH.GetAllHeld().ToHashSet();

        // A Gigantamax form: the species Max Soup changes (Gigantamax.CanToggle) and Melmetal, whose factor came only from
        // Pokemon GO. The factor stays through evolution: Sword's card 1641 gave it to a Bulbasaur for its Venusaur.
        static bool CanGigantamax(ushort species, byte form) =>
            species == (ushort)PKHeX.Core.Species.Melmetal || Gigantamax.CanToggle(species, form) ||
            EvolutionTree.Evolves8.Forward.GetEvolutions(species, form).Any(e => Gigantamax.CanToggle(e.Species, e.Form));

        static IReadOnlySet<ushort> RaidRewardItems()
        {
            InventoryType[] pouches = [InventoryType.Items, InventoryType.TMHMs, InventoryType.Medicine, InventoryType.Berries,
                                       InventoryType.Balls, InventoryType.BattleItems, InventoryType.Treasure,
                                       InventoryType.Ingredients, InventoryType.Candy];
            var storage = ItemStorage9SV.Instance;
            return pouches.SelectMany(p => storage.GetItems(p).ToArray().Where(i => storage.IsLegal(p, i, 1))).ToHashSet();
        }

        JsonObject Gift(byte[] data)
        {
            if (data.Length != WC8.Size)
                throw new InvalidDataException("A WC8 record must contain 720 bytes.");
            var card = new WC8(data);
            var held = GiftItems();
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
                if (data[0x24B] > 1 || (data[0x24B] == 1 && !CanGigantamax(card.Species, card.Form)))
                    throw new InvalidDataException("Neither this species nor its evolutions have a Gigantamax form.");
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

        // A FireRed/LeafGreen save: its trainer, party and box contents. Sector checksums are checked by
        // pokeldn.frlg.save.sav, the same test the game runs at load; PKHeX's own note is reported beside it.
        SAV3FRLG LoadSave(JsonObject request)
        {
            var data = Convert.FromBase64String((string)request["data"]!);
            return SaveUtil.GetSaveFile(new Memory<byte>(data), "") as SAV3FRLG
                   ?? throw new InvalidDataException("This is not a FireRed or LeafGreen save PKHeX can read.");
        }

        JsonObject SaveRead(Game game, JsonObject request)
        {
            var sav = LoadSave(request);
            var party = new JsonArray();
            foreach (var pk in sav.PartyData)
                party.Add(Describe(game, pk, new LegalityAnalysis(pk)));
            var boxes = new JsonArray();
            for (var b = 0; b < sav.BoxCount; b++)
            {
                var mons = new JsonArray();
                var slots = sav.GetBoxData(b);
                for (var i = 0; i < slots.Length; i++)
                    if (slots[i].Species != 0)
                        mons.Add(new JsonObject { ["slot"] = i, ["species_id"] = slots[i].Species,
                                                  ["species"] = strings.specieslist[slots[i].Species],
                                                  ["level"] = slots[i].CurrentLevel, ["shiny"] = slots[i].IsShiny,
                                                  ["egg"] = slots[i].IsEgg, ["nickname"] = slots[i].Nickname });
                boxes.Add(new JsonObject { ["name"] = sav.GetBoxName(b), ["mons"] = mons });
            }
            return new JsonObject
            {
                ["name"] = sav.OT, ["gender"] = sav.Gender, ["trainer_id"] = sav.DisplayTID,
                ["secret_id"] = sav.DisplaySID, ["hours"] = sav.PlayedHours, ["minutes"] = sav.PlayedMinutes,
                ["money"] = sav.Money, ["coins"] = sav.Coin, ["max_money"] = sav.MaxMoney,
                ["max_coins"] = sav.MaxCoins, ["badges"] = System.Numerics.BitOperations.PopCount((uint)sav.Badges),
                ["seen"] = sav.SeenCount, ["caught"] = sav.CaughtCount, ["japanese"] = sav.Japanese,
                ["checksum_note"] = sav.ChecksumsValid ? "" : sav.ChecksumInfo.Trim(),
                ["party"] = party, ["boxes"] = boxes,
            };
        }

        // One box's Pokemon with PKHeX's legality verdict: seconds for a full box, so the app asks per box.
        JsonObject SaveBox(Game game, JsonObject request)
        {
            var sav = LoadSave(request);
            var mons = new JsonArray();
            foreach (var pk in sav.GetBoxData((int)request["box"]!))
                mons.Add(pk.Species == 0 ? null : Describe(game, pk, new LegalityAnalysis(pk)));
            return new JsonObject { ["mons"] = mons };
        }

        // Trainer fields, then the party as listed: {"keep": n} for the save's own slot n, {"data": PK3} for a
        // Pokemon the app built. Written back through PKHeX, which recomputes every sector checksum.
        JsonObject SaveEdit(Game game, JsonObject request)
        {
            var sav = LoadSave(request);
            if (request["trainer"] is JsonObject trainer)
                foreach (var (name, value) in trainer)
                    switch (name)
                    {
                        case "name":
                            var ot = ((string)value!).Trim();
                            if (ot.Length == 0 || ot.Length > (sav.Japanese ? 5 : 7))
                                throw new ArgumentException($"A trainer name is 1 to {(sav.Japanese ? 5 : 7)} characters.");
                            sav.OT = ot;
                            break;
                        case "gender": sav.Gender = checked((byte)(int)value!); break;
                        case "money": sav.Money = Math.Min(checked((uint)(long)value!), (uint)sav.MaxMoney); break;
                        case "coins": sav.Coin = Math.Min(checked((uint)(long)value!), (uint)sav.MaxCoins); break;
                        default: throw new ArgumentException($"Unsupported edit {name}.");
                    }
            if (request["party"] is JsonArray wanted)
            {
                var old = sav.PartyData;
                var party = new List<PKM>();
                foreach (var slot in wanted)
                {
                    if (slot is not JsonObject o)
                        continue;
                    if (o["keep"] is { } keep)
                        party.Add(old[(int)keep]);
                    else
                    {
                        var pk = EntityFormat.GetFromBytes(Convert.FromBase64String((string)o["data"]!), EntityContext.Gen3) as PK3
                                 ?? throw new InvalidDataException("A party Pokemon is not a Gen 3 Pokemon.");
                        if (!pk.ChecksumValid)
                            throw new InvalidDataException("A party Pokemon's checksum is invalid.");
                        pk.ResetPartyStats();
                        party.Add(pk);
                    }
                }
                if (party.Count is 0 or > 6)
                    throw new ArgumentException("A party holds one to six Pokemon.");
                sav.PartyData = party;
            }
            var reply = SaveRead(game, new JsonObject { ["data"] = Convert.ToBase64String(sav.Write(default).Span) });
            reply["data"] = Convert.ToBase64String(sav.Write(default).Span);
            return reply;
        }

        JsonObject Describe(Game game, PKM pk, LegalityAnalysis la)
        {
            var accepted = Accepted(pk, la);
            var moves = new JsonArray();
            foreach (var move in pk.Moves)
                if (move != 0)
                    moves.Add(strings.movelist[move]);
            var result = new JsonObject
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
                ["is_nicknamed"] = pk.IsNicknamed,
                ["ot"] = pk.OriginalTrainerName,
                ["ot_gender"] = pk.OriginalTrainerGender,
                ["trainer_id"] = pk.DisplayTID,
                ["secret_id"] = pk.DisplaySID,
                ["nature"] = strings.natures[(int)pk.StatAlignment],
                ["ball"] = strings.balllist[pk.Ball],
                ["ability"] = game.Context == EntityContext.Gen9a ? "" : strings.abilitylist[pk.Ability],
                ["held_item"] = pk.HeldItem == 0 ? "" : strings.GetItemStrings(game.Context, game.Versions[0])[pk.HeldItem],
                ["held_item_id"] = pk.HeldItem,
                ["moves"] = moves,
                ["move_ids"] = new JsonArray(pk.Moves.Where(m => m != 0).Select(m => (JsonNode?)(int)m).ToArray()),
                ["pid"] = pk.PID,
                ["encryption_constant"] = pk.EncryptionConstant,
                ["tracker"] = (pk is IHomeTrack home ? home.Tracker : 0).ToString(),
                ["encounter"] = la.EncounterOriginal.LongName,
                ["parsed"] = la.Parsed,
                ["home_tracker"] = TrackerState(pk, la),
                ["legal"] = accepted,
                ["report"] = la.Report(displayLanguage),
                ["problems"] = accepted ? "" : Plain(la),
            };
            if (displayLanguage != "en")
            {
                // Persisted summaries and peer metadata retain the same English names as before.
                var english = GameInfo.GetStrings("en");
                result["canonical"] = new JsonObject
                {
                    ["species"] = english.specieslist[pk.Species],
                    ["form"] = pk.Form == 0 ? "" : ShowdownParsing.GetStringFromForm(pk.Form, english, pk.Species, pk.Context),
                    ["nature"] = english.natures[(int)pk.StatAlignment],
                    ["ball"] = english.balllist[pk.Ball],
                    ["ability"] = game.Context == EntityContext.Gen9a ? "" : english.abilitylist[pk.Ability],
                    ["held_item"] = pk.HeldItem == 0 ? "" : english.GetItemStrings(game.Context, game.Versions[0])[pk.HeldItem],
                    ["moves"] = new JsonArray(pk.Moves.Where(m => m != 0).Select(m => (JsonNode?)english.movelist[m]).ToArray()),
                    ["encounter"] = la.EncounterOriginal.LongName,
                };
            }
            return result;
        }

        // "made" for a tracker this request filled, "empty" for one PKHeX wants and the record lacks.
        string TrackerState(PKM pk, LegalityAnalysis la)
            => pk is IHomeTrack { HasTracker: true } home && madeTrackers.Contains(home.Tracker) ? "made"
               : la.Results.Any(r => r.Result == LegalityCheckResultCode.TransferTrackerMissing) ? "empty"
               : "";

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

    }
}

// The offer options a request asks for; a stat array is HP, Atk, Def, SpA, SpD, Spe and -1 leaves a stat alone.
record Wish(Nature? Nature, int? Ability, Gender? Gender, int[] IVs, int[] Effort, int? Item, byte? Ball,
            byte? Form, byte? Friendship, ushort[] Moves)
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
        if (Number("friendship") is < 0 or > 255)
            throw new ArgumentException("Friendship is at most 255.");
        ushort[] moves = o?["moves"] is JsonArray list
            ? [.. list.Select(m => checked((ushort)(int)m!)).Where(m => m != 0).Distinct()] : [];
        if (moves.Length > 4)
            throw new ArgumentException("A Pokemon knows at most four moves.");
        return new Wish(Number("nature") is { } n ? (Nature)n : null, Number("ability"),
            Number("gender") is { } g ? (Gender)g : null, ivs, effort,
            Number("held_item"), Number("ball") is { } b ? checked((byte)b) : null,
            Number("form") is { } f ? checked((byte)f) : null, (byte?)Number("friendship"), moves);
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
        // The original trainer's: a console whose player is not the original trainer writes its handler's
        // as the species' base friendship (docs/architecture.md, Offer options).
        if (Friendship is { } friendship)
            pk.OriginalTrainerFriendship = friendship;
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
        if (Friendship is { } friendship && pk.OriginalTrainerFriendship != friendship)
            return $"friendship {friendship}";
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
