#!/usr/bin/python3

import sys, os
from dataclasses import dataclass as dc
from typing import Literal, Any

# 64-bit compiler
WORD_SIZE = 8

def fresh_gen():
    i = 0
    while True:
        yield f"__fresh_{i}"
        i += 1

fresh = fresh_gen()
consts = {}
strings = {}


def tokenize(path):
    with open(path) as f:
        src = f.read()

    def get(char):
        match char:
            case x if x.isalpha(): return 'iden'
            case '_': return 'iden'
            case ':': return 'iden'
            case x if x.isdigit(): return 'iden'
            case '{': return 'bo'
            case '}': return 'bc'
            case '(': return 'po'
            case ')': return 'pc'
            case '[': return 'ao'
            case ']': return 'ac'
            case ';': return 'eos'
            case '"': return 'quote'
            case "'": return 'single'
            case ' ' | '\t' | '\n': return 'format'
            case _: return 'symb'

    @dc
    class Token:
        content : str
        lineno : int
        path : str

    @dc
    class Streamer:
        toks : list[str]

        def peek(self, offset=0):
            return self.toks[offset].content
        def _pop(self):
            return self.toks.pop(0)
        def pop(self):
            return self._pop().content
        def has(self):
            return len(self.toks) > 0
        def expect(self, should):
            be = self._pop()
            if be.content != should:
                print(f"Error in `{be.path}` at line {be.lineno}: Expected `{should}` got `{be.content}`")
                sys.exit(1)

    toks = []
    buffer = ''
    string  = False
    comment = False
    literal = False
    state = None
    lineno = 1
    for char in src:
        kind = get(char)
        if char == '\n': lineno += 1


        if buffer == '//'   : comment = True
        if state  == 'quote': string = not string
        if state  == 'single': literal = not literal

        if (state != kind or state in ('bo', 'bc', 'po', 'pc')) and not string and not comment and not literal:
            if state not in (None, 'format'):
                toks.append(Token(buffer, lineno, path))
            buffer = ''

        if char == '\n' and comment: 
            buffer = ''
            comment = False
            literal = False
            string  = False

        buffer += char
        state = kind

    
    return Streamer(toks)

# shares ABI with linux system calls
ABI = ('rax', 'rdi', 'rsi', 'rdx', 'r10', 'r8', 'r9')


@dc
class AstLeaf:
    value : Any
    kind : Literal['lit', 'var', 'call', 'const', 'meta', 'string', 'char', 'index']

    @classmethod
    def parse(cls, stream):
        match stream.pop():
            case '(': #)
                expr = AstExpr.parse(stream)
                stream.expect(')')
                return expr
            case x if x.startswith("'"):
                char = x.strip("'")
                match char:
                    case '\\n': char = '\n'
                    case '\\r': char = '\r'
                    case '\\t': char = '\t'
                    case '\\0': char = '\0'
                    case '\\\\': char = '\\'
                return cls(char, 'char')

            case name if stream.peek() == '(': #)
                stream.pop()
                params = []
                while stream.peek() != ')':
                    params.append(AstExpr.parse(stream))
                    if stream.peek() == ',': stream.pop()
                stream.expect(')')
                return cls((name, params), 'call')

            case table if stream.peek() == '[': #]
                stream.expect('[') #]
                index = None if stream.peek() == ']' else AstExpr.parse(stream)
                stream.expect(']')
                return cls((table, index), 'row_access')

            case string if '"' in string: return cls(string.strip('"'), 'string')
            case number if number.isdigit(): return cls(number, 'lit')
            case x: return cls(x, 'meta') #resolve during compile

    def _resolve(self, scope, store=False):
        if self.kind != 'meta': return

        if   self.value in consts: self.kind = 'const'
        elif self.value in scope:  self.kind = 'var'
        elif store: self.kind = 'var'
        else:
            print(f"Error: Unable to resolve leaf: `{self.value}`")
            sys.exit(1)

    def eval(self):
        if self.kind  == 'lit' : return int(self.value)
        if self.value in consts: return consts[self.value]

        print(f"Unsupported compiler-time leaf: `{x}`")
        exit(1)

    def load(self, emit, scope): #load into rax
        self._resolve(scope)
        match self.kind:
            case 'lit':   emit(f'mov rax, {self.value}')
            case 'char':  emit(f'mov rax, {ord(self.value)}')
            case 'const': emit(f'mov rax, {consts[self.value]}')
            case 'var':   emit(f'mov rax, [__vars + {scope[self.value]}]')
            case 'call':
                name, params = self.value
                scope.save(emit)
                regs = ABI[:len(params)]

                for param in params:
                    param.load(emit, scope)
                    emit('push rax')

                for reg in regs[::-1]:
                    emit(f"pop {reg}")

                if name == 'syscall':
                    emit('syscall')
                else:
                    emit(f"call {name}")

                scope.restore(emit)

            case 'string':
                label = next(fresh)
                strings[label] = self.value
                emit(f'mov rax, {label}')

            case 'row_access':
                table_name, index = self.value
                table = tables[table_name]

                if index: index.load(emit, scope)
                else:     emit("mov rax, 0")
                emit(f"mov rbx, {table.inner_size}")
                emit(f"mul rbx") #this is horribily inefficient, i know
                emit(f"mov rbx, {table.vaddr}")
                emit(f"add rax, rbx")


    def store(self, emit, scope): #store from rax
        self._resolve(scope, store=True)

        if self.kind == 'var':
            scope.alloc(self.value)
            emit(f'mov [__vars + {scope[self.value]}], rax')

        else:
            print(f"Error: Trying to store into non-writable lvalue (kind={self.kind})")
            sys.exit(1)

        




