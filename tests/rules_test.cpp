#include "gungi.hpp"
#include <algorithm>
#include <iostream>
#include <random>
#include <set>
#include <stdexcept>
using namespace gungi;
int assertions = 0;
void check(bool condition, const std::string &name) {
  ++assertions;
  if (!condition)
    throw std::runtime_error(name);
}
Undo checked_move(Position &p, const Move &m, bool record_history = true) {
  const uint64_t before = p.hash();
  auto u = make_move(p, m, record_history);
  check(updated_hash(p, m, u, before) == p.hash(),
        "incremental hash matches packed full key");
  return u;
}
Position empty() {
  Position p;
  p.draft = false;
  p.done = {true, true};
  return p;
}
void put(Position &p, int q, int c, int k, int height = 1) {
  p.board[q] = {};
  for (int i = 1; i < height; ++i)
    p.board[q].push(piece(c, Pawn));
  p.board[q].push(piece(c, k));
}
bool reaches(const Position &p, int from, int to) {
  auto d = destinations(p, from);
  return std::find(d.begin(), d.end(), to) != d.end();
}
Move move(int a, int b, Move::Action action = Move::Route, bool betray = false,
          int k = -1) {
  return {a, b, k, action, betray};
}
bool has(const std::vector<Move> &ms, Move m) {
  return std::find(ms.begin(), ms.end(), m) != ms.end();
}
void movement() {
  const int counts[14][3] = {
      {8, 16, 24}, {20, 24, 28}, {20, 24, 28}, {6, 12, 18}, {4, 8, 12},
      {5, 9, 13},  {6, 10, 14},  {8, 12, 16},  {5, 10, 15}, {2, 4, 6},
      {4, 8, 11},  {4, 8, 12},   {3, 6, 9},    {3, 6, 9}};
  for (int k = 0; k < 14; ++k)
    for (int t = 1; t <= 3; ++t) {
      auto p = empty();
      put(p, 40, 0, k, t);
      check(int(destinations(p, 40).size()) == counts[k][t - 1],
            "movement_table " + std::to_string(k) + ":" + std::to_string(t));
      auto a = destinations(p, 40);
      put(p, 40, 1, k, t);
      auto b = destinations(p, 40);
      for (int &q : a)
        q = 80 - q;
      std::sort(a.begin(), a.end());
      std::sort(b.begin(), b.end());
      check(a == b, "movement_symmetry");
    }
  auto p = empty();
  put(p, 67, 0, Cannon);
  check(!reaches(p, 67, 58) && !reaches(p, 67, 49) && reaches(p, 67, 40),
        "cannon_skip_two");
  put(p, 58, 1, Pawn);
  check(reaches(p, 67, 40), "cannon_leap");
  put(p, 49, 1, Pawn, 2);
  check(!reaches(p, 67, 40), "cannon_high_block");
  p = empty();
  put(p, 40, 0, General, 2);
  put(p, 31, 1, Pawn);
  check(reaches(p, 40, 31) && !reaches(p, 40, 22), "blocking ordinary");
  put(p, 31, 1, Pawn, 3);
  check(!reaches(p, 40, 31), "higher target capture prohibited");
  p = empty();
  put(p, 40, 0, Archer, 2);
  put(p, 49, 1, Pawn);
  check(!reaches(p, 40, 58), "archer backward cannot leap");
}
void archer() {
  // Source (4,4), forward -row. Explicit destinations transcribed from R5
  // photos.
  auto p = empty();
  put(p, 40, 0, Archer);
  put(p, 32, 1, Pawn, 2);
  check(reaches(p, 40, 21) && reaches(p, 40, 22) && !reaches(p, 40, 23),
        "archer_001");
  p = empty();
  put(p, 40, 0, Archer);
  put(p, 31, 1, Pawn);
  check(reaches(p, 40, 21) && reaches(p, 40, 22) && reaches(p, 40, 23) &&
            !reaches(p, 40, 31),
        "archer_002");
  put(p, 31, 1, Pawn, 2);
  check(!reaches(p, 40, 21) && !reaches(p, 40, 22) && !reaches(p, 40, 23),
        "archer_003");
  p = empty();
  put(p, 40, 0, Archer, 2);
  put(p, 32, 1, Pawn, 3);
  check(reaches(p, 40, 21) && reaches(p, 40, 22) && reaches(p, 40, 11) &&
            reaches(p, 40, 13) && !reaches(p, 40, 23) && !reaches(p, 40, 15),
        "archer_004");
  p = empty();
  put(p, 40, 0, Archer, 3);
  put(p, 31, 1, Pawn, 3);
  for (int q : {21, 22, 23, 11, 13, 15, 1, 4, 7})
    check(reaches(p, 40, q), "archer_005");
  p = empty();
  put(p, 40, 0, Archer, 2);
  put(p, 22, 1, Pawn, 2);
  for (int q : {21, 22, 23, 11, 13, 15})
    check(reaches(p, 40, q), "archer_006");
  put(p, 22, 1, Pawn, 3);
  check(!reaches(p, 40, 22) && !reaches(p, 40, 13) && reaches(p, 40, 21) &&
            reaches(p, 40, 23) && reaches(p, 40, 11) && reaches(p, 40, 15),
        "archer_007");
}
void actions() {
  auto p = empty();
  put(p, 40, 0, Shinobi, 3);
  p.board[20].push(piece(1, Pawn));
  p.board[20].push(piece(0, Samurai));
  p.board[20].push(piece(1, Pawn));
  auto original = p.key();
  auto u = checked_move(p, move(40, 20, Move::Capture));
  check(p.board[20].size == 2 && p.board[20].p[0] == piece(0, Samurai) &&
            p.board[20].top() == piece(0, Shinobi),
        "capture preserves friendly order");
  check(p.board[40].size == 2 && p.hand[0][Pawn] == 0,
        "move_top and captured not hand");
  undo_move(p, move(40, 20, Move::Capture), u);
  check(p.key() == original, "undo capture");
  p = empty();
  put(p, 40, 0, Pawn);
  put(p, 31, 0, Pawn, 2);
  check(!has(pseudo_moves(p), move(40, 31, Move::Stack)),
        "stack higher prohibited");
  put(p, 31, 1, Marshal);
  check(!has(pseudo_moves(p), move(40, 31, Move::Stack)),
        "stack marshal prohibited");
  p = empty();
  put(p, 40, 0, Tactician, 2);
  put(p, 30, 1, Pawn, 2);
  p.hand[0][Pawn] = 1;
  check(!has(pseudo_moves(p), move(40, 30, Move::Stack, true)),
        "betrayal_all insufficient same kind");
  p.hand[0][Pawn] = 2;
  check(has(pseudo_moves(p), move(40, 30, Move::Stack, true)) &&
            has(pseudo_moves(p), move(40, 30, Move::Stack)),
        "betrayal_all optional");
  u = checked_move(p, move(40, 30, Move::Stack, true));
  check(p.hand[0][Pawn] == 0 && p.board[30].size == 3 &&
            side(p.board[30].p[0]) == 0 && side(p.board[30].p[1]) == 0,
        "betrayal_all consumption");
  undo_move(p, move(40, 30, Move::Stack, true), u);
  p.board[30].p[0] = piece(1, Spear);
  check(!has(pseudo_moves(p), move(40, 30, Move::Stack, true)),
        "betrayal_all mixed insufficient");
  p.hand[0][Spear] = 1;
  check(has(pseudo_moves(p), move(40, 30, Move::Stack, true)),
        "betrayal_all mixed sufficient");
  p = empty();
  put(p, 76, 0, Marshal);
  put(p, 40, 0, Pawn);
  put(p, 13, 0, Pawn);
  p.board[13].push(piece(1, Samurai));
  p.hand[0][Spear] = 1;
  check(has(pseudo_moves(p), move(-1, 36, Move::Drop, false, Spear)) &&
            !has(pseudo_moves(p), move(-1, 27, Move::Drop, false, Spear)),
        "arata top frontier inclusive");
  check(!has(pseudo_moves(p), move(-1, 13, Move::Drop, false, Spear)),
        "arata enemy top prohibited");
  p = empty();
  put(p, 40, 1, Pawn);
  p.board[40].push(piece(0, Samurai));
  p.hand[0][Tactician] = 1;
  p.hand[0][Pawn] = 1;
  check(has(pseudo_moves(p), move(-1, 40, Move::Drop, true, Tactician)),
        "arata betrayal below friendly top");
  p.board[40].p[0] = piece(1, Tactician);
  check(!has(pseudo_moves(p), move(-1, 40, Move::Drop, true, Tactician)) &&
            has(pseudo_moves(p), move(-1, 40, Move::Drop, false, Tactician)),
        "arata reserves the dropped tactician before betrayal exchange");
  auto plain = move(-1, 40, Move::Drop, false, Tactician);
  auto reserved = checked_move(p, plain);
  check(p.hand[0][Tactician] == 0 && p.board[40].p[0] == piece(1, Tactician),
        "arata cannot consume one tactician twice");
  undo_move(p, plain, reserved);
  put(p, 49, 0, Pawn, 2);
  check(!has(pseudo_moves(p), move(49, 40, Move::Capture)),
        "capture buried enemy prohibited");
}
void draft() {
  auto p = Position::initial();
  check(legal_moves(p).size() == 27, "draft marshal only");
  auto m = move(-1, 76, Move::Drop, false, Marshal);
  checked_move(p, m);
  check(p.turn == 1, "draft alternates");
  checked_move(p, move(-1, 4, Move::Drop, false, Marshal));
  checked_move(p, move(-1, -1, Move::Done));
  check(p.draft && p.turn == 1, "draft_done first");
  checked_move(p, move(-1, 13, Move::Drop, false, Pawn));
  check(p.turn == 1 && p.draft, "draft_done repeated second");
  checked_move(p, move(-1, -1, Move::Done));
  check(!p.draft && p.turn == 0, "draft_done battle original first");
  p.validate();
  p = Position::initial(1);
  checked_move(p, move(-1, 4, Move::Drop, false, Marshal));
  checked_move(p, move(-1, 76, Move::Drop, false, Marshal));
  checked_move(p, move(-1, 13, Move::Drop, false, Pawn));
  checked_move(p, move(-1, -1, Move::Done));
  check(!p.draft && p.turn == 1, "draft_done second before first");
  p = Position::initial();
  p.hand[0].fill(0);
  p.hand[1].fill(0);
  p.hand[0][Marshal] = p.hand[1][Marshal] = 1;
  checked_move(p, move(-1, 76, Move::Drop, false, Marshal));
  checked_move(p, move(-1, 4, Move::Drop, false, Marshal));
  check(!p.draft && p.turn == 0, "draft exhausted");
}
void safety() {
  auto p = empty();
  put(p, 76, 0, Marshal);
  put(p, 0, 1, Marshal);
  put(p, 4, 1, General);
  put(p, 67, 0, Samurai);
  check(!in_check(p, 0), "king_safety blocked");
  check(!has(legal_moves(p), move(67, 57)), "king_safety discovered check");
  p.board[67] = {};
  check(in_check(p, 0), "king_safety in check");
  put(p, 60, 0, Pawn);
  p.hand[0][Pawn] = 1;
  check(has(legal_moves(p), move(-1, 67, Move::Drop, false, Pawn)),
        "king_safety arata escape");
  p = empty();
  put(p, 80, 0, Marshal);
  put(p, 0, 1, Marshal);
  put(p, 63, 1, General);
  put(p, 59, 1, Lieutenant);
  check(!in_check(p, 0) && legal_moves(p).empty() && outcome(p) == "stalemate",
        "termination stalemate");
  put(p, 71, 1, Pawn, 3);
  check(outcome(p) == "checkmate", "termination checkmate");
}
void restoration() {
  std::mt19937 rng(12345);
  for (int game = 0; game < 4; ++game) {
    auto p = Position::initial(game % 2);
    for (int n = 0; n < 180; ++n) {
      auto before = encode(p);
      if (n % 5 == 0) {
        std::array<std::array<bool, 81>, 2> expected{};
        for (int from = 0; from < 81; ++from) {
          const int v = p.board[from].top();
          if (v)
            for (int to : destinations(p, from))
              expected[side(v)][to] = true;
        }
        for (int by = 0; by < 2; ++by)
          for (int to = 0; to < 81; ++to)
            check(attacked(p, to, by) == expected[by][to],
                  "direct attack lookup matches all generated destinations");
      }
      auto ms = legal_moves(p);
      std::vector<Move> tactical;
      for (const auto &m : ms)
        if (m.action == Move::Capture || m.action == Move::Stack || m.betray)
          tactical.push_back(m);
      check(legal_moves(p, true) == tactical,
            "early tactical filtering matches full ordered legal moves");
      check(has_legal_move(p) == !ms.empty(),
            "early legal existence matches all moves");
      check(encode(p) == before, "early legal existence preserves full state");
      if (ms.empty())
        break;
      for (size_t i = 0; i < std::min<size_t>(ms.size(), 8); ++i) {
        auto u = checked_move(p, ms[i]);
        undo_move(p, ms[i], u);
        check(encode(p) == before, "undo random full state");
      }
      auto m = ms[rng() % ms.size()];
      checked_move(p, m);
      p.validate();
      check(encode(decode(encode(p))) == encode(p), "JSON roundtrip");
    }
  }
  auto p = empty();
  put(p, 76, 0, Marshal);
  put(p, 4, 1, Marshal);
  p.history = {p.key()};
  check(perft(p, 1) == 5 && perft(p, 2) == 25, "perft independent kings");
  auto k = p.key();
  p.history = {k, k, k};
  check(!p.repeated(), "repetition third");
  p.history.push_back(k);
  check(p.repeated() && outcome(p) == "repetition", "repetition fourth");
  p.hand[0][Pawn] = 1;
  check(!p.repeated(), "repetition hand");
  p.hand[0][Pawn] = 0;
  p.turn = 1;
  check(!p.repeated(), "repetition turn");
  auto j = encode(Position::initial());
  j["board"][0] = {999};
  bool rejected = false;
  try {
    decode(j);
  } catch (...) {
    rejected = true;
  }
  check(rejected, "invalid input rejected");
}
int main() {
  try {
    movement();
    archer();
    actions();
    draft();
    safety();
    restoration();
    std::cout << assertions << " assertions passed\n";
  } catch (const std::exception &e) {
    std::cerr << e.what() << "\n";
    return 1;
  }
}
