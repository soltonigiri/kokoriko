#include "gungi.hpp"
#include "network.hpp"
#include <ctime>
#include <fstream>
#include <iostream>

using namespace gungi;

int main(int argc, char **argv) {
  if (argc != 4) {
    std::cerr << "usage: bench_evaluation POSITIONS.json FLOAT.nnue INT.nnue\n";
    return 2;
  }
  json data;
  std::ifstream(argv[1]) >> data;
  std::vector<Position> positions;
  for (const auto &value : data)
    positions.push_back(decode(value));
  if (positions.empty())
    return 2;
  Network floating, integer;
  floating.load(argv[2]);
  integer.load(argv[3]);
  json report;
  report["positions"] = positions.size();
  report["timing"] = "process CPU seconds; excludes model and position loading";
  auto measure = [&](const std::string &name, auto evaluator,
                     int repeats = 1000) {
    double sum = 0;
    const auto start = std::clock();
    for (int i = 0; i < repeats; ++i)
      for (const auto &position : positions)
        sum += evaluator(position);
    const double seconds = double(std::clock() - start) / CLOCKS_PER_SEC;
    report[name] = {
        {"cpu_seconds", seconds},
        {"evaluations_per_cpu_second", repeats * positions.size() / seconds},
        {"checksum", sum}};
  };
  measure(
      "packed_key", [](const Position &p) { return p.key().size(); }, 10000);
  measure("full_hash", [](const Position &p) { return p.hash(); }, 10000);
  measure(
      "exact_repetition", [](const Position &p) { return p.repeated(); },
      10000);
  // Isolate hash update cost on real moves, outside make/undo and move
  // generation.
  double hash_sum = 0;
  double hash_seconds = 0;
  int hash_updates = 0;
  for (auto position : positions) {
    auto moves = legal_moves(position);
    if (moves.empty())
      continue;
    const auto parent = position.hash();
    const auto undo = make_move(position, moves.front());
    if (updated_hash(position, moves.front(), undo, parent) != position.hash())
      return 1;
    const auto began = std::clock();
    for (int i = 0; i < 10000; ++i)
      hash_sum += updated_hash(position, moves.front(), undo, parent);
    hash_seconds += double(std::clock() - began) / CLOCKS_PER_SEC;
    hash_updates += 10000;
  }
  report["incremental_hash"] = {{"cpu_seconds", hash_seconds},
                                {"updates", hash_updates},
                                {"checksum", hash_sum}};
  measure("classical", [](const Position &p) { return evaluate(p); });
  for (int mask : {1, 2, 4, 8, 15})
    measure("strategic_group_" + std::to_string(mask),
            [mask](const Position &p) {
              const auto features = strategic_features(p, mask);
              int sum = 0;
              for (const auto value : features)
                sum += value;
              return sum;
            });
  measure("float_full",
          [&](const Position &p) { return floating.predict(p, false); });
  measure("float_incremental",
          [&](const Position &p) { return floating.predict(p, true); });
  measure("integer_full",
          [&](const Position &p) { return integer.predict(p, false); });
  measure("integer_incremental",
          [&](const Position &p) { return integer.predict(p, true); });
  // Residual models add the classical score in the actual search evaluator.
  // Keep prediction timings above comparable with earlier reports.
  measure("float_evaluator_incremental",
          [&](const Position &p) { return floating.evaluate(p, true); });
  measure("integer_evaluator_incremental",
          [&](const Position &p) { return integer.evaluate(p, true); });
  std::cout << report.dump(2) << '\n';
}
