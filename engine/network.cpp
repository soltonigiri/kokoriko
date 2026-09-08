#include "network.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <stdexcept>
namespace gungi {
std::vector<int> features(const Position &p, bool relative) {
  std::vector<int> f;
  f.reserve(84);
  const int view = relative ? p.turn : 0;
  for (int q = 0; q < 81; ++q) {
    const auto &tower = p.board[view ? 80 - q : q];
    for (int t = 0; t < tower.size; ++t) {
      const int v = view ? 1 + (tower.p[t] + 13) % 28 : tower.p[t];
      f.push_back((q * 3 + t) * 28 + v - 1);
    }
  }
  for (int c = 0; c < 2; ++c)
    for (int k = 0; k < 14; ++k)
      f.push_back(6804 + (c * 14 + k) * 5 + p.hand[c ^ view][k]);
  f.push_back(6944 + (p.turn ^ view));
  f.push_back(6946 + int(p.draft));
  f.push_back(6948 + (p.first ^ view));
  f.push_back(6950 + int(p.done[view]));
  f.push_back(6952 + int(p.done[1 ^ view]));
  return f;
}
void Network::load(const std::string &path) {
  std::ifstream in(path, std::ios::binary);
  if (!in)
    throw std::invalid_argument("cannot open model");
  std::vector<char> bytes((std::istreambuf_iterator<char>(in)), {});
  if (bytes.size() < 32 || std::memcmp(bytes.data(), "KOKONN01", 8))
    throw std::invalid_argument("invalid model header");
  uint32_t dims[4];
  uint64_t expected;
  std::memcpy(dims, bytes.data() + 8, 16);
  std::memcpy(&expected, bytes.data() + 24, 8);
  const bool linear_format = dims[3] == 7;
  if (linear_format
          ? (dims[0] != LINEAR_FEATURES || dims[1] != 1 || dims[2] != 1)
          : (dims[0] != FEATURES || (dims[1] != 64 && dims[1] != HIDDEN) ||
             dims[2] != SECOND || dims[3] > 6))
    throw std::invalid_argument("incompatible model dimensions/format");
  uint64_t hash = 1469598103934665603ULL;
  for (size_t i = 32; i < bytes.size(); ++i) {
    hash ^= static_cast<unsigned char>(bytes[i]);
    hash *= 1099511628211ULL;
  }
  if (hash != expected)
    throw std::invalid_argument("model checksum mismatch");
  Network next;
  if (linear_format) {
    if (bytes.size() != 32 + sizeof(next.linear_weights))
      throw std::invalid_argument("unexpected model payload");
    std::memcpy(next.linear_weights.data(), bytes.data() + 32,
                sizeof(next.linear_weights));
    for (int32_t value : next.linear_weights)
      if (value < -30000 || value > 30000)
        throw std::invalid_argument("invalid model value");
    next.ready = next.integer = next.linear = true;
    *this = std::move(next);
    return;
  }
  next.hidden_size = int(dims[1]);
  next.relative = dims[3] >= 3;
  next.residual = dims[3] >= 5;
  next.integer = dims[3] == 1 || dims[3] == 2 || dims[3] == 4 || dims[3] == 6;
  next.scale = dims[3] == 2 || dims[3] == 4 || dims[3] == 6 ? 512 : 256;
  size_t offset = 32;
  auto read = [&](auto &vector, size_t count) {
    using T = typename std::decay_t<decltype(vector)>::value_type;
    size_t n = count * sizeof(T);
    if (offset + n > bytes.size())
      throw std::invalid_argument("truncated model");
    vector.resize(count);
    std::memcpy(vector.data(), bytes.data() + offset, n);
    offset += n;
  };
  if (next.integer) {
    std::vector<int32_t> last;
    read(next.qw1, FEATURES * next.hidden_size);
    read(next.qb1, next.hidden_size);
    read(next.qw2, SECOND * next.hidden_size);
    read(next.qb2, SECOND);
    read(next.qw3, SECOND);
    read(last, 1);
    next.qb3 = last[0];
    auto bounded = [](const auto &values, int64_t limit) {
      for (auto value : values)
        if (int64_t(value) < -limit || int64_t(value) > limit)
          throw std::invalid_argument("invalid model value");
    };
    for (const auto *weights : {&next.qw1, &next.qw2, &next.qw3})
      bounded(*weights, 64 * next.scale);
    bounded(next.qb1, 64 * next.scale);
    bounded(next.qb2, int64_t(64) * next.scale * next.scale);
    bounded(last, int64_t(64) * next.scale * next.scale);
  } else {
    std::vector<float> last;
    read(next.w1, FEATURES * next.hidden_size);
    read(next.b1, next.hidden_size);
    read(next.w2, SECOND * next.hidden_size);
    read(next.b2, SECOND);
    read(next.w3, SECOND);
    read(last, 1);
    next.b3 = last[0];
    for (const auto *v :
         {&next.w1, &next.b1, &next.w2, &next.b2, &next.w3, &last})
      for (float x : *v)
        if (!std::isfinite(x) || std::abs(x) > 64)
          throw std::invalid_argument("invalid model value");
  }
  if (offset != bytes.size())
    throw std::invalid_argument("unexpected model payload");
  next.ready = true;
  *this = std::move(next);
}
float Network::predict(const Position &p, bool incremental) {
  if (!ready)
    throw std::logic_error("model not loaded");
  if (linear) {
    const auto basis = evaluation_features(p);
    int64_t score = 0;
    for (int i = 0; i < LINEAR_FEATURES; ++i)
      score += int64_t(basis[i]) * linear_weights[i];
    return float(std::clamp(score, int64_t(-20000), int64_t(20000)));
  }
  auto now = features(p, relative);
  auto &cache = caches[relative ? p.turn : 0];
  auto &previous = cache.previous;
  auto &accumulator = cache.floating;
  auto &qaccumulator = cache.quantized;
  if (!incremental || previous.empty()) {
    if (integer)
      std::copy(qb1.begin(), qb1.end(), qaccumulator.begin());
    else
      std::copy(b1.begin(), b1.end(), accumulator.begin());
    previous.clear();
  }
  auto update = [&](int index, int sign) {
    if (integer)
      for (int j = 0; j < hidden_size; ++j)
        qaccumulator[j] += sign * int(qw1[index * hidden_size + j]);
    else
      for (int j = 0; j < hidden_size; ++j)
        accumulator[j] += sign * w1[index * hidden_size + j];
  };
  size_t a = 0, b = 0;
  while (a < previous.size() || b < now.size()) {
    if (a == previous.size()) {
      update(now[b++], 1);
      continue;
    }
    if (b == now.size()) {
      update(previous[a++], -1);
      continue;
    }
    if (previous[a] == now[b]) {
      ++a;
      ++b;
    } else if (previous[a] < now[b])
      update(previous[a++], -1);
    else
      update(now[b++], 1);
  }
  previous = std::move(now);
  if (integer) {
    std::array<int, HIDDEN> activated{};
    for (int j = 0; j < hidden_size; ++j)
      activated[j] = std::clamp(qaccumulator[j], 0, scale);
    std::array<int, SECOND> hidden{};
    for (int i = 0; i < SECOND; ++i) {
      int64_t v = qb2[i];
      for (int j = 0; j < hidden_size; ++j)
        v += int64_t(qw2[i * hidden_size + j]) * activated[j];
      hidden[i] = std::clamp<int64_t>((v + scale / 2) / scale, 0, scale);
    }
    int64_t out = qb3;
    for (int i = 0; i < SECOND; ++i)
      out += int64_t(qw3[i]) * hidden[i];
    return float(out) * (600.0f / float(scale * scale));
  }
  std::array<float, HIDDEN> activated{};
  for (int j = 0; j < hidden_size; ++j)
    activated[j] = std::clamp(accumulator[j], 0.0f, 1.0f);
  float out = b3;
  for (int i = 0; i < SECOND; ++i) {
    float v = b2[i];
    for (int j = 0; j < hidden_size; ++j)
      v += w2[i * hidden_size + j] * activated[j];
    out += w3[i] * std::clamp(v, 0.0f, 1.0f);
  }
  return out * 600;
}
int Network::evaluate(const Position &p, bool incremental) {
  const int base = residual ? gungi::evaluate(p) : 0;
  return std::clamp(base + int(std::lround(predict(p, incremental))), -20000,
                    20000);
}
} // namespace gungi
