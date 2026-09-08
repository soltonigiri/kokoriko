#pragma once
#include "gungi.hpp"
#include <array>
namespace gungi {
inline constexpr int FEATURES = 6954, HIDDEN = 256, SECOND = 32;
std::vector<int> features(const Position &, bool relative = false);
class Network {
public:
  void load(const std::string &path);
  int evaluate(const Position &, bool incremental = true);
  float predict(const Position &, bool incremental = true);
  bool loaded() const { return ready; }
  bool quantized() const { return integer; }
  bool relative_features() const { return relative; }
  bool linear_model() const { return linear; }

private:
  bool ready = false, integer = false, relative = false, residual = false;
  bool linear = false;
  std::array<int32_t, LINEAR_FEATURES> linear_weights{};
  int scale = 256;
  int hidden_size = HIDDEN;
  std::vector<float> w1, w2, w3, b1, b2;
  float b3 = 0;
  std::vector<int16_t> qw1, qw2, qw3;
  std::vector<int32_t> qb1, qb2;
  int32_t qb3 = 0;
  struct Accumulator {
    std::vector<int> previous;
    std::array<float, HIDDEN> floating{};
    std::array<int32_t, HIDDEN> quantized{};
  };
  std::array<Accumulator, 2> caches;
};
} // namespace gungi
