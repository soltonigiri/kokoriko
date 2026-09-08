#pragma once
#include "gungi.hpp"
#include <atomic>
#include <chrono>
#include <functional>
#include <unordered_map>
namespace gungi {
struct SearchOptions {
  int milliseconds = 1000, max_depth = 32, hash_mb = 32, qdepth = 3;
  uint64_t node_limit = 0;
  bool tuned = false;
  bool selective = false;
  bool reuse_moves = true;
  bool reuse_scores = true;
  int qchecks = 0, qevasions = 0;
  bool exposure_order = true;
  // Nonzero caller-owned identity for an immutable evaluator. Zero disables
  // score retention across run() calls, including for arbitrary lambdas.
  uint64_t evaluator_tag = 0;
};
struct SearchResult {
  Move move;
  int score = 0, depth = 0;
  uint64_t nodes = 0;
  uint64_t score_hits = 0;
  double elapsed_ms = 0;
  std::vector<Move> pv;
};
using Evaluator = std::function<int(const Position &)>;
using MoveObserver =
    std::function<void(const Position &, const Move &, const Undo &, bool)>;
class Searcher {
public:
  // Call after a new game, rule change or evaluator change.
  void clear();
  SearchResult run(Position position, SearchOptions options,
                   std::atomic<bool> *stop = nullptr,
                   Evaluator evaluator = evaluate, MoveObserver observer = {});

private:
  struct Entry {
    uint64_t key = 0;
    Move move;
    int score = 0, depth = -1, bound = 0;
    uint32_t generation = 0;
  };
  std::vector<Entry> table;
  std::array<uint64_t, 8> score_profile{};
  uint32_t generation = 0;
  struct MoveEntry {
    uint64_t key = 0;
    Move move;
    bool valid = false;
  };
  std::vector<MoveEntry> move_table;
  // Exact keys: hash collisions cannot change repetition adjudication.
  std::unordered_map<std::string, int> repetitions;
  bool repeated(const Position &) const;
  void pop_repetition(const Position &);
  std::array<std::array<Move, 2>, 72> killers{};
  std::array<std::array<std::array<int, 81>, 95>, 2> history_scores{};
  SearchOptions limits;
  std::atomic<bool> *cancel = nullptr;
  Evaluator eval;
  MoveObserver observer;
  std::chrono::steady_clock::time_point start, deadline;
  uint64_t nodes = 0;
  uint64_t score_hits = 0;
  bool aborted = false;
  bool expired();
  int alpha_beta(Position &, int depth, int alpha, int beta, int ply,
                 uint64_t context, uint64_t position_hash,
                 std::vector<Move> &pv);
  int quiet(Position &, int alpha, int beta, int ply, int remaining,
            bool terminal_checked = false, int check_budget = -1,
            int quiet_checks = -1);
  void order(const Position &, std::vector<Move> &, const Move &preferred,
             int ply = 0) const;
};
json encode(const SearchResult &);
} // namespace gungi
