/*
 * Real C++17 pack example.
 *
 * Build: g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -O2 -g
 *          -o /tmp/cpp_example examples/packs/cpp_example.cpp
 * Run:   /tmp/cpp_example
 *
 * The program exercises the runbook: an RAII guard removes a temporary
 * directory, std::filesystem writes and reads a file, std::unique_ptr owns a
 * value, std::from_chars parses input with an explicit error path, and the
 * assertions fail the process if any behavior regresses. It prints
 * CPP_PACK_OK only when every check passes.
 */

#include <algorithm>
#include <cassert>
#include <charconv>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <numeric>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

namespace {

class TempDir {
  public:
    explicit TempDir(std::filesystem::path value) : path_(std::move(value)) {}
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;
    TempDir(TempDir&&) = delete;
    TempDir& operator=(TempDir&&) = delete;
    ~TempDir() {
        std::error_code error;
        std::filesystem::remove_all(path_, error);
    }

    const std::filesystem::path& path() const noexcept { return path_; }

  private:
    std::filesystem::path path_;
};

int parse_int(std::string_view text) {
    int value = 0;
    const char* begin = text.data();
    const char* end = begin + text.size();
    const auto result = std::from_chars(begin, end, value);
    if (result.ec != std::errc{} || result.ptr != end) {
        throw std::invalid_argument("not an integer: " + std::string(text));
    }
    return value;
}

}  // namespace

int main() {
    static_assert(sizeof(int) >= 4, "int must be at least 32 bits");

    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const TempDir temp(std::filesystem::temp_directory_path() /
                       ("zc-cpp-" + std::to_string(stamp)));
    std::filesystem::create_directories(temp.path());

    const auto file = temp.path() / "loan.txt";
    {
        std::ofstream out(file, std::ios::binary);
        out << "member=7\namount=1250\n";
        if (!out) {
            std::cerr << "FAIL: cannot write " << file << '\n';
            return 1;
        }
    }

    std::ifstream in(file, std::ios::binary);
    const std::string content((std::istreambuf_iterator<char>(in)),
                              std::istreambuf_iterator<char>());
    assert(content == "member=7\namount=1250\n");

    std::vector<int> amounts{120, 40, 900, 250};
    std::sort(amounts.begin(), amounts.end());
    const int total = std::accumulate(amounts.begin(), amounts.end(), 0);
    assert((amounts == std::vector<int>{40, 120, 250, 900}));
    assert(total == 1310);

    auto loan = std::make_unique<std::string>("LN-2026-0001");
    assert(loan->rfind("LN-", 0) == 0);

    const int parsed = parse_int("1250");
    assert(parsed == 1250);

    bool rejected = false;
    try {
        (void)parse_int("12x");
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);

    std::cout << std::boolalpha
              << "cpp: filesystem=" << std::filesystem::exists(file)
              << " raii=ok sorted_total=" << total
              << " parsed=" << parsed
              << " rejected_bad_input=" << rejected << '\n';
    std::cout << "CPP_PACK_OK\n";
    return 0;
}
