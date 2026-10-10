using System.Text.Json.Nodes;

// The raid finder's seed scan (pokeldn.sv.raid_scan packs the request): each seed's encounter, its boss
// up to the nature, the score, every filter and the rewards, over every core. It names the seeds
// pokeldn.sv.raid_search keeps, which then makes their raids in Python (docs/sv_raid.md, Finding a seed).
static class RaidScan
{
    const long NoMatch = long.MaxValue;
    const long Visit = -1;                  // a seed whose table has no encounter
    const long ScoreLimit = 1L << 31;
    const ulong Second = 0x82A2B175229D6A5B;
    const int Block = 1 << 16;
    // A packed encounter row's columns.
    const int Species = 0, Stars = 1, Flawless = 2, AbilityRule = 3, Gender = 4, Cutoff = 5, Ratio = 6,
        Nature = 7, Toxtricity = 8, Shiny = 9, Tera = 10, Level = 11, Material = 12, NFixed = 13,
        NLottery = 14, LotteryTotal = 15, Ivs = 16, Abilities = 22, Types = 25, Base = 27, Evs = 33,
        Columns = 39;
    const int ModeStandard = 0, ModeBlack = 1;
    const int ShinyNever = 1, ShinyAlways = 2;

    sealed class Context
    {
        public int Mode, Objective, Width, FixedWidth, LotteryWidth;
        public bool Lowest;
        public long[] StarCeil = [], StarVal = [], Totals = [], Lut = [], Rows = [], Fixed = [], Lottery = [];
        public long[] ToxtTab = [], ToxtN = [], Shards = [], Slots = [], RewardColumns = [], Filters = [];
        public long[] IvRanges = [], Want = [];
    }

    static long[] Longs(JsonNode? node) => node is JsonArray a ? a.Select(v => (long)v!).ToArray() : [];

    public static JsonObject Run(JsonObject request)
    {
        var c = new Context
        {
            Mode = (int)request["mode"]!, Objective = (int)request["objective"]!, Lowest = (bool)request["lowest"]!,
            Width = (int)request["lut_width"]!, FixedWidth = (int)request["fixed_width"]!,
            LotteryWidth = (int)request["lottery_width"]!,
            StarCeil = Longs(request["star_ceil"]), StarVal = Longs(request["star_val"]),
            Totals = Longs(request["totals"]), Lut = Longs(request["lut"]), Rows = Longs(request["rows"]),
            Fixed = Longs(request["fixed"]), Lottery = Longs(request["lottery"]),
            ToxtTab = Longs(request["toxt_tab"]), ToxtN = Longs(request["toxt_n"]), Shards = Longs(request["shards"]),
            Slots = Longs(request["slots"]), RewardColumns = Longs(request["columns"]),
            Filters = Longs(request["filters"]), IvRanges = Longs(request["ivs"]), Want = Longs(request["want"]),
        };
        var start = (long)request["start"]!;
        var count = (long)request["count"]!;
        var keep = (string)request["keep"]!;      // "best", "species" or "first"
        var limit = (int)request["limit"]!;

        var visits = new List<long>();
        var best = new List<long>();
        var bySpecies = new Dictionary<long, long>();
        long first = -1;
        var gate = new object();
        var blocks = (count + Block - 1) / Block;
        Parallel.For(0L, blocks, (b, loop) =>
        {
            long from = b * Block, to = Math.Min(count, from + Block);
            if (keep == "first" && Volatile.Read(ref first) is >= 0 and var found && found < from)
                return;
            var localVisits = new List<long>();
            var localBest = new PriorityQueue<long, long>();      // the largest rank leaves first
            var localSpecies = new Dictionary<long, long>();
            long localFirst = -1;
            for (var off = from; off < to; off++)
            {
                var rank = Evaluate(c, (uint)((start + off) & 0xFFFFFFFF), out var species);
                if (rank == Visit)
                {
                    localVisits.Add(off);
                    continue;
                }
                if (rank == NoMatch)
                    continue;
                if (keep == "first")
                {
                    localFirst = off;
                    break;
                }
                if (keep == "species")
                {
                    if (!localSpecies.TryGetValue(species, out var held) || rank < held)
                        localSpecies[species] = rank;
                    continue;
                }
                localBest.Enqueue(rank, -rank);
                if (localBest.Count > limit)
                    localBest.Dequeue();
            }
            lock (gate)
            {
                visits.AddRange(localVisits);
                if (localFirst >= 0 && (first < 0 || localFirst < first))
                    Volatile.Write(ref first, localFirst);
                foreach (var (species, rank) in localSpecies)
                    if (!bySpecies.TryGetValue(species, out var held) || rank < held)
                        bySpecies[species] = rank;
                while (localBest.TryDequeue(out var rank, out _))
                    best.Add(rank);
            }
        });

        best.Sort();
        if (best.Count > limit)
            best.RemoveRange(limit, best.Count - limit);
        visits.Sort();
        if (first >= 0)
            visits.RemoveAll(v => v > first);
        return new JsonObject
        {
            ["ranks"] = new JsonArray(best.Select(r => (JsonNode)r).ToArray()),
            ["species"] = new JsonArray(bySpecies.Select(p => (JsonNode)new JsonArray(p.Key, p.Value)).ToArray()),
            ["first"] = first,
            ["visits"] = new JsonArray(visits.Select(v => (JsonNode)v).ToArray()),
        };
    }

