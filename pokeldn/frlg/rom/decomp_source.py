"""Read the decompilation's C sources the way the compiler did: definition order, and call order.

A dump gives a body's `bl` targets in address order (`thumb.bl_targets`); this gives the calls in
the order agbcc emits them (post-order, `firered_switch` branches only). A body is aligned only when
the two lists have the same length. docs/frlg_rom_map.md, Reading the source.
"""
import re

# A call through a pointer: agbcc emits `bl` to a veneer (0x081E2224, `CALL_VIA_R0`), so it holds
# one slot in the measured list and names nothing.
INDIRECT = "*indirect*"

# The `firered_switch` build [decomp:Makefile:227]; an identifier not in here is 0 in `#if`.
BUILD = {
    "REVISION": 0xA,
    "FIRERED": 1,
    "MODERN": 0,
    "NDEBUG": 1,
    "LIBRFU_VERSION": 1026,
    "__STDC_VERSION__": 199409,
}

# Macros that emit no call, and drop what was appended inside them: the asserts under NDEBUG
# [decomp:include/gba/isagbprint.h:53-57]; NELEMS/ARRAY_COUNT are `sizeof`s.
EMPTY_MACROS = frozenset({"AGB_ASSERT", "AGB_WARNING", "AGB_ASSERT_EX", "AGB_WARNING_EX",
                          "NELEMS", "ARRAY_COUNT"})

# Macros that look like a call and expand to arithmetic: no `bl`, but their arguments keep their
# slots. `ScriptReadByte` [decomp:include/script.h:24] put a phantom `bl` in 151 bodies.
NO_CALL_MACROS = frozenset({"ScriptReadByte", "MAP_GROUP", "MAP_NUM", "BG_PLTT_ID", "OBJ_PLTT_ID",
                            "PLTT_SIZEOF"})

# Argument-count dispatch to one ROM symbol [decomp:include/pokemon.h:343]; GetMonData2 is an alias
# of GetMonData3 [decomp:src/pokemon.c:2970].
ALIASES = {"GetMonData": "GetMonData3", "GetBoxMonData": "GetBoxMonData3"}

# Keywords that take a parenthesised group without being a call.
NOT_CALLS = frozenset("""
if else while for switch return sizeof do case break continue goto default typedef struct union
enum static const volatile unsigned signed void register extern inline __attribute__ asm
""".split())

# Enough type vocabulary to tell a cast `(u8)(x)` and a declarator `u16 (*p)(void)` from a call.
TYPE_WORDS = frozenset("""
void bool8 bool16 bool32 char short int long float double signed unsigned
u8 u16 u32 u64 s8 s16 s32 s64 vu8 vu16 vu32 vs8 vs16 vs32 size_t
struct union enum const volatile
""".split())

_TOKEN = re.compile(r"[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+|->|\+\+|--|\S")

# A definition is a signature at column 0 with its brace on the next or the same line (the same-line
# form is `sloopsvc.c`).
_DEFINITION = re.compile(
    r"(?m)^(?P<sig>[A-Za-z_][A-Za-z0-9_ \t*]*?)(?P<name>[A-Za-z_]\w*)[ \t]*"
    r"\((?P<args>[^;{}]*)\)[ \t]*\n?\{",
)

_DIRECTIVE = re.compile(r"^[ \t]*#[ \t]*(\w+)[ \t]*(.*)$")


def strip_comments(text):
    """-> the source with comments and literals blanked; newlines kept so line numbers hold."""
    out, i, n = [], 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "/*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("".join(c if c == "\n" else " " for c in text[i:end]))
            i = end
        elif two == "//":
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(" " * (end - i))
            i = end
        elif text[i] in "\"'":
            quote, j = text[i], i + 1
            while j < n and text[j] != quote:
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def evaluate(expression, build=None):
    """-> the truth of one `#if` expression under `build`: `defined`, comparisons, `&&`, `||`, `!`,
    integer literals; an undefined name is 0."""
    values = BUILD if build is None else build
    text = re.sub(r"defined\s*\(\s*(\w+)\s*\)", lambda m: str(int(m.group(1) in values)), expression)
    text = re.sub(r"defined\s+(\w+)", lambda m: str(int(m.group(1) in values)), text)
    text = re.sub(r"\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\b", r"\1", text)
    text = re.sub(r"\w+", lambda m: (m.group(0) if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", m.group(0))
                                     else str(values.get(m.group(0), 0))), text)
    text = text.replace("&&", " and ").replace("||", " or ").replace("!=", " __ne__ ")
    text = text.replace("!", " not ").replace(" __ne__ ", " != ")
    try:
        return bool(eval(text, {"__builtins__": {}}, {}))  # noqa: S307 - digits and operators only
    except Exception:
        return False


