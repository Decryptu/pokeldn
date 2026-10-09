// Dump pointer-sized values and references around an address.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.mem.MemoryAccessException;

public class DumpPointers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Address start = currentProgram.getAddressFactory().getAddress(args[0]);
        int before = args.length > 1 ? Integer.decode(args[1]) : 0;
        int count = args.length > 2 ? Integer.decode(args[2]) : 32;
        start = start.subtract(before * 8L);
        for (int i = 0; i < count; i++) {
            Address at = start.add(i * 8L);
            try {
                long raw = getLong(at);
                Address target = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(raw);
                Function function = getFunctionAt(target);
                println(at + "  " + String.format("%016x", raw) + "  " +
                    (function == null ? "" : function.getName() + " @ " + function.getEntryPoint()));
            }
            catch (MemoryAccessException exception) {
                println(at + "  <uninitialized>");
            }
        }
        println("REFERENCES TO " + args[0] + ":");
        Address original = currentProgram.getAddressFactory().getAddress(args[0]);
        ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(original);
        while (refs.hasNext()) {
            Reference ref = refs.next();
            Function caller = getFunctionContaining(ref.getFromAddress());
            println("  " + ref.getReferenceType() + " " + ref.getFromAddress() + " " +
                (caller == null ? "<none>" : caller.getName() + " @ " + caller.getEntryPoint()));
        }
    }
}
