// Dump listing instructions beginning at supplied addresses.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class DumpInstructions extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String arg : getScriptArgs()) {
            Address address = currentProgram.getAddressFactory().getAddress(arg);
            println("ADDRESS " + address);
            Instruction instruction = getInstructionContaining(address);
            if (instruction == null) instruction = getInstructionAfter(address.subtract(1));
            for (int i = 0; i < 80 && instruction != null; i++) {
                println("  " + instruction.getAddress() + " :: " + instruction);
                if (i > 0 && instruction.getFlowType().isTerminal()) break;
                instruction = instruction.getNext();
            }
        }
    }
}