def preprocess(text, build=None):
    """-> the source with the branches this build does not compile blanked, line count preserved."""
    out, stack = [], []          # stack of [active here, some branch already taken]
    continuing = False
    for line in text.split("\n"):
        if continuing:
            continuing = line.rstrip().endswith("\\")
            out.append("")
            continue
        match = _DIRECTIVE.match(line)
        if not match:
            out.append(line if all(active for active, _taken in stack) else "")
            continue
        keyword, rest = match.group(1), match.group(2)
        outer = all(active for active, _taken in stack)
        if keyword in ("if", "ifdef", "ifndef"):
            if keyword == "ifdef":
                value = evaluate(f"defined({rest.split()[0]})" if rest.split() else "0", build)
            elif keyword == "ifndef":
                value = not evaluate(f"defined({rest.split()[0]})" if rest.split() else "0", build)
            else:
                value = evaluate(rest, build)
            stack.append([outer and value, value])
        elif keyword == "elif" and stack:
            taken = stack[-1][1]
            value = (not taken) and evaluate(rest, build)
            stack[-1] = [outer_of(stack) and value, taken or value]
        elif keyword == "else" and stack:
            taken = stack[-1][1]
            stack[-1] = [outer_of(stack) and not taken, True]
        elif keyword == "endif" and stack:
            stack.pop()
        continuing = line.rstrip().endswith("\\")
        out.append("")
    return "\n".join(out)


def outer_of(stack):
    """-> whether everything ENCLOSING the innermost conditional is active."""
    return all(active for active, _taken in stack[:-1])


def _is_type_list(tokens, open_index, close_index):
    """-> True if the parentheses hold a type (a cast or declarator) rather than an expression."""
    inside = tokens[open_index + 1:close_index]
    if not inside:
        return False
    words = [t for t in inside if t.isidentifier()]
    stars = [t for t in inside if t == "*"]
    if not words or len(words) + len(stars) != len(inside):
        return False
    return words[0] in TYPE_WORDS or (words[0].endswith("_t") and len(words) == 1)


def _is_indirect_call(tokens, open_index):
    """-> True if the `(` at open_index calls through what the group before it evaluated to; a cast,
    a declarator and `if (a < b) f();` also put `(` after `)`."""
    if tokens[open_index - 1] == "]":
        return True
    if tokens[open_index - 1] != ")":
        return False
    depth, index = 0, open_index - 1
    while index >= 0:
        if tokens[index] == ")":
            depth += 1
        elif tokens[index] == "(":
            depth -= 1
            if depth == 0:
                before = tokens[index - 1] if index else ""
                if before in NOT_CALLS:
                    return False
                return not _is_type_list(tokens, index, open_index - 1)
        index -= 1
    return False


def call_sequence(body):
    """-> [called name] in `bl` order, INDIRECT for a call by pointer. Post-order: a call is
    appended at its closing parenthesis; an `EMPTY_MACROS` call removes what was appended in it."""
    tokens = _TOKEN.findall(body)
    calls, stack = [], []
    for index, token in enumerate(tokens):
        if token == "(":
            previous = tokens[index - 1] if index else ""
            if previous.isidentifier() and previous not in NOT_CALLS and previous not in TYPE_WORDS:
                stack.append((previous, len(calls)))
            elif previous in (")", "]") and _is_indirect_call(tokens, index):
                stack.append((INDIRECT, len(calls)))
            else:
                stack.append((None, len(calls)))
        elif token == ")" and stack:
            name, mark = stack.pop()
            if name in EMPTY_MACROS:
                del calls[mark:]
            elif name in NO_CALL_MACROS:
                pass
            elif name is not None:
                calls.append(ALIASES.get(name, name))
    return calls


def functions(text, build=None):
    """-> [(name, line, body)] in definition order, which agbcc keeps in the ROM."""
    source = preprocess(strip_comments(text), build)
    out = []
    for match in _DEFINITION.finditer(source):
        if match.group("name") in NOT_CALLS or match.group("sig").strip().endswith("="):
            continue
        start = match.end() - 1
        end = source.find("\n}", start)
        if end < 0:
            continue
        out.append((match.group("name"), source.count("\n", 0, match.start()) + 1,
                    source[start:end + 2]))
    return out


def read_tree(paths, build=None):
    """-> ({name: [calls]}, {name: (file, index)}); a name defined in two files is dropped."""
    calls, where, duplicates = {}, {}, set()
    for path in paths:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for index, (name, _line, body) in enumerate(functions(text, build)):
            if name in calls:
                duplicates.add(name)
                continue
            calls[name] = call_sequence(body)
            where[name] = (path.name, index)
    for name in duplicates:
        calls.pop(name, None)
        where.pop(name, None)
    return calls, where
