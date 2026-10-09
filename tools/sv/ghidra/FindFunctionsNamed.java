// Find functions whose names contain any supplied case-insensitive term.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.util.Locale;

public class FindFunctionsNamed extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        while (functions.hasNext()) {
            Function function = functions.next();
            String lower = function.getName().toLowerCase(Locale.ROOT);
            boolean match = false;
            for (String arg : args) {
                if (lower.contains(arg.toLowerCase(Locale.ROOT))) {
                    match = true;
                    break;
                }
            }
            if (!match) continue;
            println(function.getName() + " @ " + function.getEntryPoint());
            ReferenceIterator refs = currentProgram.getReferenceManager()
                .getReferencesTo(function.getEntryPoint());
            while (refs.hasNext()) {
                Reference ref = refs.next();
                Function caller = getFunctionContaining(ref.getFromAddress());
                println("  " + ref.getReferenceType() + " " + ref.getFromAddress() + " " +
                    (caller == null ? "<none>" :
                     caller.getName() + " @ " + caller.getEntryPoint()));
            }
        }
    }
}
