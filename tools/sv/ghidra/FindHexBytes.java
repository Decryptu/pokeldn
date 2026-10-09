// Find exact byte patterns in initialized program memory.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

public class FindHexBytes extends GhidraScript {
    @Override
    public void run() throws Exception {
        Memory memory = currentProgram.getMemory();
        for (String value : getScriptArgs()) {
            if ((value.length() & 1) != 0) {
                printerr("Odd-length hex pattern: " + value);
                continue;
            }
            byte[] needle = new byte[value.length() / 2];
            for (int index = 0; index < needle.length; index++) {
                needle[index] = (byte)Integer.parseInt(value.substring(index * 2, index * 2 + 2), 16);
            }
            println("SEARCH " + value);
            for (MemoryBlock block : memory.getBlocks()) {
                if (!block.isInitialized()) continue;
                Address cursor = block.getStart();
                while (cursor != null && cursor.compareTo(block.getEnd()) <= 0) {
                    Address hit = memory.findBytes(cursor, block.getEnd(), needle, null, true, monitor);
                    if (hit == null) break;
                    println("  HIT " + hit + " block=" + block.getName());
                    cursor = hit.add(1);
                }
            }
        }
    }
}
