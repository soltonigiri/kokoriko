#pragma once
#include "gungi.hpp"
#include <atomic>
#include <chrono>
#include <functional>
namespace gungi {
struct SearchOptions {
  int milliseconds = 1000, max_depth = 32, hash_mb = 32, qdepth = 3;
  uint64_t node_limit = 0;
  bool tuned = false;
  bool selective = false;
};
struct SearchResult {
  Move move;
  int score = 0, depth = 0;
  uint64_t nodes = 0;
  double elapsed_ms = 0;
  std::vector<Move> pv;
};
using Evaluator = std::function<int(const Position &)>;
class Searcher {
public:
  SearchResult run(Position position, SearchOptions options,
                   std::atomic<bool> *stop = nullptr,
                   Evaluator evaluator = evaluate);

private:
  struct Entry {
    uint64_t key = 0;
    Move move;
    int score = 0, depth = -1, bound = 0;
  };
  std::vector<Entry> table;
  std::array<std::array<Move, 2>, 72> killers{};
  std::array<std::array<std::array<int, 81>, 95>, 2> history_scores{};
  SearchOptions limits;
  std::atomic<bool> *cancel = nullptr;
  Evaluator eval;
  std::chrono::steady_clock::time_point start, deadline;
  uint64_t nodes = 0;
  bool aborted = false;
  bool expired();
  int alpha_beta(Position &, int depth, int alpha, int beta, int ply,
                 uint64_t context, uint64_t position_hash,
                 std::vector<Move> &pv);
  int quiet(Position &, int alpha, int beta, int ply, int remaining,
            bool terminal_checked = false);
  void order(const Position &, std::vector<Move> &, const Move &preferred,
             int ply = 0) const;
};
json encode(const SearchResult &);
} // namespace gungi
