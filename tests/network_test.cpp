#include "network.hpp"
#include <chrono>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
using namespace gungi;
namespace {
template <class T> void append(std::vector<char> &bytes, const T &value) {
  const auto *begin = reinterpret_cast<const char *>(&value);
  bytes.insert(bytes.end(), begin, begin + sizeof(value));
}
void model(const std::filesystem::path &path, int hidden, bool relative,
           bool integer) {
  std::mt19937 rng(741);
  std::vector<char> body;
  auto layer = [&](int count, int width, int bias) {
    for (int i = 0; i < count; ++i) {
      const int n = bias ? bias : int(rng() % 7) - 3;
      if (!integer)
        append(body, float(n) / 500.f);
      else if (width == 4)
        append(body, int32_t(n));
      else
        append(body, int16_t(n));
    }
  };
  layer(FEATURES * hidden, 2, 0);
  layer(hidden, 4, 128);
  layer(SECOND * hidden, 2, 0);
  if (integer)
    layer(SECOND, 4, 65536);
  else
    layer(SECOND, 4, 128);
  layer(SECOND, 2, 0);
  if (integer)
    append(body, int32_t(0));
  else
    append(body, float(0));
  uint64_t hash = 1469598103934665603ULL;
  for (unsigned char byte : body) {
    hash ^= byte;
    hash *= 1099511628211ULL;
  }
  std::ofstream stream(path, std::ios::binary);
  stream.write("KOKONN01", 8);
  const uint32_t dims[4] = {
      FEATURES, uint32_t(hidden), SECOND,
      uint32_t(relative ? (integer ? 4 : 3) : (integer ? 2 : 0))};
  stream.write(reinterpret_cast<const char *>(dims), sizeof(dims));
  stream.write(reinterpret_cast<const char *>(&hash), sizeof(hash));
  stream.write(body.data(), std::streamsize(body.size()));
}
uint64_t checks = 0;
float max_error = 0;
void verify(Network &network, Position &p, int depth) {
  const float before = network.predict(p, true);
  const float full = network.predict(p, false);
  const float error = std::abs(before - full);
  max_error = std::max(max_error, error);
  if (network.quantized() ? error != 0 : error > 0.01f)
    throw std::runtime_error(
        "direct NNUE differs from full feature reconstruction");
  if (network.predict(p, true) != before)
    throw std::runtime_error("full prediction corrupted direct accumulator");
  ++checks;
  if (!depth)
    return;
  auto moves = legal_moves(p);
  const size_t count = std::min<size_t>(12, moves.size());
  for (size_t i = 0; i < count; ++i) {
    const auto &move = moves[i * moves.size() / count];
    auto u = make_move(p, move);
    network.update(p, move, u, false);
    verify(network, p, depth - 1);
    network.update(p, move, u, true);
    undo_move(p, move, u);
    if (network.predict(p, true) != before)
      throw std::runtime_error("NNUE undo did not restore parent exactly");
  }
}
} // namespace
int main() {
  const auto directory =
      std::filesystem::temp_directory_path() /
      ("kokoriko-network-" +
       std::to_string(
           std::chrono::steady_clock::now().time_since_epoch().count()));
  std::filesystem::create_directory(directory);
  try {
    std::vector<Position> positions;
    auto p = Position::initial();
    std::mt19937 rng(17);
    for (int ply = 0; ply < 80; ++ply) {
      if (ply % 8 == 0)
        positions.push_back(p);
      const auto moves = legal_moves(p);
      if (moves.empty())
        break;
      make_move(p, moves[rng() % moves.size()]);
    }
    p = Position{};
    p.draft = false;
    p.done = {true, true};
    p.board[76].push(piece(0, Marshal));
    p.board[4].push(piece(1, Marshal));
    p.board[40].push(piece(0, Pawn));
    p.board[40].push(piece(0, Tactician));
    p.board[30].push(piece(1, Pawn));
    p.board[30].push(piece(1, Spear));
    p.board[49].push(piece(1, Pawn));
    p.board[49].push(piece(0, Samurai));
    p.hand[0][Pawn] = p.hand[0][Spear] = 1;
    p.history = {p.key()};
    p.validate();
    positions.push_back(p);
    p.board[40].p[1] = piece(0, Major);
    p.hand[0][Tactician] = 1;
    p.history = {p.key()};
    p.validate();
    positions.push_back(p);
    for (int hidden : {64, 256})
      for (bool relative : {false, true})
        for (bool integer : {false, true}) {
          model(directory / "test.nnue", hidden, relative, integer);
          Network network;
          network.load((directory / "test.nnue").string());
          for (auto position : positions) {
            network.begin_search(position);
            verify(network, position, 2);
            // Explicitly cover every betrayal/capture even if a sampled branch
            // omitted that move from the traversal above.
            for (const auto &move : legal_moves(position)) {
              if (!move.betray && move.action != Move::Capture)
                continue;
              auto u = make_move(position, move);
              network.update(position, move, u, false);
              verify(network, position, 1);
              network.update(position, move, u, true);
              undo_move(position, move, u);
            }
            network.end_search();
          }
        }
    std::filesystem::remove_all(directory);
    std::cout << checks << " accumulator comparisons; max error " << max_error
              << '\n';
  } catch (const std::exception &e) {
    std::filesystem::remove_all(directory);
    std::cerr << e.what() << '\n';
    return 1;
  }
}
