#include "gungi.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>
namespace gungi {
namespace {
bool inside(int r, int c) { return r >= 0 && r < 9 && c >= 0 && c < 9; }
uint64_t hash_field(size_t index, unsigned char value) {
  if (!value)
    return 0;
  uint64_t z = index * 256 + value + 0x9e3779b97f4a7c15ULL;
  z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
  z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
  return z ^ (z >> 31);
}
std::string hex(const std::string &s) {
  std::string out;
  for (unsigned char c : s) {
    out += "0123456789abcdef"[c >> 4];
    out += "0123456789abcdef"[c & 15];
  }
  return out;
}
std::string unhex(const std::string &s) {
  if (s.size() % 2)
    throw std::invalid_argument("bad history key");
  auto digit = [](char c) {
    if (c >= '0' && c <= '9')
      return c - '0';
    if (c >= 'a' && c <= 'f')
      return c - 'a' + 10;
    throw std::invalid_argument("bad hex");
  };
  std::string out;
  for (size_t i = 0; i < s.size(); i += 2)
    out += static_cast<char>(digit(s[i]) * 16 + digit(s[i + 1]));
  return out;
}
bool can_betray(const Position &p, int to, int reserved = -1) {
  auto need = std::array<int, 14>{};
  if (reserved >= 0)
    ++need[reserved];
  bool found = false;
  for (int i = 0; i < p.board[to].size; ++i) {
    int v = p.board[to].p[i];
    if (side(v) != p.turn) {
      ++need[type(v)];
      found = true;
    }
  }
  for (int t = 0; t < 14; ++t)
    if (need[t] > p.hand[p.turn][t])
      return false;
  return found;
}
} // namespace
Position Position::initial(int first_) {
  if (first_ < 0 || first_ > 1)
    throw std::invalid_argument("first must be 0 or 1");
  Position p;
  p.first = p.turn = first_;
  p.hand[0] = p.hand[1] = SUPPLY;
  p.history.push_back(p.key());
  return p;
}
std::string Position::key() const {
  std::string s;
  s.reserve(276);
  for (const auto &t : board)
    for (int i = 0; i < 3; ++i)
      s += static_cast<char>(i < t.size ? t.p[i] : 0);
  for (const auto &h : hand)
    for (int n : h)
      s += static_cast<char>(n);
  s += static_cast<char>(turn);
  s += static_cast<char>(first);
  s += static_cast<char>(draft);
  s += static_cast<char>(done[0]);
  s += static_cast<char>(done[1]);
  return s;
}
uint64_t Position::hash() const {
  // Independent full reconstruction retained for differential verification.
  return position_key_hash(key());
}
uint64_t position_key_hash(std::string_view packed) {
  uint64_t h = 0;
  for (size_t i = 0; i < packed.size(); ++i)
    h ^= hash_field(i, static_cast<unsigned char>(packed[i]));
  return h;
}
uint64_t updated_hash(const Position &p, const Move &m, const Undo &u,
                      uint64_t h) {
  auto change = [&](size_t index, int before, int after) {
    if (before != after)
      h ^= hash_field(index, before) ^ hash_field(index, after);
  };
  auto tower = [&](int square, const Tower &before) {
    if (square < 0)
      return;
    const auto &after = p.board[square];
    for (int i = 0; i < 3; ++i)
      change(square * 3 + i, i < before.size ? before.p[i] : 0,
             i < after.size ? after.p[i] : 0);
  };
  tower(m.from, u.from);
  tower(m.to, u.to);
  for (int k = 0; k < 14; ++k)
    change(243 + u.turn * 14 + k, u.hand[k], p.hand[u.turn][k]);
  change(271, u.turn, p.turn);
  // first (272) never changes during play.
  change(273, u.draft, p.draft);
  change(274, u.done[0], p.done[0]);
  change(275, u.done[1], p.done[1]);
  return h;
}
bool Position::repeated() const {
  auto k = key();
  return std::count(history.begin(), history.end(), k) >= 4;
}
int Position::marshal(int player) const {
  for (int q = 0; q < 81; ++q)
    if (board[q].top() == piece(player, Marshal))
      return q;
  return -1;
}
void Position::validate() const {
  if (turn < 0 || turn > 1 || first < 0 || first > 1)
    throw std::invalid_argument("invalid side");
  auto counts = hand;
  for (int c = 0; c < 2; ++c)
    for (int t = 0; t < 14; ++t)
      if (hand[c][t] < 0 || hand[c][t] > SUPPLY[t])
        throw std::invalid_argument("invalid hand");
  for (int q = 0; q < 81; ++q) {
    const auto &t = board[q];
    if (t.size < 0 || t.size > 3)
      throw std::invalid_argument("invalid height");
    for (int i = 0; i < t.size; ++i) {
      int v = t.p[i];
      if (v < 1 || v > 28)
        throw std::invalid_argument("invalid piece");
      if (type(v) == Marshal && i != t.size - 1)
        throw std::invalid_argument("covered marshal");
      ++counts[side(v)][type(v)];
      if (draft && ((side(v) == 0 && q / 9 < 6) || (side(v) == 1 && q / 9 > 2)))
        throw std::invalid_argument("draft outside home");
    }
  }
  for (int c = 0; c < 2; ++c)
    for (int t = 0; t < 14; ++t)
      if (counts[c][t] > SUPPLY[t])
        throw std::invalid_argument("piece supply exceeded");
  if (!draft && (hand[0][Marshal] || hand[1][Marshal]))
    throw std::invalid_argument("marshal in hand during battle");
  if (draft && (done[1 - first] || done[turn]))
    throw std::invalid_argument("invalid draft rights");
  if (!history.empty() && history.back() != key())
    throw std::invalid_argument("history does not end at position");
}
static std::vector<int> raw_destinations(const Position &p, int square) {
  std::vector<int> out;
  if (square < 0 || square >= 81 || !p.board[square].size)
    return out;
  const int t = p.board[square].size, v = p.board[square].top(), k = type(v),
            r = square / 9, c = square % 9, f = side(v) == 0 ? -1 : 1;
  auto ray = [&](int dr, int dc, int minimum, int maximum, bool leap) {
    for (int d = 1; d <= maximum; ++d) {
      int nr = r + dr * d, nc = c + dc * d;
      if (!inside(nr, nc))
        break;
      int h = p.board[nr * 9 + nc].size;
      if (h > t)
        break;
      if (d >= minimum)
        out.push_back(nr * 9 + nc);
      if (h && !leap)
        break;
    }
  };
  if (k == Archer) {
    ray(-f, 0, 1, t, false);
    if (inside(r + f, c) && p.board[(r + f) * 9 + c].size <= t) {
      for (int wing = -1; wing <= 1; ++wing) {
        if (wing && (!inside(r + f, c + wing) ||
                     p.board[(r + f) * 9 + c + wing].size > t))
          continue;
        for (int d = 1; d <= t; ++d) {
          int nr = r + f * (d + 1), nc = c + wing * d;
          if (!inside(nr, nc))
            break;
          if (p.board[nr * 9 + nc].size > t)
            break;
          out.push_back(nr * 9 + nc);
        }
      }
    }
    return out;
  }
  for (int dr = -1; dr <= 1; ++dr)
    for (int dc = -1; dc <= 1; ++dc) {
      if (!dr && !dc)
        continue;
      int rel = dr * f;
      bool diag = dr && dc, vertical = dr && !dc, horizontal = !dr && dc;
      int max = 0, min = 1;
      bool leap = false;
      switch (k) {
      case Marshal:
        max = t;
        break;
      case General:
        max = diag ? t : 8;
        break;
      case Lieutenant:
        max = diag ? 8 : t;
        break;
      case Major:
        if (!diag || rel == 1)
          max = t;
        break;
      case Samurai:
        if (vertical || (diag && rel == 1))
          max = t;
        break;
      case Spear:
        if (vertical)
          max = t + (rel == 1);
        else if (diag && rel == 1)
          max = t;
        break;
      case Rider:
        if (vertical)
          max = t + 1;
        else if (horizontal)
          max = t;
        break;
      case Shinobi:
        if (diag)
          max = t + 1;
        break;
      case Fortress:
        if (horizontal || (vertical && rel == 1) || (diag && rel == -1))
          max = t;
        break;
      case Pawn:
        if (vertical)
          max = t;
        break;
      case Cannon:
        if (vertical && rel == 1) {
          min = 3;
          max = t + 2;
          leap = true;
        } else if (horizontal || (vertical && rel == -1))
          max = t;
        break;
      case Musketeer:
        if (vertical && rel == 1) {
          min = 2;
          max = t + 1;
          leap = true;
        } else if (diag && rel == -1)
          max = t;
        break;
      case Tactician:
        if ((diag && rel == 1) || (vertical && rel == -1))
          max = t;
        break;
      }
      if (max)
        ray(dr, dc, min, max, leap);
    }
  return out;
}
namespace {
struct Path {
  int to = -1;
  std::array<int, 9> through{};
  int length = 0;
  bool leap = false;
};
struct Paths {
  std::vector<Path> ordered;
  std::array<uint8_t, 81> by_target{};
};
const Paths &paths(int v, int height, int square) {
  static const auto table = [] {
    std::array<Paths, 28 * 3 * 81> all;
    for (int value = 1; value <= 28; ++value)
      for (int t = 1; t <= 3; ++t)
        for (int q = 0; q < 81; ++q) {
          Position blank;
          for (int i = 0; i < t; ++i)
            blank.board[q].push(value);
          int forward = side(value) == 0 ? -1 : 1;
          for (int to : raw_destinations(blank, q)) {
            Path path;
            path.to = to;
            int rd = to / 9 - q / 9, cd = to % 9 - q % 9;
            int dr = (rd > 0) - (rd < 0), dc = (cd > 0) - (cd < 0);
            path.leap = rd * forward > 0 &&
                        (type(value) == Archer || type(value) == Cannon ||
                         type(value) == Musketeer);
            if (type(value) == Archer && path.leap) {
              path.through[path.length++] = q + forward * 9;
              if (dc)
                path.through[path.length++] = q + forward * 9 + dc;
              for (int d = 1; d < std::abs(rd) - 1; ++d)
                path.through[path.length++] =
                    (q / 9 + forward * (d + 1)) * 9 + q % 9 + dc * d;
            } else {
              int distance = std::max(std::abs(rd), std::abs(cd));
              for (int d = 1; d < distance; ++d)
                path.through[path.length++] =
                    (q / 9 + dr * d) * 9 + q % 9 + dc * d;
            }
            auto &group = all[((value - 1) * 3 + t - 1) * 81 + q];
            if (group.by_target[to])
              throw std::logic_error("duplicate movement destination");
            group.ordered.push_back(path);
            group.by_target[to] = static_cast<uint8_t>(group.ordered.size());
          }
        }
    return all;
  }();
  return table[((v - 1) * 3 + height - 1) * 81 + square];
}
bool clear_path(const Position &p, const Path &path, int height) {
  if (p.board[path.to].size > height)
    return false;
  for (int i = 0; i < path.length; ++i)
    if (p.board[path.through[i]].size > (path.leap ? height : 0))
      return false;
  return true;
}
} // namespace
std::vector<int> destinations(const Position &p, int square) {
  std::vector<int> out;
  if (square < 0 || square >= 81 || !p.board[square].size)
    return out;
  const auto &source = p.board[square];
  out.reserve(32);
  for (const auto &path : paths(source.top(), source.size, square).ordered)
    if (clear_path(p, path, source.size))
      out.push_back(path.to);
  return out;
}
namespace {
template <class Visitor> bool visit_pseudo(const Position &p, Visitor visit) {
  const int player = p.turn;
  auto add = [&](Move m, int moving) {
    if (visit(m))
      return true;
    if (moving == Tactician &&
        (m.action == Move::Stack || m.action == Move::Drop) &&
        can_betray(p, m.to, m.action == Move::Drop ? moving : -1)) {
      m.betray = true;
      if (visit(m))
        return true;
    }
    return false;
  };
  if (!p.draft) {
    for (int q = 0; q < 81; ++q) {
      const auto &source = p.board[q];
      const int v = source.top();
      if (!v || side(v) != player)
        continue;
      for (const auto &path : paths(v, source.size, q).ordered) {
        if (!clear_path(p, path, source.size))
          continue;
        const int to = path.to;
        const auto &target = p.board[to];
        if (!target.size) {
          if (add({q, to, -1, Move::Route, false}, type(v)))
            return true;
        } else {
          if (side(target.top()) != player &&
              add({q, to, -1, Move::Capture, false}, type(v)))
            return true;
          if (target.size < 3 && type(target.top()) != Marshal &&
              add({q, to, -1, Move::Stack, false}, type(v)))
            return true;
        }
      }
    }
  }
  int frontier = player == 0 ? 8 : 0;
  if (!p.draft)
    for (int q = 0; q < 81; ++q) {
      int v = p.board[q].top();
      if (v && side(v) == player)
        frontier =
            player == 0 ? std::min(frontier, q / 9) : std::max(frontier, q / 9);
    }
  for (int k = 0; k < 14; ++k) {
    if (!p.hand[player][k] || (p.hand[player][Marshal] && k != Marshal))
      continue;
    for (int q = 0; q < 81; ++q) {
      int r = q / 9;
      bool allowed = p.draft ? (player == 0 ? r >= 6 : r <= 2)
                             : (player == 0 ? r >= frontier : r <= frontier);
      if (!allowed)
        continue;
      const auto &target = p.board[q];
      if (target.size && (target.size >= 3 || type(target.top()) == Marshal ||
                          side(target.top()) != player))
        continue;
      if (add({-1, q, k, Move::Drop, false}, k))
        return true;
    }
  }
  return p.draft && !p.hand[player][Marshal] &&
         visit({-1, -1, -1, Move::Done, false});
}
} // namespace
std::vector<Move> pseudo_moves(const Position &p) {
  std::vector<Move> out;
  out.reserve(512);
  visit_pseudo(p, [&](const Move &m) {
    out.push_back(m);
    return false;
  });
  return out;
}
bool attacked(const Position &p, int square, int by) {
  if (square < 0)
    return false;
  for (int q = 0; q < 81; ++q) {
    const auto &source = p.board[q];
    int v = source.top();
    if (!v || side(v) != by || source.size < p.board[square].size)
      continue;
    const auto &group = paths(v, source.size, q);
    const auto index = group.by_target[square];
    if (index && clear_path(p, group.ordered[index - 1], source.size))
      return true;
  }
  return false;
}
bool in_check(const Position &p, int player) {
  return attacked(p, p.marshal(player), 1 - player);
}
Undo make_move(Position &p, const Move &m, bool record_history) {
  Undo u{m.from >= 0 ? p.board[m.from] : Tower{},
         m.to >= 0 ? p.board[m.to] : Tower{},
         p.hand[p.turn],
         p.turn,
         p.draft,
         p.done,
         p.history.size()};
  int player = p.turn;
  if (m.action == Move::Done)
    p.done[player] = true;
  else {
    int moving =
        m.action == Move::Drop ? piece(player, m.kind) : p.board[m.from].pop();
    if (m.action == Move::Drop)
      --p.hand[player][m.kind];
    auto &dst = p.board[m.to];
    if (m.action == Move::Capture) {
      Tower kept;
      for (int i = 0; i < dst.size; ++i)
        if (side(dst.p[i]) == player)
          kept.push(dst.p[i]);
      dst = kept;
    }
    if (m.betray)
      for (int i = 0; i < dst.size; ++i)
        if (side(dst.p[i]) != player) {
          int k = type(dst.p[i]);
          --p.hand[player][k];
          dst.p[i] = piece(player, k);
        }
    dst.push(moving);
  }
  if (p.draft) {
    if (std::accumulate(p.hand[player].begin(), p.hand[player].end(), 0) == 0)
      p.done[player] = true;
    if (p.done[1 - p.first]) {
      p.draft = false;
      p.turn = p.first;
      p.done = {true, true};
    } else
      p.turn = p.done[1 - player] ? player : 1 - player;
  } else
    p.turn = 1 - player;
  if (record_history)
    p.history.push_back(p.key());
  return u;
}
void undo_move(Position &p, const Move &m, const Undo &u) {
  if (m.from >= 0)
    p.board[m.from] = u.from;
  if (m.to >= 0)
    p.board[m.to] = u.to;
  p.hand[u.turn] = u.hand;
  p.turn = u.turn;
  p.draft = u.draft;
  p.done = u.done;
  p.history.resize(u.history_size);
}
std::vector<Move> legal_moves(Position &p, bool tactical_only,
                              bool terminal_checked) {
  if (!terminal_checked &&
      ((!p.draft && (p.marshal(0) < 0 || p.marshal(1) < 0)) || p.repeated()))
    return {};
  std::vector<Move> out;
  int player = p.turn;
  const int king = p.marshal(player);
  out.reserve(512);
  visit_pseudo(p, [&](const Move &m) {
    if (tactical_only && m.action != Move::Capture && m.action != Move::Stack &&
        !m.betray)
      return false;
    auto u = make_move(p, m, false);
    const int next_king = (m.from == king && king >= 0) ||
                                  (m.action == Move::Drop && m.kind == Marshal)
                              ? m.to
                              : king;
    bool safe = !attacked(p, next_king, 1 - player);
    undo_move(p, m, u);
    if (safe)
      out.push_back(m);
    return false;
  });
  return out;
}
bool has_legal_move(Position &p, bool terminal_checked) {
  if (!terminal_checked &&
      ((!p.draft && (p.marshal(0) < 0 || p.marshal(1) < 0)) || p.repeated()))
    return false;
  const int player = p.turn, king = p.marshal(player);
  return visit_pseudo(p, [&](const Move &m) {
    const auto u = make_move(p, m, false);
    const int next_king = (m.from == king && king >= 0) ||
                                  (m.action == Move::Drop && m.kind == Marshal)
                              ? m.to
                              : king;
    const bool safe = !attacked(p, next_king, 1 - player);
    undo_move(p, m, u);
    return safe;
  });
}
std::string outcome(Position &p) {
  if (!p.draft && (p.marshal(0) < 0 || p.marshal(1) < 0))
    return "capture";
  if (p.repeated())
    return "repetition";
  if (!has_legal_move(p))
    return in_check(p, p.turn) ? "checkmate" : "stalemate";
  return "ongoing";
}
std::array<int, LINEAR_FEATURES> evaluation_weights() {
  constexpr int values[14] = {0,   900, 750, 420, 300, 330, 350,
                              380, 280, 100, 340, 320, 300, 260};
  std::array<int, LINEAR_FEATURES> weights{};
  for (int k = 0; k < 14; ++k) {
    weights[k] = values[k];
    weights[14 + k] = values[k] * 7 / 10;
    weights[28 + k] = values[k] * 4 / 5;
  }
  weights[42] = 3;
  weights[43] = 2;
  weights[44] = 8;
  return weights;
}
std::array<int, LINEAR_FEATURES> evaluation_features(const Position &p) {
  std::array<int, LINEAR_FEATURES> result{};
  for (int c = 0; c < 2; ++c) {
    const int sign = c == p.turn ? 1 : -1;
    for (int k = 0; k < 14; ++k)
      result[28 + k] += sign * p.hand[c][k];
  }
  for (int q = 0; q < 81; ++q) {
    const auto &tower = p.board[q];
    for (int t = 0; t < tower.size; ++t) {
      const int v = tower.p[t];
      result[(t == tower.size - 1 ? 0 : 14) + type(v)] +=
          side(v) == p.turn ? 1 : -1;
    }
    const int v = tower.top();
    if (!v)
      continue;
    const int c = side(v), sign = c == p.turn ? 1 : -1;
    if (type(v) != Marshal) {
      result[42] += sign * int(destinations(p, q).size());
      result[43] += sign * (c == 0 ? 8 - q / 9 : q / 9);
    } else {
      for (int dr = -1; dr <= 1; ++dr)
        for (int dc = -1; dc <= 1; ++dc) {
          const int r = q / 9 + dr, col = q % 9 + dc;
          if (inside(r, col)) {
            const int near = p.board[r * 9 + col].top();
            if (near && side(near) == c)
              result[44] += sign;
          }
        }
    }
  }
  return result;
}
int evaluate(const Position &p) {
  constexpr int values[14] = {0,   900, 750, 420, 300, 330, 350,
                              380, 280, 100, 340, 320, 300, 260};
  int scores[2] = {0, 0};
  for (int c = 0; c < 2; ++c)
    for (int k = 0; k < 14; ++k)
      scores[c] += p.hand[c][k] * values[k] * 4 / 5;
  for (int q = 0; q < 81; ++q) {
    const auto &tower = p.board[q];
    for (int t = 0; t < tower.size; ++t) {
      int v = tower.p[t], c = side(v), k = type(v);
      scores[c] += values[k] * (t == tower.size - 1 ? 10 : 7) / 10;
    }
    int v = tower.top();
    if (!v)
      continue;
    int c = side(v), k = type(v);
    if (k != Marshal) {
      scores[c] += int(destinations(p, q).size()) * 3;
      scores[c] += (c == 0 ? 8 - q / 9 : q / 9) * 2;
    } else {
      for (int dr = -1; dr <= 1; ++dr)
        for (int dc = -1; dc <= 1; ++dc) {
          int r = q / 9 + dr, col = q % 9 + dc;
          if (inside(r, col)) {
            int near = p.board[r * 9 + col].top();
            if (near && side(near) == c)
              scores[c] += 8;
          }
        }
    }
  }
  return scores[p.turn] - scores[1 - p.turn];
}
std::array<int, STRATEGIC_FEATURES> strategic_features(const Position &p,
                                                       uint8_t groups) {
  std::array<int, STRATEGIC_FEATURES> out{};
  if (p.draft || !groups)
    return out;
  constexpr int value[14] = {0,  90, 75, 42, 30, 33, 35,
                             38, 28, 10, 34, 32, 30, 26};
  if (groups & 1)
    for (const auto &tower : p.board) {
      if (tower.size < 2)
        continue;
      const int owner = side(tower.top()), sign = owner == p.turn ? 1 : -1;
      for (int t = 0; t < tower.size - 1; ++t)
        if (side(tower.p[t]) != owner)
          out[0] += sign * value[type(tower.p[t])];
      const int exposed = tower.p[tower.size - 2];
      out[1] += sign * (side(exposed) == owner ? 1 : -1) * value[type(exposed)];
    }
  // History is irrelevant to these features; avoid copying a game's history
  // for each legality probe.
  Position scratch;
  scratch.board = p.board;
  scratch.hand = p.hand;
  scratch.first = p.first;
  scratch.draft = false;
  scratch.done = p.done;
  for (int c = 0; c < 2; ++c) {
    const int sign = c == p.turn ? 1 : -1, king = p.marshal(c);
    if (king < 0)
      continue;
    scratch.turn = c;
    auto safe = [&](const Move &move, int next_king) {
      auto u = make_move(scratch, move, false);
      const bool result = !attacked(scratch, next_king, 1 - c);
      undo_move(scratch, move, u);
      return result;
    };
    if (groups & 2) {
      for (int dr = -1; dr <= 1; ++dr)
        for (int dc = -1; dc <= 1; ++dc) {
          const int r = king / 9 + dr, col = king % 9 + dc;
          if (inside(r, col) && attacked(p, r * 9 + col, 1 - c))
            out[2] -= sign;
        }
      for (int to : destinations(p, king)) {
        const auto &target = p.board[to];
        bool flight = false;
        if (!target.size)
          flight = safe({king, to, -1, Move::Route}, to);
        else {
          if (side(target.top()) != c)
            flight = safe({king, to, -1, Move::Capture}, to);
          if (!flight && target.size < 3 && type(target.top()) != Marshal)
            flight = safe({king, to, -1, Move::Stack}, to);
        }
        out[3] += sign * int(flight);
      }
    }
    if (!(groups & 12))
      continue;
    int frontier = c == 0 ? 8 : 0, reserve_kinds = 0;
    for (int q = 0; q < 81; ++q)
      if (p.board[q].size && side(p.board[q].top()) == c)
        frontier =
            c == 0 ? std::min(frontier, q / 9) : std::max(frontier, q / 9);
    for (int n : p.hand[c])
      reserve_kinds += n > 0;
    auto drop_square = [&](int q) {
      const auto &t = p.board[q];
      return (c == 0 ? q / 9 >= frontier : q / 9 <= frontier) &&
             (!t.size ||
              (t.size < 3 && side(t.top()) == c && type(t.top()) != Marshal));
    };
    std::array<bool, 81> betrayal_targets{};
    int best_gain = 0;
    auto betrayal = [&](const Move &move) {
      if (!can_betray(scratch, move.to,
                      move.action == Move::Drop ? Tactician : -1) ||
          !safe(move, king))
        return;
      int gain = 0;
      const auto &target = p.board[move.to];
      for (int t = 0; t < target.size; ++t)
        if (side(target.p[t]) != c)
          gain += value[type(target.p[t])];
      best_gain = std::max(best_gain, gain);
      betrayal_targets[move.to] = true;
    };
    if ((groups & 4) && reserve_kinds) {
      for (int from = 0; from < 81; ++from)
        if (p.board[from].top() == piece(c, Tactician))
          for (int to : destinations(p, from))
            if (p.board[to].size && p.board[to].size < 3 &&
                type(p.board[to].top()) != Marshal)
              betrayal({from, to, -1, Move::Stack, true});
      if (p.hand[c][Tactician])
        for (int q = 0; q < 81; ++q)
          if (p.board[q].size && drop_square(q))
            betrayal({-1, q, Tactician, Move::Drop, true});
      out[4] += sign * best_gain;
      out[5] += sign * std::count(betrayal_targets.begin(),
                                  betrayal_targets.end(), true);
    }
    if ((groups & 8) && reserve_kinds) {
      const bool checked = in_check(p, c);
      const int kind = int(std::find_if(p.hand[c].begin(), p.hand[c].end(),
                                        [](int n) { return n > 0; }) -
                           p.hand[c].begin());
      for (int q = 0; q < 81; ++q)
        if (drop_square(q) &&
            (!checked || safe({-1, q, kind, Move::Drop}, king))) {
          out[6] += sign * std::min(4, reserve_kinds);
          if (std::abs(q / 9 - frontier) <= 1)
            out[7] += sign;
        }
    }
  }
  return out;
}
std::array<int, EXTENDED_FEATURES> extended_features(const Position &p) {
  std::array<int, EXTENDED_FEATURES> result{};
  const auto base = evaluation_features(p);
  const auto extra = strategic_features(p);
  std::copy(base.begin(), base.end(), result.begin());
  std::copy(extra.begin(), extra.end(), result.begin() + LINEAR_FEATURES);
  return result;
}
std::array<int, EXTENDED_FEATURES> extended_weights() {
  std::array<int, EXTENDED_FEATURES> result{};
  const auto base = evaluation_weights();
  constexpr std::array<int, STRATEGIC_FEATURES> extra{3, 1, 12, 8, 2, 6, 1, 2};
  std::copy(base.begin(), base.end(), result.begin());
  std::copy(extra.begin(), extra.end(), result.begin() + LINEAR_FEATURES);
  return result;
}
json encode(const Move &m) {
  const char *names[] = {"move", "stack", "capture", "drop", "done"};
  return {{"from", m.from},
          {"to", m.to},
          {"piece", m.kind},
          {"action", names[m.action]},
          {"betray", m.betray}};
}
Move decode_move(const json &j) {
  Move m;
  m.from = j.value("from", -1);
  m.to = j.value("to", -1);
  m.kind = j.value("piece", -1);
  m.betray = j.value("betray", false);
  auto a = j.at("action").get<std::string>();
  const std::array<std::string, 5> names{"move", "stack", "capture", "drop",
                                         "done"};
  auto it = std::find(names.begin(), names.end(), a);
  if (it == names.end())
    throw std::invalid_argument("unknown action");
  m.action = static_cast<Move::Action>(it - names.begin());
  return m;
}
json encode(const Position &p) {
  json board = json::array(), history = json::array();
  for (const auto &t : p.board) {
    json a = json::array();
    for (int i = 0; i < t.size; ++i)
      a.push_back(t.p[i]);
    board.push_back(a);
  }
  for (const auto &k : p.history)
    history.push_back(hex(k));
  return {{"version", 1},     {"rules", RULES}, {"board", board},
          {"hand", p.hand},   {"turn", p.turn}, {"first", p.first},
          {"draft", p.draft}, {"done", p.done}, {"history", history}};
}
Position decode(const json &j) {
  if (j.at("version") != 1 || j.at("rules") != RULES)
    throw std::invalid_argument("unsupported position version/rules");
  Position p;
  p.turn = j.at("turn");
  p.first = j.at("first");
  p.draft = j.at("draft");
  p.done = j.at("done").get<std::array<bool, 2>>();
  p.hand = j.at("hand").get<std::array<std::array<int, 14>, 2>>();
  if (!j.at("board").is_array() || j.at("board").size() != 81)
    throw std::invalid_argument("board must have 81 squares");
  for (int q = 0; q < 81; ++q) {
    const auto &a = j["board"][q];
    if (!a.is_array() || a.size() > 3)
      throw std::invalid_argument("invalid tower");
    for (const auto &v : a) {
      int n = v.get<int>();
      if (n < 1 || n > 28)
        throw std::invalid_argument("invalid piece");
      p.board[q].push(n);
    }
  }
  if (j.contains("history")) {
    if (!j["history"].is_array() || j["history"].size() > 100000)
      throw std::invalid_argument("invalid history");
    for (const auto &k : j["history"]) {
      auto s = unhex(k.get<std::string>());
      if (s.size() != 276)
        throw std::invalid_argument("invalid history key length");
      p.history.push_back(s);
    }
  }
  if (p.history.empty())
    p.history.push_back(p.key());
  p.validate();
  return p;
}
uint64_t perft(Position &p, int depth) {
  if (depth == 0)
    return 1;
  uint64_t nodes = 0;
  for (const auto &m : legal_moves(p)) {
    auto u = make_move(p, m);
    nodes += perft(p, depth - 1);
    undo_move(p, m, u);
  }
  return nodes;
}
} // namespace gungi
