#include "search.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
using namespace gungi;
int minimax(Position &p, int depth) {
  auto ms = legal_moves(p);
  if (ms.empty())
    return p.repeated() ? 0 : -30000;
  if (depth == 0)
    return evaluate(p);
  int best = -32000;
  for (const auto &m : ms) {
    int player = p.turn;
    auto u = make_move(p, m);
    int v = minimax(p, depth - 1);
    if (p.turn != player)
      v = -v;
    undo_move(p, m, u);
    best = std::max(best, v);
  }
  return best;
}
int main() {
  try {
    Position p;
    p.draft = false;
    p.done = {true, true};
    p.board[76].push(piece(0, Marshal));
    p.board[4].push(piece(1, Marshal));
    p.board[67].push(piece(0, Pawn));
    p.board[13].push(piece(1, Pawn));
    p.history = {p.key()};
    Searcher search;
    SearchOptions opt;
    opt.milliseconds = 10000;
    opt.max_depth = 3;
    opt.qdepth = 0;
    opt.hash_mb = 1;
    int truth = minimax(p, 3);
    auto r = search.run(p, opt);
    if (r.depth != 3 || r.score != truth)
      throw std::runtime_error("alpha beta differs from full minimax");
    opt.tuned = true;
    r = search.run(p, opt);
    if (r.depth != 3 || r.score != truth)
      throw std::runtime_error("tuned PVS differs from full minimax");
    opt.selective = true;
    r = search.run(p, opt);
    if (r.depth != 3 || r.score != truth)
      throw std::runtime_error(
          "selective PVS fails independent minimax fixture");
    opt.selective = false;
    // Identical boards with different repetition histories must not share
    // scores, including when a Searcher retains position-only move hints across
    // runs.
    {
      Position fresh = p;
      fresh.board[58].push(piece(0, Pawn));
      fresh.history = {fresh.key()};
      Position nearing_draw = fresh;
      nearing_draw.history.clear();
      for (const auto &move : legal_moves(fresh)) {
        auto u = make_move(fresh, move);
        for (int i = 0; i < 3; ++i)
          nearing_draw.history.push_back(fresh.key());
        undo_move(fresh, move, u);
      }
      nearing_draw.history.push_back(nearing_draw.key());
      auto shallow = opt;
      shallow.max_depth = 1;
      for (bool reuse : {false, true}) {
        shallow.reuse_moves = reuse;
        for (auto *position : {&fresh, &nearing_draw, &fresh}) {
          const auto state = encode(*position);
          const int expected = minimax(*position, 1);
          const auto actual = search.run(*position, shallow);
          if (actual.depth != 1 || actual.score != expected ||
              encode(*position) != state)
            throw std::runtime_error(
                "history-dependent score or repetition undo mismatch");
        }
      }
      if (minimax(nearing_draw, 1) != 0 || minimax(fresh, 1) == 0)
        throw std::runtime_error("ineffective repetition fixture");
      // Evaluator changes cannot reuse old bounds, even with the same history.
      auto changed = search.run(fresh, shallow, nullptr,
                                [](const Position &) { return 1234; });
      if (changed.score != -1234)
        throw std::runtime_error("stale evaluator score reused");
      search.clear();
      Searcher empty;
      auto cleared = search.run(fresh, shallow);
      auto cold = empty.run(fresh, shallow);
      if (cleared.score != cold.score || cleared.move != cold.move ||
          cleared.nodes != cold.nodes)
        throw std::runtime_error("clear did not reset search information");
    }
    // Score retention requires an explicit evaluator identity. Reordering past
    // visits preserves the fourfold-repetition context; changing counts does
    // not.
    {
      Position same = p;
      auto move = legal_moves(same).front();
      auto u = make_move(same, move);
      std::string other = same.key();
      undo_move(same, move, u);
      same.history = {other, same.key(), other, same.key()};
      auto cached = opt;
      cached.max_depth = 2;
      cached.evaluator_tag = 77;
      search.clear();
      auto first = search.run(same, cached);
      std::swap(same.history[0], same.history[1]);
      auto warm = search.run(same, cached);
      if (first.score != warm.score || warm.score_hits == 0 ||
          warm.nodes >= first.nodes)
        throw std::runtime_error(
            "equivalent repetition counts failed score reuse");
      cached.reuse_moves = false;
      search.clear();
      auto scores_only_cold = search.run(same, cached);
      auto scores_only_warm = search.run(same, cached);
      if (scores_only_warm.score != scores_only_cold.score ||
          scores_only_warm.nodes >= scores_only_cold.nodes)
        throw std::runtime_error(
            "disabling move hints discarded retained scores");
      cached.evaluator_tag = 78;
      auto changed = search.run(same, cached, nullptr,
                                [](const Position &) { return 1234; });
      Searcher fresh;
      auto reference = fresh.run(same, cached, nullptr,
                                 [](const Position &) { return 1234; });
      if (changed.score != reference.score)
        throw std::runtime_error("evaluator tag failed score invalidation");
      cached.evaluator_tag = 77;
      same.history = {same.key()};
      auto different = search.run(same, cached);
      fresh.clear();
      auto uncached = fresh.run(same, cached);
      if (different.score != uncached.score)
        throw std::runtime_error(
            "changed repetition counts reused stale score");
    }
    // An enabled evasion budget continues checked qdepth-zero leaves.
    {
      Position tactical;
      tactical.draft = false;
      tactical.done = {true, true};
      tactical.board[76].push(piece(0, Marshal));
      tactical.board[4].push(piece(1, Marshal));
      tactical.board[30].push(piece(0, General));
      tactical.history = {tactical.key()};
      bool checking_move = false;
      for (const auto &move : legal_moves(tactical)) {
        auto u = make_move(tactical, move);
        checking_move |= in_check(tactical, tactical.turn);
        undo_move(tactical, move, u);
      }
      auto shallow = opt;
      shallow.max_depth = 1;
      shallow.qdepth = 0;
      int checked_evaluations = 0;
      auto evaluator = [&](const Position &state) {
        checked_evaluations += in_check(state, state.turn);
        return evaluate(state);
      };
      shallow.qevasions = 0;
      search.clear();
      auto cutoff = search.run(tactical, shallow, nullptr, evaluator);
      if (cutoff.depth != 1 || cutoff.score != minimax(tactical, 1) ||
          checked_evaluations == 0)
        throw std::runtime_error(
            "zero evasion budget differs from fixed-depth minimax");
      shallow.qevasions = 8;
      checked_evaluations = 0;
      search.clear();
      auto actual = search.run(tactical, shallow, nullptr, evaluator);
      if (!checking_move || actual.depth != 1 || checked_evaluations != 0)
        throw std::runtime_error(
            "qdepth zero evaluated a check before evasions");
    }
    auto before = encode(p);
    opt.milliseconds = 5;
    opt.max_depth = 32;
    r = search.run(p, opt);
    auto ms = legal_moves(p);
    if (std::find(ms.begin(), ms.end(), r.move) == ms.end() ||
        encode(p) != before || r.elapsed_ms > 250)
      throw std::runtime_error("time budget/state/legality");
    // The second player may take consecutive draft turns. Explicit minimax uses
    // actual side changes.
    p = Position::initial();
    make_move(p, {-1, 76, Marshal, Move::Drop});
    make_move(p, {-1, 4, Marshal, Move::Drop});
    make_move(p, {-1, -1, -1, Move::Done});
    p.hand[1].fill(0);
    p.hand[1][Pawn] = 1;
    p.history = {p.key()};
    opt.milliseconds = 10000;
    opt.max_depth = 2;
    truth = minimax(p, 2);
    r = search.run(p, opt);
    if (r.score != truth)
      throw std::runtime_error("draft repeated player sign");
    std::atomic<bool> stop{true};
    r = search.run(p, opt, &stop);
    if (r.depth != 0)
      throw std::runtime_error("cancel before search");
    for (int mode = 0; mode < 3; ++mode) {
      p = Position{};
      p.draft = false;
      p.done = {true, true};
      p.board[76].push(piece(0, Marshal));
      p.board[4].push(piece(1, Marshal));
      p.board[67].push(piece(0, Pawn));
      p.board[58].push(piece(1, General));
      p.history = {p.key()};
      opt.milliseconds = 1000;
      opt.max_depth = 2;
      opt.qdepth = 2;
      opt.tuned = mode > 0;
      opt.selective = mode == 2;
      r = search.run(p, opt);
      if (r.move.action != Move::Capture || r.move.from != 67 ||
          r.move.to != 58)
        throw std::runtime_error("tactical capture missed");
      if (opt.selective) {
        opt.max_depth = 3;
        r = search.run(p, opt);
        if (r.move.action != Move::Capture || r.move.from != 67 ||
            r.move.to != 58)
          throw std::runtime_error(
              "selective search loses tactical capture at depth three");
      }
      p = Position{};
      p.draft = false;
      p.done = {true, true};
      p.turn = 1;
      p.board[80].push(piece(0, Marshal));
      p.board[0].push(piece(1, Marshal));
      p.board[63].push(piece(1, General));
      p.board[68].push(piece(1, Lieutenant));
      p.history = {p.key()};
      if (in_check(p, 0))
        throw std::runtime_error(
            "invalid tactical fixture: opponent already checked");
      opt.max_depth = 1;
      r = search.run(p, opt);
      make_move(p, r.move);
      if (r.score < 29000 ||
          (outcome(p) != "stalemate" && outcome(p) != "checkmate"))
        throw std::runtime_error("forced terminal win missed");
    }
    std::cout << "search minimax, clock, state, draft, cancellation passed\n";
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
