// Find instructions whose scalar operands match one of the supplied values.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import java.util.LinkedHashSet;
import java.util.Set;

public class FindScalarFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String arg : getScriptArgs()) {
            long wanted = Long.decode(arg);
            Set<String> hits = new LinkedHashSet<>();
            InstructionIterator instructions = currentProgram.getListing().getInstructions(true);
            while (instructions.hasNext()) {
                Instruction instruction = instructions.next();
                boolean matched = false;
                for (int operand = 0; operand < instruction.getNumOperands() && !matched; operand++) {
                    for (Object object : instruction.getOpObjects(operand)) {
                        if (object instanceof Scalar && ((Scalar)object).getUnsignedValue() == wanted) {
                            matched = true;
                            break;
                        }
                    }
                }
                if (matched) {
                    Function function = getFunctionContaining(instruction.getAddress());
                    hits.add(instruction.getAddress() + " " +
                        (function == null ? "<none>" : function.getName() + " @ " + function.getEntryPoint()) +
                        " :: " + instruction);
                }
            }
            println("VALUE " + arg + " HITS " + hits.size());
            for (String hit : hits) println(hit);
        }
    }
}
