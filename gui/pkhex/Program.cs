// PKHeX.Core for the app: one JSON request per line on stdin, one JSON reply per line on stdout.
//   {"cmd":"species","game":"bdsp"}
//   {"cmd":"names","game":"swsh","list":"moves"}          species, moves, items or balls
//   {"cmd":"make","game":"bdsp","species":25,"level":30,"shiny":true,"nickname":"","trainer":{...}}
//   {"cmd":"check","game":"bdsp","data":"<base64>"}
// Bytes go out in the form each launcher reads: see Games below.
using System.Text.Json.Nodes;
using PKHeX.Core;
using static PKHeX.Core.GameVersion;

var strings = GameInfo.GetStrings("en");
var games = new Dictionary<string, Game>
{
    ["frlg"] = new([FR, LG, E, R, S], PersonalTable.FR, EntityContext.Gen3, () => new PK3(), DecryptedParty),
    // Let's Go trades the 232-byte encrypted box structure, the first 0xE8 bytes of a PB7.
    ["lgpe"] = new([GP, GE], PersonalTable.GG, EntityContext.Gen7b, () => new PB7(), pk => EncryptedStored(pk)[..0xE8]),
    ["bdsp"] = new([BD, SP], PersonalTable.BDSP, EntityContext.Gen8b, () => new PB8(), EncryptedStored),
    ["swsh"] = new([SW, SH], PersonalTable.SWSH, EntityContext.Gen8, () => new PK8(), EncryptedStored),
    ["pla"] = new([PLA], PersonalTable.LA, EntityContext.Gen8a, () => new PA8(), EncryptedStored),
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
            "check" => Check(game, Convert.FromBase64String((string)request["data"]!)),
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
    var species = (ushort)(int)request["species"]!;
    var level = (int?)request["level"] ?? 0;
    var shiny = (bool?)request["shiny"] ?? false;
    var nickname = (string?)request["nickname"] ?? "";
    var t = request["trainer"]!.AsObject();
    var versions = game.Versions;
    if ((string?)request["version"] is { } v && Enum.TryParse<GameVersion>(v, out var chosen))
        versions = [chosen, .. versions.Where(x => x != chosen)];
    var trainer = new SimpleTrainerInfo(versions[0])
    {
        OT = (string)t["ot"]!, TID16 = (ushort)(int)t["tid"]!, SID16 = (ushort)(int)t["sid"]!,
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
        if (level > pk.CurrentLevel)
            pk.CurrentLevel = (byte)Math.Min(level, 100);
        if (shiny)
            pk.SetIsShiny(true);
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

JsonObject Check(Game game, byte[] data)
{
    if (game.Context == EntityContext.Gen7b && data.Length < 0x104)
        data = [.. data, .. new byte[0x104 - data.Length]];
    var pk = EntityFormat.GetFromBytes(data, game.Context)
             ?? throw new InvalidDataException($"{data.Length} bytes are not a Pokemon of this game.");
    // A box record carries no party stats; the receiving console computes them, so do the same.
    if (pk is PB7 pb7)
    {
        pb7.ResetPartyStats();
        pb7.ResetCalculatedValues();
    }
    return Describe(game, pk, new LegalityAnalysis(pk));
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
