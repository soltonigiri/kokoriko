#include "search.hpp"
#include <algorithm>
#include <cassert>
#include <cmath>
namespace gungi {
namespace {
constexpr int MATE = 30000, INF = 32000;
uint64_t mix(uint64_t a, uint64_t b) {
  a ^= b + 0x9e3779b97f4a7c15ULL + (a << 6) + (a >> 2);
  return a;
}
uint64_t repetition_token(uint64_t key, int count) {
  return count ? mix(key, uint64_t(count) * 0xd6e8feb86659fd93ULL) : 0;
}
int store_score(int score, int ply) {
  return score > 29000 ? score + ply : score < -29000 ? score - ply : score;
}
int load_score(int score, int ply) {
  return score > 29000 ? score - ply : score < -29000 ? score + ply : score;
}
int missing_king(const Position &p, int ply) {
  if (p.marshal(p.turn) < 0)
    return -MATE + ply;
  if (p.marshal(1 - p.turn) < 0)
    return MATE - ply;
  return 0;
}
} // namespace
bool Searcher::repeated(const Position &p) const {
  const auto it = p.history.empty() ? repetitions.end()
                                    : repetitions.find(p.history.back());
  const bool result = it != repetitions.end() && it->second >= 4;
  assert(result == p.repeated());
  return result;
}
void Searcher::pop_repetition(const Position &p) {
  const auto it = repetitions.find(p.history.back());
  assert(it != repetitions.end() && it->second > 0);
  if (--it->second == 0)
    repetitions.erase(it);
}
bool Searcher::expired() {
  if ((cancel && cancel->load()) ||
      (limits.node_limit && nodes >= limits.node_limit) ||
      std::chrono::steady_clock::now() >= deadline)
    aborted = true;
  return aborted;
}
void Searcher::order(const Position &p, std::vector<Move> &moves,
                     const Move &preferred, int ply) const {
  auto priority = [&](const Move &m) {
    int s = m == preferred ? 1000000 : 0;
    constexpr int value[14] = {20000, 900, 750, 420, 300, 330, 350,
                               380,   280, 100, 340, 320, 300, 260};
    if (limits.tuned && m.to >= 0) {
      int origin = m.from >= 0 ? m.from : 81 + m.kind;
      s += history_scores[p.turn][origin][m.to];
      if (ply < 72 && m == killers[ply][0])
        s += 8000;
      else if (ply < 72 && m == killers[ply][1])
        s += 7000;
    }
    if (m.action == Move::Capture) {
      s += limits.tuned ? 20000 : 1000 + p.board[m.to].size * 100;
      if (limits.tuned) {
        for (int i = 0; i < p.board[m.to].size; ++i) {
          int v = p.board[m.to].p[i];
          if (side(v) != p.turn)
            s += 10 * value[type(v)];
        }
        if (m.from >= 0)
          s -= value[type(p.board[m.from].top())];
      }
      if (type(p.board[m.to].top()) == Marshal)
        s += 20000;
    }
    if (m.betray)
      s += limits.tuned ? 15000 : 800;
    if (limits.tuned && limits.exposure_order && m.from >= 0 &&
        p.board[m.from].size > 1) {
      const auto &tower = p.board[m.from];
      const int exposed = tower.p[tower.size - 2];
      s += (side(exposed) == p.turn ? 1 : -1) * value[type(exposed)] / 4;
    }
    if (m.action == Move::Stack)
      s += 20;
    if (m.action == Move::Drop) {
      s += 10;
      if (p.draft) {
        int r = m.to / 9, c = m.to % 9;
        s += 10 - std::abs(c - 4) * 2;
        if (m.kind == Marshal)
          s += (p.turn == 0 ? r : 8 - r) * 5;
        else
          s += (p.turn == 0 ? 8 - r : r) * 4;
      }
    }
    return s;
  };
  std::vector<std::pair<int, Move>> ranked;
  ranked.reserve(moves.size());
  for (const auto &m : moves)
    ranked.emplace_back(priority(m), m);
  std::stable_sort(
      ranked.begin(), ranked.end(),
      [](const auto &a, const auto &b) { return a.first > b.first; });
  for (size_t i = 0; i < moves.size(); ++i)
    moves[i] = ranked[i].second;
}
int Searcher::quiet(Position &p, int alpha, int beta, int ply, int remaining,
                    bool terminal_checked, int check_budget, int quiet_checks) {
  if (check_budget < 0)
    check_budget = limits.qevasions;
  if (quiet_checks < 0)
    quiet_checks = limits.qchecks;
  ++nodes;
  if ((nodes & 31) == 0 && expired())
    return 0;
  if (!terminal_checked) {
    if (!p.draft) {
      int end = missing_king(p, ply);
      if (end)
        return end;
    }
    if (repeated(p))
      return 0;
  }
  if (!has_legal_move(p, true))
    return -MATE + ply;
  if (p.draft)
    return eval(p);
  bool check = in_check(p, p.turn);
  // Forced evasions have a separate budget after ordinary qdepth expires.
  // Terminal/repetition gates run before either bounded cutoff.
  if (ply >= 72 || (remaining <= 0 && (!check || check_budget <= 0)))
    return eval(p);
  if (!check) {
    int stand = eval(p);
    if (stand >= beta)
      return stand;
    alpha = std::max(alpha, stand);
  }
  auto moves = legal_moves(p, !check && quiet_checks <= 0, true);
  order(p, moves, Move{}, ply);
  for (const auto &m : moves) {
    if (!check && quiet_checks <= 0 && m.action != Move::Capture && !m.betray &&
        m.action != Move::Stack)
      continue;
    int player = p.turn;
    auto u = make_move(p, m);
    ++repetitions[p.history.back()];
    const bool optional_check =
        !check && m.action != Move::Capture && !m.betray;
    // Checking routes and drops are bounded separately from forced evasions.
    // This also includes discovered checks when a tower's top piece moves.
    if (optional_check && !in_check(p, p.turn)) {
      pop_repetition(p);
      undo_move(p, m, u);
      continue;
    }
    if (observer)
      observer(p, m, u, false);
    const int next_budget = check_budget - int(remaining <= 0);
    const int next_checks = std::max(0, quiet_checks - int(optional_check));
    int score = p.turn == player
                    ? quiet(p, alpha, beta, ply + 1, remaining - 1, false,
                            next_budget, next_checks)
                    : -quiet(p, -beta, -alpha, ply + 1, remaining - 1, false,
                             next_budget, next_checks);
    if (observer)
      observer(p, m, u, true);
    pop_repetition(p);
    undo_move(p, m, u);
    if (aborted)
      return 0;
    if (score >= beta)
      return score;
    alpha = std::max(alpha, score);
  }
  return alpha;
}
int Searcher::alpha_beta(Position &p, int depth, int alpha, int beta, int ply,
                         uint64_t context, uint64_t position_hash,
                         std::vector<Move> &pv) {
  ++nodes;
  if ((nodes & 31) == 0 && expired())
    return 0;
  if (!p.draft) {
    int end = missing_king(p, ply);
    if (end)
      return end;
  }
  if (repeated(p))
    return 0;
  if (depth <= 0)
    return quiet(p, alpha, beta, ply, limits.qdepth, true);
  uint64_t key = mix(position_hash, context);
  Entry &slot = table[key % table.size()];
  Entry cached = slot;
  Move preferred;
  if (limits.reuse_moves) {
    const auto &hint = move_table[position_hash % move_table.size()];
    if (hint.valid && hint.key == position_hash)
      preferred = hint.move;
  }
  if (cached.depth >= 0 && cached.key == key) {
    preferred = cached.move;
    if (cached.depth >= depth && ply > 0) {
      int score = load_score(cached.score, ply);
      if (cached.bound == 0 || (cached.bound == 1 && score >= beta) ||
          (cached.bound == 2 && score <= alpha)) {
        ++score_hits;
        pv = {cached.move};
        return score;
      }
    }
  }
  auto moves = legal_moves(p, false, true);
  if (moves.empty())
    return -MATE + ply;
  order(p, moves, preferred, ply);
  int original_alpha = alpha, best = -INF;
  Move best_move = moves.front();
  const bool can_reduce =
      limits.selective && !p.draft && depth >= 3 && !in_check(p, p.turn);
  int move_index = 0;
  for (const auto &m : moves) {
    ++move_index;
    if (expired())
      return 0;
    int player = p.turn;
    auto u = make_move(p, m);
    const int count = ++repetitions[p.history.back()];
    if (observer)
      observer(p, m, u, false);
    std::vector<Move> child;
    uint64_t child_hash = updated_hash(p, m, u, position_hash);
    assert(child_hash == p.hash());
    uint64_t child_context = context ^ repetition_token(child_hash, count - 1) ^
                             repetition_token(child_hash, count);
    auto visit = [&](int low, int high, int next_depth) {
      child.clear();
      return p.turn == player ? alpha_beta(p, next_depth, low, high, ply + 1,
                                           child_context, child_hash, child)
                              : -alpha_beta(p, next_depth, -high, -low, ply + 1,
                                            child_context, child_hash, child);
    };
    int score;
    if (!limits.tuned || best == -INF)
      score = visit(alpha, beta, depth - 1);
    else {
      const bool reduce = can_reduce && move_index > 8 &&
                          m.action != Move::Capture && !m.betray &&
                          !in_check(p, p.turn);
      score = visit(alpha, alpha + 1, depth - 1 - int(reduce));
      if (reduce && !aborted && score > alpha)
        score = visit(alpha, alpha + 1, depth - 1);
      if (!aborted && score > alpha && score < beta)
        score = visit(alpha, beta, depth - 1);
    }
    if (observer)
      observer(p, m, u, true);
    pop_repetition(p);
    undo_move(p, m, u);
    if (aborted)
      return 0;
    if (score > best) {
      best = score;
      best_move = m;
      pv = child;
      pv.insert(pv.begin(), m);
    }
    alpha = std::max(alpha, score);
    if (alpha >= beta) {
      if (limits.tuned && m.action != Move::Capture && !m.betray && m.to >= 0) {
        if (ply < 72 && killers[ply][0] != m) {
          killers[ply][1] = killers[ply][0];
          killers[ply][0] = m;
        }
        int origin = m.from >= 0 ? m.from : 81 + m.kind;
        auto &h = history_scores[player][origin][m.to];
        h = std::min(6000, h + depth * depth);
      }
      break;
    }
  }
  if ((slot.key == key && slot.depth <= depth) ||
      (slot.key != key &&
       (slot.generation != generation || slot.depth <= depth + 2)))
    slot = {key,
            best_move,
            store_score(best, ply),
            depth,
            best <= original_alpha ? 2
            : best >= beta         ? 1
                                   : 0,
            generation};
  if (limits.reuse_moves)
    move_table[position_hash % move_table.size()] = {position_hash, best_move,
                                                     true};
  return best;
}
void Searcher::clear() {
  table.clear();
  move_table.clear();
  killers = {};
  history_scores = {};
  repetitions.clear();
  score_profile = {};
  generation = 0;
}
SearchResult Searcher::run(Position p, SearchOptions options,
                           std::atomic<bool> *stop, Evaluator evaluator,
                           MoveObserver callback) {
  limits = options;
  cancel = stop;
  eval = std::move(evaluator);
  observer = std::move(callback);
  nodes = 0;
  score_hits = 0;
  killers = {};
  if (!options.reuse_moves) {
    history_scores = {};
    move_table.clear();
  }
  repetitions.clear();
  for (const auto &key : p.history)
    ++repetitions[key];
  for (auto &player : history_scores)
    for (auto &origin : player)
      for (auto &score : origin)
        score /= 2;
  aborted = false;
  start = std::chrono::steady_clock::now();
  deadline =
      start + std::chrono::milliseconds(std::max(1, options.milliseconds));
  const size_t bytes =
      size_t(std::clamp(options.hash_mb, 1, 512)) * 1024 * 1024;
  const size_t hint_bytes = options.reuse_moves ? bytes / 4 : 0;
  const size_t entries =
      std::max<size_t>(1, (bytes - hint_bytes) / sizeof(Entry));
  const std::array<uint64_t, 8> profile{options.evaluator_tag,
                                        uint64_t(options.qdepth),
                                        uint64_t(options.qchecks),
                                        uint64_t(options.tuned),
                                        uint64_t(options.selective),
                                        uint64_t(options.qevasions),
                                        uint64_t(options.exposure_order),
                                        uint64_t(options.reuse_moves)};
  if (!options.reuse_scores || !options.evaluator_tag ||
      profile != score_profile || table.size() != entries)
    table.assign(entries, {});
  score_profile = profile;
  ++generation;
  const size_t hints = hint_bytes / sizeof(MoveEntry);
  if (move_table.size() != hints)
    move_table.assign(hints, {});
  SearchResult result;
  auto moves = legal_moves(p);
  if (moves.empty()) {
    result.score = p.repeated() ? 0 : -MATE;
    result.elapsed_ms = std::chrono::duration<double, std::milli>(
                            std::chrono::steady_clock::now() - start)
                            .count();
    return result;
  }
  Move preferred;
  const uint64_t root_hash = p.hash();
  if (options.reuse_moves) {
    const auto &hint = move_table[root_hash % move_table.size()];
    if (hint.valid && hint.key == root_hash)
      preferred = hint.move;
  }
  order(p, moves, preferred);
  result.move = moves.front();
  result.score = eval(p);
  result.pv = {result.move};
  uint64_t context = 0;
  for (const auto &[key, count] : repetitions)
    context ^= repetition_token(position_key_hash(key), count);
  for (int depth = 1; depth <= std::clamp(options.max_depth, 1, 64); ++depth) {
    if (expired())
      break;
    std::vector<Move> pv;
    int score = alpha_beta(p, depth, -INF, INF, 0, context, root_hash, pv);
    if (aborted)
      break;
    if (!pv.empty()) {
      result.move = pv.front();
      result.pv = std::move(pv);
    }
    result.score = score;
    result.depth = depth;
    if (std::abs(score) > 29000)
      break;
  }
  result.nodes = nodes;
  result.score_hits = score_hits;
  result.elapsed_ms = std::chrono::duration<double, std::milli>(
                          std::chrono::steady_clock::now() - start)
                          .count();
  return result;
}
json encode(const SearchResult &r) {
  json pv = json::array();
  for (const auto &m : r.pv)
    pv.push_back(encode(m));
  return {{"move", encode(r.move)},
          {"score", r.score},
          {"depth", r.depth},
          {"nodes", r.nodes},
          {"score_hits", r.score_hits},
          {"elapsed_ms", r.elapsed_ms},
          {"pv", pv}};
}
} // namespace gungi