    // xoroshiro128+ from a 32-bit seed and the game's fixed second word (pokeldn.sv.raid_encounter.Xoroshiro).
    struct Rng(uint seed)
    {
        ulong s0 = seed, s1 = Second;

        ulong Next()
        {
            ulong a = s0, b = s1, result = a + b;
            b ^= a;
            s0 = ((a << 24) | (a >> 40)) ^ b ^ (b << 16);
            s1 = (b << 37) | (b >> 27);
            return result;
        }

        public long NextInt(long maximum = 0xFFFFFFFF)
        {
            ulong mask = 0;
            for (var m = (ulong)(maximum - 1); m != 0; m >>= 1)
                mask = (mask << 1) | 1;
            while (true)
            {
                var value = Next() & mask;
                if (value < (ulong)maximum)
                    return (long)value;
            }
        }
    }

    static long Item(long item, long category, Context c, int row, long gem) =>
        item != 0 ? item : category == 1 ? c.Rows[row * Columns + Material] : category == 2 ? c.Shards[gem] : 0;

    // -> the seed's rank, its score and seed as one number, lowest best; NoMatch when a filter turns it
    // away, Visit when its table has no encounter. As raid_encounter.select, boss_fields, rewards and tera_type.
    static long Evaluate(Context c, uint seed, out long species)
    {
        species = -1;
        var rand = new Rng(seed);
        long stars = 6, r;
        if (c.Mode == ModeStandard)
        {
            var roll = rand.NextInt(100);
            for (var k = 0; k < c.StarCeil.Length; k++)
                if (roll <= c.StarCeil[k])
                {
                    stars = c.StarVal[k];
                    break;
                }
            r = c.Lut[stars * c.Width + rand.NextInt(c.Totals[stars])];
        }
        else if (c.Mode == ModeBlack)
            r = c.Lut[6 * c.Width + rand.NextInt(c.Totals[6])];
        else
        {
            rand.NextInt(100);
            r = c.Lut[rand.NextInt(c.Totals[0])];
            if (r >= 0)
                stars = c.Rows[r * Columns + Stars];
        }
        if (r < 0)
            return Visit;
        var row = (int)r;
        long Col(int column) => c.Rows[row * Columns + column];
        var f = c.Filters;
        species = Col(Species);
        if ((f[0] >= 0 && stars != f[0]) || (f[2] >= 0 && species != f[2]))
            return NoMatch;

        long gem;
        if (Col(Tera) >= 2)
            gem = Col(Tera) - 2;
        else
        {
            var t = new Rng(seed);
            gem = Col(Tera) == 1 ? t.NextInt(18) : Col(Types + (int)t.NextInt(2));
        }

        for (var w = 0; w < c.Want.Length / 2; w++)
        {
            long got = 0;
            for (var j = 0; j < Col(NFixed); j++)
            {
                var at = (row * c.FixedWidth + j) * 3;
                if (Item(c.Fixed[at], c.Fixed[at + 1], c, row, gem) == c.Want[2 * w] && c.Fixed[at + 2] != 0)
                    got += c.Fixed[at + 2];
            }
            if (Col(LotteryTotal) != 0)
            {
                var a = new Rng(seed);
                var roll = a.NextInt(100);
                var column = 0;
                foreach (var edge in c.RewardColumns)
                    if (roll >= edge)
                        column++;
                var draws = c.Slots[(stars - 1) * (c.RewardColumns.Length + 1) + column];
                for (var d = 0; d < draws; d++)
                {
                    var threshold = a.NextInt(Col(LotteryTotal));
                    for (var j = 0; j < Col(NLottery); j++)
                    {
                        var at = (row * c.LotteryWidth + j) * 4;
                        var weight = c.Lottery[at + 3];
                        if (weight > threshold)
                        {
                            if (Item(c.Lottery[at], c.Lottery[at + 1], c, row, gem) == c.Want[2 * w] && c.Lottery[at + 2] != 0)
                                got += c.Lottery[at + 2];
                            break;
                        }
                        threshold -= weight;
                    }
                }
            }
            if (got < c.Want[2 * w + 1])
                return NoMatch;
        }

        var b = new Rng(seed);
        b.NextInt();
        var fake = b.NextInt();
        var pid = b.NextInt();
        long tid = fake & 0xFFFF, sid = fake >> 16, low = pid & 0xFFFF;
        var sparkles = (tid ^ sid ^ (pid >> 16) ^ low) < 16;
        if (Col(Shiny) == ShinyNever && sparkles)
            pid ^= 0x10000000;
        else if (Col(Shiny) == ShinyAlways && !sparkles)
            pid = ((tid ^ sid ^ low) << 16) | low;
        var shiny = (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 16;
        if ((f[1] >= 0 && shiny != (f[1] == 1)) || (f[3] >= 0 && gem != f[3]))
            return NoMatch;

        Span<long> ivs = stackalloc long[6];            // HP Atk Def SpA SpD Spe, the draw's order
        for (var k = 0; k < 6; k++)
            ivs[k] = Col(Ivs + k);
        for (var n = 0; n < Col(Flawless); n++)
        {
            var index = b.NextInt(6);
            while (ivs[(int)index] >= 0)
                index = b.NextInt(6);
            ivs[(int)index] = 31;
        }
        for (var k = 0; k < 6; k++)
            if (ivs[k] < 0)
                ivs[k] = b.NextInt(32);
        var rule = Col(AbilityRule);
        var ability = rule == 0 ? b.NextInt(2) : rule == 1 ? b.NextInt(3) : rule - 2;
        var ratio = Col(Ratio);
        long gender = Col(Gender) >= 0 ? Col(Gender) : ratio switch
        {
            0xFF => 2,
            0xFE => 1,
            0 => 0,
            _ => b.NextInt(100) < Col(Cutoff) ? 1 : 0,
        };
        long nature;
        if (Col(Nature) >= 0)
            nature = Col(Nature);
        else if (Col(Toxtricity) >= 0)
        {
            var form = Col(Toxtricity);
            nature = c.ToxtTab[form * (c.ToxtTab.Length / c.ToxtN.Length) + b.NextInt(c.ToxtN[form])];
        }
        else
            nature = b.NextInt(25);
        if ((f[4] >= 0 && nature != f[4]) || (f[5] >= 0 && gender != f[5])
            || (f[6] >= 0 && Col(Abilities + (int)ability) != f[6]))
            return NoMatch;

        // The boss's IVs and stats are HP Atk Def Spe SpA SpD.
        Span<long> stats = [ivs[0], ivs[1], ivs[2], ivs[5], ivs[3], ivs[4]];
        for (var k = 0; k < 6; k++)
            if (stats[k] < c.IvRanges[2 * k] || stats[k] > c.IvRanges[2 * k + 1])
                return NoMatch;
        var level = Col(Level);
        for (var k = 0; k < 6; k++)
            stats[k] = (2 * Col(Base + k) + stats[k] + Col(Evs + k) / 4) * level / 100 + 5;
        stats[0] += level + 5;
        long up = nature / 5 + 1, down = nature % 5 + 1;
        if (up != down)
        {
            stats[(int)up] = stats[(int)up] * 110 / 100;
            stats[(int)down] = stats[(int)down] * 90 / 100;
        }
        long hp = stats[0], atk = stats[1], def = stats[2], spe = stats[3], spa = stats[4], spd = stats[5];
        var score = c.Objective switch
        {
            0 => hp * (def + spd),
            1 => hp * def,
            2 => hp * spd,
            3 => Math.Max(atk, spa),
            _ => hp + atk + def + spe + spa + spd,
        };
        return ((c.Lowest ? score : ScoreLimit - score) << 32) | seed;
    }
}
