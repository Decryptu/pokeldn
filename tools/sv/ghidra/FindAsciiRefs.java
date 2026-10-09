// Find ASCII bytes in loaded memory and print all references to each match.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.nio.charset.StandardCharsets;

public class FindAsciiRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        Memory memory = currentProgram.getMemory();
        for (String needle : getScriptArgs()) {
            byte[] bytes = needle.getBytes(StandardCharsets.US_ASCII);
            println("SEARCH " + needle);
            for (MemoryBlock block : memory.getBlocks()) {
                Address cursor = block.getStart();
                while (cursor != null && cursor.compareTo(block.getEnd()) <= 0) {
                    Address hit = memory.findBytes(cursor, block.getEnd(), bytes, null, true, monitor);
                    if (hit == null) break;
                    println("  HIT " + hit);
                    byte[] context = new byte[256];
                    memory.getBytes(hit.subtract(128), context);
                    println("    CONTEXT " + new String(context, StandardCharsets.US_ASCII).replace('\0', '|'));
                    for (int delta = -128; delta <= 128; delta++) {
                        Address candidate = hit.add(delta);
                        ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(candidate);
                        while (refs.hasNext()) {
                            Reference ref = refs.next();
                            Function function = getFunctionContaining(ref.getFromAddress());
                            println("    TARGET " + candidate + " " + ref.getReferenceType() + " " +
                                ref.getFromAddress() + " " + (function == null ? "<none>" :
                                function.getName() + " @ " + function.getEntryPoint()));
                        }
                    }
                    cursor = hit.add(1);
                }
            }
        }
    }
}
