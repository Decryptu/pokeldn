// Dump selected functions, callers, callees, and decompiler output from a read-only project.
//@category PokeLDN

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

public class DumpRaidFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        println("PROGRAM " + currentProgram.getName() + " " + currentProgram.getImageBase());
        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.toggleSyntaxTree(true);
        if (!decompiler.openProgram(currentProgram)) {
            printerr("Unable to initialize decompiler");
            return;
        }

        String[] args = getScriptArgs();
        for (String value : args) {
            Address address = currentProgram.getAddressFactory().getAddress(value);
            Function function = getFunctionContaining(address);
            if (function == null) {
                println("MISSING " + value);
                continue;
            }
            println("\n===== " + function.getName() + " @ " + function.getEntryPoint() + " =====");
            println("CALLERS:");
            ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(function.getEntryPoint());
            while (refs.hasNext()) {
                Reference ref = refs.next();
                Function caller = getFunctionContaining(ref.getFromAddress());
                println("  " + ref.getReferenceType() + " " + ref.getFromAddress() + " " +
                    (caller == null ? "<none>" : caller.getName() + " @ " + caller.getEntryPoint()));
            }
            println("CALLEES:");
            for (Function callee : function.getCalledFunctions(monitor)) {
                println("  " + callee.getName() + " @ " + callee.getEntryPoint());
            }
            DecompileResults result = decompiler.decompileFunction(function, 120, monitor);
            if (result.decompileCompleted()) {
                println(result.getDecompiledFunction().getC());
            }
            else {
                println("DECOMPILE FAILED: " + result.getErrorMessage());
            }
        }
        decompiler.dispose();
    }
}
