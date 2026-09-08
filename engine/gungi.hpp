#pragma once
#include <array>
#include <cstdint>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>
namespace gungi {
using json = nlohmann::json;
inline constexpr const char *RULES = "product-advanced-2026-09-all-betrayal-v1";
enum Type {
  Marshal,
  General,
  Lieutenant,
  Major,
  Samurai,
  Spear,
  Rider,
  Shinobi,
  Fortress,
  Pawn,
  Cannon,
  Archer,
  Musketeer,
  Tactician
};
inline constexpr std::array<int, 14> SUPPLY{1, 1, 1, 2, 2, 3, 2,
                                            2, 2, 4, 1, 2, 1, 1};
inline constexpr std::array<const char *, 14> NAMES{
    "帥", "大", "中", "小", "侍", "槍", "馬",
    "忍", "砦", "兵", "砲", "弓", "筒", "謀"};
inline int piece(int side, int type) { return 1 + side * 14 + type; }
inline int side(int p) { return (p - 1) / 14; }
inline int type(int p) { return (p - 1) % 14; }
struct Tower {
  std::array<uint8_t, 3> p{};
  int8_t size = 0;
  int top() const { return size ? p[size - 1] : 0; }
  void push(int v) { p[size++] = static_cast<uint8_t>(v); }
  int pop() {
    int v = p[--size];
    p[size] = 0;
    return v;
  }
  bool operator==(const Tower &) const = default;
};
struct Move {
  int from = -1, to = -1, kind = -1; // kind is the hand piece for drops
  enum Action { Route, Stack, Capture, Drop, Done } action = Route;
  bool betray = false;
  bool operator==(const Move &) const = default;
};
struct Position {
  std::array<Tower, 81> board{};
  std::array<std::array<int, 14>, 2> hand{};
  int turn = 0, first = 0;
  bool draft = true;
  std::array<bool, 2> done{};
  // Exact packed keys prevent repetition decisions from depending on hash
  // collisions.
  std::vector<std::string> history;
  static Position initial(int first = 0);
  std::string key() const;
  uint64_t hash() const;
  bool repeated() const;
  int marshal(int player) const;
  void validate() const;
};
struct Undo {
  Tower from, to;
  // Every move changes only the moving player's reserves.
  std::array<int, 14> hand;
  int turn;
  bool draft;
  std::array<bool, 2> done;
  size_t history_size;
};
std::vector<int> destinations(const Position &, int square);
std::vector<Move> pseudo_moves(const Position &);
bool attacked(const Position &, int square, int by);
bool in_check(const Position &, int player);
// Search can skip the terminal gate after checking missing marshals and
// repetition.
std::vector<Move> legal_moves(Position &, bool tactical_only = false,
                              bool terminal_checked = false);
bool has_legal_move(Position &, bool terminal_checked = false);
Undo make_move(Position &, const Move &, bool record_history = true);
void undo_move(Position &, const Move &, const Undo &);
std::string
outcome(Position &); // ongoing, checkmate, stalemate, capture, repetition
int evaluate(const Position &); // side-to-move score, excluding terminal rules
inline constexpr int LINEAR_FEATURES = 45;
std::array<int, LINEAR_FEATURES> evaluation_features(const Position &);
std::array<int, LINEAR_FEATURES> evaluation_weights();
json encode(const Position &);
Position decode(const json &);
json encode(const Move &);
Move decode_move(const json &);
uint64_t perft(Position &, int depth);
} // namespace gungi
