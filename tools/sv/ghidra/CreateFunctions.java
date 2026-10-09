// Disassemble indirect entry points and create functions in the disposable project copy.
//@category PokeLDN

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class CreateFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String arg : getScriptArgs()) {
            Address address = currentProgram.getAddressFactory().getAddress(arg);
            DisassembleCommand command = new DisassembleCommand(address, null, true);
            boolean disassembled = command.applyTo(currentProgram, monitor);
            if (getFunctionAt(address) == null) createFunction(address, "IND_" + arg);
            println(address + " disassembled=" + disassembled + " function=" + getFunctionAt(address));
        }
    }
}
