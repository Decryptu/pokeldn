using System.Buffers.Binary;
using PKHeX.Core;

// A PKSM bank (`/3ds/PKSM/banks/NAME.bnk`) read for the Bank's import [docs/gui.md, Importing].
// Layout: PKSM common/source/BankFile.cpp; generation tags: PKSM-Core include/enums/Generation.hpp.
static class PksmBank
{
    const int SlotsPerBox = 30, MaxBoxes = 500;

    public sealed record Contents(int Boxes, List<(int Box, int Slot, PKM Pokemon)> Pokemon);

    // Null when the bytes do not start with PKSM's magic; InvalidDataException when they do and the rest is wrong.
    public static Contents? Read(byte[] data)
    {
        if (data.Length < 12 || !data.AsSpan(0, 8).SequenceEqual("PKSMBANK"u8))
            return null;
        var version = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(8));
        // Version 1 has no box count; versions 1 and 2 keep 260 bytes of record, version 3 0x148 and 4 of padding.
        var (header, entry) = version switch
        {
            1 => (12, 264),
            2 => (16, 264),
            3 => (16, 0x150),
            _ => throw new InvalidDataException($"PKSM bank version {version} is not one this app reads."),
        };
        if (data.Length < header)
            throw new InvalidDataException("The PKSM bank is cut short.");
        long boxes = version == 1
            ? (data.Length - header) / entry / SlotsPerBox
            : BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(12));
        if (boxes is 0 or > MaxBoxes)
            throw new InvalidDataException($"The PKSM bank claims {boxes} boxes.");
        var found = new List<(int, int, PKM)>();
        var slots = Math.Min(boxes * SlotsPerBox, (data.Length - header) / entry);
        for (var i = 0; i < slots; i++)
        {
            var at = header + i * entry;
            var tag = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(at));
            if (Entity(tag, data.AsSpan(at + 4, entry - 4)) is { Species: not 0 } pk)
                found.Add(((int)(i / SlotsPerBox), (int)(i % SlotsPerBox), pk));
        }
        return new Contents((int)boxes, found);
    }

    // PKSM stores each record decrypted at its BOX_LENGTH, padded with 0xFF; Gen 1 and 2 as a one-Pokemon list with both names
    // (PKSM 3ds/source/Bank.cpp, Bank::pkm), whose last name byte tells the Japanese length from the other.
    static PKM? Entity(uint tag, ReadOnlySpan<byte> data) => tag switch
    {
        7 => List(data, 59, 69),
        8 => List(data, 63, 73),
        6 => new PK3(data[..80].ToArray()),
        0 => new PK4(data[..136].ToArray()),
        1 => new PK5(data[..136].ToArray()),
        2 => new PK6(data[..232].ToArray()),
        3 => new PK7(data[..232].ToArray()),
        4 => new PB7(data[..232].ToArray()),
        5 => new PK8(data[..0x148].ToArray()),
        _ => null,  // 0xFFFFFFFF is an empty slot; PKSM reads no other tag back either
    };

    static PKM? List(ReadOnlySpan<byte> data, int jp, int intl)
    {
        var end = data[jp - 1];
        var length = end is 0x50 or 0 ? jp : intl;
        return EntityFormat.GetFromBytes(data[..length].ToArray());
    }
}
