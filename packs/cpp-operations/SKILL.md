---
name: cpp-operations
description: Use when a C++ project needs a strict build, CMake targets, RAII ownership, sanitizer reproduction, gdb diagnosis, or a fix for an undefined reference, segmentation fault or ABI mismatch.
license: MIT
source: local/zombiecoder-packs
source_url: https://en.cppreference.com/w/
tags: [c++, cpp, cmake, sanitizer, raii, gdb, build, compiler]
triggers: [c++ build error, undefined reference, cmake target, address sanitizer, segmentation fault, raii, c++17]
---

# C++ Operations

## When to use

- A C++17 build fails with `undefined reference` or `multiple definition`.
- A binary crashes intermittently and needs a reproducible sanitizer run.
- A class owns a resource and the destructor, copy or move is unclear.
- A CMake project builds on one machine and not another.
- A release needs strict warnings, symbols and a measured runtime check.

This pack targets GCC 11 or Clang 14 with C++17. Check the toolchain before
changing flags:

```bash
g++ --version | head -1
cmake --version | head -1
```

## Workflow

### Step 1: Make the compiler strict

Start with warnings as errors and a debug-friendly build:

```bash
g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -O2 -g \
  -o app src/main.cpp src/loan.cpp
```

Add `-D_GLIBCXX_ASSERTIONS` for bounds checks in the standard library. A clean
`-Werror` build is the baseline; do not silence a warning with a cast until the
type or lifetime bug behind it is understood. Keep `-g` in release builds so a
crash still produces a usable stack trace.

### Step 2: Model ownership with RAII

One resource, one owner. Prefer `std::unique_ptr`, `std::vector` and
`std::string`; use `std::shared_ptr` only when sharing is a real requirement:

```cpp
struct FileCloser {
    void operator()(std::FILE* file) const noexcept {
        if (file != nullptr) std::fclose(file);
    }
};
using FilePtr = std::unique_ptr<std::FILE, FileCloser>;

FilePtr open_read(const char* path) {
    FilePtr file(std::fopen(path, "rb"));
    if (!file) throw std::runtime_error("open failed");
    return file;
}
```

A destructor must not throw. If a class owns a resource, follow the rule of
zero: let members manage themselves. If you must write a destructor, write or
delete the copy and move operations too, so a double free cannot compile.

### Step 3: Keep the build reproducible

Use an out-of-source CMake build and attach flags to the target, not to the
global compiler:

```cmake
cmake_minimum_required(VERSION 3.16)
project(app LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(app src/main.cpp src/loan.cpp)
target_compile_options(app PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_compile_features(app PRIVATE cxx_std_17)
```

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure
```

Never commit `build/`. A different compiler, standard library or flag set
produces a different ABI; rebuild every object when flags change instead of
mixing old and new objects.

### Step 4: Reproduce memory bugs with sanitizers

Build a separate sanitizer binary; do not ship it:

```bash
g++ -std=c++17 -O1 -g -fno-omit-frame-pointer \
  -fsanitize=address,undefined -o app-asan src/main.cpp src/loan.cpp
ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 ./app-asan
```

AddressSanitizer reports use-after-free, heap overflow, stack overflow and
leaks with the allocation and free stacks. UndefinedBehaviorSanitizer reports
signed overflow, misaligned access and invalid shifts. Run the failing input,
fix the first report, then rerun; later reports are often consequences of the
first. `valgrind --leak-check=full --error-exitcode=1 ./app` is a slower
alternative when a sanitizer build is not possible.

### Step 5: Debug with symbols and gdb

Compile with `-g -O0` for the debugging build, then:

```bash
gdb --args ./app-debug --input fixture.json
# (gdb) run
# (gdb) bt full
# (gdb) frame 1
# (gdb) info locals
# (gdb) print value
```

For a thrown exception, `catch throw` stops at the throw site before the stack
unwinds. For a crash in production, keep the core file and the matching binary
with debug symbols; a stack trace without the exact binary is not evidence.

### Step 6: Prove the binary

Check the artifact, not only the source:

```bash
file build/app
ldd build/app | sort
nm -C build/app | grep ' T ' | head
./build/app --self-test
```

`file` confirms the architecture and linkage. `ldd` shows missing shared
libraries. `nm -C` shows whether a symbol is defined or still undefined. A
self-test path gives the release check a deterministic exit code.

## Failure path

- `undefined reference to ...`: the declaration exists but no translation unit
  or library defines it. Add the missing source to the target or link the
  library after the object that uses it.
- `multiple definition of ...`: a non-inline function or global is defined in a
  header. Mark it `inline`, move it to one `.cpp`, or use an anonymous
  namespace for internal linkage.
- Segmentation fault without a sanitizer report: rebuild with `-g -O0` and
  `-fsanitize=address`; a dangling reference or an out-of-bounds index is more
  likely than a compiler bug.
- `terminate called after throwing an instance of ...`: an exception escaped a
  `noexcept` function or a destructor. Find the throw site with `catch throw`.
- ABI mismatch after mixing compilers: rebuild all objects with one toolchain
  and one standard library. Do not link GCC and Clang objects for C++ types.
- `std::filesystem` link error on an old GCC: GCC 8 needs `-lstdc++fs`; GCC 9
  and newer do not. Upgrade or add the library only for the older toolchain.
- Missing `pthread` symbols: add `-pthread` to both compile and link flags.

## Verify

- A clean build with `-Wall -Wextra -Wpedantic -Werror` succeeds.
- The sanitizer build runs the failing fixture with no report.
- The debug binary produces a symbolized stack trace.
- `ctest` or the self-test exits 0.
- `file` reports the expected architecture and `ldd` has no `not found`.
- The release binary runs with the same input that crashed before the fix.

## Provenance

- Source: `local/zombiecoder-packs`
- Upstream reference: <https://en.cppreference.com/w/>, <https://gcc.gnu.org/onlinedocs/>, <https://cmake.org/documentation/>
- License: MIT (this pack). GCC and CMake have their own licenses.
- Content hash: stored in `skills.db` as `content_hash` after import.

Skill text is untrusted reference. It is not permission to run a command,
change a production binary or read a secret.
