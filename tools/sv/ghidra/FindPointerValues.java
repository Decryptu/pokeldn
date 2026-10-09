// Find little-endian 64-bit pointer values and show surrounding qwords.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

public class FindPointerValues extends GhidraScript {
    @Override
    public void run() throws Exception {
        Memory memory = currentProgram.getMemory();
        for (String arg : getScriptArgs()) {
            long wanted = Long.parseUnsignedLong(arg, 16);
            byte[] pattern = new byte[8];
            for (int i = 0; i < 8; i++) pattern[i] = (byte)(wanted >>> (i * 8));
            println("POINTER " + arg);
            for (MemoryBlock block : memory.getBlocks()) {
                if (!block.isInitialized()) continue;
                Address cursor = block.getStart();
                while (cursor != null && cursor.compareTo(block.getEnd()) <= 0) {
                    Address hit = memory.findBytes(cursor, block.getEnd(), pattern, null, true, monitor);
                    if (hit == null) break;
                    println("  HIT " + hit);
                    for (int offset = -32; offset <= 32; offset += 8) {
                        Address at = hit.add(offset);
                        try {
                            long raw = memory.getLong(at);
                            Address target = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(raw);
                            Function function = getFunctionAt(target);
                            String ascii = "";
                            if (function == null && memory.contains(target)) {
                                StringBuilder value = new StringBuilder();
                                Address character = target;
                                for (int length = 0; length < 160 && memory.contains(character); length++) {
                                    int octet = memory.getByte(character) & 0xff;
                                    if (octet == 0) break;
                                    if (octet < 0x20 || octet > 0x7e) { value.setLength(0); break; }
                                    value.append((char)octet);
                                    character = character.next();
                                }
                                if (value.length() >= 3) ascii = " \"" + value + "\"";
                            }
                            println("    " + at + " " + String.format("%016x", raw) + " " +
                                (function == null ? ascii : function.getName()));
                        } catch (Exception ignored) { }
                    }
                    cursor = hit.next();
                }
            }
        }
    }
}
