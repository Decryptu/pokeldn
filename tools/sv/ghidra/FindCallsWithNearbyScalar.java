// Find calls to a function with a matching scalar in the preceding instructions.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

public class FindCallsWithNearbyScalar extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Address target = currentProgram.getAddressFactory().getAddress(args[0]);
        long wanted = Long.decode(args[1]);
        int distance = args.length > 2 ? Integer.decode(args[2]) : 12;
        ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(target);
        while (refs.hasNext()) {
            Reference ref = refs.next();
            if (!ref.getReferenceType().isCall()) continue;
            Instruction instruction = getInstructionAt(ref.getFromAddress());
            StringBuilder window = new StringBuilder();
            boolean matched = false;
            for (int i = 0; i <= distance && instruction != null; i++) {
                window.insert(0, instruction.getAddress() + " " + instruction + "\n");
                for (int operand = 0; operand < instruction.getNumOperands(); operand++) {
                    for (Object object : instruction.getOpObjects(operand)) {
                        if (object instanceof Scalar && ((Scalar)object).getUnsignedValue() == wanted)
                            matched = true;
                    }
                }
                instruction = instruction.getPrevious();
            }
            if (matched) {
                Function function = getFunctionContaining(ref.getFromAddress());
                println("MATCH " + ref.getFromAddress() + " " +
                    (function == null ? "<none>" : function.getName() + " @ " + function.getEntryPoint()));
                println(window.toString());
            }
        }
    }
}
