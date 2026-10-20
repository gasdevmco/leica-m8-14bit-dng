// Pre-analysis setup for the M8 PXA image imported as a raw binary at 0x20000 (ARM:LE:32:v5t):
// seed disassembly at the image start and enable the analyzers that find code without symbols.
// @category M8
import ghidra.app.script.GhidraScript;

public class M8Pre extends GhidraScript {
    @Override
    protected void run() throws Exception {
        setAnalysisOption(currentProgram, "ARM Aggressive Instruction Finder", "true");
        setAnalysisOption(currentProgram, "Function Start Search", "true");
        disassemble(toAddr(0x20000));
        println("M8Pre: seeded 0x20000, aggressive instruction finder on");
    }
}
