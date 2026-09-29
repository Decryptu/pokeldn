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
    string? firstProblem = null;
    // The first encounter that stays legal with the requested level, shininess and nickname wins.
    foreach (var encounter in EncounterMovesetGenerator.GenerateEncounters(blank, trainer, ReadOnlyMemory<ushort>.Empty, versions).Take(80))
    {
        if (encounter is not IEncounterConvertible convertible)
            continue;
        var pk = convertible.ConvertToPKM(trainer);
        if (pk.GetType() != blank.GetType() || !new LegalityAnalysis(pk).Valid)
            continue;
        // An egg or a pre-evolution encounter is evolved into the species asked for.
        if (pk.Species != species)
        {
            pk.Species = species;
            pk.ClearNickname();
        }
        if (level > 0 && level < pk.CurrentLevel)
            continue;
        if (level > pk.CurrentLevel)
            pk.CurrentLevel = (byte)Math.Min(level, 100);
        pk.SetIsShiny(shiny);
        if (nickname.Length > 0)
            pk.SetNickname(nickname);
        if (pk is PB7 pb7)
        {
            AwakeningUtil.SetSuggestedAwakenedValues(pb7, pb7);
            pb7.ResetCalculatedValues();
        }
        pk.ResetPartyStats();
        pk.RefreshChecksum();
        var la = new LegalityAnalysis(pk);
        if (la.Valid)
            return Describe(game, pk, la);
        firstProblem ??= la.Report();
    }
    var name = strings.specieslist[species];
    throw new InvalidOperationException(firstProblem is null
        ? $"PKHeX has no legal {name} for this game."
        : $"No legal {name} with these choices. {firstProblem}");
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
