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
            "make" => Make(game, request),
            "check" => Check(game, Convert.FromBase64String((string)request["data"]!), request),
            "gift" => Gift(Convert.FromBase64String((string)request["data"]!)),
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
        case "balls":
            for (var b = 1; b <= blank.MaxBallID; b++)
                Add(b, strings.balllist[b]);
            break;
        default:
            throw new ArgumentException($"unknown list {list}");
    }
    return new JsonObject { ["names"] = names };
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
    var t = request["trainer"]!.AsObject();
    var versions = game.Versions;
    if ((string?)request["version"] is { Length: > 0 } v)
    {
        if (!Enum.TryParse<GameVersion>(v, out var chosen) || !versions.Contains(chosen))
            throw new ArgumentException("This version is incompatible with the selected game.");
        versions = [chosen, .. versions.Where(x => x != chosen)];
    }
    var trainer = new SimpleTrainerInfo(versions[0])
    {
        OT = (string)t["ot"]!, TID16 = checked((ushort)(int)t["tid"]!), SID16 = checked((ushort)(int)t["sid"]!),
        Language = (int)t["language"]!, Gender = (byte)(int)t["gender"]!,
    };
    var blank = game.Blank();
    blank.Species = species;
    // Encounters are matched on the blank's gender: a female-only Vespiquen comes only from a female Combee.
    var detail = game.Table[species];
    var gender = detail.OnlyFemale ? Gender.Female : detail.OnlyMale ? Gender.Male : Gender.Random;
    if (gender != Gender.Random)
        blank.Gender = (byte)gender;
    string? firstProblem = null;
    var lowest = int.MaxValue;
    var shinyLocked = false;
    // The first encounter that stays legal with the requested level, shininess and nickname wins.
    // The first pass takes encounters as they come; the second lets an evolved Pokemon climb to its evolution level.
    foreach (var climb in new[] { false, true })
    {
        foreach (var encounter in EncounterMovesetGenerator.GenerateEncounters(blank, trainer, ReadOnlyMemory<ushort>.Empty, versions).Take(80))
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
            var criteria = EncounterCriteria.Unrestricted with { Gender = gender };
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
                if (built.Form >= detail.FormCount)
                    built.Form = 0;
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
                if (shiny && !pk.IsShiny)
                    pk.SetIsShiny(true);
                if (nickname.Length > 0)
                    pk.SetNickname(nickname);
                var la = Mend(pk, evolved, encounter, trainer);
                if (la.Valid)
                    return Describe(game, pk, la);
                firstProblem ??= la.Report();
            }
        }
    }
    var name = strings.specieslist[species];
    throw new InvalidOperationException(firstProblem is not null
        ? $"No legal {name} with these choices. {firstProblem}"
        : lowest != int.MaxValue
            ? $"{name} cannot be lower than level {lowest} in this game."
            : shinyLocked
                ? $"{name} cannot be shiny in this game."
                : $"PKHeX has no legal {name} for this game.");
}

// Repairs a built record one step at a time, each step on top of the last, and stops at the first that is legal.
LegalityAnalysis Mend(PKM pk, bool evolved, IEncounterTemplate encounter, ITrainerInfo trainer)
{
    var la = Refresh(pk);
    if (la.Valid)
        return la;
    var repairs = new List<Action>();
    // Event Pokemon that Sword/Shield received only through HOME (Zeraora, Melmetal) carry a HOME tracker.
    // This comes first: a refit would replace the event's fixed moves.
    if (encounter is MysteryGift && pk is IHomeTrack { HasTracker: false } home)
        repairs.Add(() => home.Tracker = (ulong)Random.Shared.NextInt64(1, long.MaxValue));
    // Moves, relearn moves and move flags depend on the species and level just set.
    repairs.Add(() => Refit(pk));
    if (evolved)
        // The ability keeps its slot but names the species it was caught as.
        repairs.Add(() => { pk.RefreshAbility(pk.AbilityNumber >> 1 & 3); Refit(pk); });
    if (pk.HandlingTrainerName.Length == 0)
        repairs.Add(() =>
        {
            // A trade evolution has been through a trade, and some gifts (Z-A's Magearna) arrive already handled.
            pk.CurrentHandler = 1;
            pk.HandlingTrainerName = "PkCamp";
            pk.HandlingTrainerGender = (byte)(1 - trainer.Gender);
            if (pk is IHandlerLanguage language)
                language.HandlingTrainerLanguage = (byte)trainer.Language;
            Refit(pk);
        });
    if (evolved)
    {
        // Evolutions that count something (critical hits, damage taken, Rage Fist uses, coins) start from that count.
        if (FormArgumentUtil.GetFormArgumentMinEvolution(pk.Species, encounter.Species) is var counted and not 0)
            repairs.Add(() => { FormArgumentUtil.ChangeFormArgument(pk, counted); Refit(pk); });
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
        la = Refresh(pk);
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

LegalityAnalysis Refresh(PKM pk)
{
    if (pk is PB7 pb7)
    {
        AwakeningUtil.SetSuggestedAwakenedValues(pb7, pb7);
        pb7.ResetCalculatedValues();
    }
    pk.ResetPartyStats();
    pk.RefreshChecksum();
    return new LegalityAnalysis(pk);
}

void Refit(PKM pk)
{
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
    if ((bool?)request["fresh"] == true)
    {
        var xor = (pk.PID >> 16) ^ (pk.PID & 0xFFFF);
        var high = (uint)Random.Shared.Next(0x10000);
        pk.PID = (high << 16) | (high ^ xor);
        pk.EncryptionConstant = (uint)Random.Shared.NextInt64(1, 1L << 32);
    }
    pk.ResetPartyStats();
    pk.RefreshChecksum();
    // A box record carries no party stats; the receiving console computes them, so do the same.
    if (pk is PB7 pb7)
    {
        pb7.ResetPartyStats();
        pb7.ResetCalculatedValues();
    }
    return Describe(game, pk, new LegalityAnalysis(pk));
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
        if (data[0x243] > 2 || (data[0x246] > 24 && data[0x246] != 255) ||
            data[0x247] > 4 || data[0x248] > 4 || data[0x24A] > 10)
            throw new InvalidDataException("Invalid gift gender, nature, ability, shininess or Dynamax level.");
    }
    else if (card.IsItem)
    {
        for (var i = 0; i < 6; i++)
            if (!ValidItem(card.GetItem(i)) || (card.GetItem(i) != 0 && card.GetQuantity(i) is < 1 or > 999))
                throw new InvalidDataException("Invalid gift item or quantity; bag items only, up to 999.");
    }
    else if (card.CardType != WC8.GiftType.BP)
        throw new InvalidDataException("Supported WC8 gifts are Pokemon, bag items and BP.");
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
        ["level"] = pk.CurrentLevel,
        ["shiny"] = pk.IsShiny,
        ["nickname"] = pk.Nickname,
        ["ot"] = pk.OriginalTrainerName,
        ["nature"] = strings.natures[(int)pk.Nature],
        ["ball"] = strings.balllist[pk.Ball],
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

record Game(GameVersion[] Versions, IPersonalTable Table, EntityContext Context, Func<PKM> Blank,
            Func<PKM, byte[]> Write);
