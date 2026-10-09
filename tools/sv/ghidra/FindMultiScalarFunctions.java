// Rank functions by how many supplied scalar operands they reference.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class FindMultiScalarFunctions extends GhidraScript {
    private static class Hit {
        Function function;
        Set<Long> values = new LinkedHashSet<>();
        List<String> instructions = new ArrayList<>();
        Hit(Function function) { this.function = function; }
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Set<Long> wanted = new LinkedHashSet<>();
        for (String arg : args) wanted.add(Long.decode(arg));
        Map<String, Hit> hits = new LinkedHashMap<>();
        InstructionIterator instructions = currentProgram.getListing().getInstructions(true);
        while (instructions.hasNext()) {
            Instruction instruction = instructions.next();
            Set<Long> matched = new LinkedHashSet<>();
            for (int operand = 0; operand < instruction.getNumOperands(); operand++) {
                for (Object object : instruction.getOpObjects(operand)) {
                    if (object instanceof Scalar) {
                        long value = ((Scalar)object).getUnsignedValue();
                        if (wanted.contains(value)) matched.add(value);
                    }
                }
            }
            if (matched.isEmpty()) continue;
            Function function = getFunctionContaining(instruction.getAddress());
            if (function == null) continue;
            String key = function.getEntryPoint().toString();
            Hit hit = hits.computeIfAbsent(key, ignored -> new Hit(function));
            hit.values.addAll(matched);
            hit.instructions.add(instruction.getAddress() + " :: " + instruction);
        }
        List<Hit> ranked = new ArrayList<>(hits.values());
        ranked.sort(Comparator.<Hit>comparingInt(hit -> hit.values.size()).reversed()
            .thenComparing(hit -> hit.function.getEntryPoint()));
        for (Hit hit : ranked) {
            if (hit.values.size() < 2) continue;
            println("SCORE " + hit.values.size() + "/" + wanted.size() + " " +
                hit.function.getName() + " @ " + hit.function.getEntryPoint() +
                " VALUES " + hit.values);
            for (String line : hit.instructions) println("  " + line);
        }
    }
}