OPS = ('+', '-', '==', '!=', '<', '>', '*', '/', '&', '|', '^', '<<', '>>', ':') 

@dc
class AstExpr:
    left  : "AstExpr | AstLeaf"
    right : "AstExpr | AstLeaf"
    op    : str

    @classmethod
    def parse(cls, stream):
        left = AstLeaf.parse(stream)

        if stream.peek() not in OPS:
            return left

        op = stream._pop()
        right = AstExpr.parse(stream)
        return cls(left, right, op.content)

    def load(self, emit, scope):
        self.right.load(emit, scope)
        emit('push rax')
        self.left.load(emit, scope)
        emit('pop rbx')

        match self.op:
            case '+': emit('add rax, rbx')
            case '-': emit('sub rax, rbx')
            case '==' | '!=' | '<' | '>':
                emit('cmp rax, rbx')
                match self.op:
                    case '==': emit('sete cl')
                    case '!=': emit('setne cl')
                    case '>':  emit("seta cl")
                    case '<':  emit("setb cl")
                emit('movzx rax, cl')
            case '*': emit('mul rbx')
            case '/':
                emit('xor rdx, rdx')
                emit('div rbx')
            case '&': emit('and rax, rbx')
            case '|': emit('or  rax, rbx')
            case '^': emit('xor rax, rbx')
            case '>>': 
                emit('mov rcx, rbx')
                emit('shr rax, cl')
            case '<<': 
                emit('mov rcx, rbx')
                emit('shl rax, cl')

            case ':':
                emit("mov rax, [rax + rbx]")


    def store(self, emit, scope):
        if self.op != ':':
            print(f"Error: Trying to store into `{self.op}`-operator expression")
            sys.exit(1)

        emit("mov r10, rax")

        self.right.load(emit, scope)
        emit('push rax')
        self.left.load(emit, scope)
        emit('pop rbx')

        emit("mov [rax + rbx], r10")



@dc
class AstAssign:
    dst : AstExpr
    src : AstExpr

    def compile(self, emit, scope):
        self.src.load(emit, scope)
        self.dst.store(emit, scope)


@dc
class AstReturn:
    value : AstExpr

    @classmethod
    def parse(cls, stream):
        stream.expect('return')
        value = AstExpr.parse(stream)
        stream.expect(';')
        return cls(value)

    def compile(self, emit, scope):
        self.value.load(emit, scope)
        emit('ret')

