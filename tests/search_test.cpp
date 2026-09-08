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
