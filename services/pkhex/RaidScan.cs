using System.Numerics;
using System.Runtime.CompilerServices;
using System.Text.Json;
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
        ScaleType = 39, Scale = 40, Columns = 41;
    const int ModeStandard = 0, ModeBlack = 1;
    const int ShinyNever = 1, ShinyAlways = 2;
    // A row's scale rule: two draws, a band (ScaleBands) or its own value; the size marks filtered.
    const int ScaleRandom = 0, ScaleValue = 6;
    const int MarkEither = 0, MarkMini = 1, MarkJumbo = 2;
    const int ByRewards = 5;                // the objective that ranks by the rewards wanted, in their order

    sealed class Context
    {
        public int Mode, Objective, Width, FixedWidth, LotteryWidth;
        public bool Lowest;
        public long[] StarOf = [], Totals = [], Lut = [], Rows = [], Fixed = [], Lottery = [];
        public long[] ToxtTab = [], ToxtN = [], Shards = [], Slots = [], RewardColumns = [], Filters = [];
        public long[] ScaleBands = [];      // each band rule's (span, low), from rule 1
        public long[] IvRanges = [], Want = [];
        public long[][] Amounts = [];       // ByRewards: every total of each leading wanted item, from its least
        public long[] RowRank = [];         // each row's best rank a seed can have, its seed left out
        // A row's stats (HP Atk Def Spe SpA SpD) with each IV and, 32nd, the best the IV filter lets
        // through, at the best its nature can make them.
        public long[] Reach = [];
        public long[] Drawn = [];           // each row's largest lottery amount of each wanted item, any Tera type it takes
        public long Tail = 1;               // ByRewards: the places of the ranked items after the first, multiplied
        // The lottery rows that can give a wanted item, each row's from Hits[HitAt[row]]: the draws that
        // land on one (at least the first, under the second) and its place in the lottery.
        public long[] Hits = [];
        public int[] HitAt = [];

        public Dictionary<string, (long[] RowRank, long[] Reach, long[] Drawn, long[] Hits, int[] HitAt)> Bounds = [];

        public Context Copy() => (Context)MemberwiseClone();
    }

    // Contexts' tables by their key (pokeldn.sv.raid_scan.pack), so that a search's requests after the
    // first, and later searches of the same context, leave them out.
    static readonly Dictionary<string, Context> Tables = [];

    static long[] Longs(JsonNode? node) => node?.AsArray().Select(n => n!.GetValue<long>()).ToArray() ?? [];

    static Context Load(JsonObject request)
    {
        var c = new Context
        {
            Mode = (int)request["mode"]!,
            FixedWidth = (int)request["fixed_width"]!, LotteryWidth = (int)request["lottery_width"]!,
            Totals = Longs(request["totals"]), Rows = Longs(request["rows"]),
            Fixed = Longs(request["fixed"]), Lottery = Longs(request["lottery"]),
            ToxtTab = Longs(request["toxt_tab"]), ToxtN = Longs(request["toxt_n"]), Shards = Longs(request["shards"]),
            Slots = Longs(request["slots"]), RewardColumns = Longs(request["columns"]),
            ScaleBands = Longs(request["scale_bands"]),
        };
        // The star roll -> the raid's stars: the first ceiling at or above the roll's.
        var ceilings = Longs(request["star_ceil"]);
        var starValues = Longs(request["star_val"]);
        c.StarOf = new long[100];
        for (var roll = 0; roll < 100; roll++)
        {
            c.StarOf[roll] = 6;
            for (var k = 0; k < ceilings.Length; k++)
                if (roll <= ceilings[k])
                {
                    c.StarOf[roll] = starValues[k];
                    break;
                }
        }
        // The draw table: a star count's draw -> its row, -1 for none. The first row whose range
        // holds a draw takes it, so the rows fill it last to first.
        var ranges = Longs(request["ranges"]);
        c.Width = (int)c.Totals.Max() + 1;
        c.Lut = new long[8 * c.Width];
        Array.Fill(c.Lut, -1L);
        for (var i = ranges.Length / 3 - 1; i >= 0; i--)
            c.Lut.AsSpan((int)(ranges[3 * i] * c.Width + ranges[3 * i + 1]),
                (int)Math.Max(0, ranges[3 * i + 2] - ranges[3 * i + 1])).Fill(i);
        return c;
    }

    public static JsonObject Run(JsonObject request)
    {
        var key = (string)request["tables"]!;
        if (request["rows"] is not null)
        {
            if (Tables.Count >= 64)
                Tables.Clear();
            Tables[key] = Load(request);
        }
        else if (!Tables.ContainsKey(key))
            throw new ArgumentException("unknown tables");
        var template = Tables[key];
        var c = template.Copy();
        c.Objective = (int)request["objective"]!;
        c.Lowest = (bool)request["lowest"]!;
        c.Filters = Longs(request["filters"]);
        c.IvRanges = Longs(request["ivs"]);
        c.Want = Longs(request["want"]);
        c.Amounts = request["amounts"]?.AsArray().Select(Longs).ToArray() ?? [];
        c.Tail = 1;
        for (var w = 1; w < c.Amounts.Length; w++)
            c.Tail *= c.Amounts[w].Length;
        var start = (long)request["start"]!;
        var count = (long)request["count"]!;
        var keep = (string)request["keep"]!;      // "best", "species" or "first"
        bool keepFirst = keep == "first", keepSpecies = keep == "species";
        var limit = (int)request["limit"]!;
        var rows = c.Rows.Length / Columns;
        // The bounds hang on the objective, the filters and the rewards wanted: kept with the tables for
        // the next request.
        var bounds = $"{c.Objective} {c.Lowest} {string.Join(',', c.Filters)} {string.Join(',', c.IvRanges)} "
            + $"{string.Join(',', c.Want)} "
            + string.Join(';', c.Amounts.Select(a => string.Join(',', a)));
        if (template.Bounds.TryGetValue(bounds, out var made))
            (c.RowRank, c.Reach, c.Drawn, c.Hits, c.HitAt) = made;
        else
        {
            Bound(c);
            if (template.Bounds.Count >= 32)
                template.Bounds.Clear();
            template.Bounds[bounds] = (c.RowRank, c.Reach, c.Drawn, c.Hits, c.HitAt);
        }

        // A seed whose best rank cannot pass the bar is turned away before its boss is drawn: the
        // limit-th best rank kept so far (Python's, from the request, then every block's), or with
        // one boss per species its row's best.
        var bar = request["bar"] is { } given ? (long)given : NoMatch;
        var rowBest = new long[keepSpecies ? rows : 0];
        Array.Fill(rowBest, NoMatch);
        if (request["species_bars"] is JsonArray held)
            foreach (var pair in held)
                for (var row = 0; row < rowBest.Length; row++)
                    if (c.Rows[row * Columns + Species] == (long)pair![0]!)
                        rowBest[row] = (long)pair[1]!;
        var visits = new List<long>();
        var best = new PriorityQueue<long, long>();       // the largest rank leaves first
        long first = -1;
        var gate = new object();
        var blocks = (count + Block - 1) / Block;
        Parallel.For(0L, blocks, (b, loop) =>
        {
            long from = b * Block, to = Math.Min(count, from + Block);
            if (keepFirst && Volatile.Read(ref first) is >= 0 and var found && found < from)
                return;
            var localVisits = new List<long>();
            var localBest = new PriorityQueue<long, long>();
            long[] localRows;
            lock (gate)
                localRows = (long[])rowBest.Clone();
            var cut = keepFirst ? NoMatch : Volatile.Read(ref bar);
            long localFirst = -1;
            for (var off = from; off < to; off++)
            {
                if (!keepFirst && (off & 0xFFF) == 0)
                    cut = Math.Min(cut, Volatile.Read(ref bar));
                var rank = Evaluate(c, (uint)((start + off) & 0xFFFFFFFF), cut, localRows, out var row);
                if (rank == Visit)
                {
                    localVisits.Add(off);
                    continue;
                }
                if (rank == NoMatch)
                    continue;
                if (keepFirst)
                {
                    localFirst = off;
                    break;
                }
                if (keepSpecies)
                {
                    if (rank < localRows[row])
                        localRows[row] = rank;
                    continue;
                }
                // Every rank here is under the cut, so it is among the block's best.
                if (localBest.Count < limit)
                    localBest.Enqueue(rank, -rank);
                else
                    localBest.EnqueueDequeue(rank, -rank);
                if (localBest.Count == limit)
                    cut = Math.Min(cut, localBest.Peek());
            }
            lock (gate)
            {
                visits.AddRange(localVisits);
                if (localFirst >= 0 && (first < 0 || localFirst < first))
                    Volatile.Write(ref first, localFirst);
                for (var row = 0; row < rowBest.Length; row++)
                    rowBest[row] = Math.Min(rowBest[row], localRows[row]);
                while (localBest.TryDequeue(out var rank, out _))
                {
                    best.Enqueue(rank, -rank);
                    if (best.Count > limit)
                        best.Dequeue();
                }
                if (best.Count == limit)
                    Volatile.Write(ref bar, Math.Min(bar, best.Peek()));
            }
        });

        var ranks = new List<long>();
        while (best.TryDequeue(out var rank, out _))
            ranks.Add(rank);
        ranks.Sort();
        var bySpecies = new Dictionary<long, long>();
        for (var row = 0; row < rowBest.Length; row++)
        {
            var species = c.Rows[row * Columns + Species];
            if (rowBest[row] != NoMatch && (!bySpecies.TryGetValue(species, out var low) || rowBest[row] < low))
                bySpecies[species] = rowBest[row];
        }
        visits.Sort();
        if (first >= 0)
            visits.RemoveAll(v => v > first);
        return new JsonObject
        {
            ["ranks"] = new JsonArray(ranks.Select(r => (JsonNode)r).ToArray()),
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
            var top = (ulong)(maximum - 1);
            var mask = top == 0 ? 0 : ulong.MaxValue >> BitOperations.LeadingZeroCount(top);
            while (true)
            {
                var value = Next() & mask;
                if (value < (ulong)maximum)
                    return (long)value;
            }
        }
    }

    const int ReachRow = 6 * 33;
    // The boss's IVs HP Atk Def Spe SpA SpD, each one's place in the draw's order.
    static readonly int[] DrawOrder = [0, 1, 2, 5, 3, 4];

    // Each row's best rank and stats (RowRank, Reach), and the lottery rows and largest amounts of the
    // rewards wanted (Hits, Drawn), for the request's objective, filters and rewards.
    static void Bound(Context c)
    {
        var rows = c.Rows.Length / Columns;
        c.RowRank = new long[rows];
        c.Reach = new long[rows * ReachRow];
        c.Drawn = new long[rows * (c.Want.Length / 2)];
        var hits = new List<long>();
        c.HitAt = new int[rows + 1];
        for (var row = 0; row < rows; row++)
        {
            c.HitAt[row] = hits.Count / 3;
            long lo = 0;
            for (var j = 0; j < c.Rows[row * Columns + NLottery]; j++)
            {
                var at = (row * c.LotteryWidth + j) * 4;
                var weight = c.Lottery[at + 3];
                if (weight != 0 && Wanted(c, c.Lottery[at], c.Lottery[at + 1], row))
                    hits.AddRange([lo, lo + weight, j]);
                lo += weight;
            }
        }
        c.HitAt[rows] = hits.Count / 3;
        c.Hits = [.. hits];
        Span<long> reach = stackalloc long[6];
        for (var row = 0; row < rows; row++)
        {
            var line = c.Rows.AsSpan(row * Columns, Columns);
            for (var iv = 0; iv <= 32; iv++)
            {
                for (var k = 0; k < 6; k++)
                    reach[k] = iv < 32 ? iv : c.IvRanges[2 * k + (c.Lowest ? 0 : 1)];
                Stats(c, line, reach, line[Nature]);
                for (var k = 0; k < 6; k++)
                    c.Reach[row * ReachRow + k * 33 + iv] = reach[k];
            }
            // The row's best rank: its flawless IVs at 31 wherever they can fall, its other IVs the best
            // the filter lets through, and its nature, or the best of the 25.
            var open = 0;
            for (var k = 0; k < 6; k++)
                if (line[Ivs + k] < 0)
                    open |= 1 << k;
            var flawless = Math.Min((int)line[Flawless], BitOperations.PopCount((uint)open));
            long fromNature = line[Nature] >= 0 ? line[Nature] : 0, toNature = line[Nature] >= 0 ? line[Nature] : 24;
            c.RowRank[row] = NoMatch;
            for (var placed = 0; placed < 64; placed++)
            {
                if ((placed & ~open) != 0 || BitOperations.PopCount((uint)placed) != flawless)
                    continue;
                for (var nature = fromNature; nature <= toNature; nature++)
                {
                    for (var k = 0; k < 6; k++)
                    {
                        var d = DrawOrder[k];
                        reach[k] = line[Ivs + d] >= 0 ? line[Ivs + d]
                            : (placed >> d & 1) != 0 ? 31 : c.IvRanges[2 * k + (c.Lowest ? 0 : 1)];
                    }
                    Stats(c, line, reach, nature);
                    c.RowRank[row] = Math.Min(c.RowRank[row],
                        Ranked(c, reach[0], reach[1], reach[2], reach[3], reach[4], reach[5], 0));
                }
            }
            if (c.Want.Length != 0)
                c.RowRank[row] = c.Objective == ByRewards ? RewardBound(c, row)
                    : Math.Max(c.RowRank[row], RewardBound(c, row));
            if (c.Filters[7] >= 0 && !CanMark(c, line, c.Filters[7]))
                c.RowRank[row] = NoMatch;
        }
    }

    // -> whether the row's scale rule can give a scale the size mark wants: 0 for the Mini mark, 255
    // for the Jumbo mark.
    static bool CanMark(Context c, ReadOnlySpan<long> line, long mark)
    {
        long low = 0, high = 255;
        if (line[ScaleType] == ScaleValue)
            low = high = line[Scale];
        else if (line[ScaleType] != ScaleRandom)
        {
            var band = 2 * (int)(line[ScaleType] - 1);
            (low, high) = (c.ScaleBands[band + 1], c.ScaleBands[band + 1] + c.ScaleBands[band] - 1);
        }
        return Marked(mark, low) || Marked(mark, high);
    }

    static bool Marked(long mark, long scale) =>
        mark == MarkEither ? scale is 0 or 255 : scale == (mark == MarkMini ? 0 : 255);

    // -> NoMatch when no raid of the row gives the least wanted of each item, whatever its Tera type;
    // otherwise ByRewards the best rank the most it can give of each makes, and 0 for the others.
    static long RewardBound(Context c, int row)
    {
        var line = c.Rows.AsSpan(row * Columns, Columns);
        var stars = line[Stars];
        long draws = 0;
        if (line[LotteryTotal] != 0)
            for (var column = 0; column <= c.RewardColumns.Length; column++)
                draws = Math.Max(draws, c.Slots[(stars - 1) * (c.RewardColumns.Length + 1) + column]);
        var best = NoMatch;
        for (long gem = 0; gem < 18; gem++)
        {
            if ((line[Tera] >= 2 && gem != line[Tera] - 2) || (c.Filters[3] >= 0 && gem != c.Filters[3]))
                continue;
            long score = 0;
            var gives = true;
            for (var w = 0; w < c.Want.Length / 2; w++)
            {
                long most = 0, drawn = 0;
                for (var j = 0; j < line[NFixed]; j++)
                {
                    var at = (row * c.FixedWidth + j) * 3;
                    if (Item(c.Fixed[at], c.Fixed[at + 1], c, row, gem) == c.Want[2 * w])
                        most += c.Fixed[at + 2];
                }
                for (var j = 0; j < line[NLottery]; j++)
                {
                    var at = (row * c.LotteryWidth + j) * 4;
                    if (c.Lottery[at + 3] != 0 && Item(c.Lottery[at], c.Lottery[at + 1], c, row, gem) == c.Want[2 * w])
                        drawn = Math.Max(drawn, c.Lottery[at + 2]);
                }
                c.Drawn[row * (c.Want.Length / 2) + w] = Math.Max(c.Drawn[row * (c.Want.Length / 2) + w], drawn);
                most += draws * drawn;
                gives &= most >= c.Want[2 * w + 1];
                if (w < c.Amounts.Length)
                    score = score * c.Amounts[w].Length + Digit(c.Amounts[w], most);
            }
            if (gives)
                best = Math.Min(best, c.Objective == ByRewards ? (ScoreLimit - 1 - score) << 32 : 0);
        }
        return best;
    }

    // Makes a boss of `line` with these IVs (HP Atk Def Spe SpA SpD) and nature its stats, in place; for
    // a nature not drawn yet (-1) the best stats any nature can give, as one raises a stat by a tenth
    // and lowers another by a tenth, and every score grows with each stat.
    static void Stats(Context c, ReadOnlySpan<long> line, Span<long> stats, long nature)
    {
        var level = line[Level];
        for (var k = 0; k < 6; k++)
            stats[k] = (2 * line[Base + k] + stats[k] + line[Evs + k] / 4) * level / 100 + 5;
        stats[0] += level + 5;
        if (nature < 0)
            for (var k = 1; k < 6; k++)
                stats[k] = stats[k] * (c.Lowest ? 90 : 110) / 100;
        else if (nature / 5 != nature % 5)
        {
            long up = nature / 5 + 1, down = nature % 5 + 1;
            stats[(int)up] = stats[(int)up] * 110 / 100;
            stats[(int)down] = stats[(int)down] * 90 / 100;
        }
    }

    // -> the rank of a boss with these stats: its score and seed as one number, lowest best.
    static long Ranked(Context c, long hp, long atk, long def, long spe, long spa, long spd, uint seed)
    {
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

    // -> the best rank a boss of `row` with these IVs (the draw's order HP Atk Def SpA SpD Spe, six
    // bits each, 32 for one not drawn yet) can have, its nature drawn or not.
    static long Reached(Context c, int row, ulong ivs, uint seed)
    {
        var t = c.Reach.AsSpan(row * ReachRow, ReachRow);
        return Ranked(c, t[(int)(ivs & 63)], t[33 + (int)(ivs >> 6 & 63)], t[66 + (int)(ivs >> 12 & 63)],
            t[99 + (int)(ivs >> 30 & 63)], t[132 + (int)(ivs >> 18 & 63)], t[165 + (int)(ivs >> 24 & 63)], seed);
    }

    static long Item(long item, long category, Context c, int row, long gem) =>
        item != 0 ? item : category == 1 ? c.Rows[row * Columns + Material] : category == 2 ? c.Shards[gem] : 0;

    // -> whether a reward row of the row gives a wanted item with some Tera type.
    static bool Wanted(Context c, long item, long category, int row)
    {
        for (long gem = 0; gem < (category == 2 ? 18 : 1); gem++)
            for (var w = 0; w < c.Want.Length; w += 2)
                if (Item(item, category, c, row, gem) == c.Want[w])
                    return true;
        return false;
    }

    // -> the seed's rank, its score and seed as one number, lowest best; NoMatch when a filter turns it
    // away or its rank cannot be under `bar` (its row's in `rowBars` when there are), Visit when its
    // table has no encounter. As raid_encounter.select, boss_fields, rewards and tera_type.
    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    static long Evaluate(Context c, uint seed, long bar, long[] rowBars, out int row)
    {
        row = -1;
        var rand = new Rng(seed);
        long stars = 6, r;
        if (c.Mode == ModeStandard)
        {
            stars = c.StarOf[rand.NextInt(100)];
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
        row = (int)r;
        var line = c.Rows.AsSpan(row * Columns, Columns);
        var f = c.Filters;
        if ((f[0] >= 0 && stars != f[0]) || (f[2] >= 0 && line[Species] != f[2]))
            return NoMatch;
        if (rowBars.Length != 0)
            bar = rowBars[row];
        if ((c.RowRank[row] | seed) >= bar)
            return NoMatch;
        return Boss(c, seed, row, stars, bar);
    }

    // Evaluate past the encounter, for the few seeds that get there.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long Boss(Context c, uint seed, int row, long stars, long bar)
    {
        var line = c.Rows.AsSpan(row * Columns, Columns);
        var f = c.Filters;
        long gem = -1;                    // drawn only for the rewards and the Tera filter
        if (line[Tera] >= 2)
            gem = line[Tera] - 2;
        else if (c.Want.Length != 0 || f[3] >= 0)
            gem = new Rng(seed).NextInt(18);      // rules 0 and 1 both draw any type (raid_encounter.tera_type)

        // Ranked by rewards they come first, and a seed that cannot beat the bar stops here; otherwise
        // after the IVs, which turn away most seeds more cheaply.
        var byRewards = c.Objective == ByRewards;
        long given = 0;
        if (byRewards && ((given = Rewards(c, line, row, stars, gem, seed, bar)) >= bar))
            return NoMatch;

        var b = new Rng(seed);
        b.NextInt();
        var fake = b.NextInt();
        var pid = b.NextInt();
        long tid = fake & 0xFFFF, sid = fake >> 16, low = pid & 0xFFFF;
        var sparkles = (tid ^ sid ^ (pid >> 16) ^ low) < 16;
        if (line[Shiny] == ShinyNever && sparkles)
            pid ^= 0x10000000;
        else if (line[Shiny] == ShinyAlways && !sparkles)
            pid = ((tid ^ sid ^ low) << 16) | low;
        var shiny = (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 16;
        if ((f[1] >= 0 && shiny != (f[1] == 1)) || (f[3] >= 0 && gem != f[3]))
            return NoMatch;

        // HP Atk Def SpA SpD Spe, the draw's order, six bits each: 32 for one not drawn yet.
        ulong ivs = 0;
        var taken = 0;
        for (var k = 0; k < 6; k++)
        {
            var iv = line[Ivs + k];
            ivs |= (ulong)(iv >= 0 ? iv : 32) << (6 * k);
            if (iv >= 0)
                taken |= 1 << k;
        }
        for (var n = 0; n < line[Flawless]; n++)
        {
            var index = (int)b.NextInt(6);
            while ((taken >> index & 1) != 0)
                index = (int)b.NextInt(6);
            taken |= 1 << index;
            ivs = (ivs & ~(63UL << (6 * index))) | (31UL << (6 * index));
        }
        if (!byRewards && bar != NoMatch && Reached(c, row, ivs, seed) >= bar)    // its IVs so far
            return NoMatch;
        for (var k = 0; k < 6; k++)
            if ((taken >> k & 1) == 0)
                ivs = (ivs & ~(63UL << (6 * k))) | ((ulong)b.NextInt(32) << (6 * k));
        for (var k = 0; k < 6; k++)
        {
            var iv = (long)(ivs >> (6 * DrawOrder[k]) & 63);
            if (iv < c.IvRanges[2 * k] || iv > c.IvRanges[2 * k + 1])
                return NoMatch;
        }
        if (!byRewards && bar != NoMatch && Reached(c, row, ivs, seed) >= bar)
            return NoMatch;
        if (!byRewards && c.Want.Length != 0 && Rewards(c, line, row, stars, gem, seed, bar) == NoMatch)
            return NoMatch;
        return Finish(c, line, b, ivs, seed, bar, given);
    }

    // -> NoMatch when the seed's rewards miss the least wanted of an item; otherwise ByRewards its rank,
    // the leading wanted items' totals as one number, a digit each (Digit, the first the most significant),
    // and 0 for the others. As raid_encounter.rewards, drawn once for every item. The draws stop once
    // those left cannot bring the first item to its least or, ByRewards, to the place the bar's first
    // digit holds, below which no score beats the bar.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long Rewards(Context c, ReadOnlySpan<long> line, int row, long stars, long gem, uint seed, long bar)
    {
        var wanted = c.Want.Length / 2;
        var need = c.Want[1];
        if (c.Objective == ByRewards && bar != NoMatch)
        {
            var lead = Math.Max(ScoreLimit - 1 - (bar >> 32), 0) / c.Tail;
            if (lead >= c.Amounts[0].Length)
                return NoMatch;
            need = Math.Max(need, c.Amounts[0][lead]);
        }
        var most = c.Drawn[row * wanted];
        Span<long> got = stackalloc long[wanted];
        for (var j = 0; j < line[NFixed]; j++)
        {
            var at = (row * c.FixedWidth + j) * 3;
            var item = Item(c.Fixed[at], c.Fixed[at + 1], c, row, gem);
            for (var w = 0; w < wanted; w++)
                if (item == c.Want[2 * w])
                    got[w] += c.Fixed[at + 2];
        }
        if (line[LotteryTotal] != 0)
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
                if (got[0] + (draws - d) * most < need)
                    return NoMatch;
                var threshold = a.NextInt(line[LotteryTotal]);
                for (var h = 3 * c.HitAt[row]; h < 3 * c.HitAt[row + 1]; h += 3)
                    if (threshold >= c.Hits[h] && threshold < c.Hits[h + 1])
                    {
                        var at = (row * c.LotteryWidth + (int)c.Hits[h + 2]) * 4;
                        var item = Item(c.Lottery[at], c.Lottery[at + 1], c, row, gem);
                        for (var w = 0; w < wanted; w++)
                            if (item == c.Want[2 * w])
                                got[w] += c.Lottery[at + 2];
                        break;
                    }
            }
        }
        long score = 0;
        for (var w = 0; w < wanted; w++)
        {
            if (got[w] < c.Want[2 * w + 1])
                return NoMatch;
            if (w < c.Amounts.Length)
                score = score * c.Amounts[w].Length + Digit(c.Amounts[w], got[w]);
        }
        return c.Objective == ByRewards ? ((ScoreLimit - 1 - score) << 32) | seed : 0;
    }

    // -> the place of a total among an item's amounts (ascending): the last one it reaches, else 0.
    static long Digit(long[] amounts, long total)
    {
        var digit = 0;
        while (digit + 1 < amounts.Length && amounts[digit + 1] <= total)
            digit++;
        return digit;
    }

    // Boss past the IVs: the ability, gender and nature, their filters and the rank, for the few
    // seeds that get there.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long Finish(Context c, ReadOnlySpan<long> line, Rng b, ulong ivs, uint seed, long bar, long given)
    {
        var f = c.Filters;
        var rule = line[AbilityRule];
        var ability = rule == 0 ? b.NextInt(2) : rule == 1 ? b.NextInt(3) : rule - 2;
        var ratio = line[Ratio];
        long gender = line[Gender] >= 0 ? line[Gender] : ratio switch
        {
            0xFF => 2,
            0xFE => 1,
            0 => 0,
            _ => b.NextInt(100) < line[Cutoff] ? 1 : 0,
        };
        long nature;
        if (line[Nature] >= 0)
            nature = line[Nature];
        else if (line[Toxtricity] >= 0)
        {
            var form = line[Toxtricity];
            nature = c.ToxtTab[form * (c.ToxtTab.Length / c.ToxtN.Length) + b.NextInt(c.ToxtN[form])];
        }
        else
            nature = b.NextInt(25);
        if ((f[4] >= 0 && nature != f[4]) || (f[5] >= 0 && gender != f[5])
            || (f[6] >= 0 && line[Abilities + (int)ability] != f[6]))
            return NoMatch;
        if (f[7] >= 0)
        {
            // The height and weight come first (raid_encounter.boss_fields), then the scale.
            long scale = line[Scale];
            if (line[ScaleType] != ScaleValue)
            {
                b.NextInt(0x81); b.NextInt(0x80); b.NextInt(0x81); b.NextInt(0x80);
                var band = 2 * (int)(line[ScaleType] - 1);
                scale = line[ScaleType] == ScaleRandom ? b.NextInt(0x81) + b.NextInt(0x80)
                    : b.NextInt(c.ScaleBands[band]) + c.ScaleBands[band + 1];
            }
            if (!Marked(f[7], scale))
                return NoMatch;
        }
        if (c.Objective == ByRewards)
            return given;

        // The boss's IVs and stats are HP Atk Def Spe SpA SpD.
        Span<long> stats = stackalloc long[6];
        for (var k = 0; k < 6; k++)
            stats[k] = (long)(ivs >> (6 * DrawOrder[k]) & 63);
        Stats(c, line, stats, nature);
        var rank = Ranked(c, stats[0], stats[1], stats[2], stats[3], stats[4], stats[5], seed);
        return rank < bar ? rank : NoMatch;
    }
}