@dc
class AstLabel:
    name : str

    @classmethod
    def parse(cls, stream):
        stream.expect('lab')
        name = stream.pop()
        stream.expect(';')
        return cls(name)

    def compile(self, emit, scope):
        emit(scope.render_label(self.name) + ':')

@dc
class AstJump:
    target : str
    cond   : "AstExpr | None"

    @classmethod
    def parse(cls, stream):
        stream.expect('jump')
        target = stream.pop()
        cond = None

        if stream.peek() == '~':
            stream.pop()
            cond = AstExpr.parse(stream)

        stream.expect(';')
        return cls(target, cond)

    def compile(self, emit, scope):
        label = scope.render_label(self.target)
        if self.cond is not None:
            self.cond.load(emit, scope)
            emit("cmp rax, 0")
            emit(f"jne {label}")
        else:
            emit(f"jmp {label}")

@dc
class AstInplace:
    expr : AstExpr

    def compile(self, emit, scope):
        self.expr.load(emit, scope)


@dc
class AstBlock:
    nodes : list

    @staticmethod
    def node(stream):
        match stream.peek():
            case 'return': return AstReturn.parse(stream)
            case 'lab'   : return AstLabel.parse(stream)
            case 'jump'  : return AstJump.parse(stream)

        first = AstExpr.parse(stream)

        if stream.peek() != '=':
            stream.expect(';')
            return AstInplace(first)
        stream.expect('=')

        second = AstExpr.parse(stream)
        stream.expect(';')
        return AstAssign(first, second)

    @classmethod
    def parse(cls, stream):
        stream.expect('{') #}

        nodes = []
        while stream.peek() != '}':
            nodes.append(cls.node(stream))

        stream.expect('}')
        return cls(nodes)

    def compile(self, emit, scope):
        for node in self.nodes:
            node.compile(emit, scope)


@dc
class AstFnDef:
    name   : str
    params : list[str]
    body   : AstBlock

    @classmethod
    def parse(cls, stream):
        stream.expect('fn')
        name = stream.pop().replace(':', '_')
        stream.expect('(') #)
        
        params = []
        while stream.peek() != ')':
            params.append(stream.pop())
            if stream.peek() == ',':
                stream.pop()

        stream.expect(')')
        body = AstBlock.parse(stream)
        return cls(name, params, body)

    @dc
    class _LocalScope:
        fn_name : str
        vars : dict[str, int] #variable name to address
        allocer : int = 0

        def alloc(self, name):
            if name in self.vars: return

            self.vars[name] = self.allocer * WORD_SIZE
            self.allocer += 1

        def __getitem__(self, name):
            return self.vars[name]

        def __contains__(self, name):
            return name in self.vars

        def save(self, emit):
            for vaddr in range(self.allocer):
                addr = vaddr * WORD_SIZE
                emit(f'push qword [__vars + {addr}]')

        def restore(self, emit):
            for neg_vaddr in range(self.allocer):
                vaddr = (self.allocer - 1) - neg_vaddr 
                addr = vaddr * WORD_SIZE
                emit(f'pop qword [__vars + {addr}]')

        def render_label(self, name):
            return f"__local_{self.fn_name}_{name}"


    def compile(self, emit):
        scope = self._LocalScope(self.name, {})
        emit(f"{self.name}:")

        #allocate local parameter variables
        regs = ABI[:len(self.params)]
        for param, reg in zip(self.params, regs):
            scope.alloc(param)
            emit(f'mov [__vars + {scope[param]}], {reg}')

        self.body.compile(emit, scope)
        emit("xor rax, rax") # return null by default
        emit("ret")

# prevent redundant uses
using = set()

