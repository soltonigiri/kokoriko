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
  const int repeats = 100;
  auto measure = [&](const std::string &name, auto evaluator) {
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
  measure("classical", [](const Position &p) { return evaluate(p); });
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