@dc
class AstTable:
    @dc
    class Field:
        name  : str
        count : int

        offset : int = 0

        @classmethod
        def parse(cls, stream):
            name = stream.pop()
            count = 1

            if stream.peek() == '[': #]
                stream.expect('[') #]
                count = AstExpr.parse(stream).eval()
                stream.expect(']')

            return cls(name, count)

        def alloc(self, iter):
            self.offset = iter
            consts[self.name] = self.offset
            return iter + self.size()

        def size(self):
            return self.count * WORD_SIZE

    head   : Field
    fields : list[Field]

    inner_size : int
    outer_size : int

    # caution: big number!
    vaddr : int = None

    @classmethod
    def parse(cls, stream):
        stream.expect('table')
        head = cls.Field.parse(stream)

        fields = []
        stream.expect('{') #}
        while stream.peek() != '}': #}
            fields.append(cls.Field.parse(stream))
            if stream.peek() == ',': stream.pop()
        stream.expect('}')

        # compute offsets
        iter = 0
        for field in fields:
            iter = field.alloc(iter)

        inner_size = iter
        outer_size = inner_size * head.count

        return cls(head, fields, inner_size, outer_size)



fns : list[AstFnDef] = []
tables : dict[str, AstTable] = {}

iota = 0

def parse_const(stream):
    global iota

    stream.expect('const')    
    name = stream.pop()
    stream.expect('=')
    value = stream.pop()

    match value:
        case 'iota':
            consts[name] = iota
            iota += 1
        case 'alpha':
            iota = 0
            consts[name] = iota
        case _:
            consts[name] = int(value)

def parse_prog(path):
    global fns, tables
    stream = tokenize(path)

    while stream.has():
        match stream.peek():
            case 'fn':
                fns.append(AstFnDef.parse(stream))

            case 'table':
                table = AstTable.parse(stream)
                tables[table.head.name] = table

            case 'use':
                stream.expect('use')
                path = stream.pop().strip('"')

                if path not in using:
                    using.add(path)
                    print(f'import: {path}')
                    parse_prog(path)

            case 'const':
                parse_const(stream)

            case x: 
                print(f"Error: Invalid toplevel prefix: {x}")
                sys.exit(1)

def compute_layout():
    # this assumes 48-bit vas
    VADDR_BASE = 1 << 46 # lower 47 bits are for rest of program (should be enough hehe)
    VADDR_INTER = VADDR_BASE // len(tables) 

    for index, table in enumerate(tables.values()):
        table.vaddr = VADDR_BASE + (index * VADDR_INTER)

def compile_prog(emit):
    for fn in fns:
        fn.compile(emit)


def runtime(emit):
    # headers
    emit('format ELF64')
    emit("section '.text' executable")

    emit("extrn runtime_init")

    emit("public __table_table")
    emit("public _start")
    emit("_start:")

    emit("call runtime_init")

    # process parameters 
    # system V abi, section 3.4 process init
    # (https://web.archive.org/web/20160706074221/http://www.x86-64.org/documentation/abi.pdf)
    emit("mov rax, [rsp]")
    emit("lea rdi, [rsp+8]")

    emit("call main")

    emit("mov rdi, rax")
    emit("mov rax, 60")
    emit("syscall")


def emit_table_table_entry(emit, base_addr, compile_size):
    emit(f"dq {hex(base_addr)}")
    emit(f"dq {str(compile_size)}")

    # runtime data
    emit(f"dq 0")

def finalize(emit):
    #basic buffers
    VAR_COUNT = 100 # concurrent local variables
    emit("section '.data' writeable")
    emit(f'__vars: rq {VAR_COUNT}')

    #table table
    emit("__table_table:")
    for table in tables.values():
        emit_table_table_entry(
            emit,
            table.vaddr, 
            table.outer_size
        )

    emit("dq 0")

    #emit strings
    for label, string in strings.items():
        string = string.encode('utf-8').decode('unicode_escape')
        emit(f"{label}:")
        for char in string:
            emit(f"\tdb {ord(char)}")
        emit("\tdb 0")


def main():
    parse_prog(sys.argv[1])
    compute_layout()

    asm = []
    emitter = lambda x: asm.append(x)
    runtime(emitter)
    compile_prog(emitter)
    finalize(emitter)

    with open('build.asm', 'w') as f:
        f.write('\n'.join(asm))




if __name__ == '__main__':
    main()
